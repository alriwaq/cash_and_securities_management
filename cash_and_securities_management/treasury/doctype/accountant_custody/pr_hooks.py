"""
Server-side hooks for Purchase Receipt and Purchase Invoice
to keep Accountant Custody quantities in sync.

These functions are registered in hooks.py under doc_events.
"""

import frappe
from frappe import _
from frappe.utils import flt


def on_pr_submit(doc, method):
	"""Triggered after a Purchase Receipt is submitted."""
	if not doc.get("custom_accountant_custody"):
		return
	custody_name = doc.custom_accountant_custody
	custody_doc = frappe.get_doc("Accountant Custody", custody_name)
	custody_doc.update_received_quantities()


def on_pr_cancel(doc, method):
	"""Triggered after a Purchase Receipt is cancelled. Reverses accepted quantities."""
	if not doc.get("custom_accountant_custody"):
		return
	custody_name = doc.custom_accountant_custody
	custody_doc = frappe.get_doc("Accountant Custody", custody_name)
	custody_doc.update_received_quantities()


def on_pr_validate(doc, method):
	"""Triggered on Purchase Receipt validate. Validates items match Accountant Custody."""
	if not doc.get("custom_accountant_custody"):
		return
	custody_name = doc.custom_accountant_custody
	custody_doc = frappe.get_doc("Accountant Custody", custody_name)

	if custody_doc.status == "Settled":
		frappe.throw(
			_("Cannot create a Purchase Receipt against a Settled Accountant Custody {0}.").format(
				custody_name
			)
		)

	# Validate that PR items match Accountant Custody items
	custody_item_codes = {item.item_code for item in custody_doc.custody_items if item.is_stock_item or item.is_fixed_asset}
	for pr_item in doc.items:
		if pr_item.item_code not in custody_item_codes:
			frappe.throw(
				_("Item {0} in Purchase Receipt is not in Accountant Custody {1}.").format(
					pr_item.item_code, custody_name
				)
			)

	# Validate that PR qty does not exceed Accountant Custody qty
	for pr_item in doc.items:
		for custody_item in custody_doc.custody_items:
			if custody_item.item_code == pr_item.item_code:
				# Sum already received qty from other submitted PRs
				already_received = frappe.db.sql(
					"""
					SELECT SUM(pri.qty)
					FROM `tabPurchase Receipt Item` pri
					JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
					WHERE pr.custom_accountant_custody = %s
					AND pr.docstatus = 1
					AND pr.name != %s
					AND pri.item_code = %s
				""",
					(custody_name, doc.name, pr_item.item_code),
				)[0][0] or 0

				max_allowed = flt(custody_item.qty) - flt(already_received)
				if flt(pr_item.qty) > max_allowed:
					frappe.throw(
						_(
							"Row {0}: Qty {1} for item {2} exceeds the remaining receivable quantity {3} in Accountant Custody {4}."
						).format(
							pr_item.idx,
							pr_item.qty,
							pr_item.item_code,
							max_allowed,
							custody_name,
						)
					)
				break


def on_pi_submit(doc, method):
	"""Triggered after a Purchase Invoice is submitted.
	Updates billed quantities, sets purchase_invoice link, and sets status to Invoiced.
	Works whether PI was created from the AC button or from the PR button.
	"""
	if not doc.get("custom_accountant_custody"):
		return
	custody_name = doc.custom_accountant_custody
	try:
		custody_doc = frappe.get_doc("Accountant Custody", custody_name)
	except frappe.DoesNotExistError:
		frappe.log_error(
			f"Accountant Custody {custody_name} not found during PI submit hook",
			"on_pi_submit"
		)
		return
	custody_doc.update_billed_quantities(pi_name=doc.name)


def on_pi_cancel(doc, method):
	"""Triggered after a Purchase Invoice is cancelled. Resets billed quantities and status."""
	if not doc.get("custom_accountant_custody"):
		return
	custody_name = doc.custom_accountant_custody
	custody_doc = frappe.get_doc("Accountant Custody", custody_name)

	# Reset billed quantities
	for custody_item in custody_doc.custody_items:
		custody_item.billed_qty = 0
	custody_doc._calculate_totals()
	custody_doc.db_set("purchase_invoice", None)
	custody_doc.db_set("status", "Fully Received")
	custody_doc.save(ignore_permissions=True)


