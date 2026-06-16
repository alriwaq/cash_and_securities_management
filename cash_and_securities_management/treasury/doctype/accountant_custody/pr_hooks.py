"""
Document Event Hooks — v5  (Single Self-Settling Account + Auto-Reconciliation)
treasury/doctype/accountant_custody/pr_hooks.py

All doc_event handlers for Purchase Receipt, Purchase Invoice, and Payment Entry.

Single-Account Model:
  PI.credit_to  = custody_account (Custody type, party_type=Custodian)
  PE.paid_to    = custody_account (Custody type, party_type=Custodian)
  Both documents share the same party → ERPNext reconciliation engine works natively.

Two-way auto-reconciliation:
  Trigger A — PI submitted  → search for unreconciled PEs (FIFO), allocate, record.
  Trigger B — PE submitted  → search for unreconciled PIs (FIFO), allocate, record.

Cancellation order enforced (strict hierarchy):
  Purchase Invoice → Purchase Receipt → Accountant Custody → Custody Request → Advance PE
"""
import frappe
from frappe import _
from frappe.utils import flt, nowdate

CONSOLIDATED = "Consolidated (Party-Based)"


# ─── Purchase Receipt Hooks ───────────────────────────────────────────────────

def on_pr_validate(doc, method):
	"""
	Propagates custom_accountant_custody and custom_custodian from the AC.
	Validates that PR item quantities do not exceed AC item quantities.
	"""
	if doc.get("custom_accountant_custody"):
		if not doc.get("custom_source_document_type"):
			doc.custom_source_document_type = "Custody"

		if not doc.get("custom_custodian"):
			custodian = frappe.db.get_value(
				"Accountant Custody",
				doc.custom_accountant_custody,
				"custodian",
			)
			if custodian:
				doc.custom_custodian = custodian

		_validate_pr_qty_against_ac(doc)


def on_pr_before_submit(doc, method):
	"""
	Submit-time custody swap for Purchase Receipt.
	Routes stock_received_but_not_billed to the custodian's custody_account.
	Also sets party_type=Custodian so the PR is visible in reconciliation.
	"""
	if not _is_custody_purchase_doc(doc):
		return

	if doc.get("custom_accountant_custody"):
		_validate_pr_qty_against_ac(doc)

	ac_doc, custodian = _resolve_custody_context(doc)
	if not ac_doc:
		return

	doc.custom_source_document_type = "Custody"
	if custodian and not doc.get("custom_custodian"):
		doc.custom_custodian = custodian

	# In single-account model: stock_received_but_not_billed → custody_account
	custody_account = frappe.db.get_value("Custodian", ac_doc.custodian, "custody_account")
	if custody_account and doc.meta.has_field("stock_received_but_not_billed"):
		doc.stock_received_but_not_billed = custody_account

	# Set party so PR is visible in reconciliation tool
	if custodian:
		doc.party_type = "Custodian"
		doc.party = custodian


def on_pr_submit(doc, method):
	"""Updates received quantities on the linked Accountant Custody."""
	if not doc.get("custom_accountant_custody"):
		return

	ac_doc = frappe.get_doc("Accountant Custody", doc.custom_accountant_custody)
	ac_doc.update_received_quantities()

	if doc.get("custom_custodian"):
		_safe_update_custodian_dashboard(doc.custom_custodian)


def on_pr_cancel(doc, method):
	"""Enforces cancellation order, then resets received quantities."""
	if not doc.get("custom_accountant_custody"):
		return

	from cash_and_securities_management.treasury.balances import (
		validate_cancellation_order_for_pr,
	)
	validate_cancellation_order_for_pr(doc)

	ac_doc = frappe.get_doc("Accountant Custody", doc.custom_accountant_custody)
	ac_doc.update_received_quantities()

	if doc.get("custom_custodian"):
		_safe_update_custodian_dashboard(doc.custom_custodian)


# ─── Purchase Invoice Hooks ───────────────────────────────────────────────────

