"""
Shared utility functions for the Treasury module.
"""
import frappe
from frappe import _


def get_settings():
	"""
	Safely fetch Treasury Settings.

	For Single doctypes, Frappe stores the record in tabSingles.
	This helper checks if the DocType is installed and if the singleton
	has been saved. If not, it auto-initializes it so controllers
	do not crash.
	"""
	doctype = "Treasury Settings"

	# First verify the DocType itself is installed in the database
	if not frappe.db.exists("DocType", doctype):
		# DocType not yet installed — return empty defaults silently
		return frappe._dict()

	# For Single doctypes, check if any value exists in tabSingles
	# get_singles_value returns None if no record has been saved yet
	exists = frappe.db.get_singles_value(doctype, "name")
	if not exists:
		# Auto-create the singleton record with empty defaults
		try:
			doc = frappe.new_doc(doctype)
			doc.flags.ignore_permissions = True
			doc.flags.ignore_mandatory = True
			doc.insert()
			frappe.db.commit()
		except Exception:
			# If insert fails (e.g., race condition), return an empty object
			return frappe._dict()

	try:
		return frappe.get_cached_doc(doctype)
	except Exception:
		return frappe._dict()
