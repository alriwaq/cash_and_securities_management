"""
Setup functions for Cash and Securities Management app.
Called by Frappe during app installation and migration.
"""
import frappe


def after_install():
	"""
	Called once after the app is installed on a site via bench install-app.

	Purpose:
	  - Cleans up old records from previous module names.
	  - Ensures the 'Treasury' Module Def exists.
	  - Auto-initializes the Treasury Settings singleton record.
	"""
	_cleanup_old_records()
	_ensure_module_def()
	_initialize_settings()


def after_migrate():
	"""
	Called after every bench migrate.
	Ensures the Settings record exists even after upgrades.
	"""
	_cleanup_old_records()
	_ensure_module_def()
	_initialize_settings()


def _cleanup_old_records():
	"""Remove old DocType, Workspace, and Module Def records from previous module names."""
	# ── Old DocType: Cash and Securities Settings ──
	if frappe.db.exists("DocType", "Cash and Securities Settings"):
		try:
			frappe.delete_doc("DocType", "Cash and Securities Settings", force=True, ignore_permissions=True)
			frappe.logger().info("Cleaned up old DocType: Cash and Securities Settings")
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
			frappe.logger().info(f"Cleaned up old Workspace: {ws_name}")
		except Exception:
			pass

	# ── Old Module Def records ──
	for old_module in ["Custody Management", "Cash and Securities Management"]:
		if frappe.db.exists("Module Def", old_module):
			try:
				frappe.delete_doc("Module Def", old_module, force=True, ignore_permissions=True)
				frappe.logger().info(f"Cleaned up old Module Def: {old_module}")
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


def _initialize_settings():
	"""Initialize the Treasury Settings singleton if it does not exist."""
	doctype = "Treasury Settings"

	# Verify the DocType is installed before trying to create a record
	if not frappe.db.exists("DocType", doctype):
		frappe.logger().warning(
			f"DocType {doctype} not found in database. "
			f"It should be auto-imported from the app's doctype folder during migrate."
		)
		return

	# For Single doctypes, check tabSingles for any saved value
	# If no value exists, the record has never been saved
	try:
		existing = frappe.db.sql(
			"SELECT value FROM tabSingles WHERE doctype=%s AND field='creation' LIMIT 1",
			(doctype,)
		)
		if existing:
			return  # Already initialized, nothing to do
	except Exception:
		pass

	try:
		doc = frappe.new_doc(doctype)
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.insert()
		frappe.db.commit()
		frappe.logger().info(
			f"Cash and Securities Management: Initialized {doctype} singleton."
		)
	except Exception as e:
		# Log but do not raise — a missing Settings record should not block installation
		frappe.logger().warning(
			f"Cash and Securities Management: Could not initialize {doctype}: {e}"
		)
