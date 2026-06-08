"""
Custodian Balance Summary Report
==================================
One row per custodian showing the full financial position:

  Opening Balance (before from_date)
  + Total Disbursed (Custody Request PEs in period)
  - Total Invoiced  (Accountant Custody PIs in period)
  = Closing Balance (outstanding advance)

Also shows:
  - Custody Limit
  - Available Limit  = Limit - Closing Balance
  - # Open ACs       = Accountant Custody docs not fully invoiced
  - Status           = Custodian.status

Filters
-------
  company          : mandatory
  from_date        : optional
  to_date          : optional (defaults to today)
  custodian        : optional
  status           : optional (Active / Suspended / Closed)
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate


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
            "label": _("Employee Name"),
            "fieldname": "employee_name",
            "fieldtype": "Data",
            "width": 180,
        },
        {
            "label": _("Custody Account"),
            "fieldname": "custody_account",
            "fieldtype": "Link",
            "options": "Account",
            "width": 180,
        },
        {
            "label": _("Custody Limit"),
            "fieldname": "custody_limit",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 130,
        },
        {
            "label": _("Opening Balance"),
            "fieldname": "opening_balance",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 140,
        },
        {
            "label": _("Disbursed (Period)"),
            "fieldname": "total_disbursed",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 150,
        },
        {
            "label": _("Invoiced (Period)"),
            "fieldname": "total_invoiced",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 150,
        },
        {
            "label": _("Closing Balance"),
            "fieldname": "closing_balance",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 140,
        },
        {
            "label": _("Available Limit"),
            "fieldname": "available_limit",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 130,
        },
        {
            "label": _("Open ACs"),
            "fieldname": "open_acs",
            "fieldtype": "Int",
            "width": 90,
        },
        {
            "label": _("Status"),
            "fieldname": "status",
            "fieldtype": "Data",
            "width": 100,
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
    custodian_filters = {"company": filters.company}
    if filters.get("custodian"):
        custodian_filters["name"] = filters.custodian
    if filters.get("status"):
        custodian_filters["status"] = filters.status

    custodians = frappe.get_all(
        "Custodian",
        filters=custodian_filters,
        fields=["name", "employee_name", "custody_account", "custody_limit", "status"],
    )

    if not custodians:
        return []

    company_currency = frappe.db.get_value("Company", filters.company, "default_currency")
    account_list = [c.custody_account for c in custodians if c.custody_account]

    if not account_list:
        return []

    # ── GL totals helper (parameterized) ─────────────────────────────────────
    def _gl_sum(accounts, date_condition="", extra_params=None):
        """Return {account: {total_debit, total_credit}} for given accounts."""
        if not accounts:
            return {}
        placeholders = ", ".join(["%s"] * len(accounts))
        sql = f"""
            SELECT
                account,
                SUM(debit)  AS total_debit,
                SUM(credit) AS total_credit
            FROM `tabGL Entry`
            WHERE
                account IN ({placeholders})
                AND company = %s
                AND is_cancelled = 0
                {date_condition}
            GROUP BY account
        """
        params = list(accounts) + [filters.company]
        if extra_params:
            params.extend(extra_params)
        rows = frappe.db.sql(sql, params, as_dict=True)
        return {r.account: r for r in rows}

    # Opening balance: all GL entries BEFORE from_date
    opening_condition = ""
    opening_params = []
    if filters.get("from_date"):
        opening_condition = "AND posting_date < %s"
        opening_params = [filters.from_date]

    opening_gl = _gl_sum(account_list, opening_condition, opening_params)

    # Period GL: entries between from_date and to_date
    period_condition = ""
    period_params = []
    if filters.get("from_date") and filters.get("to_date"):
        period_condition = "AND posting_date BETWEEN %s AND %s"
        period_params = [filters.from_date, filters.to_date]
    elif filters.get("to_date"):
        period_condition = "AND posting_date <= %s"
        period_params = [filters.to_date]

    period_gl = _gl_sum(account_list, period_condition, period_params)

    # Open ACs per custodian (not fully invoiced)
    open_ac_counts = {}
    if custodians:
        cust_names = [c.name for c in custodians]
        placeholders = ", ".join(["%s"] * len(cust_names))
        rows = frappe.db.sql(
            f"""
            SELECT custodian, COUNT(*) AS cnt
            FROM `tabAccountant Custody`
            WHERE
                custodian IN ({placeholders})
                AND company = %s
                AND docstatus = 1
                AND status NOT IN ('Fully Invoiced', 'Closed')
            GROUP BY custodian
            """,
            cust_names + [filters.company],
            as_dict=True,
        )
        open_ac_counts = {r.custodian: r.cnt for r in rows}

    # ── Build rows ────────────────────────────────────────────────────────────
    result = []
    for c in custodians:
        acc = c.custody_account
        if not acc:
            continue

        og = opening_gl.get(acc, frappe._dict(total_debit=0, total_credit=0))
        pg = period_gl.get(acc, frappe._dict(total_debit=0, total_credit=0))

        opening_balance = flt(og.total_debit) - flt(og.total_credit)
        period_debit    = flt(pg.total_debit)
        period_credit   = flt(pg.total_credit)

        # Debit = advance disbursed; Credit = invoice settled
        total_disbursed = period_debit
        total_invoiced  = period_credit
        closing_balance = opening_balance + period_debit - period_credit

        custody_limit   = flt(c.custody_limit)
        available_limit = custody_limit - closing_balance if custody_limit else 0.0

        result.append({
            "custodian":       c.name,
            "employee_name":   c.employee_name or c.name,
            "custody_account": acc,
            "custody_limit":   custody_limit,
            "opening_balance": opening_balance,
            "total_disbursed": total_disbursed,
            "total_invoiced":  total_invoiced,
            "closing_balance": closing_balance,
            "available_limit": available_limit,
            "open_acs":        open_ac_counts.get(c.name, 0),
            "status":          c.status,
            "currency":        frappe.db.get_value("Account", acc, "account_currency")
                               or company_currency,
        })

    return result
