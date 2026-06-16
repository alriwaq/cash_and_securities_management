"""
Rename workflow_state → custom_vault_state on Payment Entry.

This patch:
1. Renames the DB column (preserving existing data)
2. Deletes the old Custom Field record (workflow_state)
3. Creates the new Custom Field record (custom_vault_state) if it doesn't exist
4. Deletes the Cash Payment Vault Approval Workflow doc (if it exists)
5. Clears the Workflow State field reference from Payment Entry DocType
"""
import frappe


def execute():
    # ── Step 1: Rename the column in the database ──────────────────────────────
    # Check if old column exists
    old_col_exists = frappe.db.sql(
        """
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'tabPayment Entry'
          AND COLUMN_NAME = 'workflow_state'
          AND TABLE_SCHEMA = DATABASE()
        """
    )
    new_col_exists = frappe.db.sql(
        """
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'tabPayment Entry'
          AND COLUMN_NAME = 'custom_vault_state'
          AND TABLE_SCHEMA = DATABASE()
        """
    )

    if old_col_exists and not new_col_exists:
        # Rename column (preserves data)
        frappe.db.sql(
            """
            ALTER TABLE `tabPayment Entry`
            CHANGE COLUMN `workflow_state` `custom_vault_state`
            VARCHAR(140) DEFAULT 'Draft'
            """
        )
        frappe.db.commit()
    elif old_col_exists and new_col_exists:
        # Both exist — copy data from old to new, then drop old
        frappe.db.sql(
            """
            UPDATE `tabPayment Entry`
            SET `custom_vault_state` = `workflow_state`
            WHERE `workflow_state` IS NOT NULL
              AND `workflow_state` != ''
              AND (`custom_vault_state` IS NULL OR `custom_vault_state` = '' OR `custom_vault_state` = 'Draft')
            """
        )
        try:
            frappe.db.sql("ALTER TABLE `tabPayment Entry` DROP COLUMN `workflow_state`")
        except Exception:
            pass  # Column may be locked by Frappe internals
        frappe.db.commit()
    elif not old_col_exists and not new_col_exists:
        # Neither exists — create the new column
        frappe.db.sql(
            """
            ALTER TABLE `tabPayment Entry`
            ADD COLUMN `custom_vault_state` VARCHAR(140) DEFAULT 'Draft'
            """
        )
        frappe.db.commit()
    # else: only new_col_exists — nothing to do

    # ── Step 2: Delete old Custom Field record ─────────────────────────────────
    old_cf = frappe.db.get_value(
        "Custom Field",
        {"dt": "Payment Entry", "fieldname": "workflow_state"},
        "name",
    )
    if old_cf:
        frappe.delete_doc("Custom Field", old_cf, force=True, ignore_permissions=True)

    # ── Step 3: Ensure new Custom Field record exists ──────────────────────────
    new_cf = frappe.db.get_value(
        "Custom Field",
        {"dt": "Payment Entry", "fieldname": "custom_vault_state"},
        "name",
    )
    if not new_cf:
        cf_doc = frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "Payment Entry",
                "fieldname": "custom_vault_state",
                "fieldtype": "Select",
                "label": "حالة سير العمل / Vault State",
                "options": "Draft\nPending Vault Approval\nVault Approved\nSubmitted to GL\nRejected",
                "default": "Draft",
                "insert_after": "mode_of_payment",
                "depends_on": "eval:doc.mode_of_payment == 'Cash'",
                "read_only": 1,
                "allow_on_submit": 1,
                "no_copy": 1,
                "module": "Treasury",
            }
        )
        cf_doc.flags.ignore_permissions = True
        cf_doc.insert()

    # ── Step 4: Delete the Workflow document ───────────────────────────────────
    if frappe.db.exists("Workflow", "Cash Payment Vault Approval"):
        frappe.delete_doc("Workflow", "Cash Payment Vault Approval", force=True, ignore_permissions=True)

    # ── Step 5: Clear any workflow association on Payment Entry DocType ─────────
    # The DocType may have a cached workflow_state_field reference
    try:
        frappe.db.sql(
            """
            UPDATE `tabDocType` SET workflow_state_field = NULL
            WHERE name = 'Payment Entry' AND workflow_state_field IS NOT NULL
            """
        )
    except Exception:
        pass

    frappe.db.commit()
    frappe.clear_cache(doctype="Payment Entry")
