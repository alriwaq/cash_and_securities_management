"""
Centralized Balance Engine — v2.1
treasury/balances.py

All financial recalculations for the Treasury module are consolidated here.
Individual DocType controllers and doc_event hooks call these functions instead
of performing inline calculations. This ensures a single source of truth and
prevents synchronization lag between related documents.

Public API:
  update_custodian_dashboard(custodian_name)
      Recalculate and persist all financial summary fields on a Custodian.
      (Replaces the v2.0 name recalculate_custodian_balances — old name kept
       as an alias for backward compatibility.)

  recalculate_custody_request_status(custody_request_name)
      Recalculate paid_amount, remaining_to_pay, and status for a Custody Request.

  recalculate_accountant_custody_status(accountant_custody_name)
      Recalculate the granular status of an Accountant Custody.

  validate_cancellation_order_for_pi(pi_doc)
      Prevent PI cancellation if a settlement JE/PE exists.

  validate_cancellation_order_for_pr(pr_doc)
      Prevent PR cancellation if a submitted PI exists.

  validate_advance_cancellation(payment_entry_doc)
      Prevent cancellation of an advance Payment Entry if any Accountant Custody
      records have been submitted (partially or fully settled) against it.
"""
import frappe
from frappe.utils import flt


# ─── Custodian Dashboard Engine ───────────────────────────────────────────────

def update_custodian_dashboard(custodian_name):
	"""
	Recalculate and persist all financial summary fields on a Custodian.
	All figures are derived exclusively from submitted (docstatus=1) documents
	to ensure draft or cancelled records do not skew the financial reality.

	Fields updated:
	  total_disbursed      — sum of all submitted advance Payment Entry paid_amounts
	  total_outstanding    — total_disbursed minus total advance-deduction settlements
	  pending_requests     — sum of advance_amounts on Approved/Partly Paid CRs
	  pending_settlements  — sum of billed amounts on un-settled ACs

	This function is the canonical dashboard recalculation entry point.
	It is called:
	  - on_submit / on_cancel of Payment Entry (via pr_hooks)
	  - on_submit / on_cancel of Purchase Receipt (via pr_hooks)
	  - on_submit / on_cancel of Purchase Invoice (via pr_hooks)
	  - on_submit / on_cancel of Journal Entry (via pr_hooks)
	  - directly from Custodian.refresh_outstanding()
	"""
	if not frappe.db.exists("Custodian", custodian_name):
		return

	# ── Total disbursed (submitted advance Payment Entries) ───────────────
	total_disbursed = flt(frappe.db.sql(
		"""SELECT COALESCE(SUM(pe.paid_amount), 0)
		   FROM `tabPayment Entry` pe
		   WHERE pe.custom_custodian = %s
		     AND pe.docstatus = 1
		     AND pe.payment_type = 'Internal Transfer'""",
		(custodian_name,),
	)[0][0] or 0)

	# ── Total settled (advance deductions from submitted JEs) ─────────────
	total_settled = flt(frappe.db.sql(
		"""SELECT COALESCE(SUM(cse.advance_amount_allocated), 0)
		   FROM `tabCustody Settlement Entry` cse
		   JOIN `tabAccountant Custody` ac ON ac.name = cse.parent
		   WHERE ac.custom_custodian = %s
		     AND ac.docstatus = 1""",
		(custodian_name,),
	)[0][0] or 0)

	# ── Outstanding = disbursed - settled ─────────────────────────────────
	total_outstanding = total_disbursed - total_settled

	# ── Pending requests (Approved or Partly Paid CRs) ────────────────────
	pending_requests = flt(frappe.db.sql(
		"""SELECT COALESCE(SUM(advance_amount), 0)
		   FROM `tabCustody Request`
		   WHERE custodian = %s
		     AND docstatus = 1
		     AND status IN ('Approved', 'Partly Paid')""",
		(custodian_name,),
	)[0][0] or 0)

	# ── Pending settlements (Fully Invoiced ACs not yet settled) ──────────
	pending_settlements = flt(frappe.db.sql(
		"""SELECT COALESCE(SUM(total_billed_amount - COALESCE(total_settled_amount, 0)), 0)
		   FROM `tabAccountant Custody`
		   WHERE custodian = %s
		     AND docstatus = 1
		     AND status IN ('Fully Invoiced', 'Partly Settled')""",
		(custodian_name,),
	)[0][0] or 0)

	frappe.db.set_value(
		"Custodian",
		custodian_name,
		{
			"total_disbursed": total_disbursed,
			"total_outstanding": total_outstanding,
			"pending_requests": pending_requests,
			"pending_settlements": pending_settlements,
		},
		update_modified=False,
	)
	frappe.logger().debug(
		f"Custodian {custodian_name}: disbursed={total_disbursed}, "
		f"outstanding={total_outstanding}, pending_req={pending_requests}, "
		f"pending_settle={pending_settlements}"
	)


# Backward-compatibility alias (v2.0 name)
def recalculate_custodian_balances(custodian_name):
	"""Alias for update_custodian_dashboard — kept for backward compatibility."""
	return update_custodian_dashboard(custodian_name)


# ─── Custody Request Status Engine ───────────────────────────────────────────