def on_pi_validate(doc, method):
	"""
	Propagates custom_accountant_custody and custom_custodian from the linked PR.
	Sets custom_source_document_type = 'Custody' and validates AC status.
	"""
	if not doc.get("custom_accountant_custody"):
		for pi_item in doc.items:
			if pi_item.get("purchase_receipt"):
				pr_ac = frappe.db.get_value(
					"Purchase Receipt", pi_item.purchase_receipt, "custom_accountant_custody"
				)
				pr_custodian = frappe.db.get_value(
					"Purchase Receipt", pi_item.purchase_receipt, "custom_custodian"
				)
				pr_source_type = frappe.db.get_value(
					"Purchase Receipt", pi_item.purchase_receipt, "custom_source_document_type"
				)
				if pr_ac:
					doc.custom_accountant_custody = pr_ac
				if pr_custodian:
					doc.custom_custodian = pr_custodian
				if pr_source_type and not doc.get("custom_source_document_type"):
					doc.custom_source_document_type = pr_source_type
				break

	if not doc.get("custom_accountant_custody"):
		return

	if not doc.get("custom_source_document_type"):
		doc.custom_source_document_type = "Custody"

	ac_name = doc.custom_accountant_custody
	ac_doc = frappe.get_doc("Accountant Custody", ac_name)

	if ac_doc.status in ("Fully Invoiced", "Closed", "Cancelled"):
		frappe.throw(
			_("Cannot modify a Purchase Invoice linked to a {0} Accountant Custody {1}.").format(
				ac_doc.status, ac_name
			)
		)


def on_pi_before_submit(doc, method):
	"""
	Submit-time custody swap for Purchase Invoice.
	Routes credit_to to the custodian's single custody_account (Custody type).
	This is the self-settling step: PI credit reduces the advance balance.
	"""
	if not _is_custody_purchase_doc(doc):
		return

	ac_doc, custodian = _resolve_custody_context(doc)
	if not ac_doc:
		return

	doc.custom_source_document_type = "Custody"
	if custodian and not doc.get("custom_custodian"):
		doc.custom_custodian = custodian

	# Single-account model: credit_to = custody_account (Custody type)
	custody_account = frappe.db.get_value("Custodian", ac_doc.custodian, "custody_account")
	if not custody_account:
		frappe.throw(
			_("Custody Account is not configured for Custodian {0}. "
			  "Please submit the Custodian record to auto-create the account.").format(
				ac_doc.custodian
			),
			title=_("Missing Custody Account"),
		)

	doc.credit_to = custody_account


def on_pi_submit(doc, method):
	"""
	Triggered after a Purchase Invoice is submitted.
	Updates billed quantities on the AC, then triggers auto-reconciliation
	(Trigger A: PI submitted → search for available advance PEs).
	"""
	if not doc.get("custom_accountant_custody"):
		return

	ac_doc = frappe.get_doc("Accountant Custody", doc.custom_accountant_custody)
	ac_doc.update_billed_quantities(pi_name=doc.name)

	# Trigger A: reconcile this PI against available advance PEs (FIFO)
	_auto_reconcile_pi_against_pes(doc)

	if doc.get("custom_custodian"):
		_safe_update_custodian_dashboard(doc.custom_custodian)


def on_pi_cancel(doc, method):
	"""Triggered after a Purchase Invoice is cancelled."""
	if not doc.get("custom_accountant_custody"):
		return

	from cash_and_securities_management.treasury.balances import (
		validate_cancellation_order_for_pi,
	)
	validate_cancellation_order_for_pi(doc)

	ac_doc = frappe.get_doc("Accountant Custody", doc.custom_accountant_custody)
	ac_doc.update_billed_quantities()

	if doc.get("custom_custodian"):
		_safe_update_custodian_dashboard(doc.custom_custodian)


# ─── Payment Entry Hooks ──────────────────────────────────────────────────────

