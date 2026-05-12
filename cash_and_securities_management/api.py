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
def create_custody_settlement(
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


@frappe.whitelist()
def create_custody_payment_entry_from_pi(purchase_invoice):
    pi = frappe.get_doc("Purchase Invoice", purchase_invoice)

    if pi.docstatus != 1:
        frappe.throw(_("Purchase Invoice {0} must be submitted before payment.").format(pi.name))

    if pi.get("custom_source_document_type") != "Custody" or not pi.get("custom_accountant_custody"):
        frappe.throw(
            _("Purchase Invoice {0} is not a custody invoice.").format(pi.name),
            title=_("Invalid Purchase Invoice"),
        )

    outstanding = flt(pi.get("outstanding_amount"))
    if outstanding <= 0:
        frappe.throw(_("Purchase Invoice {0} has no outstanding amount.").format(pi.name))

    ac_doc = frappe.get_doc("Accountant Custody", pi.custom_accountant_custody)
    advance_account, payable_account = ac_doc._get_custodian_accounts()

    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = "Internal Transfer"
    pe.posting_date = frappe.utils.nowdate()
    pe.company = pi.company
    pe.party_type = "Custodian"
    pe.party = pi.custom_custodian or ac_doc.custodian
    pe.paid_from = advance_account
    pe.paid_to = payable_account
    pe.paid_amount = outstanding
    pe.received_amount = outstanding
    pe.reference_no = pi.name
    pe.reference_date = frappe.utils.nowdate()
    pe.remarks = _("Custody settlement payment for Purchase Invoice {0}").format(pi.name)

    pe.custom_source_document_type = "Custody"
    pe.custom_accountant_custody = pi.custom_accountant_custody
    pe.custom_custodian = pi.custom_custodian or ac_doc.custodian
    pe.custom_custody_request = ac_doc.custody_request

    pe.append(
        "references",
        {
            "reference_doctype": "Purchase Invoice",
            "reference_name": pi.name,
            "total_amount": flt(pi.get("grand_total")),
            "outstanding_amount": outstanding,
            "allocated_amount": outstanding,
        },
    )

    pe.flags.ignore_permissions = True
    pe.insert()
    pe.submit()
    return pe.name


@frappe.whitelist()
def get_payment_entry(dt, dn, party_amount=None, bank_account=None, bank_amount=None):
    if dt != "Purchase Invoice":
        from erpnext.accounts.doctype.payment_entry.payment_entry import (
            get_payment_entry as erpnext_get_payment_entry,
        )

        return erpnext_get_payment_entry(
            dt,
            dn,
            party_amount=party_amount,
            bank_account=bank_account,
            bank_amount=bank_amount,
        )

    pi_doc = frappe.get_doc("Purchase Invoice", dn)
    is_custody_pi = (
        pi_doc.get("custom_source_document_type") == "Custody"
        and bool(pi_doc.get("custom_accountant_custody"))
    )
    if not is_custody_pi:
        from erpnext.accounts.doctype.payment_entry.payment_entry import (
            get_payment_entry as erpnext_get_payment_entry,
        )

        return erpnext_get_payment_entry(
            dt,
            dn,
            party_amount=party_amount,
            bank_account=bank_account,
            bank_amount=bank_amount,
        )

    pe_name = create_custody_payment_entry_from_pi(dn)
    return frappe.get_doc("Payment Entry", pe_name)


@frappe.whitelist()
def get_accountant_custody_settlements_dashboard(accountant_custody):
    if not accountant_custody:
        return {"rows": []}

    pi_rows = frappe.get_all(
        "Purchase Invoice",
        filters={"custom_accountant_custody": accountant_custody},
        fields=["name", "posting_date", "grand_total", "outstanding_amount", "status", "docstatus"],
        order_by="posting_date asc, name asc",
    )

    pe_map = {}
    pe_refs = frappe.db.sql(
        """
        select per.reference_name as purchase_invoice, pe.name as payment_entry,
               pe.posting_date, pe.paid_amount, pe.docstatus
        from `tabPayment Entry Reference` per
        inner join `tabPayment Entry` pe on pe.name = per.parent
        where per.reference_doctype = 'Purchase Invoice'
          and pe.custom_accountant_custody = %s
        order by pe.posting_date asc, pe.name asc
        """,
        (accountant_custody,),
        as_dict=True,
    )

    for ref in pe_refs:
        pe_map.setdefault(ref.purchase_invoice, []).append(
            {
                "payment_entry": ref.payment_entry,
                "posting_date": ref.posting_date,
                "paid_amount": flt(ref.paid_amount),
                "docstatus": ref.docstatus,
            }
        )

    rows = []
    for pi in pi_rows:
        rows.append(
            {
                "purchase_invoice": pi.name,
                "pi_posting_date": pi.posting_date,
                "pi_total": flt(pi.grand_total),
                "pi_outstanding": flt(pi.outstanding_amount),
                "pi_status": pi.status,
                "pi_docstatus": pi.docstatus,
                "payments": pe_map.get(pi.name, []),
            }
        )

    return {"rows": rows}


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
