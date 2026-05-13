"""
Cash and Securities Management — Public API Layer (v3)
api.py

Architecture: JS (UI) → api.py (service boundary) → DocType method (accounting engine)

All whitelisted endpoints are thin wrappers that:
  1. Cast and validate incoming arguments (all frappe.call args arrive as strings)
  2. Delegate to the DocType controller method
  3. Return a simple scalar (document name) for the JS callback
"""
import json

import frappe
from frappe import _
from frappe.utils import flt


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _is_custody_purchase_receipt(pr_doc):
	return bool(
		pr_doc
		and pr_doc.get("custom_source_document_type") == "Custody"
		and pr_doc.get("custom_accountant_custody")
	)


def _resolve_pr_doc(doc=None, purchase_receipt=None):
	if purchase_receipt:
		return frappe.get_doc("Purchase Receipt", purchase_receipt)

	if not doc:
		return None

	if isinstance(doc, str):
		try:
			payload = json.loads(doc)
		except Exception:
			payload = {}
	elif isinstance(doc, dict):
		payload = doc
	else:
		payload = getattr(doc, "as_dict", lambda: {})()

	if payload.get("doctype") == "Purchase Receipt":
		return payload

	return None


# ─── Quantity Validation ──────────────────────────────────────────────────────

@frappe.whitelist()
def validate_custody_receipt_qty(doc=None, purchase_receipt=None, accountant_custody=None):
	"""
	Validate Purchase Receipt quantities for custody flow.

	Supports calls with any of these payload styles:
	  - doc: JSON string/dict for Purchase Receipt
	  - purchase_receipt: PR name
	  - accountant_custody: fallback AC name
	"""
	pr_doc = _resolve_pr_doc(doc=doc, purchase_receipt=purchase_receipt)
	if not pr_doc:
		return {"ok": True}

	ac_name = pr_doc.get("custom_accountant_custody") or accountant_custody
	if not ac_name:
		return {"ok": True}

	if not frappe.db.exists("Accountant Custody", ac_name):
		frappe.throw(
			_("Accountant Custody {0} was not found.").format(ac_name),
			title=_("Invalid Accountant Custody"),
		)

	ac_doc = frappe.get_doc("Accountant Custody", ac_name)

	remaining_by_item = {}
	for row in ac_doc.get("custody_items") or []:
		item_code = row.get("item_code")
		if not item_code:
			continue
		remaining = flt(row.get("qty")) - flt(row.get("accepted_qty"))
		remaining_by_item[item_code] = flt(remaining_by_item.get(item_code)) + flt(remaining)

	requested_by_item = {}
	for row in pr_doc.get("items") or []:
		item_code = row.get("item_code")
		if not item_code:
			continue
		requested_by_item[item_code] = flt(requested_by_item.get(item_code)) + flt(row.get("qty"))

	for item_code, requested_qty in requested_by_item.items():
		allowed_qty = flt(remaining_by_item.get(item_code))
		if requested_qty > allowed_qty + 1e-9:
			frappe.throw(
				_("Item {0}: requested qty {1} exceeds remaining custody qty {2}.").format(
					frappe.bold(item_code),
					requested_qty,
					allowed_qty,
				),
				title=_("Quantity Exceeds Custody Balance"),
			)

	return {"ok": True}


# ─── Purchase Receipt ─────────────────────────────────────────────────────────

@frappe.whitelist()
def make_purchase_invoice(source_name, target_doc=None, args=None):
	"""
	Custody-safe wrapper around ERPNext's PR → PI mapper.

	ERPNext's native mapper fetches supplier payment terms during postprocess.
	Custody PRs intentionally do not use Supplier, so we temporarily neutralize
	that lookup only for custody documents and then restore the original helper.
	"""
	pr_doc = frappe.get_doc("Purchase Receipt", source_name)

	if not _is_custody_purchase_receipt(pr_doc):
		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
			make_purchase_invoice as erpnext_make_purchase_invoice,
		)
		return erpnext_make_purchase_invoice(source_name, target_doc=target_doc, args=args)

	import erpnext.accounts.party as accounts_party
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
		make_purchase_invoice as erpnext_make_purchase_invoice,
	)

	original_get_payment_terms_template = accounts_party.get_payment_terms_template

	def _skip_payment_terms_template(*_args, **_kwargs):
		return None

	accounts_party.get_payment_terms_template = _skip_payment_terms_template
	try:
		pi_doc = erpnext_make_purchase_invoice(source_name, target_doc=target_doc, args=args)

		if pi_doc and getattr(pi_doc, "doctype", None) == "Purchase Invoice":
			if not pi_doc.get("custom_source_document_type"):
				pi_doc.custom_source_document_type = "Custody"
			if not pi_doc.get("custom_accountant_custody"):
				pi_doc.custom_accountant_custody = pr_doc.custom_accountant_custody
			if not pi_doc.get("custom_custodian"):
				pi_doc.custom_custodian = pr_doc.custom_custodian

		return pi_doc
	finally:
		accounts_party.get_payment_terms_template = original_get_payment_terms_template