def on_payment_before_submit(doc, method):
	"""
	Bypass ERPNext's party-account type validation for custody advance PEs.
	In the single-account model, party_type=Custodian is used with a Custody
	account — ERPNext's default check expects Payable/Receivable, so we must
	bypass it for custody PEs.
	"""
	if not _is_custody_pe(doc):
		return

	doc.flags.ignore_permissions = True

	if not doc.get("custom_source_document_type"):
		doc.custom_source_document_type = "Custody Advance"

	# Ensure party fields are set for Consolidated mode
	if doc.get("custom_custodian") and not doc.get("party"):
		settings = frappe.db.get_singles_dict("Treasury Settings")
		mode = settings.get("accounting_mode") or CONSOLIDATED
		if mode == CONSOLIDATED:
			doc.party_type = "Custodian"
			doc.party = doc.custom_custodian


def on_payment_submit(doc, method):
	"""
	Triggered after a Payment Entry is submitted.
	Handles advance disbursement PEs: recalculate CR paid_amount.
	Trigger B: PE submitted → search for unreconciled PIs (FIFO).
	"""
	custody_request = doc.get("custom_custody_request")
	if custody_request:
		_safe_recalculate_custody_request(custody_request)

	custodian = doc.get("custom_custodian")
	if custodian:
		_safe_update_custodian_dashboard(custodian)

	# Trigger B: if this is a custody advance PE, reconcile against outstanding PIs
	if _is_custody_pe(doc) and doc.get("custom_custodian"):
		_auto_reconcile_pe_against_pis(doc)


def on_payment_cancel(doc, method):
	"""
	Triggered after a Payment Entry is cancelled.
	Handles advance PE: enforce strict hierarchy guard, then recalculate CR.
	"""
	custody_request = doc.get("custom_custody_request")
	if custody_request:
		from cash_and_securities_management.treasury.balances import (
			validate_advance_cancellation,
		)
		validate_advance_cancellation(doc)
		_safe_recalculate_custody_request(custody_request)

	custodian = doc.get("custom_custodian")
	if custodian:
		_safe_update_custodian_dashboard(custodian)


# ─── Journal Entry Hooks ──────────────────────────────────────────────────────

def on_journal_submit(doc, method):
	"""If linked to an Accountant Custody, recalculates status."""
	ac_name = doc.get("custom_accountant_custody")
	if not ac_name:
		return
	try:
		from cash_and_securities_management.treasury.balances import (
			recalculate_accountant_custody_status,
		)
		recalculate_accountant_custody_status(ac_name)
	except Exception as e:
		frappe.log_error(str(e), f"on_journal_submit: failed to update AC {ac_name}")


def on_journal_cancel(doc, method):
	"""Recalculates the linked Accountant Custody status."""
	ac_name = doc.get("custom_accountant_custody")
	if not ac_name:
		return
	try:
		from cash_and_securities_management.treasury.balances import (
			recalculate_accountant_custody_status,
		)
		recalculate_accountant_custody_status(ac_name)
	except Exception as e:
		frappe.log_error(str(e), f"on_journal_cancel: failed to update AC {ac_name}")


# ─── Auto-Reconciliation Engine ───────────────────────────────────────────────

