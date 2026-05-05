"""
Shared utility functions for the Treasury module.
"""
import frappe
from frappe import _


def get_settings():
	"""
	Safely fetch Treasury Settings as a plain dict.

	Uses frappe.db.get_singles_dict() which reads directly from the
	tabSingles table and returns a frappe._dict with no field-name
	validation. This avoids the "Field name does not exist on Treasury
	Settings" error that occurs when frappe.get_cached_doc() is used
	and the DocType metadata cache is stale or the field is not yet
	registered in the current session.

	Returns a frappe._dict so callers can use .get("fieldname") safely —
	missing keys return None instead of raising an exception.
	"""
	doctype = "Treasury Settings"

	# Guard: DocType not yet installed (first deploy before bench migrate)
	if not frappe.db.exists("DocType", doctype):
		return frappe._dict()

	try:
		# get_singles_dict reads directly from tabSingles and returns a
		# plain frappe._dict. It never raises "Field name does not exist"
		# because it does not validate against the DocType field list.
		data = frappe.db.get_singles_dict(doctype)
		return data if data else frappe._dict()
	except Exception:
		return frappe._dict()
