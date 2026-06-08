"""
Patch: fix_custody_account_type
================================
v1 (original): Cleared account_type on custody accounts that were incorrectly
               set to 'Receivable'.

v2 (current):  Migrates all custody accounts to the dedicated 'Custody'
               account_type regardless of their current type (Receivable,
               Payable, blank).  This ensures:
                 • Custody accounts are excluded from standard AP/AR reports
                 • The PI override (validate_credit_to_acc) accepts them cleanly
                 • No custom checkbox (custom_is_custody_account) is needed
"""
import frappe


def execute():
    custodian_accounts = frappe.db.sql(
        """
        SELECT c.custody_account
        FROM `tabCustodian` c
        WHERE c.custody_account IS NOT NULL
          AND c.custody_account != ''
        """,
        as_dict=True,
    )

    if not custodian_accounts:
        return

    for row in custodian_accounts:
        account_name = row.get("custody_account")
        if not account_name:
            continue

        current_type = frappe.db.get_value("Account", account_name, "account_type")
        # Migrate any non-Custody account to the dedicated Custody type
        if current_type != "Custody":
            frappe.db.set_value(
                "Account",
                account_name,
                "account_type",
                "Custody",
                update_modified=False,
            )
            frappe.logger().info(
                f"Patch fix_custody_account_type: set account_type='Custody' "
                f"on '{account_name}' (was '{current_type}')"
            )

    frappe.db.commit()
