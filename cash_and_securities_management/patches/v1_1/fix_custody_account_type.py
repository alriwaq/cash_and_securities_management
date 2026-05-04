"""
Patch: fix_custody_account_type
================================
Custody accounts were created with account_type = 'Receivable', which
requires a Customer party on every transaction (Payment Entry, Journal Entry).
This is incorrect — custody accounts are plain current-asset ledgers similar
to a petty-cash account.

This patch clears the account_type on all existing custody accounts so that
transactions can be posted without a party.
"""
import frappe


def execute():
    # Find all accounts whose name ends with '- Custody' and are linked to a Custodian
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

        # Only fix accounts that are currently set to Receivable
        current_type = frappe.db.get_value("Account", account_name, "account_type")
        if current_type == "Receivable":
            frappe.db.set_value(
                "Account",
                account_name,
                "account_type",
                "",
                update_modified=False,
            )
            frappe.logger().info(
                f"Patch fix_custody_account_type: cleared account_type on '{account_name}'"
            )

    frappe.db.commit()
