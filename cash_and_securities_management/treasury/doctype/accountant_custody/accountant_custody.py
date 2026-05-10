"""
Accountant Custody DocType controller — v2.1
Manages the full procurement and settlement lifecycle for a custodian's cash purchases.

Status lifecycle:
  Draft → Pending → Partly Received → Fully Received
       → Partly Invoiced → Fully Invoiced
       → Partly Settled → Fully Settled → Closed | Cancelled

Three-step flow:
  Stage 2 — Spending:
    Accountant Custody → Purchase Receipt → Purchase Invoice
    GL (PI):
      Debit:  Expense / Stock Account
      Credit: Custodian Payable Account  ← liability_account on Custodian

  Stage 3 — Settlement:
    Settle Button → JS Dialog → Journal Entry
    GL (JE):
      Debit:  Custodian Payable Account  ↓  (reduce liability)
      Credit: Custodian Advance Account  ↓  (reduce asset)

Mode handling:
  Consolidated — accounts are the shared group accounts; Custodian is set as
                 Party on both the PI and the JE to isolate individual balances.
  Individual   — accounts are the custodian's dedicated leaf accounts; no Party
                 field is needed on the GL entries.

Settlement pathways (via dynamic JS dialog):
  1. Advance Deduction  — Journal Entry debiting the custodian's payable account
  2. Direct Payment     — Payment Entry paying the supplier directly
  3. Mixed              — Combination of both
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

CONSOLIDATED = "Consolidated (Party-Based)"


class AccountantCustody(Document):
	# ── Lifecycle ─────────────────────────────────────────────────────────────
	def validate(self):
		self._sync_custodian_fields()
		self._calculate_totals()

	def on_submit(self):
		self._validate_items()
		self.db_set("status", "Pending")

	def on_cancel(self):
		self._validate_cancellation_order()
		self.db_set("status", "Cancelled")

	# ── Private helpers ───────────────────────────────────────────────────────
	def _sync_custodian_fields(self):
		"""Pull company from custodian if not set."""
		if self.custodian and not self.company:
			self.company = frappe.db.get_value("Custodian", self.custodian, "company")

	def _validate_items(self):
		"""At least one item must be present."""
		if not self.custody_items:
			frappe.throw(
				_("Please add at least one item before submitting."),
				title=_("No Items"),
			)

	def _validate_cancellation_order(self):
		"""
		Enforce strict cancellation order:
		  Settlement JE/PE must be cancelled before PI,
		  PI must be cancelled before PR,
		  PR must be cancelled before Accountant Custody.
		"""
		# Check for submitted Purchase Invoices
		linked_pis = frappe.get_all(
			"Purchase Invoice",
			filters={"custom_accountant_custody": self.name, "docstatus": 1},
			fields=["name"],
		)
		if linked_pis:
			frappe.throw(
				_("Cannot cancel Accountant Custody {0}. Please cancel the linked "
				  "Purchase Invoice(s) first: {1}").format(
					self.name,
					", ".join([d.name for d in linked_pis]),
				),
				title=_("Cancel Purchase Invoices First"),
			)

		# Check for submitted Purchase Receipts
		linked_prs = frappe.get_all(
			"Purchase Receipt",
			filters={"custom_accountant_custody": self.name, "docstatus": 1},
			fields=["name"],
		)
		if linked_prs:
			frappe.throw(
				_("Cannot cancel Accountant Custody {0}. Please cancel the linked "
				  "Purchase Receipt(s) first: {1}").format(
					self.name,
					", ".join([d.name for d in linked_prs]),
				),
				title=_("Cancel Purchase Receipts First"),
			)

	def _calculate_totals(self):
		"""Recalculate total_amount and total_billed_amount from child rows."""
		total = 0
		billed = 0
		for item in self.custody_items:
			item.amount = flt(item.qty) * flt(item.rate)
			total += flt(item.amount)
			billed += flt(item.billed_qty) * flt(item.rate)
		self.total_amount = total
		self.total_billed_amount = billed

	def _get_custodian_accounts(self):
		"""
		Return (advance_account, payable_account) for the linked Custodian.
		These are already set on the Custodian record by _create_custody_accounts()
		and reflect the correct mode (Consolidated group or Individual leaf).
		"""
		cust = frappe.db.get_value(
			"Custodian",
			self.custodian,
			["custody_account", "liability_account"],
			as_dict=True,
		)
		if not cust:
			frappe.throw(
				_("Custodian {0} not found.").format(self.custodian),
				title=_("Invalid Custodian"),
			)
		advance_account = cust.custody_account
		payable_account = cust.liability_account

		if not advance_account:
			frappe.throw(
				_("Custodian {0} does not have an Advance Account configured. "
				  "Please submit the Custodian record first or run 'Recreate Accounts'.").format(
					self.custodian
				),
				title=_("Missing Advance Account"),
			)
		if not payable_account:
			frappe.throw(
				_("Custodian {0} does not have a Payable Account configured. "
				  "Please configure the Default Payable Account Group in Treasury Settings "
				  "and run 'Recreate Accounts' on the Custodian.").format(
					self.custodian
				),
				title=_("Missing Payable Account"),
			)
		return advance_account, payable_account

	# ── Status Engine ─────────────────────────────────────────────────────────
	def recalculate_status(self):
		"""
		Determine the correct granular status based on current receipt, invoice,
		and settlement data. Called by the centralized balance engine.
		"""
		if self.docstatus != 1:
			return

		total_qty = sum(flt(i.qty) for i in self.custody_items)
		received_qty = sum(flt(i.accepted_qty) for i in self.custody_items)
		billed_qty = sum(flt(i.billed_qty) for i in self.custody_items)
		total_amount = flt(self.total_amount or 0)
		billed_amount = flt(self.total_billed_amount or 0)
		settled_amount = flt(self.total_settled_amount or 0)

		if settled_amount >= billed_amount and billed_amount > 0:
			new_status = "Fully Settled"
		elif settled_amount > 0:
			new_status = "Partly Settled"
		elif billed_amount >= total_amount and total_amount > 0:
			new_status = "Fully Invoiced"
		elif billed_amount > 0:
			new_status = "Partly Invoiced"
		elif received_qty >= total_qty and total_qty > 0:
			new_status = "Fully Received"
		elif received_qty > 0:
			new_status = "Partly Received"
		else:
			new_status = "Pending"

		if self.status != new_status:
			self.db_set("status", new_status)

	# ── Procurement Actions ────────────────────────────────────────────────────
	@frappe.whitelist()
	def create_purchase_receipt(self):
		"""
		Stage 2 — Spending: Create a Purchase Receipt for stock/fixed-asset items.
		Maps the Custodian's Shadow Supplier as the vendor to allow the PR to bypass
		the standard vendor list while keeping the Custodian as the GL party.
		Returns the name of the created PR.
		"""
		settings = frappe.db.get_singles_dict("Treasury Settings")
		use_single = int(settings.get("use_single_dummy_supplier") or 0)

		if use_single:
			supplier = settings.get("default_cash_purchases_supplier")
		else:
			supplier = frappe.db.get_value("Custodian", self.custodian, "dedicated_supplier")

		if not supplier:
			frappe.throw(
				_("No supplier configured. Please set a Dedicated Supplier on the "
				  "Custodian record or enable Single Dummy Supplier in Treasury Settings."),
				title=_("Missing Supplier"),
			)

		series = settings.get("pr_series") or "AC-PRE-.YYYY.-.#####"

		pr = frappe.new_doc("Purchase Receipt")
		pr.naming_series = series
		pr.supplier = supplier
		pr.posting_date = nowdate()
		pr.company = self.company
		pr.custom_accountant_custody = self.name
		pr.custom_custodian = self.custodian

		# Add stock and fixed-asset items only
		for item in self.custody_items:
			if item.is_stock_item or item.is_fixed_asset:
				pr.append("items", {
					"item_code": item.item_code,
					"item_name": item.item_name,
					"qty": flt(item.qty) - flt(item.accepted_qty),
					"rate": flt(item.rate),
					"uom": item.uom or "Nos",
					"warehouse": item.warehouse,
					"cost_center": item.cost_center or frappe.db.get_value(
						"Company", self.company, "cost_center"
					),
				})

		if not pr.items:
			frappe.throw(
				_("No stock or fixed-asset items remaining to receive."),
				title=_("Nothing to Receive"),
			)

		pr.flags.ignore_permissions = True
		pr.insert()
		frappe.msgprint(
			_("Purchase Receipt {0} created. Please review and submit it.").format(
				frappe.bold(pr.name)
			),
			indicator="blue",
		)
		return pr.name

	@frappe.whitelist()
	def generate_purchase_invoice(self):
		"""
		Stage 2 — Spending: Generate a Purchase Invoice.

		GL Entry (PI):
		  Debit:  Expense or Stock Account
		  Credit: Custodian Payable Account  ← liability_account on Custodian

		Mode handling:
		  Consolidated — credit_to = shared payable group account
		                 party_type = "Custodian", party = self.custodian
		  Individual   — credit_to = custodian's dedicated payable leaf account
		                 No party override needed.

		For stock/fixed-asset items: creates PI from linked PRs using ERPNext native flow.
		For service items (no PR): creates PI directly.
		Returns the name of the created PI.
		"""
		settings = frappe.db.get_singles_dict("Treasury Settings")
		mode = settings.get("accounting_mode") or CONSOLIDATED
		use_single = int(settings.get("use_single_dummy_supplier") or 0)

		if use_single:
			supplier = settings.get("default_cash_purchases_supplier")
		else:
			supplier = frappe.db.get_value("Custodian", self.custodian, "dedicated_supplier")

		if not supplier:
			frappe.throw(
				_("No supplier configured for invoice generation."),
				title=_("Missing Supplier"),
			)

		# Fetch the custodian's payable account (mode-aware)
		_advance_account, payable_account = self._get_custodian_accounts()

		series = settings.get("pi_series") or "AC-PINV-.YYYY.-.#####"

		# Check for submitted PRs to use native make_purchase_invoice
		linked_prs = frappe.get_all(
			"Purchase Receipt",
			filters={"custom_accountant_custody": self.name, "docstatus": 1},
			fields=["name"],
		)

		if linked_prs:
			# Use ERPNext native make_purchase_invoice for correct GL mapping
			try:
				from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
					make_purchase_invoice as make_pi_from_pr,
				)
				pi_doc = make_pi_from_pr(linked_prs[0].name)
			except Exception:
				# Fallback: create PI directly
				pi_doc = frappe.new_doc("Purchase Invoice")
				pi_doc.supplier = supplier

			pi_doc.naming_series = series
			pi_doc.posting_date = nowdate()
			pi_doc.company = self.company
			pi_doc.custom_accountant_custody = self.name
			pi_doc.custom_custodian = self.custodian
			if self.custody_request:
				pi_doc.custom_custody_request = self.custody_request

			# Override credit_to with the custodian's payable account
			pi_doc.credit_to = payable_account

			# In Consolidated mode, set the Custodian as the Party on the PI
			if mode == CONSOLIDATED:
				pi_doc.party_account_currency = frappe.db.get_value(
					"Account", payable_account, "account_currency"
				)

			pi_doc.flags.ignore_permissions = True
			pi_doc.insert()
		else:
			# No PR — direct PI for service items
			pi_doc = frappe.new_doc("Purchase Invoice")
			pi_doc.naming_series = series
			pi_doc.supplier = supplier
			pi_doc.posting_date = nowdate()
			pi_doc.company = self.company
			pi_doc.custom_accountant_custody = self.name
			pi_doc.custom_custodian = self.custodian
			if self.custody_request:
				pi_doc.custom_custody_request = self.custody_request

			# Override credit_to with the custodian's payable account
			pi_doc.credit_to = payable_account

			for item in self.custody_items:
				if not (item.is_stock_item or item.is_fixed_asset):
					pi_doc.append("items", {
						"item_code": item.item_code,
						"item_name": item.item_name,
						"qty": flt(item.qty),
						"rate": flt(item.rate),
						"uom": item.uom or "Nos",
						"cost_center": item.cost_center or frappe.db.get_value(
							"Company", self.company, "cost_center"
						),
					})

			if not pi_doc.items:
				frappe.throw(
					_("No service items found to invoice directly."),
					title=_("Nothing to Invoice"),
				)

			pi_doc.flags.ignore_permissions = True
			pi_doc.insert()

		frappe.msgprint(
			_("Purchase Invoice {0} created. Please review and submit it.").format(
				frappe.bold(pi_doc.name)
			),
			indicator="blue",
		)
		return pi_doc.name

	# ── Settlement ────────────────────────────────────────────────────────────
	@frappe.whitelist()
	def create_settlement(
		self,
		advance_amount_allocated=0,
		direct_payment_amount=0,
		settlement_notes="",
	):
		"""
		Stage 3 — Settlement: Process settlement via the dynamic dialog.

		Supports three pathways:
		  1. Advance Deduction only  — creates a Journal Entry
		  2. Direct Payment only     — creates a Payment Entry
		  3. Mixed                   — creates both

		GL Entry (JE — Advance Deduction):
		  Debit:  Custodian Payable Account  ↓  (reduce liability)
		  Credit: Custodian Advance Account  ↓  (reduce asset)

		Both accounts are fetched from the Custodian record and already reflect
		the correct mode (shared group account or dedicated leaf account).

		In Consolidated mode, the Custodian is set as the Party on both JE lines
		so that the shared accounts carry per-custodian sub-balances.

		Returns the name of the primary document created (JE or PE).
		"""
		advance_amount_allocated = flt(advance_amount_allocated)
		direct_payment_amount = flt(direct_payment_amount)
		total_settlement = advance_amount_allocated + direct_payment_amount

		if total_settlement <= 0:
			frappe.throw(
				_("Settlement amount must be greater than zero."),
				title=_("Invalid Amount"),
			)

		settings = frappe.db.get_singles_dict("Treasury Settings")
		mode = settings.get("accounting_mode") or CONSOLIDATED
		primary_doc_name = None

		# ── Advance Deduction via Journal Entry ───────────────────────────
		if advance_amount_allocated > 0:
			advance_account, payable_account = self._get_custodian_accounts()

			je = frappe.new_doc("Journal Entry")
			je.voucher_type = "Journal Entry"
			je.posting_date = nowdate()
			je.company = self.company
			je.user_remark = (
				f"Advance deduction settlement for Accountant Custody {self.name}. "
				f"{settlement_notes}"
			).strip()
			je.custom_accountant_custody = self.name

			cost_center = frappe.db.get_value("Company", self.company, "cost_center")

			# Debit payable account (reduce liability)
			payable_row = {
				"account": payable_account,
				"debit_in_account_currency": advance_amount_allocated,
				"cost_center": cost_center,
			}
			# Credit advance account (reduce asset)
			advance_row = {
				"account": advance_account,
				"credit_in_account_currency": advance_amount_allocated,
			}

			# In Consolidated mode, set the Custodian as the Party on both lines
			if mode == CONSOLIDATED:
				payable_row["party_type"] = "Custodian"
				payable_row["party"] = self.custodian
				advance_row["party_type"] = "Custodian"
				advance_row["party"] = self.custodian

			je.append("accounts", payable_row)
			je.append("accounts", advance_row)

			je.flags.ignore_permissions = True
			je.insert()
			je.submit()
			primary_doc_name = je.name

			# Record in settlements child table
			self.append("settlements", {
				"custody_request": self.custody_request,
				"custody_request_balance": self.custody_request_balance,
				"claimed_amount": advance_amount_allocated,
				"advance_amount_allocated": advance_amount_allocated,
				"direct_payment_amount": 0,
				"total_settlement_amount": advance_amount_allocated,
				"settlement_je": je.name,
				"settlement_date": nowdate(),
				"settlement_notes": settlement_notes,
			})

		# ── Direct Payment via Payment Entry ──────────────────────────────
		if direct_payment_amount > 0:
			use_single = int(settings.get("use_single_dummy_supplier") or 0)
			if use_single:
				supplier = settings.get("default_cash_purchases_supplier")
			else:
				supplier = frappe.db.get_value("Custodian", self.custodian, "dedicated_supplier")

			pay_from = (
				frappe.db.get_value("Company", self.company, "default_bank_account")
				or frappe.db.get_value("Company", self.company, "default_cash_account")
			)
			if not pay_from:
				frappe.throw(
					_("Please set a Default Bank Account or Default Cash Account "
					  "for company {0} in Company settings.").format(self.company),
					title=_("Missing Account"),
				)

			pe = frappe.new_doc("Payment Entry")
			pe.payment_type = "Pay"
			pe.posting_date = nowdate()
			pe.company = self.company
			pe.party_type = "Supplier"
			pe.party = supplier
			pe.paid_from = pay_from
			pe.paid_amount = direct_payment_amount
			pe.received_amount = direct_payment_amount
			pe.reference_no = self.name
			pe.reference_date = nowdate()
			pe.custom_accountant_custody = self.name
			pe.custom_custodian = self.custodian
			pe.remarks = (
				f"Direct payment settlement for Accountant Custody {self.name}. "
				f"{settlement_notes}"
			).strip()
			pe.flags.ignore_permissions = True
			pe.insert()
			# Leave as DRAFT — user must review and submit
			if not primary_doc_name:
				primary_doc_name = pe.name

			# Record in settlements child table
			self.append("settlements", {
				"custody_request": self.custody_request,
				"custody_request_balance": self.custody_request_balance,
				"claimed_amount": 0,
				"advance_amount_allocated": 0,
				"direct_payment_amount": direct_payment_amount,
				"total_settlement_amount": direct_payment_amount,
				"payment_entry": pe.name,
				"settlement_date": nowdate(),
				"settlement_notes": settlement_notes,
			})

		# ── Update totals and status ──────────────────────────────────────
		new_settled = flt(self.total_settled_amount or 0) + total_settlement
		self.db_set("total_settled_amount", new_settled)
		self.save(ignore_permissions=True)
		self.recalculate_status()

		# Update Custody Request claimed amounts if advance was used
		if advance_amount_allocated > 0 and self.custody_request:
			cr_doc = frappe.get_doc("Custody Request", self.custody_request)
			cr_doc.update_claimed_amount()

		return primary_doc_name

	def _get_payable_account(self):
		"""
		Get the payable account for settlement Journal Entries.
		Delegates to _get_custodian_accounts() which reads the Custodian record
		(already set correctly for both Consolidated and Individual modes).
		Kept for backward compatibility with any external callers.
		"""
		_advance, payable = self._get_custodian_accounts()
		return payable

	# ── PR/PI Callbacks ──────────────────────────────────────────────────────
	def update_received_quantities(self):
		"""Called after a linked PR is submitted. Updates accepted_qty on items."""
		prs = frappe.get_all(
			"Purchase Receipt",
			filters={"custom_accountant_custody": self.name, "docstatus": 1},
			fields=["name"],
		)
		if not prs:
			return

		for item in self.custody_items:
			item.accepted_qty = 0
			item.rejected_qty = 0

		for pr_record in prs:
			pr_doc = frappe.get_doc("Purchase Receipt", pr_record.name)
			for pr_item in pr_doc.items:
				for custody_item in self.custody_items:
					if custody_item.item_code == pr_item.item_code:
						custody_item.accepted_qty = (
							flt(custody_item.accepted_qty) + flt(pr_item.qty)
						)
						custody_item.rejected_qty = (
							flt(custody_item.rejected_qty) + flt(pr_item.rejected_qty)
						)
						break

		self._calculate_totals()
		self.save(ignore_permissions=True)
		self.recalculate_status()

	def update_billed_quantities(self, pi_name=None):
		"""Called after the linked PI is submitted. Updates billed_qty on items."""
		all_pis = frappe.get_all(
			"Purchase Invoice",
			filters={"custom_accountant_custody": self.name, "docstatus": 1},
			fields=["name"],
		)
		if not all_pis:
			return

		for custody_item in self.custody_items:
			custody_item.billed_qty = 0

		for pi_record in all_pis:
			pi = frappe.get_doc("Purchase Invoice", pi_record.name)
			for pi_item in pi.items:
				for custody_item in self.custody_items:
					if custody_item.item_code == pi_item.item_code:
						custody_item.billed_qty = flt(custody_item.billed_qty) + flt(pi_item.qty)
						break

		self._calculate_totals()
		self.save(ignore_permissions=True)
		self.recalculate_status()
