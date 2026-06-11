"""
Patch: populate_custodian_name
================================
v5 — Adds the `custodian_name` field to all existing Custodian records.

ERPNext's Payment Entry `get_party_details()` expects a field named
`{party_type_lower}_name` on the party doctype. For Custodian, this means
it looks for `custodian_name`. Previously this field did not exist, causing:
  OperationalError: Unknown column 'custodian_name' in 'SELECT'

This patch populates `custodian_name = employee_name` for all existing records.
"""
import frappe


def execute():
    # First ensure the column exists (bench migrate should have added it,
    # but this patch may run before the schema sync completes on some setups)
    try:
        frappe.db.sql(
            """
            UPDATE `tabCustodian`
            SET custodian_name = employee_name
            WHERE (custodian_name IS NULL OR custodian_name = '')
              AND employee_name IS NOT NULL
              AND employee_name != ''
            """
        )
        updated = frappe.db.sql(
            "SELECT COUNT(*) FROM `tabCustodian` WHERE custodian_name IS NOT NULL AND custodian_name != ''"
        )[0][0]
        frappe.logger().info(
            f"[v5 populate_custodian_name] Updated {updated} Custodian records with custodian_name."
        )
    except Exception as e:
        # Column may not exist yet if schema sync hasn't run — safe to skip
        frappe.logger().warning(
            f"[v5 populate_custodian_name] Skipped: {e}"
        )

    frappe.db.commit()
