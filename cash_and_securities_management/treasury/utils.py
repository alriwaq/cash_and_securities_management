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
	and the DocType metadata cache is stale.

	IMPORTANT — Checkbox values:
	  tabSingles stores checkbox values as the strings "0" and "1".
	  In Python, any non-empty string is truthy, so `if "0":` evaluates
	  to True. This function casts all checkbox fields to int so that
	  callers can safely use `if settings.get("use_single_dummy_supplier"):`
	  and get the correct boolean behaviour.

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

		# Cast known checkbox fields from string "0"/"1" to int 0/1
		# so that `if settings.get("checkbox_field"):` works correctly.
		checkbox_fields = [
			"use_single_dummy_supplier",
		]
		for field in checkbox_fields:
			if field in data:
				try:
					data[field] = int(data[field])
				except (ValueError, TypeError):
					data[field] = 0

		return data
	except Exception:
		return frappe._dict()
