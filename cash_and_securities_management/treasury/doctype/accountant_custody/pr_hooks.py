"""
Document Event Hooks — v2
treasury/doctype/accountant_custody/pr_hooks.py

All doc_event handlers for Purchase Receipt, Purchase Invoice, Payment Entry,
and Journal Entry. Each handler delegates financial recalculations to the
centralized balance engine in treasury/balances.py.

Cancellation order enforced:
  Settlement JE/PE → Purchase Invoice → Purchase Receipt → Accountant Custody → Custody Request
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
	"""
	if doc.get("custom_accountant_custody"):
		# Ensure custodian is also set
		if not doc.get("custom_custodian"):
			custodian = frappe.db.get_value(
				"Accountant Custody",
				doc.custom_accountant_custody,
				"custodian",
			)
			if custodian:
				doc.custom_custodian = custodian


def on_pr_submit(doc, method):
	"""
	Triggered after a Purchase Receipt is submitted.
	Updates received quantities on the linked Accountant Custody and
	triggers the centralized balance recalculation.
	"""
	if not doc.get("custom_accountant_custody"):
		return

	ac_name = doc.custom_accountant_custody
	try:
		ac_doc = frappe.get_doc("Accountant Custody", ac_name)
		ac_doc.update_received_quantities()
	except Exception as e:
		frappe.log_error(str(e), f"on_pr_submit: failed to update AC {ac_name}")

	# Cascade balance recalculation
	if doc.get("custom_custodian"):
		_safe_recalculate_custodian(doc.custom_custodian)


def on_pr_cancel(doc, method):
	"""
	Triggered after a Purchase Receipt is cancelled.
	Enforces cancellation order, then resets received quantities.
	"""
	if not doc.get("custom_accountant_custody"):
		return

	# Enforce order: PI must be cancelled before PR
	from cash_and_securities_management.treasury.balances import (
		validate_cancellation_order_for_pr,
	)
	validate_cancellation_order_for_pr(doc)

	ac_name = doc.custom_accountant_custody
	try:
		ac_doc = frappe.get_doc("Accountant Custody", ac_name)
		ac_doc.update_received_quantities()
	except Exception as e:
		frappe.log_error(str(e), f"on_pr_cancel: failed to update AC {ac_name}")

	if doc.get("custom_custodian"):
		_safe_recalculate_custodian(doc.custom_custodian)


# ─── Purchase Invoice Hooks ───────────────────────────────────────────────────

def on_pi_validate(doc, method):
	"""
	Triggered on Purchase Invoice validate.
	Propagates custom_accountant_custody and custom_custodian from the linked
	PR when the PI is created via ERPNext's standard Create → Purchase Invoice.
	"""
	if not doc.get("custom_accountant_custody"):
		# Try to inherit from the first PR item reference
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
				if pr_ac:
					doc.custom_accountant_custody = pr_ac
				if pr_custodian:
					doc.custom_custodian = pr_custodian
				break

	if not doc.get("custom_accountant_custody"):
		return

	ac_name = doc.custom_accountant_custody
	ac_doc = frappe.get_doc("Accountant Custody", ac_name)

	if ac_doc.status in ("Fully Settled", "Closed", "Cancelled"):
		frappe.throw(
			_("Cannot modify a Purchase Invoice linked to a {0} Accountant Custody {1}.").format(
				ac_doc.status, ac_name
			)
		)


def on_pi_submit(doc, method):
	"""
	Triggered after a Purchase Invoice is submitted.
	Updates billed quantities on the linked Accountant Custody.
	"""
	if not doc.get("custom_accountant_custody"):
		return

	ac_name = doc.custom_accountant_custody
	try:
		ac_doc = frappe.get_doc("Accountant Custody", ac_name)
		ac_doc.update_billed_quantities(pi_name=doc.name)
	except Exception as e:
		frappe.log_error(str(e), f"on_pi_submit: failed to update AC {ac_name}")

	if doc.get("custom_custodian"):
		_safe_recalculate_custodian(doc.custom_custodian)


def on_pi_cancel(doc, method):
	"""
	Triggered after a Purchase Invoice is cancelled.
	Enforces cancellation order, then resets billed quantities.
	"""
	if not doc.get("custom_accountant_custody"):
		return

	# Enforce order: Settlement JE must be cancelled before PI
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
		_safe_recalculate_custodian(doc.custom_custodian)


# ─── Payment Entry Hooks ──────────────────────────────────────────────────────

def on_payment_submit(doc, method):
	"""
	Triggered after a Payment Entry is submitted.
	If linked to a Custody Request, recalculates its paid_amount and status.
	Then cascades to the Custodian balance.
	"""
	custody_request = doc.get("custom_custody_request")
	custodian = doc.get("custom_custodian")

	if custody_request:
		_safe_recalculate_custody_request(custody_request)
	elif custodian:
		_safe_recalculate_custodian(custodian)


def on_payment_cancel(doc, method):
	"""
	Triggered after a Payment Entry is cancelled.
	Reverses the paid amount update on the linked Custody Request.
	"""
	custody_request = doc.get("custom_custody_request")
	custodian = doc.get("custom_custodian")

	if custody_request:
		_safe_recalculate_custody_request(custody_request)
	elif custodian:
		_safe_recalculate_custodian(custodian)


# ─── Journal Entry Hooks ──────────────────────────────────────────────────────

def on_journal_submit(doc, method):
	"""
	Triggered after a Journal Entry is submitted.
	If linked to an Accountant Custody (settlement JE), recalculates its status.
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

def _safe_recalculate_custodian(custodian_name):
	"""Safely call the custodian balance engine, logging errors without raising."""
	try:
		from cash_and_securities_management.treasury.balances import (
			recalculate_custodian_balances,
		)
		recalculate_custodian_balances(custodian_name)
	except Exception as e:
		frappe.log_error(str(e), f"_safe_recalculate_custodian: {custodian_name}")


def _safe_recalculate_custody_request(custody_request_name):
	"""Safely call the custody request balance engine, logging errors without raising."""
	try:
		from cash_and_securities_management.treasury.balances import (
			recalculate_custody_request_status,
		)
		recalculate_custody_request_status(custody_request_name)
	except Exception as e:
		frappe.log_error(str(e), f"_safe_recalculate_custody_request: {custody_request_name}")