def on_pi_validate(doc, method):
	"""Triggered on Purchase Invoice validate. Validates items and reflects changes to Custody.
	Also propagates custom_custodian and custom_accountant_custody from linked PR items
	when the PI is created via ERPNext's standard Create -> Purchase Invoice button on a PR.
	"""
	# Propagate custom fields from the linked PR if not already set.
	# This handles the case where the user clicks "Create -> Purchase Invoice"
	# directly on a Purchase Receipt that has custom_accountant_custody set.
	if not doc.get("custom_accountant_custody"):
		# Try to inherit from the first PR item reference
		for pi_item in doc.items:
			if pi_item.get("purchase_receipt"):
				pr_ac = frappe.db.get_value(
					"Purchase Receipt", pi_item.purchase_receipt, "custom_accountant_custody"
				)
				pr_custodian = frappe.db.get_value(
					"Purchase Receipt", pi_item.purchase_receipt, "custom_custodian"
				)
				if pr_ac:
					doc.custom_accountant_custody = pr_ac
				if pr_custodian:
					doc.custom_custodian = pr_custodian
				break
	if not doc.get("custom_accountant_custody"):
		return
	custody_name = doc.custom_accountant_custody
	custody_doc = frappe.get_doc("Accountant Custody", custody_name)

	if custody_doc.status == "Settled":
		frappe.throw(
			_("Cannot modify a Purchase Invoice linked to a Settled Accountant Custody {0}.").format(
				custody_name
			)
		)

	# Reflect PI changes back to custody items (for service items)
	for pi_item in doc.items:
		for custody_item in custody_doc.custody_items:
			if custody_item.item_code == pi_item.item_code:
				if not (custody_item.is_stock_item or custody_item.is_fixed_asset):
					# Service item: update rate from PI
					custody_item.rate = flt(pi_item.rate)
					custody_item.billed_qty = flt(pi_item.qty)
				break

	custody_doc._calculate_totals()
	custody_doc.save(ignore_permissions=True)


def on_payment_submit(doc, method):
	"""Triggered after a Payment Entry is submitted.
	If the PE is linked to a Custody Request, updates the custodian balance
	and marks the Custody Request status accordingly.
	"""
	from frappe.utils import flt

	custody_request = doc.get("custom_custody_request")
	custodian = doc.get("custom_custodian")

	if custody_request:
		try:
			cr_doc = frappe.get_doc("Custody Request", custody_request)
			# Sum all submitted Payment Entries for this Custody Request
			total_paid = frappe.db.sql(
				"""SELECT COALESCE(SUM(paid_amount), 0)
				   FROM `tabPayment Entry`
				   WHERE custom_custody_request = %s AND docstatus = 1""",
				(custody_request,),
			)[0][0]
			cr_doc.db_set("paid_amount", total_paid)
			unallocated = flt(total_paid) - flt(cr_doc.get("total_claimed_amount") or 0)
			cr_doc.db_set("unallocated_amount", unallocated)
			# Update status
			if flt(total_paid) >= flt(cr_doc.requested_amount):
				cr_doc.db_set("status", "Paid")
			elif flt(total_paid) > 0:
				cr_doc.db_set("status", "Partly Paid")
		except Exception as e:
			frappe.log_error(str(e), "on_payment_submit - Custody Request update failed")

	if custodian:
		try:
			custodian_doc = frappe.get_doc("Custodian", custodian)
			custodian_doc.refresh_outstanding()
		except Exception as e:
			frappe.log_error(str(e), "on_payment_submit - Custodian refresh failed")


def on_payment_cancel(doc, method):
	"""Triggered after a Payment Entry is cancelled.
	Reverses the paid amount update on the linked Custody Request.
	"""
	from frappe.utils import flt

	custody_request = doc.get("custom_custody_request")
	custodian = doc.get("custom_custodian")

	if custody_request:
		try:
			cr_doc = frappe.get_doc("Custody Request", custody_request)
			total_paid = frappe.db.sql(
				"""SELECT COALESCE(SUM(paid_amount), 0)
				   FROM `tabPayment Entry`
				   WHERE custom_custody_request = %s AND docstatus = 1""",
				(custody_request,),
			)[0][0]
			cr_doc.db_set("paid_amount", total_paid)
			unallocated = flt(total_paid) - flt(cr_doc.get("total_claimed_amount") or 0)
			cr_doc.db_set("unallocated_amount", unallocated)
			if flt(total_paid) <= 0:
				cr_doc.db_set("status", "Approved")
			elif flt(total_paid) < flt(cr_doc.requested_amount):
				cr_doc.db_set("status", "Partly Paid")
		except Exception as e:
			frappe.log_error(str(e), "on_payment_cancel - Custody Request update failed")

	if custodian:
		try:
			custodian_doc = frappe.get_doc("Custodian", custodian)
			custodian_doc.refresh_outstanding()
		except Exception as e:
			frappe.log_error(str(e), "on_payment_cancel - Custodian refresh failed")
