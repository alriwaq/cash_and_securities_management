"""
One-time patch to force-sync all Treasury DocTypes and Workspace.
This ensures all DocTypes are registered in the database even when
Developer Mode is off (e.g., on Frappe Cloud production sites).
"""
import frappe


def execute():
    # Ensure Module Def exists
    if not frappe.db.exists("Module Def", "Treasury"):
        module_def = frappe.new_doc("Module Def")
        module_def.module_name = "Treasury"
        module_def.app_name = "cash_and_securities_management"
        module_def.flags.ignore_permissions = True
        module_def.flags.ignore_mandatory = True
        module_def.insert()
        frappe.db.commit()

    # Sync all DocTypes using frappe.reload_doc
    doctypes = [
        "treasury_settings",
        "accountant_custody_item",
        "custody_settlement_entry",
        "custody_request",
        "accountant_custody",
    ]

    for dt_name in doctypes:
        try:
            frappe.reload_doc("treasury", "doctype", dt_name, force=True)
        except Exception as e:
            frappe.log_error(
                f"Patch: Could not sync DocType {dt_name}: {e}",
                "Treasury DocType Sync Patch",
            )

    # Sync workspace
    try:
        frappe.reload_doc("treasury", "workspace", "treasury", force=True)
    except Exception as e:
        frappe.log_error(
            f"Patch: Could not sync Treasury workspace: {e}",
            "Treasury Workspace Sync Patch",
        )

    frappe.db.commit()
