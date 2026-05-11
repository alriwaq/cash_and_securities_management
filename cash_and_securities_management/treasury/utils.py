"""
Shared utility functions for the Treasury module.
"""
import frappe


def get_settings():
	"""
	Safely fetch Treasury Settings as a plain dict.

	Uses frappe.db.get_singles_dict() which reads directly from the
	tabSingles table and returns a frappe._dict with no field-name
	validation. This avoids the "Field name does not exist on Treasury
	Settings" error that occurs when frappe.get_cached_doc() is used
	and the DocType metadata cache is stale.

	Returns a frappe._dict so callers can use .get("fieldname") safely —
	missing keys return None instead of raising an exception.
	"""
	doctype = "Treasury Settings"

	# Guard: DocType not yet installed (first deploy before bench migrate)
	if not frappe.db.exists("DocType", doctype):
		return frappe._dict()

	try:
		data = frappe.db.get_singles_dict(doctype)
		if not data:
			return frappe._dict()
		return data
	except Exception:
		return frappe._dict()
