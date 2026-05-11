import json

import frappe
from frappe import _
from frappe.utils import flt


def _is_custody_purchase_receipt(pr_doc):
    return bool(
        pr_doc
        and pr_doc.get("custom_source_document_type") == "Custody"
        and pr_doc.get("custom_accountant_custody")
    )


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


@frappe.whitelist()
def make_purchase_invoice(source_name, target_doc=None, args=None):
    """Custody-safe wrapper around ERPNext's PR -> PI mapper.

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
    doc = frappe.get_doc("Accountant Custody", accountant_custody)
    return doc.create_purchase_receipt()


@frappe.whitelist()
def generate_custody_purchase_invoice(accountant_custody):
    doc = frappe.get_doc("Accountant Custody", accountant_custody)
    return doc.generate_purchase_invoice()


@frappe.whitelist()
def settle_accountant_custody(
    accountant_custody,
    advance_amount_allocated=0,
    direct_payment_amount=0,
    settlement_notes="",
):
    doc = frappe.get_doc("Accountant Custody", accountant_custody)
    return doc.create_settlement(
        advance_amount_allocated=advance_amount_allocated,
        direct_payment_amount=direct_payment_amount,
        settlement_notes=settlement_notes,
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