def recalculate_custody_request_status(custody_request_name):
	"""
	Recalculate paid_amount, remaining_to_pay, and status for a Custody Request
	based on all submitted Payment Entries linked to it.

	Status map:
	  paid_amount = 0                    → Approved
	  0 < paid_amount < advance_amount   → Partly Paid
	  paid_amount >= advance_amount      → Paid

	Triggered by:
	  - on_submit / on_cancel of Payment Entry (via pr_hooks)
	"""
	if not frappe.db.exists("Custody Request", custody_request_name):
		return

	cr = frappe.db.get_value(
		"Custody Request",
		custody_request_name,
		["advance_amount", "docstatus", "custodian"],
		as_dict=True,
	)
	if not cr or cr.docstatus != 1:
		return

	# Sum all submitted Payment Entries for this CR
	total_paid = flt(frappe.db.sql(
		"""SELECT COALESCE(SUM(paid_amount), 0)
		   FROM `tabPayment Entry`
		   WHERE custom_custody_request = %s AND docstatus = 1""",
		(custody_request_name,),
	)[0][0] or 0)

	advance_amount = flt(cr.advance_amount)
	remaining = advance_amount - total_paid

	# Determine status
	if total_paid <= 0:
		new_status = "Approved"
	elif total_paid < advance_amount:
		new_status = "Partly Paid"
	else:
		new_status = "Paid"

	frappe.db.set_value(
		"Custody Request",
		custody_request_name,
		{
			"paid_amount": total_paid,
			"remaining_to_pay": remaining,
			"status": new_status,
		},
		update_modified=False,
	)

	# Cascade to custodian dashboard
	if cr.custodian:
		update_custodian_dashboard(cr.custodian)


# ─── Accountant Custody Status Engine ────────────────────────────────────────

def recalculate_accountant_custody_status(accountant_custody_name):
	"""
	Recalculate the granular status of an Accountant Custody based on
	current receipt, invoice, and settlement data.

	Status progression:
	  Pending → Partly Received → Fully Received
	           → Partly Invoiced → Fully Invoiced
	           → Partly Settled → Fully Settled

	Triggered by:
	  - on_submit / on_cancel of Purchase Receipt (via pr_hooks)
	  - on_submit / on_cancel of Purchase Invoice (via pr_hooks)
	"""
	if not frappe.db.exists("Accountant Custody", accountant_custody_name):
		return

	ac = frappe.get_doc("Accountant Custody", accountant_custody_name)
	if ac.docstatus != 1:
		return

	ac.recalculate_status()

	# Cascade to custodian dashboard
	if ac.custodian:
		update_custodian_dashboard(ac.custodian)


# ─── Cancellation Order Validation ───────────────────────────────────────────

def validate_cancellation_order_for_pi(pi_doc):
	"""
	Prevent cancellation of a Purchase Invoice if a submitted Journal Entry
	or Payment Entry settlement exists for the linked Accountant Custody.
	Called from on_pi_cancel hook.
	"""
	ac_name = pi_doc.get("custom_accountant_custody")
	if not ac_name:
		return

	# Check for submitted settlement JEs
	linked_jes = frappe.db.sql(
		"""SELECT je.name
		   FROM `tabJournal Entry` je
		   WHERE je.custom_accountant_custody = %s AND je.docstatus = 1""",
		(ac_name,),
		as_dict=True,
	)
	if linked_jes:
		frappe.throw(
			frappe._(
				"Cannot cancel Purchase Invoice {0}. Please cancel the linked "
				"settlement Journal Entry/Entries first: {1}"
			).format(
				pi_doc.name,
				", ".join([d.name for d in linked_jes]),
			),
			title=frappe._("Cancel Settlement Documents First"),
		)


def validate_cancellation_order_for_pr(pr_doc):
	"""
	Prevent cancellation of a Purchase Receipt if a submitted Purchase Invoice
	exists for the linked Accountant Custody.
	Called from on_pr_cancel hook.
	"""
	ac_name = pr_doc.get("custom_accountant_custody")
	if not ac_name:
		return

	linked_pis = frappe.get_all(
		"Purchase Invoice",
		filters={"custom_accountant_custody": ac_name, "docstatus": 1},
		fields=["name"],
	)
	if linked_pis:
		frappe.throw(
			frappe._(
				"Cannot cancel Purchase Receipt {0}. Please cancel the linked "
				"Purchase Invoice(s) first: {1}"
			).format(
				pr_doc.name,
				", ".join([d.name for d in linked_pis]),
			),
			title=frappe._("Cancel Purchase Invoices First"),
		)


def validate_advance_cancellation(payment_entry_doc):
	"""
	Strict Hierarchical Cancellation Guard — Stage 1 (Advance).

	Prevent cancellation of an advance Payment Entry (Internal Transfer linked
	to a Custody Request) if any Accountant Custody records have been submitted
	against the same Custody Request.

	This enforces the rule:
	  You cannot cancel the funding (advance) if spending (AC) has already
	  been recorded against it — even if the AC is only partially settled.

	Called from on_pe_cancel hook in pr_hooks.py.
	"""
	# Only applies to advance disbursements (Internal Transfer with a linked CR)
	if payment_entry_doc.payment_type != "Internal Transfer":
		return
	custody_request = payment_entry_doc.get("custom_custody_request")
	if not custody_request:
		return

	# Check for any submitted Accountant Custody linked to this Custody Request
	linked_acs = frappe.get_all(
		"Accountant Custody",
		filters={"custody_request": custody_request, "docstatus": 1},
		fields=["name", "status"],
	)
	if linked_acs:
		frappe.throw(
			frappe._(
				"Cannot cancel advance Payment Entry {0} because the linked "
				"Custody Request {1} already has submitted Accountant Custody "
				"records: {2}. "
				"Please cancel all Accountant Custody records (and their "
				"Purchase Invoices, Purchase Receipts, and settlement entries) "
				"before cancelling this advance."
			).format(
				payment_entry_doc.name,
				custody_request,
				", ".join([d.name for d in linked_acs]),
			),
			title=frappe._("Advance Cannot Be Cancelled"),
		)
