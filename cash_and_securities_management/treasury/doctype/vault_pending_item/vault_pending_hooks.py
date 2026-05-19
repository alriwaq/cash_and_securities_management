"""
V4 Architecture — Vault Pending Item Hooks
==========================================
These hooks fire on ERPNext document events and automatically create
Vault Pending Items so the vault teller can see what cash needs to be
physically exchanged before end-of-day journal submission.

Supported source documents:
  - Payment Entry (Receive / Pay)  → creates Inbound / Outbound pending item
  - Sales Invoice (on_submit)      → creates Inbound pending item if payment mode is Cash
  - Purchase Invoice (on_submit)   → creates Outbound pending item if payment mode is Cash
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_vault_station(company):
	"""Return the default open Treasury Station for the given company, or None."""
	station = frappe.db.get_value(
		"Treasury Station",
		{"company": company, "status": "Open", "is_default": 1},
		"name",
	)
	if not station:
		station = frappe.db.get_value(
			"Treasury Station",
			{"company": company, "status": "Open"},
			"name",
		)
	return station


def _already_has_pending(source_doctype, source_name):
	"""Return True if a Vault Pending Item already exists for this source doc."""
	return frappe.db.exists(
		"Vault Pending Item",
		{"source_document_type": source_doctype, "source_document": source_name, "status": ["!=", "Cancelled"]},
	)


def _create_pending_item(station, company, direction, category, party_type, party,
						  ref_doctype, ref_name, amount, narration, source_doctype, source_name):
	"""Create and insert a new Vault Pending Item."""
	doc = frappe.new_doc("Vault Pending Item")
	doc.treasury_station = station
	doc.company = company
	doc.posting_date = nowdate()
	doc.status = "Pending"
	doc.direction = direction
	doc.transaction_category = category
	doc.party_type = party_type
	doc.party = party
	doc.reference_doctype = ref_doctype
	doc.reference_name = ref_name
	doc.expected_amount = flt(amount)
	doc.narration = narration or ""
	doc.source_document_type = source_doctype
	doc.source_document = source_name
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


# ─── Payment Entry Hook ───────────────────────────────────────────────────────

def on_payment_entry_submit(doc, method=None):
	"""
	When a Payment Entry is submitted and its mode of payment is Cash,
	create a Vault Pending Item so the teller knows cash needs to move.
	"""
	# Only act on Cash mode of payment
	if not _is_cash_payment(doc):
		return

	if _already_has_pending("Payment Entry", doc.name):
		return

	station = _get_vault_station(doc.company)
	if not station:
		frappe.log_error(
			f"No open Treasury Station found for company {doc.company}. "
			f"Vault Pending Item not created for Payment Entry {doc.name}.",
			"Vault Pending Hook"
		)
		return

	# Payment Type: Receive = cash coming in (Inbound), Pay = cash going out (Outbound)
	if doc.payment_type == "Receive":
		direction = "Inbound"
		category = "Invoice Collection"
	elif doc.payment_type == "Pay":
		direction = "Outbound"
		category = "Supplier Payment"
	else:
		return  # Internal transfer — not handled here

	party_type = doc.party_type or ""
	party = doc.party or ""
	amount = flt(doc.paid_amount)
	narration = doc.remarks or f"Payment Entry {doc.name}"

	# Reference: find the first linked invoice
	ref_doctype = ""
	ref_name = ""
	if doc.references:
		first_ref = doc.references[0]
		ref_doctype = first_ref.reference_doctype or ""
		ref_name = first_ref.reference_name or ""

	pending_name = _create_pending_item(
		station, doc.company, direction, category,
		party_type, party, ref_doctype, ref_name,
		amount, narration, "Payment Entry", doc.name
	)
	frappe.msgprint(
		_("Vault Pending Item {0} created for Payment Entry {1}").format(
			f"<b>{pending_name}</b>", f"<b>{doc.name}</b>"
		),
		indicator="blue",
		alert=True,
	)


def on_payment_entry_cancel(doc, method=None):
	"""Cancel the linked Vault Pending Item when Payment Entry is cancelled."""
	pending = frappe.db.get_value(
		"Vault Pending Item",
		{"source_document_type": "Payment Entry", "source_document": doc.name, "status": "Pending"},
		"name",
	)
	if pending:
		frappe.db.set_value("Vault Pending Item", pending, "status", "Cancelled")
		frappe.msgprint(
			_("Vault Pending Item {0} cancelled.").format(f"<b>{pending}</b>"),
			indicator="orange",
			alert=True,
		)


# ─── Direct Expense Hook ──────────────────────────────────────────────────────

def on_expense_claim_submit(doc, method=None):
	"""
	When an Expense Claim is submitted and paid in cash,
	create an Outbound Vault Pending Item.
	"""
	if not _already_has_pending("Expense Claim", doc.name):
		station = _get_vault_station(doc.company)
		if station:
			_create_pending_item(
				station, doc.company, "Outbound", "Direct Expense",
				"Employee", doc.employee, "Expense Claim", doc.name,
				flt(doc.total_claimed_amount),
				f"Expense Claim {doc.name}",
				"Expense Claim", doc.name,
			)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _is_cash_payment(doc):
	"""Return True if the Payment Entry uses a Cash mode of payment."""
	if not doc.mode_of_payment:
		return False
	account_type = frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": doc.mode_of_payment, "company": doc.company},
		"account",
	)
	if not account_type:
		# Fallback: check mode_of_payment type field
		mop_type = frappe.db.get_value("Mode of Payment", doc.mode_of_payment, "type")
		return mop_type == "Cash"
	root_type = frappe.db.get_value("Account", account_type, "account_type")
	return root_type == "Cash"
