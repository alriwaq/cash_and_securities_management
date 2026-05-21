"""
V4 Architecture — Vault Pending Item Hooks
==========================================
These hooks fire on ERPNext document events and automatically create
Vault Pending Items so the vault teller can see what cash needs to be
physically exchanged before end-of-day journal submission.

Routing Logic (Fix 1):
  Each Treasury Station has a dedicated vault_account (GL Cash Account).
  When a Payment Entry is submitted, the hook matches the PE's cash account
  (paid_to for Pay, paid_from for Receive) against the vault_account of each
  open Treasury Station. Only the matching station receives the pending item.
  This ensures each teller only sees payments routed through their vault.

  Fallback: if no station matches by account, falls back to the company's
  default station (is_default=1), then to any open station for the company.

Supported source documents:
  - Payment Entry (Receive / Pay)  → creates Inbound / Outbound pending item
  - Expense Claim (on_submit)      → creates Outbound pending item
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_vault_station_for_account(company, cash_account):
	"""
	Return the open Treasury Station whose vault_account matches cash_account.
	Falls back to default station, then any open station for the company.
	"""
	if cash_account:
		# Primary: match by vault account (exact routing)
		station = frappe.db.get_value(
			"Treasury Station",
			{"company": company, "status": "Open", "vault_account": cash_account},
			"name",
		)
		if station:
			return station

	# Fallback 1: default station for company
	station = frappe.db.get_value(
		"Treasury Station",
		{"company": company, "status": "Open", "is_default": 1},
		"name",
	)
	if station:
		return station

	# Fallback 2: any open station for company
	return frappe.db.get_value(
		"Treasury Station",
		{"company": company, "status": "Open"},
		"name",
	)


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


# ───# ─── Payment Entry Hook ────────────────────────────────────────────────

def on_payment_entry_workflow_action(doc, method=None, workflow_action=None):
	"""
	V4: Fires when the AP clerk clicks "إرسال للموافقة" on a Cash Payment Entry.
	Creates a Vault Pending Item so the vault teller can see it in the cockpit.
	The PE stays in Draft (docstatus=0) until the TCJ submits it to GL.
	"""
	if workflow_action != "إرسال للموافقة":
		return
	_create_vpi_from_pe(doc)


def on_payment_entry_submit(doc, method=None):
	"""
	V4: Fires on PE submit (docstatus 0 → 1).
	For cash PEs that went through the workflow, the VPI is already created.
	This is a fallback for non-workflow cash PEs (e.g. created by TCJ directly).
	If a VPI already exists for this PE, skip creation.
	"""""
	if not _is_cash_payment(doc):
		return
	# Fallback: only create VPI on submit if not already created via workflow action
	if _already_has_pending("Payment Entry", doc.name):
		return
	# Skip if this submit is triggered by TCJ (VPI already executed)
	if doc.flags.get("submitted_by_tcj"):
		return
	_create_vpi_from_pe(doc)


def _create_vpi_from_pe(doc):
	"""Shared logic: create a Vault Pending Item from a Cash Payment Entry."""
	if not _is_cash_payment(doc):
		return

	if _already_has_pending("Payment Entry", doc.name):
		return

	# Determine which GL account the cash moves through
	if doc.payment_type == "Receive":
		direction = "Inbound"
		category = "Invoice Collection"
		cash_account = doc.paid_to
	elif doc.payment_type == "Pay":
		direction = "Outbound"
		category = "Supplier Payment"
		cash_account = doc.paid_from
	else:
		return  # Internal transfer — not handled here

	station = _get_vault_station_for_account(doc.company, cash_account)
	if not station:
		frappe.log_error(
			f"No open Treasury Station found for company {doc.company} "
			f"with vault_account={cash_account}. "
			f"Vault Pending Item not created for Payment Entry {doc.name}.",
			"Vault Pending Hook"
		)
		return

	party_type = doc.party_type or ""
	party = doc.party or ""
	amount = flt(doc.paid_amount)
	narration = doc.remarks or f"Payment Entry {doc.name}"

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
		_("Vault Pending Item {0} created for Payment Entry {1} → Station {2}").format(
			f"<b>{pending_name}</b>", f"<b>{doc.name}</b>", f"<b>{station}</b>"
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


# ─── Expense Claim Hook ───────────────────────────────────────────────────────

def on_expense_claim_submit(doc, method=None):
	"""
	When an Expense Claim is submitted and paid in cash,
	create an Outbound Vault Pending Item routed to the default station.
	Expense claims don't have a specific cash account, so we use the
	default station for the company.
	"""
	if _already_has_pending("Expense Claim", doc.name):
		return

	station = _get_vault_station_for_account(doc.company, None)
	if not station:
		return

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
	# Check the account linked to this mode of payment for the company
	mop_account = frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": doc.mode_of_payment, "company": doc.company},
		"default_account",
	)
	if mop_account:
		account_type = frappe.db.get_value("Account", mop_account, "account_type")
		return account_type == "Cash"
	# Fallback: check the mode_of_payment type field directly
	mop_type = frappe.db.get_value("Mode of Payment", doc.mode_of_payment, "type")
	return mop_type == "Cash"
