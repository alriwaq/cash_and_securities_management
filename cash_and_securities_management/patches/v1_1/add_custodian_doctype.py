"""
v1.1 Patch: Add Custodian standalone DocType and update Treasury Settings.

This patch:
1. Syncs the new Custodian DocType into the database
2. Syncs the updated Treasury Settings (renamed fields, new fields)
3. Syncs updated Custody Request (new custodian field)
4. Syncs updated Accountant Custody (new custodian field)
5. Adds the custodian column to the Custody Request table if missing
"""
import frappe


def execute():
    # ── Step 1: Sync all updated/new DocTypes ─────────────────────────────────
    doctypes = [
        ("treasury", "doctype", "treasury_settings"),
        ("treasury", "doctype", "custodian"),
        ("treasury", "doctype", "custody_request"),
        ("treasury", "doctype", "accountant_custody"),
        ("treasury", "doctype", "accountant_custody_item"),
        ("treasury", "doctype", "custody_settlement_entry"),
    ]

    for module, category, dt_name in doctypes:
        try:
            frappe.reload_doc(module, category, dt_name, force=True)
            frappe.logger().info(f"Patch v1.1: Synced {dt_name}")
        except Exception as e:
            frappe.log_error(
                f"Patch v1.1: Could not sync {dt_name}: {e}",
                "Custodian DocType Patch",
            )

    frappe.db.commit()

    # ── Step 2: Sync workspace ─────────────────────────────────────────────────
    try:
        frappe.reload_doc("treasury", "workspace", "treasury", force=True)
    except Exception as e:
        frappe.log_error(
            f"Patch v1.1: Could not sync workspace: {e}",
            "Custodian DocType Patch",
        )

    frappe.db.commit()

    # ── Step 3: Handle renamed field custody_advance_account → custody_parent_account
    # If the old column exists in tabSingles (Treasury Settings is a singleton),
    # copy the value to the new field name.
    try:
        old_value = frappe.db.sql(
            "SELECT value FROM tabSingles WHERE doctype='Treasury Settings' AND field='custody_advance_account' LIMIT 1"
        )
        if old_value and old_value[0][0]:
            # Check if new field already has a value
            new_value = frappe.db.sql(
                "SELECT value FROM tabSingles WHERE doctype='Treasury Settings' AND field='custody_parent_account' LIMIT 1"
            )
            if not new_value or not new_value[0][0]:
                frappe.db.sql(
                    """
                    INSERT INTO tabSingles (doctype, field, value)
                    VALUES ('Treasury Settings', 'custody_parent_account', %s)
                    ON DUPLICATE KEY UPDATE value = %s
                    """,
                    (old_value[0][0], old_value[0][0]),
                )
                frappe.logger().info(
                    f"Patch v1.1: Migrated custody_advance_account value to custody_parent_account"
                )
    except Exception as e:
        frappe.log_error(
            f"Patch v1.1: Could not migrate custody_advance_account: {e}",
            "Custodian DocType Patch",
        )

    frappe.db.commit()
