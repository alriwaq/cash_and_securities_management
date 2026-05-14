# Copyright (c) 2024, Cash and Securities Management Contributors
# SPDX-License-Identifier: MIT

import frappe
from frappe.model.document import Document


class CustodyAdvancePaymentEntry(Document):
	"""
	Child table row on Custody Request that tracks every advance
	Payment Entry disbursed against that request.
	"""
	pass
