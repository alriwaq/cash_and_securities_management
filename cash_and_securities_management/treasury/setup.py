"""
Setup functions for Cash and Securities Management app.
Called by Frappe during app installation and migration.
"""
import frappe


def after_install():
	"""
	Called once after the app is installed on a site via bench install-app.

	Purpose:
	  - Auto-initializes the Treasury Settings singleton record
	    so it always exists in the database from day one.
	  - Without this, any controller that calls get_settings() before the
	    user visits the Settings page would raise a DoesNotExistError.
	"""
	_initialize_settings()


def after_migrate():
	"""
	Called after every bench migrate.
	Ensures the Settings record exists even after upgrades.
	"""
	_initialize_settings()


def _initialize_settings():
	"""Initialize the Treasury Settings singleton if it does not exist."""
	doctype = "Treasury Settings"

	# Verify the DocType is installed before trying to create a record
	if not frappe.db.exists("DocType", doctype):
		return

	# For Single doctypes, check tabSingles for any saved value
	# If no value exists, the record has never been saved
	existing = frappe.db.get_singles_value(doctype, "name")
	if existing:
		return  # Already initialized, nothing to do

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