def _auto_reconcile_pi_against_pes(pi_doc):
	"""
	Trigger A: Called when a custody PI is submitted.
	Finds all unreconciled advance PEs for the same custodian + custody account,
	ordered by posting_date ASC (FIFO), and allocates as much as available
	against this PI's outstanding amount.
	Records each allocation in the linked Accountant Custody's reconciliation table.
	"""
	custodian = pi_doc.get("custom_custodian") or pi_doc.get("party")
	ac_name = pi_doc.get("custom_accountant_custody")
	if not custodian or not ac_name:
		return

	custody_account = frappe.db.get_value("Custodian", custodian, "custody_account")
	if not custody_account:
		return

	# Get current outstanding on this PI
	pi_outstanding = flt(
		frappe.db.get_value("Purchase Invoice", pi_doc.name, "outstanding_amount")
	)
	if pi_outstanding <= 0:
		return

	# Find unreconciled advance PEs for this custodian on this custody account (FIFO)
	unreconciled_pes = frappe.db.sql(
		"""
		SELECT
			pe.name,
			pe.posting_date,
			pe.unallocated_amount
		FROM `tabPayment Entry` pe
		WHERE pe.party_type = 'Custodian'
		  AND pe.party = %(custodian)s
		  AND pe.paid_to = %(account)s
		  AND pe.docstatus = 1
		  AND pe.unallocated_amount > 0.001
		ORDER BY pe.posting_date ASC, pe.creation ASC
		""",
		{"custodian": custodian, "account": custody_account},
		as_dict=True,
	)

	if not unreconciled_pes:
		return

	for pe_row in unreconciled_pes:
		if pi_outstanding <= 0:
			break

		pe_outstanding_before = flt(pe_row.unallocated_amount)
		pi_outstanding_before = pi_outstanding
		allocate = min(pe_outstanding_before, pi_outstanding)

		try:
			_create_payment_reconciliation_entry(
				company=pi_doc.company,
				party_type="Custodian",
				party=custodian,
				payment_entry=pe_row.name,
				purchase_invoice=pi_doc.name,
				allocated_amount=allocate,
				account=custody_account,
			)
		except Exception as e:
			frappe.log_error(
				str(e),
				f"_auto_reconcile_pi_against_pes: failed PE={pe_row.name} PI={pi_doc.name}",
			)
			continue

		pe_outstanding_after = pe_outstanding_before - allocate
		pi_outstanding -= allocate
		pi_outstanding_after = pi_outstanding

		# Record in Accountant Custody reconciliation table
		_record_reconciliation(
			ac_name=ac_name,
			payment_entry=pe_row.name,
			purchase_invoice=pi_doc.name,
			allocated_amount=allocate,
			pe_outstanding_before=pe_outstanding_before,
			pe_outstanding_after=pe_outstanding_after,
			pi_outstanding_before=pi_outstanding_before,
			pi_outstanding_after=pi_outstanding_after,
		)

	# Update Custody Request status after reconciliation
	cr_name = frappe.db.get_value("Accountant Custody", ac_name, "custody_request")
	if cr_name:
		_safe_recalculate_custody_request(cr_name)


def _auto_reconcile_pe_against_pis(pe_doc):
	"""
	Trigger B: Called when a custody advance PE is submitted.
	Finds all unreconciled custody PIs for the same custodian + custody account,
	ordered by posting_date ASC (FIFO), and allocates as much as available
	from this PE's unallocated amount against outstanding PIs.
	Records each allocation in the linked Accountant Custody's reconciliation table.
	"""
	custodian = pe_doc.get("custom_custodian") or pe_doc.get("party")
	if not custodian:
		return

	custody_account = frappe.db.get_value("Custodian", custodian, "custody_account")
	if not custody_account:
		return

	# Get current unallocated amount on this PE
	pe_unallocated = flt(
		frappe.db.get_value("Payment Entry", pe_doc.name, "unallocated_amount")
	)
	if pe_unallocated <= 0:
		return

	# Find unreconciled custody PIs for this custodian on this custody account (FIFO)
	# NOTE: tabPurchase Invoice has no party_type/party columns in ERPNext v15.
	# Custody PIs are identified by custom_custodian + custom_source_document_type.
	unreconciled_pis = frappe.db.sql(
		"""
		SELECT
			pi.name,
			pi.posting_date,
			pi.outstanding_amount,
			pi.custom_accountant_custody
		FROM `tabPurchase Invoice` pi
		WHERE pi.custom_custodian = %(custodian)s
		  AND pi.custom_source_document_type = 'Custody'
		  AND pi.credit_to = %(account)s
		  AND pi.docstatus = 1
		  AND pi.outstanding_amount > 0.001
		ORDER BY pi.posting_date ASC, pi.creation ASC
		""",
		{"custodian": custodian, "account": custody_account},
		as_dict=True,
	)

	if not unreconciled_pis:
		return

	for pi_row in unreconciled_pis:
		if pe_unallocated <= 0:
			break

		pi_outstanding_before = flt(pi_row.outstanding_amount)
		pe_outstanding_before = pe_unallocated
		allocate = min(pe_unallocated, pi_outstanding_before)

		try:
			_create_payment_reconciliation_entry(
				company=pe_doc.company,
				party_type="Custodian",
				party=custodian,
				payment_entry=pe_doc.name,
				purchase_invoice=pi_row.name,
				allocated_amount=allocate,
				account=custody_account,
			)
		except Exception as e:
			frappe.log_error(
				str(e),
				f"_auto_reconcile_pe_against_pis: failed PE={pe_doc.name} PI={pi_row.name}",
			)
			continue

		pe_unallocated -= allocate
		pe_outstanding_after = pe_unallocated
		pi_outstanding_after = pi_outstanding_before - allocate

		# Record in the PI's linked Accountant Custody reconciliation table
		ac_name = pi_row.get("custom_accountant_custody")
		if ac_name:
			_record_reconciliation(
				ac_name=ac_name,
				payment_entry=pe_doc.name,
				purchase_invoice=pi_row.name,
				allocated_amount=allocate,
				pe_outstanding_before=pe_outstanding_before,
				pe_outstanding_after=pe_outstanding_after,
				pi_outstanding_before=pi_outstanding_before,
				pi_outstanding_after=pi_outstanding_after,
			)

			# Update Custody Request status after reconciliation
			cr_name = frappe.db.get_value("Accountant Custody", ac_name, "custody_request")
			if cr_name:
				_safe_recalculate_custody_request(cr_name)


