"""
Document Event Hooks — v3
treasury/doctype/accountant_custody/pr_hooks.py

All doc_event handlers for Purchase Receipt, Purchase Invoice, Payment Entry,
and Journal Entry. Each handler delegates financial recalculations to the
centralized balance engine in treasury/balances.py.

Key v3 changes:
  - Settlement is now a Payment Entry (not a Journal Entry)
  - on_payment_before_submit: bypass supplier validation for custody settlement PEs
  - on_payment_submit: handles both advance PEs and settlement PEs
  - on_payment_cancel: handles both advance PEs and settlement PEs

Cancellation order enforced (strict hierarchy):
  Settlement PE → Purchase Invoice → Purchase Receipt → Accountant Custody → Custody Request
  Advance Payment Entry cannot be cancelled if any Accountant Custody records
  have been submitted against the linked Custody Request.
"""
import frappe
from frappe import _
from frappe.utils import flt


# ─── Purchase Receipt Hooks ───────────────────────────────────────────────────

def on_pr_validate(doc, method):
	"""
	Triggered on Purchase Receipt validate.
	Propagates custom_accountant_custody and custom_custodian from the AC
	if not already set (handles the case where PR is created via the AC button).
	Also validates that PR item quantities do not exceed AC item quantities.
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

		# ── PR Qty Validation ─────────────────────────────────────────────────
		# Ensure that the total received qty (existing submitted PRs + this PR)
		# does not exceed the allowed qty on the Accountant Custody for each item.
		_validate_pr_qty_against_ac(doc)


def on_pr_before_submit(doc, method):
	"""
	Submit-time custody swap for Purchase Receipt.
	Redirects the payable-side account to the Custodian account.
	"""
	if not _is_custody_purchase_doc(doc):
		return

	ac_doc, custodian = _resolve_custody_context(doc)
	if not ac_doc:
		return

	doc.custom_source_document_type = "Custody"
	if custodian and not doc.get("custom_custodian"):
		doc.custom_custodian = custodian

	_advance_account, payable_account = ac_doc._get_custodian_accounts()
	if doc.meta.has_field("stock_received_but_not_billed"):
		doc.stock_received_but_not_billed = payable_account


def on_pr_submit(doc, method):
	"""
	Triggered after a Purchase Receipt is submitted.
	Updates received quantities on the linked Accountant Custody.
	Errors are NOT silenced — they propagate to the user.
	"""
	if not doc.get("custom_accountant_custody"):
		return

	ac_name = doc.custom_accountant_custody
	ac_doc = frappe.get_doc("Accountant Custody", ac_name)
	ac_doc.update_received_quantities()

	if doc.get("custom_custodian"):
		_safe_update_custodian_dashboard(doc.custom_custodian)


def on_pr_cancel(doc, method):
	"""
	Triggered after a Purchase Receipt is cancelled.
	Enforces cancellation order, then resets received quantities.
	Errors are NOT silenced — they propagate to the user.
	"""
	if not doc.get("custom_accountant_custody"):
		return

	from cash_and_securities_management.treasury.balances import (
		validate_cancellation_order_for_pr,
	)
	validate_cancellation_order_for_pr(doc)

	ac_name = doc.custom_accountant_custody
	ac_doc = frappe.get_doc("Accountant Custody", ac_name)
	ac_doc.update_received_quantities()

	if doc.get("custom_custodian"):
		_safe_update_custodian_dashboard(doc.custom_custodian)


# ─── Purchase Invoice Hooks ───────────────────────────────────────────────────

def on_pi_validate(doc, method):
	"""
	Triggered on Purchase Invoice validate.
	Propagates custom_accountant_custody and custom_custodian from the linked PR.
	"""
	if not doc.get("custom_accountant_custody"):
		for pi_item in doc.items:
			if pi_item.get("purchase_receipt"):
				pr_ac = frappe.db.get_value(
					"Purchase Receipt",
					pi_item.purchase_receipt,
					"custom_accountant_custody",
				)
				pr_custodian = frappe.db.get_value(
					"Purchase Receipt",
					pi_item.purchase_receipt,
					"custom_custodian",
				)
				pr_source_type = frappe.db.get_value(
					"Purchase Receipt",
					pi_item.purchase_receipt,
					"custom_source_document_type",
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

	if ac_doc.status in ("Fully Settled", "Closed", "Cancelled"):
		frappe.throw(
			_("Cannot modify a Purchase Invoice linked to a {0} Accountant Custody {1}.").format(
				ac_doc.status, ac_name
			)
		)


def on_pi_before_submit(doc, method):
	"""
	Submit-time custody swap for Purchase Invoice.
	Enforces Custodian party/account mapping immediately before GL posting.
	"""
	if not _is_custody_purchase_doc(doc):
		return

	ac_doc, custodian = _resolve_custody_context(doc)
	if not ac_doc:
		return

	doc.custom_source_document_type = "Custody"
	if custodian and not doc.get("custom_custodian"):
		doc.custom_custodian = custodian

	_advance_account, payable_account = ac_doc._get_custodian_accounts()
	doc.credit_to = payable_account
	doc.party_type = "Custodian"
	doc.party = doc.custom_custodian or custodian
	doc.party_account_currency = frappe.db.get_value(
		"Account", payable_account, "account_currency"
	)


def on_pi_submit(doc, method):
	"""Triggered after a Purchase Invoice is submitted."""
	if not doc.get("custom_accountant_custody"):
		return

	ac_name = doc.custom_accountant_custody
	try:
		ac_doc = frappe.get_doc("Accountant Custody", ac_name)
		ac_doc.update_billed_quantities(pi_name=doc.name)
	except Exception as e:
		frappe.log_error(str(e), f"on_pi_submit: failed to update AC {ac_name}")

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

	ac_name = doc.custom_accountant_custody
	try:
		ac_doc = frappe.get_doc("Accountant Custody", ac_name)
		ac_doc.update_billed_quantities()
	except Exception as e:
		frappe.log_error(str(e), f"on_pi_cancel: failed to update AC {ac_name}")

	if doc.get("custom_custodian"):
		_safe_update_custodian_dashboard(doc.custom_custodian)


# ─── Payment Entry Hooks ──────────────────────────────────────────────────────

def on_payment_before_submit(doc, method):
	"""
	Bypass ERPNext's supplier-party validation for custody settlement PEs.

	ERPNext's Payment Entry validates that the party_type matches the account
	type (e.g., Supplier → Payable). For custody settlement PEs we use
	party_type = "Custodian" against a Payable account — this is intentional
	and must bypass the standard check.
	"""
	if not _is_custody_settlement_pe(doc):
		return

	# Mark as ignore_permissions so ERPNext skips the party-account type check
	doc.flags.ignore_permissions = True

	# Ensure the custom fields are propagated
	if not doc.get("custom_source_document_type"):
		doc.custom_source_document_type = "Custody Settlement"

	# Ensure party fields are set correctly for Consolidated mode
	if doc.get("custom_custodian") and not doc.get("party"):
		settings = frappe.db.get_singles_dict("Treasury Settings")
		mode = settings.get("accounting_mode") or CONSOLIDATED
		if mode == CONSOLIDATED:
			doc.party_type = "Custodian"
			doc.party = doc.custom_custodian


def on_payment_submit(doc, method):
	"""
	Triggered after a Payment Entry is submitted.

	Handles two cases:
	  1. Advance PE (custom_custody_request set): recalculate CR paid_amount
	  2. Settlement PE (custom_accountant_custody set, source = Custody Settlement):
	     recalculate AC status and custodian dashboard
	"""
	# Case 1: Advance disbursement PE
	custody_request = doc.get("custom_custody_request")
	if custody_request and not _is_custody_settlement_pe(doc):
		_safe_recalculate_custody_request(custody_request)
		return

	# Case 2: Settlement PE
	ac_name = doc.get("custom_accountant_custody")
	custodian = doc.get("custom_custodian")

	if ac_name and _is_custody_settlement_pe(doc):
		try:
			from cash_and_securities_management.treasury.balances import (
				recalculate_accountant_custody_status,
			)
			recalculate_accountant_custody_status(ac_name)
		except Exception as e:
			frappe.log_error(str(e), f"on_payment_submit: failed to update AC {ac_name}")

	if custodian:
		_safe_update_custodian_dashboard(custodian)


def on_payment_cancel(doc, method):
	"""
	Triggered after a Payment Entry is cancelled.

	Handles two cases:
	  1. Advance PE: enforce strict hierarchy guard, then recalculate CR
	  2. Settlement PE: reverse settlement row, recalculate AC status
	"""
	# Case 1: Advance disbursement PE
	custody_request = doc.get("custom_custody_request")
	if custody_request and not _is_custody_settlement_pe(doc):
		from cash_and_securities_management.treasury.balances import (
			validate_advance_cancellation,
		)
		validate_advance_cancellation(doc)
		_safe_recalculate_custody_request(custody_request)
		return

	# Case 2: Settlement PE — reverse the settlement row
	ac_name = doc.get("custom_accountant_custody")
	if ac_name and _is_custody_settlement_pe(doc):
		try:
			# Remove the Custody Settlement Entry row for this PE
			frappe.db.sql(
				"""DELETE FROM `tabCustody Settlement Entry`
				   WHERE parent = %s AND parenttype = 'Accountant Custody'
				     AND payment_entry = %s""",
				(ac_name, doc.name),
			)

			# Recalculate total_settled_amount from remaining rows
			new_total = frappe.db.sql(
				"""SELECT COALESCE(SUM(total_settlement_amount), 0)
				   FROM `tabCustody Settlement Entry`
				   WHERE parent = %s AND parenttype = 'Accountant Custody'""",
				(ac_name,),
			)[0][0] or 0
			frappe.db.set_value(
				"Accountant Custody", ac_name, "total_settled_amount", flt(new_total)
			)

			from cash_and_securities_management.treasury.balances import (
				recalculate_accountant_custody_status,
			)
			recalculate_accountant_custody_status(ac_name)
		except Exception as e:
			frappe.log_error(str(e), f"on_payment_cancel: failed to reverse settlement for AC {ac_name}")

	custodian = doc.get("custom_custodian")
	if custodian:
		_safe_update_custodian_dashboard(custodian)


# ─── Journal Entry Hooks ──────────────────────────────────────────────────────

def on_journal_submit(doc, method):
	"""
	Triggered after a Journal Entry is submitted.
	If linked to an Accountant Custody (legacy settlement JE), recalculates status.
	"""
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
	"""
	Triggered after a Journal Entry is cancelled.
	Recalculates the linked Accountant Custody status.
	"""
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

CONSOLIDATED = "Consolidated (Party-Based)"


def _validate_pr_qty_against_ac(doc):
	"""
	Validate that the total received qty (existing submitted PRs + this PR)
	does not exceed the allowed qty on the Accountant Custody for each item.

	Raises frappe.throw() with a clear message if any item exceeds its limit.
	Skips validation for PRs not linked to an Accountant Custody.
	"""
	ac_name = doc.get("custom_accountant_custody")
	if not ac_name:
		return

	# Get allowed qty per item_code from the Accountant Custody child table
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

	# Get already-received qty per item_code from other submitted PRs
	# (exclude the current PR in case of amend/resubmit)
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

	# Validate each item in the current PR
	errors = []
	for pr_item in doc.items:
		item_code = pr_item.item_code
		allowed = allowed_qty_map.get(item_code)
		if allowed is None:
			# Item not in AC — skip (could be a non-custody item on a mixed PR)
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
			title=_("Purchase Receipt Qty Exceeds Accountant Custody Limit"),
		)


def _is_custody_settlement_pe(doc):
	"""Return True when the PE is a custody settlement (not an advance disbursement)."""
	return (
		doc.get("custom_source_document_type") == "Custody Settlement"
		or (
			bool(doc.get("custom_accountant_custody"))
			and not doc.get("custom_custody_request")
		)
	)


def _is_custody_purchase_doc(doc):
	"""Return True when the PR/PI should follow custody-specific behavior."""
	return (
		doc.get("custom_source_document_type") == "Custody"
		or bool(doc.get("custom_accountant_custody"))
	)


def _resolve_custody_context(doc):
	"""
	Resolve (Accountant Custody doc, custodian) from the purchase document.
	Always prefers the explicit custom_accountant_custody link on the doc.
	Fallback only matches submitted (docstatus=1) ACs to avoid Draft ACs
	polluting the account resolution.
	Returns (None, custodian) when no AC can be resolved.
	"""
	ac_name = doc.get("custom_accountant_custody")
	custodian = doc.get("custom_custodian")

	# Primary path: explicit link on the document
	if ac_name and frappe.db.exists("Accountant Custody", ac_name):
		ac_doc = frappe.get_doc("Accountant Custody", ac_name)
		custodian = custodian or ac_doc.custodian
		return ac_doc, custodian

	# Fallback: find the most recent submitted AC for this custodian
	if custodian:
		linked_ac = frappe.db.get_value(
			"Accountant Custody",
			{"custodian": custodian, "docstatus": 1},
			"name",
			order_by="creation desc",
		)
		if linked_ac:
			return frappe.get_doc("Accountant Custody", linked_ac), custodian

	return None, custodian


def _safe_update_custodian_dashboard(custodian_name):
	"""Safely call the custodian dashboard engine, logging errors without raising."""
	try:
		from cash_and_securities_management.treasury.balances import (
			update_custodian_dashboard,
		)
		update_custodian_dashboard(custodian_name)
	except Exception as e:
		frappe.log_error(str(e), f"_safe_update_custodian_dashboard: {custodian_name}")


def _safe_recalculate_custodian(custodian_name):
	"""Alias for _safe_update_custodian_dashboard — kept for backward compatibility."""
	_safe_update_custodian_dashboard(custodian_name)


def _safe_recalculate_custody_request(custody_request_name):
	"""Safely call the custody request balance engine, logging errors without raising."""
	try:
		from cash_and_securities_management.treasury.balances import (
			recalculate_custody_request_status,
		)
		recalculate_custody_request_status(custody_request_name)
	except Exception as e:
		frappe.log_error(str(e), f"_safe_recalculate_custody_request: {custody_request_name}")
