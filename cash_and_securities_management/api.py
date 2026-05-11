import json

import frappe
from frappe import _
from frappe.utils import flt


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