def _create_payment_reconciliation_entry(
	company, party_type, party, payment_entry, purchase_invoice, allocated_amount, account
):
	"""
	Uses ERPNext's reconcile_against_document utility directly to bypass the
	Payment Reconciliation doctype validation (which rejects Custody account types).
	This correctly links the PE and PI and updates outstanding amounts.
	"""
	from erpnext.accounts.utils import reconcile_against_document

	args = frappe._dict({
		"voucher_type": "Payment Entry",
		"voucher_no": payment_entry,
		"voucher_detail_no": None,
		"against_voucher_type": "Purchase Invoice",
		"against_voucher": purchase_invoice,
		"account": account,
		"party_type": party_type,
		"party": party,
		"dr_or_cr": "credit_in_account_currency",
		"unadjusted_amount": flt(allocated_amount),
		"allocated_amount": flt(allocated_amount),
		"unreconciled_amount": flt(allocated_amount),
		"exchange_rate": 1.0,
		"account_currency": frappe.db.get_value("Account", account, "account_currency")
	})

	reconcile_against_document([args])


def _record_reconciliation(
	ac_name,
	payment_entry,
	purchase_invoice,
	allocated_amount,
	pe_outstanding_before,
	pe_outstanding_after,
	pi_outstanding_before,
	pi_outstanding_after,
):
	"""
	Appends a row to the Accountant Custody's reconciliation child table
	and updates total_allocated_amount. Uses db_set to avoid triggering
	the full AC validate cycle.
	"""
	try:
		# Check if this combination is already recorded to avoid duplicates
		existing = frappe.db.exists(
			"Accountant Custody Reconciliation",
			{
				"parent": ac_name,
				"payment_entry": payment_entry,
				"purchase_invoice": purchase_invoice,
			},
		)
		if existing:
			return

		ac_doc = frappe.get_doc("Accountant Custody", ac_name)
		ac_doc.append("reconciliations", {
			"payment_entry": payment_entry,
			"purchase_invoice": purchase_invoice,
			"reconciliation_date": nowdate(),
			"allocated_amount": allocated_amount,
			"pe_outstanding_before": pe_outstanding_before,
			"pe_outstanding_after": pe_outstanding_after,
			"pi_outstanding_before": pi_outstanding_before,
			"pi_outstanding_after": pi_outstanding_after,
		})

		# Recalculate total_allocated_amount
		total_allocated = sum(flt(r.allocated_amount) for r in ac_doc.reconciliations)
		ac_doc.total_allocated_amount = total_allocated

		ac_doc.flags.ignore_permissions = True
		ac_doc.flags.ignore_validate = True
		ac_doc.save()

	except Exception as e:
		frappe.log_error(
			str(e),
			f"_record_reconciliation: failed for AC={ac_name} PE={payment_entry} PI={purchase_invoice}",
		)


