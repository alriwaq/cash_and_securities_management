import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from cash_and_securities_management.custody_management.utils import get_settings


class AccountantCustody(Document):

	# ─── Lifecycle Hooks ──────────────────────────────────────────────────────

	def validate(self):
		self.set_defaults_from_settings()
		self.auto_link_custody_request()
		self.calculate_totals()
		self.update_custody_request_balance()
		self.validate_items()

	def on_submit(self):
		self.db_set("status", "Submitted")
		self.create_purchase_receipt()

	def on_cancel(self):
		self.validate_cancellation()
		self.db_set("status", "Cancelled")

	# ─── Defaults & Setup ─────────────────────────────────────────────────────

	def set_defaults_from_settings(self):
		settings = get_settings()
		if not self.payable_account and settings.get("default_cash_purchases_supplier"):
			supplier = settings.default_cash_purchases_supplier
			payable = frappe.db.get_value(
				"Supplier",
				supplier,
				"default_payable_account",
			)
			if payable:
				self.payable_account = payable

	def auto_link_custody_request(self):
		"""Auto-link to the first unpaid Custody Request for this employee if not set."""
		if self.custody_request or not self.employee:
			return
		first_unpaid = frappe.db.get_value(
			"Custody Request",
			{
				"employee": self.employee,
				"status": ["in", ["Paid", "Partly Claimed"]],
				"docstatus": 1,
			},
			"name",
			order_by="posting_date asc, creation asc",
		)
		if first_unpaid:
			self.custody_request = first_unpaid

	def update_custody_request_balance(self):
		if self.custody_request:
			balance = frappe.db.get_value(
				"Custody Request", self.custody_request, "remaining_balance"
			)
			self.custody_request_balance = flt(balance)

	# ─── Calculations ─────────────────────────────────────────────────────────

	def calculate_totals(self):
		total = 0
		accepted_total = 0
		billed_total = 0
		for item in self.custody_items:
			item.amount = flt(item.qty) * flt(item.rate)
			item.pending_qty = flt(item.qty) - flt(item.accepted_qty)
			total += flt(item.amount)
			accepted_total += flt(item.accepted_qty) * flt(item.rate)
			billed_total += flt(item.billed_qty) * flt(item.rate)
		self.total_amount = total
		self.total_accepted_amount = accepted_total
		self.total_billed_amount = billed_total

	# ─── Validations ──────────────────────────────────────────────────────────

	def validate_items(self):
		for item in self.custody_items:
			if item.is_stock_item and not item.warehouse:
				frappe.throw(
					_("Row {0}: Warehouse is required for stock item {1}").format(
						item.idx, item.item_code
					)
				)
			if item.is_fixed_asset and not item.asset_location:
				frappe.throw(
					_("Row {0}: Asset Location is required for fixed asset {1}").format(
						item.idx, item.item_code
					)
				)

	def validate_cancellation(self):
		if self.status == "Settled":
			frappe.throw(
				_("Cannot cancel a Settled Accountant Custody. Please cancel the settlement first.")
			)
		# Check for active linked Purchase Receipts
		linked_prs = frappe.get_all(
			"Purchase Receipt",
			filters={"custom_accountant_custody": self.name, "docstatus": 1},
			fields=["name"],
		)
		if linked_prs:
			frappe.throw(
				_(
					"Cannot cancel Accountant Custody {0}. Please cancel the linked Purchase Receipt(s) first: {1}"
				).format(self.name, ", ".join([d.name for d in linked_prs]))
			)
		# Check for active linked Purchase Invoice
		if self.purchase_invoice:
			pi_status = frappe.db.get_value(
				"Purchase Invoice", self.purchase_invoice, "docstatus"
			)
			if pi_status == 1:
				frappe.throw(
					_(
						"Cannot cancel Accountant Custody {0}. Please cancel the linked Purchase Invoice {1} first."
					).format(self.name, self.purchase_invoice)
				)

	# ─── Purchase Receipt Creation ─────────────────────────────────────────────

	def create_purchase_receipt(self):
		"""Auto-create a draft Purchase Receipt for all stock/fixed asset items."""
		settings = get_settings()
		stock_items = [
			item for item in self.custody_items if item.is_stock_item or item.is_fixed_asset
		]
		if not stock_items:
			# No stock/asset items — skip PR creation, go straight to Fully Received state
			self.db_set("status", "Fully Received")
			return

		# Duplicate prevention
		existing_pr = frappe.db.get_value(
			"Purchase Receipt",
			{"custom_accountant_custody": self.name, "docstatus": ["!=", 2]},
			"name",
		)
		if existing_pr:
			frappe.msgprint(
				_("A Purchase Receipt {0} already exists for this Accountant Custody.").format(
					existing_pr
				)
			)
			return

		pr = frappe.new_doc("Purchase Receipt")
		pr.supplier = settings.get("default_cash_purchases_supplier") or ""
		pr.posting_date = self.posting_date
		pr.company = self.company
		pr.cost_center = self.cost_center
		pr.project = self.project
		pr.custom_accountant_custody = self.name
		pr.custom_source_document_type = "Custody"
		if settings.get("pr_series"):
			pr.naming_series = settings.pr_series

		for item in stock_items:
			pr.append(
				"items",
				{
					"item_code": item.item_code,
					"qty": item.qty,
					"rate": item.rate,
					"warehouse": item.warehouse,
					"is_fixed_asset": item.is_fixed_asset,
					"asset_location": item.asset_location,
					"cost_center": self.cost_center,
					"project": self.project,
				},
			)

		pr.flags.ignore_permissions = True
		pr.insert()
		frappe.msgprint(
			_("Purchase Receipt {0} created in Draft. Please review and submit.").format(
				frappe.bold(pr.name)
			),
			alert=True,
		)
		self.db_set("status", "Receiving")

	# ─── Purchase Invoice Generation ──────────────────────────────────────────

	@frappe.whitelist()
	def generate_purchase_invoice(self):
		"""Called from the 'Generate Invoice' button. Creates a draft PI."""
		if self.status not in ("Receiving", "Fully Received"):
			frappe.throw(
				_("Purchase Invoice can only be generated when status is 'Receiving' or 'Fully Received'.")
			)
		if self.purchase_invoice:
			frappe.throw(
				_("A Purchase Invoice {0} already exists for this Accountant Custody.").format(
					self.purchase_invoice
				)
			)

		settings = get_settings()

		pi = frappe.new_doc("Purchase Invoice")
		pi.supplier = settings.get("default_cash_purchases_supplier") or ""
		pi.posting_date = nowdate()
		pi.company = self.company
		pi.cost_center = self.cost_center
		pi.project = self.project
		pi.custom_accountant_custody = self.name
		pi.custom_source_document_type = "Custody"
		if settings.get("pi_series"):
			pi.naming_series = settings.pi_series

		for item in self.custody_items:
			# Stock/asset items: use accepted_qty; service items: use qty
			bill_qty = flt(item.accepted_qty) if (item.is_stock_item or item.is_fixed_asset) else flt(item.qty)
			if bill_qty <= 0:
				continue
			pi.append(
				"items",
				{
					"item_code": item.item_code,
					"qty": bill_qty,
					"rate": item.rate,
					"cost_center": self.cost_center,
					"project": self.project,
					"warehouse": item.warehouse,
				},
			)

		pi.flags.ignore_permissions = True
		pi.insert()

		self.db_set("purchase_invoice", pi.name)
		self.db_set("status", "Invoiced")

		frappe.msgprint(
			_("Purchase Invoice {0} created in Draft. Please review and submit.").format(
				frappe.bold(pi.name)
			),
			alert=True,
		)
		return pi.name

	# ─── Settlement ───────────────────────────────────────────────────────────

	@frappe.whitelist()
	def create_settlement(self, settlement_type, advance_amount_allocated=0, direct_payment_amount=0, settlement_notes=""):
		"""Called from the 'Settle' button. Creates a JE and records settlement."""
		if self.status != "Invoiced":
			frappe.throw(_("Settlement can only be done when status is 'Invoiced'."))

		settings = get_settings()
		advance_amount_allocated = flt(advance_amount_allocated)
		direct_payment_amount = flt(direct_payment_amount)
		total_settlement = advance_amount_allocated + direct_payment_amount

		if abs(total_settlement - flt(self.total_billed_amount)) > 0.01:
			frappe.throw(
				_("Settlement amount {0} does not match the billed amount {1}.").format(
					total_settlement, self.total_billed_amount
				)
			)

		# Build Journal Entry
		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Journal Entry"
		je.posting_date = nowdate()
		je.company = self.company
		je.user_remark = _("Settlement for Accountant Custody {0}").format(self.name)

		# Debit Supplier Payable (to clear the PI liability)
		je.append(
			"accounts",
			{
				"account": self.payable_account,
				"debit_in_account_currency": total_settlement,
				"party_type": "Supplier",
				"party": settings.get("default_cash_purchases_supplier") or "",
				"reference_type": "Purchase Invoice",
				"reference_name": self.purchase_invoice,
				"cost_center": self.cost_center,
			},
		)

		# Credit Custody Advance (for advance portion)
		if advance_amount_allocated > 0:
			custody_request_doc = (
				frappe.get_doc("Custody Request", self.custody_request)
				if self.custody_request
				else None
			)
			advance_account = (
				custody_request_doc.advance_account
				if custody_request_doc
				else settings.get("custody_advance_account") or ""
			)
			if not advance_account:
				frappe.throw(
					_("Please set the Custody Advance Account in Cash and Securities Settings.")
				)
			je.append(
				"accounts",
				{
					"account": advance_account,
					"credit_in_account_currency": advance_amount_allocated,
					"party_type": "Employee",
					"party": self.employee,
					"cost_center": self.cost_center,
				},
			)

		# Credit Cash/Bank (for direct payment portion)
		if direct_payment_amount > 0:
			direct_account = settings.get("settlement_expense_account") or ""
			if not direct_account:
				frappe.throw(
					_("Please set the Settlement Expense Account in Cash and Securities Settings.")
				)
			je.append(
				"accounts",
				{
					"account": direct_account,
					"credit_in_account_currency": direct_payment_amount,
					"cost_center": self.cost_center,
				},
			)

		je.flags.ignore_permissions = True
		je.insert()
		je.submit()

		# Record settlement in child table
		self.append(
			"settlements",
			{
				"settlement_type": settlement_type,
				"settlement_date": nowdate(),
				"advance_amount_allocated": advance_amount_allocated,
				"direct_payment_amount": direct_payment_amount,
				"total_settlement_amount": total_settlement,
				"settlement_je": je.name,
				"settlement_notes": settlement_notes,
			},
		)
		self.db_set("status", "Settled")
		self.save(ignore_permissions=True)

		# Update Custody Request claimed amount
		if self.custody_request and advance_amount_allocated > 0:
			cr_doc = frappe.get_doc("Custody Request", self.custody_request)
			cr_doc.update_claimed_amount()

		frappe.msgprint(
			_("Settlement Journal Entry {0} created and submitted. Accountant Custody is now Settled.").format(
				frappe.bold(je.name)
			)
		)
		return je.name

	# ─── PR/PI Callbacks ──────────────────────────────────────────────────────

	def update_received_quantities(self):
		"""Called after a linked PR is submitted. Updates accepted_qty on items."""
		prs = frappe.get_all(
			"Purchase Receipt",
			filters={"custom_accountant_custody": self.name, "docstatus": 1},
			fields=["name"],
		)
		if not prs:
			return

		# Reset accepted quantities
		for item in self.custody_items:
			item.accepted_qty = 0
			item.rejected_qty = 0

		# Sum accepted quantities from all submitted PRs
		for pr_record in prs:
			pr_doc = frappe.get_doc("Purchase Receipt", pr_record.name)
			for pr_item in pr_doc.items:
				for custody_item in self.custody_items:
					if custody_item.item_code == pr_item.item_code:
						custody_item.accepted_qty = flt(custody_item.accepted_qty) + flt(pr_item.accepted_qty)
						custody_item.rejected_qty = flt(custody_item.rejected_qty) + flt(pr_item.rejected_qty)
						break

		# Recalculate totals and update status
		self.calculate_totals()
		all_received = all(
			flt(item.accepted_qty) >= flt(item.qty)
			for item in self.custody_items
			if item.is_stock_item or item.is_fixed_asset
		)
		new_status = "Fully Received" if all_received else "Receiving"
		self.db_set("status", new_status)
		self.save(ignore_permissions=True)

	def update_billed_quantities(self):
		"""Called after the linked PI is submitted. Updates billed_qty on items."""
		if not self.purchase_invoice:
			return
		pi_doc = frappe.get_doc("Purchase Invoice", self.purchase_invoice)
		for pi_item in pi_doc.items:
			for custody_item in self.custody_items:
				if custody_item.item_code == pi_item.item_code:
					custody_item.billed_qty = flt(pi_item.qty)
					break
		self.calculate_totals()
		self.save(ignore_permissions=True)
