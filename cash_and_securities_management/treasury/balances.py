"""
Centralized Balance Recalculation Engine — v3
treasury/balances.py

All financial recalculations for the Treasury module are consolidated here.
Individual DocType controllers and doc_event hooks call these functions instead
of performing inline calculations. This ensures a single source of truth and
prevents synchronization lag between related documents.

v3 changes:
  - Settlement is now a Payment Entry (not a Journal Entry)
  - validate_cancellation_order_for_pi checks for settlement PEs (not JEs)
  - recalculate_accountant_custody_status recalculates total_settled_amount
    from Custody Settlement Entry rows (which now carry payment_entry links)

Public API:
  update_custodian_dashboard(custodian_id)
  recalculate_custodian_balances(custodian_id)      <- alias for backward compat
  recalculate_custody_request_status(cr_name)
  recalculate_accountant_custody_status(ac_name)
  validate_advance_cancellation(payment_entry_doc)
  validate_cancellation_order_for_pr(pr_doc)
  validate_cancellation_order_for_pi(pi_doc)
"""
import frappe
from frappe import _
from frappe.utils import flt


# ─── Custodian Dashboard Engine ───────────────────────────────────────────────

def update_custodian_dashboard(custodian_id):
	"""
	Recalculate and persist all financial summary fields on a Custodian.
	All figures are derived exclusively from submitted (docstatus=1) documents.

	Fields updated:
	  total_disbursed      — sum of submitted advance Payment Entries
	  total_outstanding    — total_disbursed minus total_claimed
	  total_claimed        — sum of advance_amount_allocated from settlement rows
	  total_pending        — sum of total_amount on submitted but unsettled ACs
	"""
	if not custodian_id or not frappe.db.exists("Custodian", custodian_id):
		return

	# Total disbursed: submitted advance PEs (not settlement PEs)
	total_disbursed = flt(
		frappe.db.sql(
			"""
			SELECT COALESCE(SUM(pe.paid_amount), 0)
			FROM `tabPayment Entry` pe
			WHERE pe.custom_custodian = %s
			  AND pe.docstatus = 1
			  AND (pe.custom_source_document_type IS NULL
			       OR pe.custom_source_document_type NOT IN ('Custody Settlement'))
			""",
			(custodian_id,),
		)[0][0]
		or 0
	)

	# Total claimed: advance deductions from settlement PE rows
	total_claimed = flt(
		frappe.db.sql(
			"""
			SELECT COALESCE(SUM(cse.advance_amount_allocated), 0)
			FROM `tabCustody Settlement Entry` cse
			JOIN `tabAccountant Custody` ac ON ac.name = cse.parent
			WHERE ac.custodian = %s AND ac.docstatus = 1
			""",
			(custodian_id,),
		)[0][0]
		or 0
	)

	# Total outstanding = disbursed - claimed
	total_outstanding = total_disbursed - total_claimed

	# Total pending: submitted ACs not yet fully settled
	total_pending = flt(
		frappe.db.sql(
			"""
			SELECT COALESCE(SUM(total_amount), 0)
			FROM `tabAccountant Custody`
			WHERE custodian = %s
			  AND docstatus = 1
			  AND status NOT IN ('Fully Settled', 'Closed', 'Cancelled')
			""",
			(custodian_id,),
		)[0][0]
		or 0
	)

	frappe.db.set_value(
		"Custodian",
		custodian_id,
		{
			"total_disbursed": total_disbursed,
			"total_outstanding": total_outstanding,
			"total_claimed": total_claimed,
			"total_pending": total_pending,
		},
		update_modified=False,
	)


# Backward-compatibility alias
def recalculate_custodian_balances(custodian_id):
	"""Alias for update_custodian_dashboard — kept for backward compatibility."""
	return update_custodian_dashboard(custodian_id)


# ─── Custody Request Status Engine ───────────────────────────────────────────

