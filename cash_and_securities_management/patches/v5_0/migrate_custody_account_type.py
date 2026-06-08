"""
Patch: migrate_custody_account_type
=====================================
v5 — Approach B: Dedicated "Custody" account_type

Migrates all existing custody accounts (linked via tabCustodian.custody_account)
from whatever type they currently have (blank, Payable, Receivable) to the new
dedicated "Custody" account_type.

Also migrates the two shared group accounts created by setup.py:
  • Employee Custody Advances - {abbr}
  • Custodian Payables - {abbr}   (left as Payable — this is correct for the
                                   Liability payable group)

Why "Custody":
  • Naturally excluded from standard AP/AR reports (those filter Payable/Receivable)
  • Accepted by our PI override (validate_credit_to_acc checks account_type == "Custody")
  • Removes the need for the custom_is_custody_account checkbox on Account
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

    # ── 3. Remove the custom_is_custody_account checkbox from all Accounts ─────
    # The field is no longer needed — account_type = "Custody" is the signal.
    # We do NOT delete the Custom Field definition here (bench migrate handles
    # that via the updated fixture), but we clear the value so it does not
    # mislead anyone on existing databases.
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

    frappe.db.commit()
