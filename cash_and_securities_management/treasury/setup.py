"""
Setup functions for Cash and Securities Management app.
Called by Frappe during app installation and migration.
"""
import os
import frappe
from frappe.modules.import_file import import_file_by_path


def after_install():
	"""
	Called once after the app is installed on a site via bench install-app.
	"""
	_cleanup_old_records()
	_ensure_module_def()
	_sync_doctypes()
	_initialize_settings()


def after_migrate():
	"""
	Called after every bench migrate.
	"""
	_cleanup_old_records()
	_ensure_module_def()
	_sync_doctypes()
	_initialize_settings()


def _cleanup_old_records():
	"""Remove old DocType, Workspace, and Module Def records from previous module names."""
	# ── Old DocType: Cash and Securities Settings ──
	if frappe.db.exists("DocType", "Cash and Securities Settings"):
		try:
			frappe.delete_doc("DocType", "Cash and Securities Settings", force=True, ignore_permissions=True)
		except Exception:
			pass

	# ── Old Workspaces from previous module names ──
	old_workspaces = frappe.get_all(
		"Workspace",
		filters={"module": ["in", ["Custody Management", "Cash and Securities Management"]]},
		pluck="name"
	)
	for ws_name in old_workspaces:
		try:
			frappe.delete_doc("Workspace", ws_name, force=True, ignore_permissions=True)
		except Exception:
			pass

	# ── Old Module Def records ──
	for old_module in ["Custody Management", "Cash and Securities Management"]:
		if frappe.db.exists("Module Def", old_module):
			try:
				frappe.delete_doc("Module Def", old_module, force=True, ignore_permissions=True)
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
			frappe.logger().warning(f"Could not create Module Def Treasury: {e}")


def _sync_doctypes():
	"""
	Force-sync all DocType JSON files from the app's doctype folder into the database.
	This ensures DocTypes are registered even when Developer Mode is off (e.g., Frappe Cloud).
	"""
	# Find the treasury module's doctype directory
	app_path = frappe.get_app_path("cash_and_securities_management")
	doctype_dir = os.path.join(app_path, "treasury", "doctype")

	if not os.path.exists(doctype_dir):
		frappe.logger().warning(f"DocType directory not found: {doctype_dir}")
		return

	# List of all doctypes in the module
	doctypes_to_sync = [
		"treasury_settings",
		"custody_request",
		"accountant_custody",
		"accountant_custody_item",
		"custody_settlement_entry",
	]

	for dt_folder in doctypes_to_sync:
		json_path = os.path.join(doctype_dir, dt_folder, f"{dt_folder}.json")
		if os.path.exists(json_path):
			try:
				import_file_by_path(json_path, force=True)
				frappe.logger().info(f"Synced DocType from: {json_path}")
			except Exception as e:
				frappe.logger().warning(f"Could not sync DocType {dt_folder}: {e}")

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
			(doctype,)
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