def recalculate_custody_request_status(cr_name):
	"""
	Recalculate paid_amount, remaining_to_pay, and status for a Custody Request
	based on all submitted Payment Entries linked to it.

	Status map:
	  paid_amount = 0                    → Approved
	  0 < paid_amount < advance_amount   → Partly Paid
	  paid_amount >= advance_amount      → Paid

	Triggered by:
	  - on_submit / on_cancel of advance Payment Entry (via pr_hooks)
	"""
	if not cr_name or not frappe.db.exists("Custody Request", cr_name):
		return

	cr = frappe.db.get_value(
		"Custody Request",
		cr_name,
		["advance_amount", "docstatus", "custodian"],
		as_dict=True,
	)
	if not cr or cr.docstatus != 1:
		return

	# Sum all submitted advance PEs for this CR
	total_paid = flt(
		frappe.db.sql(
			"""
			SELECT COALESCE(SUM(paid_amount), 0)
			FROM `tabPayment Entry`
			WHERE custom_custody_request = %s
			  AND docstatus = 1
			  AND (custom_source_document_type IS NULL
			       OR custom_source_document_type NOT IN ('Custody Settlement'))
			""",
			(cr_name,),
		)[0][0]
		or 0
	)

	advance_amount = flt(cr.advance_amount)
	remaining = advance_amount - total_paid

	if total_paid <= 0:
		new_status = "Approved"
	elif total_paid < advance_amount:
		new_status = "Partly Paid"
	else:
		new_status = "Paid"

	frappe.db.set_value(
		"Custody Request",
		cr_name,
		{
			"paid_amount": total_paid,
			"remaining_to_pay": remaining,
			"status": new_status,
		},
		update_modified=False,
	)

	# Sync the PE child table
	try:
		cr_doc = frappe.get_doc("Custody Request", cr_name)
		cr_doc._sync_payment_entries_table()
	except Exception as e:
		frappe.log_error(str(e), f"recalculate_custody_request_status: PE table sync failed for {cr_name}")

	# Cascade to custodian dashboard
	if cr.custodian:
		update_custodian_dashboard(cr.custodian)


# ─── Accountant Custody Status Engine ────────────────────────────────────────

def recalculate_accountant_custody_status(ac_name):
	"""
	Recalculate total_settled_amount and the granular status of an Accountant
	Custody based on current receipt, invoice, and settlement PE data.

	Status progression:
	  Draft → Pending Receipt → Pending Invoice → Pending Settlement
	        → Partly Settled → Fully Settled

	Triggered by:
	  - on_submit / on_cancel of Purchase Receipt (via pr_hooks)
	  - on_submit / on_cancel of Purchase Invoice (via pr_hooks)
	  - on_submit / on_cancel of settlement Payment Entry (via pr_hooks)
	"""
	if not ac_name or not frappe.db.exists("Accountant Custody", ac_name):
		return

	# Recalculate total_settled_amount from live settlement rows
	new_total = flt(
		frappe.db.sql(
			"""
			SELECT COALESCE(SUM(total_settlement_amount), 0)
			FROM `tabCustody Settlement Entry`
			WHERE parent = %s AND parenttype = 'Accountant Custody'
			""",
			(ac_name,),
		)[0][0]
		or 0
	)
	frappe.db.set_value(
		"Accountant Custody", ac_name, "total_settled_amount", new_total,
		update_modified=False,
	)

	# Reload and recalculate status
	ac_doc = frappe.get_doc("Accountant Custody", ac_name)
	if ac_doc.docstatus == 1:
		ac_doc.recalculate_status()

	# Cascade to custodian dashboard
	if ac_doc.custodian:
		update_custodian_dashboard(ac_doc.custodian)


# ─── Cancellation Order Validation ───────────────────────────────────────────

