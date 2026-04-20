"""
Shared utility functions for the Cash and Securities Management module.
"""
import frappe
from frappe import _


def get_settings():
	"""
	Safely fetch Cash and Securities Settings.

	For Single doctypes, Frappe stores the record in tabSingles.
	The correct existence check is frappe.db.exists("DocType", doctype)
	to verify the DocType is installed, then frappe.db.get_singles_value()
	to check if the singleton record has been saved at least once.

	If the record does not exist yet (user has not visited Settings page),
	this helper auto-initializes it so controllers do not crash.
	"""
	doctype = "Cash and Securities Settings"

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
