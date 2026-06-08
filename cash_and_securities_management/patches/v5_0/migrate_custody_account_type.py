"""
Patch: migrate_custody_account_type
=====================================
v5 — Approach B: Dedicated "Custody" account_type

Migrates all existing custody accounts (linked via tabCustodian.custody_account)
from whatever type they currently have (blank, Payable, Receivable) to the new
dedicated "Custody" account_type.

Also migrates the two shared group accounts created by setup.py:
  - Employee Custody Advances - {abbr}
  - Custodian Payables - {abbr}   (left as Payable — this is correct for the
                                   Liability payable group)

Why "Custody":
  - Naturally excluded from standard AP/AR reports (those filter Payable/Receivable)
  - Accepted by our PI override (validate_credit_to_acc checks account_type == "Custody")
  - Removes the need for the custom_is_custody_account checkbox on Account

Additionally:
  - Deletes the Custom Field record for custom_is_custody_account
  - Drops the column from tabAccount
"""
import frappe


def execute():
    # ── 1. Migrate individual custody leaf accounts ────────────────────────────
    custodian_accounts = frappe.db.sql(
        """
        SELECT c.custody_account
        FROM `tabCustodian` c
        WHERE c.custody_account IS NOT NULL
          AND c.custody_account != ''
        """,
        as_dict=True,
    )

    for row in custodian_accounts:
        account_name = row.get("custody_account")
        if not account_name:
            continue
        current_type = frappe.db.get_value("Account", account_name, "account_type")
        if current_type != "Custody":
            frappe.db.set_value(
                "Account",
                account_name,
                "account_type",
                "Custody",
                update_modified=False,
            )
            frappe.logger().info(
                f"[v5 migrate_custody_account_type] '{account_name}': "
                f"'{current_type}' → 'Custody'"
            )

    # ── 2. Migrate Employee Custody Advances group accounts ────────────────────
    advance_groups = frappe.db.sql(
        """
        SELECT name FROM `tabAccount`
        WHERE account_name = 'Employee Custody Advances'
          AND is_group = 1
          AND root_type = 'Asset'
          AND account_type != 'Custody'
        """,
        as_dict=True,
    )

    for row in advance_groups:
        frappe.db.set_value(
            "Account",
            row.name,
            "account_type",
            "Custody",
            update_modified=False,
        )
        frappe.logger().info(
            f"[v5 migrate_custody_account_type] Group '{row.name}' → 'Custody'"
        )

    # ── 3. Remove the custom_is_custody_account checkbox completely ────────────
    # Step 3a: Clear the value on all accounts
    try:
        frappe.db.sql(
            """
            UPDATE `tabAccount`
            SET custom_is_custody_account = 0
            WHERE custom_is_custody_account = 1
            """
        )
        frappe.logger().info(
            "[v5 migrate_custody_account_type] Cleared custom_is_custody_account on all accounts."
        )
    except Exception:
        # Column may already be gone on fresh installs — safe to ignore
        pass

    # Step 3b: Delete the Custom Field record so the checkbox disappears from the form
    try:
        cf_name = frappe.db.get_value(
            "Custom Field",
            {"dt": "Account", "fieldname": "custom_is_custody_account"},
        )
        if cf_name:
            frappe.delete_doc("Custom Field", cf_name, force=True)
            frappe.logger().info(
                f"[v5 migrate_custody_account_type] Deleted Custom Field '{cf_name}'"
            )
    except Exception:
        pass

    # Step 3c: Drop the column from the database table
    try:
        frappe.db.sql_ddl(
            "ALTER TABLE `tabAccount` DROP COLUMN `custom_is_custody_account`"
        )
        frappe.logger().info(
            "[v5 migrate_custody_account_type] Dropped column custom_is_custody_account from tabAccount."
        )
    except Exception:
        # Column may already be gone — safe to ignore
        pass

    frappe.db.commit()
