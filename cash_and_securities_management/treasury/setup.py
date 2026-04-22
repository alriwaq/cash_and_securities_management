"""
Setup functions for Cash and Securities Management app.
Called by Frappe during app installation and migration.
"""
import os
import json
import frappe
from frappe import _


def after_install():
    """
    Called once after the app is installed on a site via bench install-app.
    """
    _cleanup_old_records()
    _ensure_module_def()
    _sync_all_doctypes()
    _sync_workspace()
    _install_fixtures()
    _initialize_settings()
    frappe.db.commit()


def after_migrate():
    """
    Called after every bench migrate.
    """
    _cleanup_old_records()
    _ensure_module_def()
    _sync_all_doctypes()
    _sync_workspace()
    _install_fixtures()
    _initialize_settings()
    frappe.db.commit()


def _cleanup_old_records():
    """Remove old DocType, Workspace, and Module Def records from previous module names."""
    # ── Old DocType: Cash and Securities Settings ──
    if frappe.db.exists("DocType", "Cash and Securities Settings"):
        try:
            frappe.delete_doc(
                "DocType", "Cash and Securities Settings",
                force=True, ignore_permissions=True
            )
        except Exception:
            pass

    # ── Old Workspaces from previous module names ──
    old_workspaces = frappe.get_all(
        "Workspace",
        filters={"module": ["in", ["Custody Management", "Cash and Securities Management"]]},
        pluck="name",
    )
    for ws_name in old_workspaces:
        try:
            frappe.delete_doc(
                "Workspace", ws_name, force=True, ignore_permissions=True
            )
        except Exception:
            pass

    # ── Old Module Def records ──
    for old_module in ["Custody Management", "Cash and Securities Management"]:
        if frappe.db.exists("Module Def", old_module):
            try:
                frappe.delete_doc(
                    "Module Def", old_module, force=True, ignore_permissions=True
                )
            except Exception:
                pass

    frappe.db.commit()


def _ensure_module_def():
    """Ensure the 'Treasury' Module Def record exists in the database."""
    if not frappe.db.exists("Module Def", "Treasury"):
        try:
            module_def = frappe.new_doc("Module Def")
            module_def.module_name = "Treasury"
            module_def.app_name = "cash_and_securities_management"
            module_def.flags.ignore_permissions = True
            module_def.flags.ignore_mandatory = True
            module_def.insert()
            frappe.db.commit()
            frappe.logger().info("Created Module Def: Treasury")
        except Exception as e:
            frappe.logger().error(f"Could not create Module Def Treasury: {e}")
    else:
        # Ensure app_name is correct on existing record
        try:
            frappe.db.set_value(
                "Module Def", "Treasury", "app_name",
                "cash_and_securities_management"
            )
        except Exception:
            pass


def _sync_all_doctypes():
    """
    Force-sync all DocType JSON files from the app's doctype folder into the database.
    Uses frappe.reload_doc() which is the standard Frappe mechanism for syncing
    DocTypes from JSON files, even when Developer Mode is off.
    """
    # Method 1: Use frappe.reload_doc (preferred, standard Frappe approach)
    doctypes_to_sync = [
        "treasury_settings",
        "accountant_custody_item",
        "custody_settlement_entry",
        "custody_request",
        "accountant_custody",
    ]

    for dt_name in doctypes_to_sync:
        try:
            frappe.reload_doc(
                "treasury",       # module name (lowercase)
                "doctype",        # doctype category
                dt_name,          # doctype folder name (scrubbed)
                force=True,
            )
            frappe.logger().info(f"reload_doc succeeded for: {dt_name}")
        except Exception as e:
            frappe.logger().error(f"reload_doc failed for {dt_name}: {e}")
            # Fallback: try import_file_by_path
            _sync_doctype_by_path(dt_name)

    frappe.db.commit()