@frappe.whitelist()
def create_custody_purchase_receipt(accountant_custody):
	"""Create a Purchase Receipt from an Accountant Custody."""
	doc = frappe.get_doc("Accountant Custody", accountant_custody)
	return doc.create_purchase_receipt()


# ─── Purchase Invoice ─────────────────────────────────────────────────────────

@frappe.whitelist()
def generate_custody_purchase_invoice(accountant_custody):
	"""Generate a Purchase Invoice from an Accountant Custody."""
	doc = frappe.get_doc("Accountant Custody", accountant_custody)
	return doc.generate_purchase_invoice()


# ─── Settlement ───────────────────────────────────────────────────────────────

@frappe.whitelist()
def create_custody_settlement(
	accountant_custody,
	advance_amount_allocated=0,
	direct_payment_amount=0,
	settlement_notes="",
):
	"""
	Service boundary for the settlement flow.

	All frappe.call() arguments arrive as strings — cast them explicitly.
	Delegates to AccountantCustody.create_settlement() which is the accounting engine.

	Returns: name of the created Payment Entry (or comma-separated names for split)
	"""
	# Cast string args from frappe.call
	advance_amount_allocated = flt(advance_amount_allocated)
	direct_payment_amount    = flt(direct_payment_amount)
	settlement_notes         = (settlement_notes or "").strip()

	if advance_amount_allocated < 0 or direct_payment_amount < 0:
		frappe.throw(_("Settlement amounts cannot be negative."))

	if advance_amount_allocated == 0 and direct_payment_amount == 0:
		frappe.throw(_("Please specify at least one settlement amount greater than zero."))

	doc = frappe.get_doc("Accountant Custody", accountant_custody)
	return doc.create_settlement(
		advance_amount_allocated=advance_amount_allocated,
		direct_payment_amount=direct_payment_amount,
		settlement_notes=settlement_notes,
	)


# ─── Settlement Summary (for dashboard) ──────────────────────────────────────

@frappe.whitelist()
def get_settlement_summary(accountant_custody):
	"""
	Return a summary of Purchase Invoices and their settlement Payment Entries
	for the Accountant Custody settlements dashboard section.

	Returns:
	  {
	    "purchase_invoices": [
	      {
	        "name": "PI-0001",
	        "grand_total": 1000.0,
	        "outstanding_amount": 0.0,
	        "status": "Paid",
	        "payment_entry": "PE-0001"   # or None
	      }, ...
	    ],
	    "total_amount": 1000.0,
	    "total_settled": 1000.0,
	    "remaining": 0.0
	  }
	"""
	if not frappe.db.exists("Accountant Custody", accountant_custody):
		frappe.throw(_("Accountant Custody {0} not found.").format(accountant_custody))

	# Get all submitted PIs linked to this AC
	pis = frappe.get_all(
		"Purchase Invoice",
		filters={
			"custom_accountant_custody": accountant_custody,
			"docstatus": 1,
		},
		fields=["name", "grand_total", "outstanding_amount", "status"],
	)

	total_amount  = 0.0
	total_settled = 0.0

	result_pis = []
	for pi in pis:
		grand_total        = flt(pi.grand_total)
		outstanding_amount = flt(pi.outstanding_amount)
		paid_amount        = grand_total - outstanding_amount

		total_amount  += grand_total
		total_settled += paid_amount

		# Find the settlement PE that references this PI
		pe_ref = frappe.db.sql(
			"""
			SELECT per.parent AS payment_entry
			FROM `tabPayment Entry Reference` per
			JOIN `tabPayment Entry` pe ON pe.name = per.parent
			WHERE per.reference_doctype = 'Purchase Invoice'
			  AND per.reference_name = %s
			  AND pe.docstatus = 1
			  AND pe.custom_source_document_type = 'Custody Settlement'
			ORDER BY pe.creation DESC
			LIMIT 1
			""",
			(pi.name,),
			as_dict=True,
		)

		result_pis.append({
			"name":               pi.name,
			"grand_total":        grand_total,
			"outstanding_amount": outstanding_amount,
			"status":             pi.status,
			"payment_entry":      pe_ref[0].payment_entry if pe_ref else None,
		})

	return {
		"purchase_invoices": result_pis,
		"total_amount":       total_amount,
		"total_settled":      total_settled,
		"remaining":          total_amount - total_settled,
	}


# ─── Backward-compatibility alias ────────────────────────────────────────────

@frappe.whitelist()
def get_accountant_custody_settlements_dashboard(accountant_custody):
	"""
	Alias for get_settlement_summary — used by the client-side JS dashboard.
	Returns the same payload as get_settlement_summary.
	"""
	return get_settlement_summary(accountant_custody)
