"""
Custody Purchased Items Report
================================
Shows every item purchased under Accountant Custody documents,
with receipt, invoice, and billing status per line.

Columns
-------
  Custodian | AC No | AC Date | Item | Description | UOM
  Ordered Qty | Received Qty | Billed Qty | Pending Qty
  Rate | Amount | Received Amount | Billed Amount | Pending Amount
  Warehouse | Cost Center | Project | Status

Filters
-------
  company          : mandatory
  from_date        : optional
  to_date          : optional
  custodian        : optional
  accountant_custody: optional
  status           : optional (Draft / Pending / Partly Received / Fully Received /
                               Partly Invoiced / Fully Invoiced / Closed)
  item_code        : optional
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if not filters.company:
        frappe.throw(_("Please select a Company."))

    columns = _get_columns()
    data    = _get_data(filters)
    return columns, data


# ─────────────────────────────────────────────────────────────────────────────
# Columns
# ─────────────────────────────────────────────────────────────────────────────

def _get_columns():
    return [
        {
            "label": _("Custodian"),
            "fieldname": "custodian",
            "fieldtype": "Link",
            "options": "Custodian",
            "width": 130,
        },
        {
            "label": _("Accountant Custody"),
            "fieldname": "accountant_custody",
            "fieldtype": "Link",
            "options": "Accountant Custody",
            "width": 160,
        },
        {
            "label": _("Date"),
            "fieldname": "posting_date",
            "fieldtype": "Date",
            "width": 100,
        },
        {
            "label": _("Item Code"),
            "fieldname": "item_code",
            "fieldtype": "Link",
            "options": "Item",
            "width": 130,
        },
        {
            "label": _("Item Name"),
            "fieldname": "item_name",
            "fieldtype": "Data",
            "width": 200,
        },
        {
            "label": _("UOM"),
            "fieldname": "uom",
            "fieldtype": "Link",
            "options": "UOM",
            "width": 70,
        },
        {
            "label": _("Ordered Qty"),
            "fieldname": "qty",
            "fieldtype": "Float",
            "width": 100,
        },
        {
            "label": _("Received Qty"),
            "fieldname": "received_qty",
            "fieldtype": "Float",
            "width": 110,
        },
        {
            "label": _("Billed Qty"),
            "fieldname": "billed_qty",
            "fieldtype": "Float",
            "width": 100,
        },
        {
            "label": _("Pending Qty"),
            "fieldname": "pending_qty",
            "fieldtype": "Float",
            "width": 100,
        },
        {
            "label": _("Rate"),
            "fieldname": "rate",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 110,
        },
        {
            "label": _("Ordered Amount"),
            "fieldname": "amount",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 130,
        },
        {
            "label": _("Received Amount"),
            "fieldname": "received_amount",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 140,
        },
        {
            "label": _("Billed Amount"),
            "fieldname": "billed_amount",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 130,
        },
        {
            "label": _("Pending Amount"),
            "fieldname": "pending_amount",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 130,
        },
        {
            "label": _("Warehouse"),
            "fieldname": "warehouse",
            "fieldtype": "Link",
            "options": "Warehouse",
            "width": 130,
        },
        {
            "label": _("Cost Center"),
            "fieldname": "cost_center",
            "fieldtype": "Link",
            "options": "Cost Center",
            "width": 130,
        },
        {
            "label": _("Project"),
            "fieldname": "project",
            "fieldtype": "Link",
            "options": "Project",
            "width": 110,
        },
        {
            "label": _("Status"),
            "fieldname": "status",
            "fieldtype": "Data",
            "width": 130,
        },
        {
            "label": _("Currency"),
            "fieldname": "currency",
            "fieldtype": "Currency",
            "width": 80,
            "hidden": 1,
        },
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────────────────────

def _get_data(filters):
    ac_filters = {"company": filters.company, "docstatus": ["!=", 2]}

    if filters.get("custodian"):
        ac_filters["custodian"] = filters.custodian
    if filters.get("accountant_custody"):
        ac_filters["name"] = filters.accountant_custody
    if filters.get("status"):
        ac_filters["status"] = filters.status
    if filters.get("from_date"):
        ac_filters["transaction_date"] = [">=", filters.from_date]
    if filters.get("to_date"):
        if "transaction_date" in ac_filters:
            ac_filters["transaction_date"] = [
                "between", [filters.from_date, filters.to_date]
            ]
        else:
            ac_filters["transaction_date"] = ["<=", filters.to_date]

    ac_docs = frappe.get_all(
        "Accountant Custody",
        filters=ac_filters,
        fields=["name", "custodian", "transaction_date", "status", "currency"],
        order_by="transaction_date desc, name desc",
    )

    if not ac_docs:
        return []

    ac_names = [d.name for d in ac_docs]
    ac_map   = {d.name: d for d in ac_docs}

    # Fetch all custody items for these ACs
    item_filters = {"parent": ["in", ac_names], "parenttype": "Accountant Custody"}
    if filters.get("item_code"):
        item_filters["item_code"] = filters.item_code

    items = frappe.get_all(
        "Accountant Custody Item",
        filters=item_filters,
        fields=[
            "parent", "item_code", "item_name", "description", "uom",
            "qty", "received_qty", "billed_qty", "rate", "amount",
            "received_amount", "billed_amount",
            "warehouse", "cost_center", "project",
        ],
        order_by="parent, idx",
    )

    rows = []
    for item in items:
        ac = ac_map.get(item.parent)
        if not ac:
            continue

        ordered_qty  = flt(item.qty)
        received_qty = flt(item.received_qty)
        billed_qty   = flt(item.billed_qty)
        pending_qty  = ordered_qty - billed_qty

        ordered_amt  = flt(item.amount)
        received_amt = flt(item.received_amount)
        billed_amt   = flt(item.billed_amount)
        pending_amt  = ordered_amt - billed_amt

        # Derive per-item status
        if billed_qty >= ordered_qty:
            item_status = _("Fully Billed")
        elif billed_qty > 0:
            item_status = _("Partly Billed")
        elif received_qty >= ordered_qty:
            item_status = _("Fully Received")
        elif received_qty > 0:
            item_status = _("Partly Received")
        else:
            item_status = _("Pending")

        rows.append({
            "custodian":          ac.custodian,
            "accountant_custody": item.parent,
            "posting_date":       ac.transaction_date,
            "item_code":          item.item_code,
            "item_name":          item.item_name or item.description or "",
            "uom":                item.uom,
            "qty":                ordered_qty,
            "received_qty":       received_qty,
            "billed_qty":         billed_qty,
            "pending_qty":        pending_qty,
            "rate":               flt(item.rate),
            "amount":             ordered_amt,
            "received_amount":    received_amt,
            "billed_amount":      billed_amt,
            "pending_amount":     pending_amt,
            "warehouse":          item.warehouse or "",
            "cost_center":        item.cost_center or "",
            "project":            item.project or "",
            "status":             item_status,
            "currency":           ac.currency or frappe.db.get_value(
                                      "Company", filters.company, "default_currency"
                                  ),
        })

    return rows