def _sync_doctype_by_path(dt_name):
    """Fallback: import a DocType JSON directly by file path."""
    try:
        from frappe.modules.import_file import import_file_by_path

        app_path = frappe.get_app_path("cash_and_securities_management")
        json_path = os.path.join(app_path, "treasury", "doctype", dt_name, f"{dt_name}.json")

        if os.path.exists(json_path):
            import_file_by_path(json_path, force=True)
            frappe.logger().info(f"import_file_by_path succeeded for: {json_path}")
        else:
            frappe.logger().error(f"DocType JSON not found: {json_path}")
    except Exception as e:
        frappe.logger().error(f"import_file_by_path failed for {dt_name}: {e}")


def _sync_workspace():
    """
    Force-sync the Treasury workspace from the JSON file.
    This ensures the workspace (module page) appears in the sidebar.
    """
    try:
        frappe.reload_doc(
            "treasury",       # module name (lowercase)
            "workspace",      # category
            "treasury",       # workspace folder name
            force=True,
        )
        frappe.logger().info("reload_doc succeeded for Treasury workspace")
    except Exception as e:
        frappe.logger().error(f"reload_doc failed for Treasury workspace: {e}")
        # Fallback: import by path
        try:
            from frappe.modules.import_file import import_file_by_path

            app_path = frappe.get_app_path("cash_and_securities_management")
            ws_path = os.path.join(
                app_path, "treasury", "workspace", "treasury", "treasury.json"
            )
            if os.path.exists(ws_path):
                import_file_by_path(ws_path, force=True)
                frappe.logger().info(f"import_file_by_path succeeded for workspace: {ws_path}")
        except Exception as e2:
            frappe.logger().error(f"Workspace import fallback also failed: {e2}")

    frappe.db.commit()


def _install_fixtures():
    """
    Import fixture JSON files (Custom Fields, Number Cards, Dashboard Charts).
    These are normally imported by Frappe's fixture mechanism, but we force-import
    them here as a safety net for production sites.
    """
    app_path = frappe.get_app_path("cash_and_securities_management")
    fixtures_dir = os.path.join(app_path, "fixtures")

    if not os.path.exists(fixtures_dir):
        return

    fixture_files = [
        "custom_field.json",
        "number_card.json",
        "dashboard_chart.json",
    ]

    for fixture_file in fixture_files:
        fixture_path = os.path.join(fixtures_dir, fixture_file)
        if not os.path.exists(fixture_path):
            continue

        try:
            with open(fixture_path, "r") as f:
                records = json.load(f)

            for record in records:
                doctype = record.get("doctype")
                name = record.get("name")
                if not doctype or not name:
                    continue

                # Skip if record already exists
                if frappe.db.exists(doctype, name):
                    continue

                try:
                    doc = frappe.get_doc(record)
                    doc.flags.ignore_permissions = True
                    doc.flags.ignore_mandatory = True
                    doc.flags.ignore_links = True
                    doc.insert()
                    frappe.logger().info(f"Installed fixture: {doctype} - {name}")
                except Exception as e:
                    frappe.logger().warning(
                        f"Could not install fixture {doctype}/{name}: {e}"
                    )
        except Exception as e:
            frappe.logger().error(f"Error reading fixture file {fixture_file}: {e}")

    frappe.db.commit()


def _initialize_settings():
    """Initialize the Treasury Settings singleton if it does not exist."""
    doctype = "Treasury Settings"

    # Verify the DocType is installed before trying to create a record
    if not frappe.db.exists("DocType", doctype):
        frappe.logger().warning(
            f"DocType {doctype} not found in database after sync. "
            f"Check the treasury_settings.json file."
        )
        return

    # For Single doctypes, check tabSingles for any saved value
    try:
        existing = frappe.db.sql(
            "SELECT value FROM tabSingles WHERE doctype=%s AND field='creation' LIMIT 1",
            (doctype,),
        )
        if existing:
            return  # Already initialized
    except Exception:
        pass

    try:
        doc = frappe.new_doc(doctype)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_mandatory = True
        doc.insert()
        frappe.db.commit()
        frappe.logger().info(f"Initialized {doctype} singleton.")
    except Exception as e:
        frappe.logger().warning(f"Could not initialize {doctype}: {e}")