# ─── Private helpers ──────────────────────────────────────────────────────────

def _validate_pr_qty_against_ac(doc):
	"""
	Validate that total received qty (existing submitted PRs + this PR)
	does not exceed the allowed qty on the Accountant Custody for each item.
	"""
	ac_name = doc.get("custom_accountant_custody")
	if not ac_name:
		return

	ac_items = frappe.db.sql(
		"""
		SELECT aci.item_code, SUM(aci.qty) AS allowed_qty
		FROM `tabAccountant Custody Item` aci
		WHERE aci.parent = %s AND aci.parenttype = 'Accountant Custody'
		GROUP BY aci.item_code
		""",
		(ac_name,),
		as_dict=True,
	)
	allowed_qty_map = {d.item_code: flt(d.allowed_qty) for d in ac_items}
	if not allowed_qty_map:
		return

	already_received = frappe.db.sql(
		"""
		SELECT pri.item_code, SUM(pri.qty) AS received_qty
		FROM `tabPurchase Receipt Item` pri
		JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
		WHERE pr.custom_accountant_custody = %s
		  AND pr.docstatus = 1
		  AND pr.name != %s
		GROUP BY pri.item_code
		""",
		(ac_name, doc.name or ""),
		as_dict=True,
	)
	received_qty_map = {d.item_code: flt(d.received_qty) for d in already_received}

	errors = []
	for pr_item in doc.items:
		item_code = pr_item.item_code
		allowed = allowed_qty_map.get(item_code)
		if allowed is None:
			continue
		existing_received = received_qty_map.get(item_code, 0)
		new_qty = flt(pr_item.qty)
		total_after = existing_received + new_qty
		if total_after > allowed + 0.001:
			errors.append(
				_("Row {0}: Item {1} — qty {2} would bring total received to {3}, "
				  "exceeding allowed qty {4} on Accountant Custody {5}").format(
					pr_item.idx, frappe.bold(item_code), new_qty,
					total_after, allowed, ac_name
				)
			)

	if errors:
		frappe.throw(
			"<br>".join(errors),
			title=_("Quantity Exceeds Accountant Custody Limit"),
		)


def _is_custody_purchase_doc(doc):
	"""Return True if this PR/PI is linked to an Accountant Custody."""
	return bool(doc.get("custom_accountant_custody"))


def _is_custody_pe(doc):
	"""Return True if this PE is a custody advance or custody-related PE."""
	return bool(doc.get("custom_custodian") or doc.get("custom_custody_request"))


def _resolve_custody_context(doc):
	"""
	Return (ac_doc, custodian_name) for a PR/PI linked to an Accountant Custody.
	Returns (None, None) if not linked.
	"""
	ac_name = doc.get("custom_accountant_custody")
	if not ac_name:
		return None, None
	try:
		ac_doc = frappe.get_doc("Accountant Custody", ac_name)
		return ac_doc, ac_doc.custodian
	except Exception:
		return None, None


def _safe_update_custodian_dashboard(custodian_id):
	try:
		from cash_and_securities_management.treasury.balances import (
			update_custodian_dashboard,
		)
		update_custodian_dashboard(custodian_id)
	except Exception as e:
		frappe.log_error(str(e), f"_safe_update_custodian_dashboard: {custodian_id}")


def _safe_recalculate_custody_request(cr_name):
	try:
		from cash_and_securities_management.treasury.balances import (
			recalculate_custody_request_status,
		)
		recalculate_custody_request_status(cr_name)
	except Exception as e:
		frappe.log_error(str(e), f"_safe_recalculate_custody_request: {cr_name}")
