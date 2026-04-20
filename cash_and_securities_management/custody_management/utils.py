"""
Shared utility functions for the Cash and Securities Management module.
"""

import frappe
from frappe import _


def get_settings():
	"""
	Safely fetch Cash and Securities Settings.

	For Single doctypes, Frappe requires at least one row in the database
	before get_doc/get_cached_doc can return a record. If the user has not
	yet visited the Settings page after installation, the record does not
	exist and a DoesNotExistError is raised.

	This helper ensures the record is auto-initialized with defaults on first
	access so that all controllers can call it safely without crashing.
	"""
	doctype = "Cash and Securities Settings"

	# Check if the single record exists in the database
	if not frappe.db.exists(doctype, doctype):
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