def validate_advance_cancellation(payment_entry_doc):
	"""
	Strict Hierarchical Cancellation Guard — Stage 1 (Advance).

	Prevent cancellation of an advance Payment Entry if any Accountant Custody
	records have been submitted against the linked Custody Request.

	Hierarchy:
	  Settlement PE → Purchase Invoice → Purchase Receipt
	  → Accountant Custody → Custody Request → Advance PE
	"""
	custody_request = payment_entry_doc.get("custom_custody_request")
	if not custody_request:
		return

	linked_acs = frappe.get_all(
		"Accountant Custody",
		filters={"custody_request": custody_request, "docstatus": 1},
		fields=["name", "status"],
	)
	if linked_acs:
		frappe.throw(
			_(
				"Cannot cancel advance Payment Entry {0} — Custody Request {1} "
				"has submitted Accountant Custody records: {2}. "
				"Please cancel all Accountant Custody records (and their Purchase "
				"Invoices, Purchase Receipts, and settlement Payment Entries) first."
			).format(
				payment_entry_doc.name,
				custody_request,
				", ".join(d.name for d in linked_acs),
			),
			title=_("Advance Cannot Be Cancelled"),
		)


def validate_cancellation_order_for_pr(pr_doc):
	"""
	Prevent cancellation of a Purchase Receipt if a submitted Purchase Invoice
	already references it.
	"""
	linked_pis = frappe.get_all(
		"Purchase Invoice",
		filters={"custom_accountant_custody": pr_doc.get("custom_accountant_custody"), "docstatus": 1},
		fields=["name"],
	) if pr_doc.get("custom_accountant_custody") else []

	# Also check via PR item references
	if not linked_pis:
		linked_pis = frappe.get_all(
			"Purchase Invoice Item",
			filters={"purchase_receipt": pr_doc.name, "docstatus": 1},
			fields=["parent"],
			distinct=True,
		)
		linked_pis = [{"name": d.parent} for d in linked_pis]

	if linked_pis:
		frappe.throw(
			_(
				"Cannot cancel Purchase Receipt {0} — it has been billed in "
				"Purchase Invoice(s): {1}. Please cancel those invoices first."
			).format(
				pr_doc.name,
				", ".join(d["name"] for d in linked_pis),
			),
			title=_("Cancel Purchase Invoices First"),
		)


def validate_cancellation_order_for_pi(pi_doc):
	"""
	Prevent cancellation of a Purchase Invoice if a submitted settlement
	Payment Entry references it.

	v3: Checks Payment Entry References table (not Journal Entry).
	"""
	# Check via Payment Entry References table
	linked_pes = frappe.db.sql(
		"""
		SELECT per.parent
		FROM `tabPayment Entry Reference` per
		JOIN `tabPayment Entry` pe ON pe.name = per.parent
		WHERE per.reference_doctype = 'Purchase Invoice'
		  AND per.reference_name = %s
		  AND pe.docstatus = 1
		""",
		(pi_doc.name,),
		as_dict=True,
	)

	if linked_pes:
		frappe.throw(
			_(
				"Cannot cancel Purchase Invoice {0} — it has been settled by "
				"Payment Entry(s): {1}. Please cancel those payment entries first."
			).format(
				pi_doc.name,
				", ".join(d.parent for d in linked_pes),
			),
			title=_("Cancel Settlement Payment Entries First"),
		)

	# Also check for any settlement PEs linked via custom_accountant_custody
	ac_name = pi_doc.get("custom_accountant_custody")
	if ac_name:
		linked_settlement_pes = frappe.get_all(
			"Payment Entry",
			filters={
				"custom_accountant_custody": ac_name,
				"custom_source_document_type": "Custody Settlement",
				"docstatus": 1,
			},
			fields=["name"],
		)
		if linked_settlement_pes:
			frappe.throw(
				_(
					"Cannot cancel Purchase Invoice {0} — Accountant Custody {1} "
					"has submitted settlement Payment Entry(s): {2}. "
					"Please cancel those first."
				).format(
					pi_doc.name,
					ac_name,
					", ".join(d.name for d in linked_settlement_pes),
				),
				title=_("Cancel Settlement Payment Entries First"),
			)
