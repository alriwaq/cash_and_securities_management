"""
Custody Ledger Report
=====================
AR/AP equivalent for Custody accounts.

Shows per-custodian:
  • Every GL entry posted against their custody_account
  • Running balance (debit = advance outstanding, credit = invoice settled)
  • Outstanding balance at report date

Filters
-------
  company          : mandatory
  from_date        : optional
  to_date          : optional (defaults to today)
  custodian        : optional — filter to one custodian
  show_zero_balance: optional — include custodians with zero outstanding
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if not filters.company:
        frappe.throw(_("Please select a Company."))

    filters.setdefault("to_date", nowdate())

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
            "width": 140,
        },
        {
            "label": _("Custodian Name"),
            "fieldname": "custodian_name",
            "fieldtype": "Data",
            "width": 180,
        },
        {
            "label": _("Posting Date"),
            "fieldname": "posting_date",
            "fieldtype": "Date",
            "width": 110,
        },
        {
            "label": _("Voucher Type"),
            "fieldname": "voucher_type",
            "fieldtype": "Data",
            "width": 140,
        },
        {
            "label": _("Voucher No"),
            "fieldname": "voucher_no",
            "fieldtype": "Dynamic Link",
            "options": "voucher_type",
            "width": 160,
        },
        {
            "label": _("Reference"),
            "fieldname": "against_voucher",
            "fieldtype": "Data",
            "width": 160,
        },
        {
            "label": _("Remarks"),
            "fieldname": "remarks",
            "fieldtype": "Data",
            "width": 220,
        },
        {
            "label": _("Debit (Advance)"),
            "fieldname": "debit",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 140,
        },
        {
            "label": _("Credit (Invoice)"),
            "fieldname": "credit",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 140,
        },
        {
            "label": _("Balance"),
            "fieldname": "balance",
            "fieldtype": "Currency",
            "options": "currency",
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
    # 1. Get all custodians in scope
    custodian_filters = {"company": filters.company}
    if filters.get("custodian"):
        custodian_filters["name"] = filters.custodian

    custodians = frappe.get_all(
        "Custodian",
        filters=custodian_filters,
        fields=["name", "employee_name", "custody_account"],
    )

    if not custodians:
        return []

    account_to_custodian = {c.custody_account: c for c in custodians if c.custody_account}
    if not account_to_custodian:
        return []

    # 2. Fetch GL entries for all custody accounts
    gl_filters = {
        "account": ["in", list(account_to_custodian.keys())],
        "company": filters.company,
        "is_cancelled": 0,
    }
    if filters.get("from_date"):
        gl_filters["posting_date"] = [">=", filters.from_date]
    if filters.get("to_date"):
        if "posting_date" in gl_filters:
            gl_filters["posting_date"] = [
                "between", [filters.from_date, filters.to_date]
            ]
        else:
            gl_filters["posting_date"] = ["<=", filters.to_date]

    gl_entries = frappe.get_all(
        "GL Entry",
        filters=gl_filters,
        fields=[
            "name", "posting_date", "account", "party_type", "party",
            "voucher_type", "voucher_no", "against_voucher_type",
            "against_voucher", "debit", "credit", "remarks",
            "account_currency", "debit_in_account_currency",
            "credit_in_account_currency",
        ],
        order_by="account, posting_date, creation",
    )

    # 3. Build rows grouped by custodian
    rows = []
    running = {}   # account → running balance

    for gl in gl_entries:
        custodian = account_to_custodian.get(gl.account)
        if not custodian:
            continue

        acc = gl.account
        running.setdefault(acc, 0.0)
        running[acc] += flt(gl.debit) - flt(gl.credit)

        rows.append({
            "custodian":      custodian.name,
            "custodian_name": custodian.employee_name or custodian.name,
            "posting_date":   gl.posting_date,
            "voucher_type":   gl.voucher_type,
            "voucher_no":     gl.voucher_no,
            "against_voucher": gl.against_voucher or "",
            "remarks":        gl.remarks or "",
            "debit":          flt(gl.debit),
            "credit":         flt(gl.credit),
            "balance":        running[acc],
            "currency":       gl.account_currency or frappe.db.get_value(
                                  "Company", filters.company, "default_currency"
                              ),
            "indent":         1,
        })

    # 4. Add custodian subtotal rows
    if not rows:
        return []

    # Group by custodian and insert subtotal rows
    final = []
    current_custodian = None
    subtotal_debit = subtotal_credit = subtotal_balance = 0.0

    for row in rows:
        if row["custodian"] != current_custodian:
            if current_custodian is not None:
                # Subtotal for previous custodian
                if not filters.get("show_zero_balance") and abs(subtotal_balance) < 0.01:
                    # Remove the rows we added for this custodian
                    while final and final[-1].get("indent") == 1 and final[-1]["custodian"] == current_custodian:
                        final.pop()
                else:
                    final.append({
                        "custodian":      current_custodian,
                        "custodian_name": "",
                        "posting_date":   None,
                        "voucher_type":   "",
                        "voucher_no":     "",
                        "against_voucher": "",
                        "remarks":        _("Subtotal — {0}").format(current_custodian),
                        "debit":          subtotal_debit,
                        "credit":         subtotal_credit,
                        "balance":        subtotal_balance,
                        "currency":       row["currency"],
                        "bold":           1,
                        "indent":         0,
                    })
                subtotal_debit = subtotal_credit = subtotal_balance = 0.0

            current_custodian = row["custodian"]

        final.append(row)
        subtotal_debit   += flt(row["debit"])
        subtotal_credit  += flt(row["credit"])
        subtotal_balance  = row["balance"]

    # Last custodian subtotal
    if current_custodian:
        if filters.get("show_zero_balance") or abs(subtotal_balance) >= 0.01:
            final.append({
                "custodian":      current_custodian,
                "custodian_name": "",
                "posting_date":   None,
                "voucher_type":   "",
                "voucher_no":     "",
                "against_voucher": "",
                "remarks":        _("Subtotal — {0}").format(current_custodian),
                "debit":          subtotal_debit,
                "credit":         subtotal_credit,
                "balance":        subtotal_balance,
                "currency":       rows[-1]["currency"] if rows else "",
                "bold":           1,
                "indent":         0,
            })

    return final
