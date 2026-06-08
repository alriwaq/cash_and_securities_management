"""
Document Event Hooks — v4  (Single Self-Settling Account)
treasury/doctype/accountant_custody/pr_hooks.py

All doc_event handlers for Purchase Receipt, Purchase Invoice, and Payment Entry.

Single-Account Model:
  PI.credit_to = custody_account (Receivable, party_type=Custodian)
  No Settlement Payment Entry is needed — the PI credit self-settles the advance.

Cancellation order enforced (strict hierarchy):
  Purchase Invoice → Purchase Receipt → Accountant Custody → Custody Request → Advance PE
"""
import frappe
from frappe import _
from frappe.utils import flt

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
	Routes credit_to to the custodian's single custody_account (Receivable).
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

	# Single-account model: credit_to = custody_account (Receivable)
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
	doc.party_type = "Custodian"
	doc.party = doc.custom_custodian or custodian
	doc.party_account_currency = (
		frappe.db.get_value("Account", custody_account, "account_currency")
		or frappe.db.get_value("Company", doc.company, "default_currency")
	)


def on_pi_submit(doc, method):
	"""Triggered after a Purchase Invoice is submitted."""
	if not doc.get("custom_accountant_custody"):
		return

	ac_doc = frappe.get_doc("Accountant Custody", doc.custom_accountant_custody)
	ac_doc.update_billed_quantities(pi_name=doc.name)

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
	In the single-account model, party_type=Custodian is used with a Receivable
	account — ERPNext's default check expects Receivable → Debtor, so we must
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
	"""
	custody_request = doc.get("custom_custody_request")
	if custody_request:
		_safe_recalculate_custody_request(custody_request)

	custodian = doc.get("custom_custodian")
	if custodian:
		_safe_update_custodian_dashboard(custodian)


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
