"""
Accountant Custody DocType controller — v3
Master document for the spending stage of the custody cycle.

Three-step flow:
  Stage 1: Custody Request → Payment Entry (advance disbursement)
  Stage 2: Accountant Custody → Purchase Receipt → Purchase Invoice
  Stage 3: Accountant Custody → Settlement Payment Entry
           (Debit Payable / Credit Advance  OR  Debit Payable / Credit Bank)

The Settlement PE references the Purchase Invoice so ERPNext marks the PI
as "Paid" automatically — identical to the standard Make Payment flow.

Architecture:
  JS (UI) → api.create_custody_settlement() → doc.create_settlement()
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now, nowdate

CONSOLIDATED = "Consolidated (Party-Based)"
INDIVIDUAL = "Individual (Account-Based)"


def _composite_key(item):
	return (
		item.get("item_code"),
		item.get("warehouse") or "",
		item.get("project") or "",
		item.get("cost_center") or "",
		item.get("uom") or "",
		flt(item.get("rate") or 0),
	)


class AccountantCustody(Document):
	# ── Lifecycle ─────────────────────────────────────────────────────────────
	def validate(self):
		self._sync_from_custody_request()
		self._validate_items()
		self._calculate_totals()
		self.recalculate_status()

	def on_submit(self):
		self.recalculate_status()

	def on_cancel(self):
		self._validate_no_settlements()
		self.db_set("status", "Cancelled")

	# ── Private helpers ───────────────────────────────────────────────────────
	def _sync_from_custody_request(self):
		"""Pull company, custodian, project from the linked Custody Request."""
		if not self.custody_request:
			return
		cr = frappe.db.get_value(
			"Custody Request",
			self.custody_request,
			["company", "custodian", "advance_amount", "paid_amount"],
			as_dict=True,
		)
		if not cr:
			return
		if not self.company:
			self.company = cr.company
		if not self.custodian:
			self.custodian = cr.custodian
		self.custody_request_balance = flt(cr.paid_amount)

	def _validate_items(self):
		"""Ensure at least one item is present."""
		if not self.custody_items:
			frappe.throw(
				_("Please add at least one item to the Accountant Custody."),
				title=_("No Items"),
			)

	def _calculate_totals(self):
		"""Recalculate total_amount from custody_items."""
		total = sum(flt(item.qty) * flt(item.rate) for item in self.custody_items)
		self.total_amount = total

	def _validate_no_settlements(self):
		"""Block cancellation if any settlement PEs exist."""
		settlement_pes = frappe.get_all(
			"Payment Entry",
			filters={
				"custom_accountant_custody": self.name,
				"custom_source_document_type": "Custody Settlement",
				"docstatus": 1,
			},
			fields=["name"],
		)
		if settlement_pes:
			frappe.throw(
				_("Cannot cancel Accountant Custody {0} — it has submitted settlement "
				  "Payment Entries: {1}. Please cancel those first.").format(
					self.name,
					", ".join(d.name for d in settlement_pes),
				),
				title=_("Active Settlements Exist"),
			)

	def _get_custodian_accounts(self):
		"""
		Return (advance_account, payable_account) for this custodian.
		Both accounts are read from the Custodian record — already set correctly
		for Consolidated (shared group) or Individual (dedicated leaf) mode.
		"""
		if not self.custodian:
			frappe.throw(
				_("Custodian is not set on this Accountant Custody."),
				title=_("Missing Custodian"),
			)

		advance_account, payable_account = frappe.db.get_value(
			"Custodian",
			self.custodian,
			["custody_account", "liability_account"],
		) or (None, None)

		if not advance_account:
			frappe.throw(
				_("Advance Account is not configured for Custodian {0}. "
				  "Please submit the Custodian record to auto-create accounts.").format(
					self.custodian
				),
				title=_("Missing Advance Account"),
			)
		if not payable_account:
			frappe.throw(
				_("Payable Account is not configured for Custodian {0}. "
				  "Please submit the Custodian record to auto-create accounts.").format(
					self.custodian
				),
				title=_("Missing Payable Account"),
			)

		return advance_account, payable_account

	# ── Status Engine ─────────────────────────────────────────────────────────
	def recalculate_status(self):
		"""
		Derive status from the state of linked documents.
		Called on validate, submit, and after any PR/PI/PE event.

		Status progression:
		  Draft → Pending → Partly Received → Fully Received
		  → Partly Invoiced → Fully Invoiced → Partly Settled → Fully Settled
		"""
		if self.docstatus == 2:
			return  # Already cancelled

		total_amount = flt(self.total_amount)
		total_settled = flt(self.total_settled_amount or 0)

		# Count submitted PRs and PIs linked to this AC
		submitted_prs = frappe.db.count(
			"Purchase Receipt",
			{"custom_accountant_custody": self.name, "docstatus": 1},
		)
		submitted_pis = frappe.db.count(
			"Purchase Invoice",
			{"custom_accountant_custody": self.name, "docstatus": 1},
		)

		if self.docstatus == 0:
			new_status = "Draft"
		elif submitted_prs == 0 and submitted_pis == 0:
			# No PRs and no PIs yet — awaiting first receipt or invoice
			new_status = "Pending"
		elif submitted_pis == 0:
			# PRs exist but no PI yet
			# Check if all stock items have been received
			total_items = len([
				i for i in self.custody_items if i.is_stock_item or i.is_fixed_asset
			])
			if total_items == 0:
				# No stock items at all — go straight to invoice
				new_status = "Fully Received"
			else:
				# Count PR items received
				received_qty = flt(frappe.db.sql(
					"""
					SELECT COALESCE(SUM(pri.accepted_qty), 0)
					FROM `tabPurchase Receipt Item` pri
					JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
					WHERE pr.custom_accountant_custody = %s AND pr.docstatus = 1
					""",
					(self.name,),
				)[0][0] or 0)
				total_qty = sum(
					flt(i.qty) for i in self.custody_items
					if i.is_stock_item or i.is_fixed_asset
				)
				if received_qty >= total_qty - 0.001:
					new_status = "Fully Received"
				else:
					new_status = "Partly Received"
		elif total_settled <= 0:
			# PIs exist but no settlement yet
			# Check if all items are invoiced
			total_billed = flt(frappe.db.sql(
				"""
				SELECT COALESCE(SUM(pii.qty), 0)
				FROM `tabPurchase Invoice Item` pii
				JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
				WHERE pi.custom_accountant_custody = %s AND pi.docstatus = 1
				""",
				(self.name,),
			)[0][0] or 0)
			total_qty = sum(flt(i.qty) for i in self.custody_items)
			if total_billed >= total_qty - 0.001:
				new_status = "Fully Invoiced"
			else:
				new_status = "Partly Invoiced"
		elif total_settled < total_amount - 0.01:
			new_status = "Partly Settled"
		else:
			new_status = "Fully Settled"

		if self.status != new_status:
			if self.docstatus == 1:
				frappe.db.set_value("Accountant Custody", self.name, "status", new_status)
			else:
				self.status = new_status

	# ── Stage 2: Purchase Receipt ─────────────────────────────────────────────
	@frappe.whitelist()
	def create_purchase_receipt(self):
		"""
		Stage 2a — Create a Purchase Receipt for stock/fixed-asset items.
		Service items bypass the PR and go directly to the PI.
		"""
		stock_items = [
			item for item in self.custody_items
			if item.is_stock_item or item.is_fixed_asset
		]
		if not stock_items:
			frappe.throw(
				_("No stock or fixed-asset items found. Service items go directly to "
				  "Purchase Invoice — use 'Create Purchase Invoice' instead."),
				title=_("No Stock Items"),
			)

		settings = frappe.db.get_singles_dict("Treasury Settings")
		series = settings.get("pr_series") or "AC-PR-.YYYY.-.#####"
		mode = settings.get("accounting_mode") or CONSOLIDATED
		_advance_account, payable_account = self._get_custodian_accounts()

		pr = frappe.new_doc("Purchase Receipt")
		pr.naming_series = series
		pr.posting_date = nowdate()
		pr.company = self.company
		pr.custom_source_document_type = "Custody"
		pr.custom_accountant_custody = self.name
		pr.custom_custodian = self.custodian
		pr.project = self.project
		pr.cost_center = self.cost_center
		pr.set_warehouse = self.warehouse
		if self.custody_request:
			pr.custom_custody_request = self.custody_request

		# Override the stock-received-but-not-billed account to the custodian payable
		pr.stock_received_but_not_billed = payable_account

		if mode == CONSOLIDATED:
			pr.party_type = "Custodian"
			pr.party = self.custodian

		for item in stock_items:
			pr.append("items", {
				"item_code": item.item_code,
				"item_name": item.item_name,
				"qty": flt(item.qty),
				"rate": flt(item.rate),
				"uom": item.uom or "Nos",
				"warehouse": item.warehouse or self.warehouse,
				"project": item.project or self.project,
				"cost_center": item.cost_center or self.cost_center or frappe.db.get_value(
					"Company", self.company, "cost_center"
				),
				"rejected_qty": 0,
			})

		pr.flags.ignore_permissions = True
		pr.insert()

		frappe.msgprint(
			_("Purchase Receipt {0} created. Please review and submit it.").format(
				frappe.bold(pr.name)
			),
			indicator="blue",
		)
		return pr.name

	# ── Stage 2: Purchase Invoice ─────────────────────────────────────────────
	@frappe.whitelist()
	def generate_purchase_invoice(self):
		"""
		Stage 2b — Create a Purchase Invoice.

		If submitted PRs exist: uses ERPNext's native make_purchase_invoice mapper
		to create the PI from those PRs (correct stock valuation).
		If no PRs: creates a direct PI for service items.

		GL Entry (via CustodyPurchaseInvoice override):
		  Debit:  Expense / Stock Account
		  Credit: Custodian Payable Account  ← party_type = Custodian
		"""
		settings = frappe.db.get_singles_dict("Treasury Settings")
		series = settings.get("pi_series") or "AC-PI-.YYYY.-.#####"
		mode = settings.get("accounting_mode") or CONSOLIDATED
		_advance_account, payable_account = self._get_custodian_accounts()

		custody_items_in_order = list(self.custody_items)
		custody_items_by_key = {}
		custody_items_by_code = {}
		for custody_item in custody_items_in_order:
			custody_items_by_key.setdefault(_composite_key(custody_item), []).append(custody_item)
			custody_items_by_code.setdefault(custody_item.item_code, []).append(custody_item)
		ordered_index = 0

		def apply_custody_item_defaults(pi_doc):
			pr_item_map = {}
			pr_detail_names = [d.get("pr_detail") for d in pi_doc.get("items") if d.get("pr_detail")]
			if pr_detail_names:
				for pr_item in frappe.get_all(
					"Purchase Receipt Item",
					filters={"name": ["in", pr_detail_names]},
					fields=["name", "item_code", "warehouse", "project", "cost_center", "uom", "rate"],
				):
					pr_item_map[pr_item.name] = pr_item

			for pi_item in pi_doc.get("items"):
				custody_item = None
				pr_item = pr_item_map.get(pi_item.get("pr_detail"))
				if pr_item and custody_items_by_key.get(_composite_key(pr_item)):
					custody_item = custody_items_by_key[_composite_key(pr_item)].pop(0)
				elif custody_items_by_code.get(pi_item.item_code):
					custody_item = custody_items_by_code[pi_item.item_code].pop(0)
				elif ordered_index < len(custody_items_in_order):
					custody_item = custody_items_in_order[ordered_index]

				if not custody_item:
					continue

				if custody_item.get("warehouse"):
					pi_item.warehouse = custody_item.warehouse
				if custody_item.get("project"):
					pi_item.project = custody_item.project
				if custody_item.get("cost_center"):
					pi_item.cost_center = custody_item.cost_center

		def append_service_items(pi_doc):
			for item in self.custody_items:
				if item.is_stock_item or item.is_fixed_asset:
					continue
				pi_doc.append("items", {
					"item_code": item.item_code,
					"item_name": item.item_name,
					"qty": flt(item.qty),
					"rate": flt(item.rate),
					"uom": item.uom or "Nos",
					"warehouse": item.warehouse,
					"project": item.project or self.project,
					"cost_center": item.cost_center or self.cost_center or frappe.db.get_value(
						"Company", self.company, "cost_center"
					),
				})

		# Check for submitted PRs to use native make_purchase_invoice
		linked_prs = frappe.get_all(
			"Purchase Receipt",
			filters={"custom_accountant_custody": self.name, "docstatus": 1},
			fields=["name"],
		)

		if linked_prs:
			try:
				from cash_and_securities_management.api import (
					make_purchase_invoice as make_pi_from_pr,
				)
				pi_doc = make_pi_from_pr(linked_prs[0].name)
				existing_pr_details = {
					d.get("pr_detail") for d in pi_doc.get("items") if d.get("pr_detail")
				}

				for linked_pr in linked_prs[1:]:
					extra_pi = make_pi_from_pr(linked_pr.name)
					for extra_item in extra_pi.get("items"):
						if extra_item.get("pr_detail") and extra_item.pr_detail in existing_pr_details:
							continue
						if extra_item.get("pr_detail"):
							existing_pr_details.add(extra_item.pr_detail)
						extra_row = extra_item.as_dict()
						for key in (
							"name", "parent", "parentfield", "parenttype",
							"doctype", "idx", "docstatus", "owner",
							"creation", "modified", "modified_by",
						):
							extra_row.pop(key, None)
						pi_doc.append("items", extra_row)
			except Exception:
				pi_doc = frappe.new_doc("Purchase Invoice")
		else:
			pi_doc = frappe.new_doc("Purchase Invoice")

		# Common PI fields
		pi_doc.naming_series = series
		pi_doc.posting_date = nowdate()
		pi_doc.company = self.company
		pi_doc.custom_source_document_type = "Custody"
		pi_doc.custom_accountant_custody = self.name
		pi_doc.custom_custodian = self.custodian
		pi_doc.project = self.project
		pi_doc.cost_center = self.cost_center
		pi_doc.set_warehouse = self.warehouse
		if self.custody_request:
			pi_doc.custom_custody_request = self.custody_request

		# Override credit_to with the custodian's payable account
		pi_doc.credit_to = payable_account

		# In Consolidated mode, set the Custodian as the Party on the PI
		if mode == CONSOLIDATED:
			pi_doc.party_type = "Custodian"
			pi_doc.party = self.custodian
			pi_doc.party_account_currency = frappe.db.get_value(
				"Account", payable_account, "account_currency"
			)

		append_service_items(pi_doc)
		apply_custody_item_defaults(pi_doc)

		if not pi_doc.items:
			frappe.throw(
				_("No purchase receipt or service items found to invoice directly."),
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

	# ── Stage 3: Settlement ────────────────────────────────────────────────────
	@frappe.whitelist()
	def create_settlement(
		self,
		advance_amount_allocated=0,
		direct_payment_amount=0,
		settlement_notes="",
	):
		"""
		Stage 3 — Settlement via Payment Entry.

		Called exclusively through the API layer:
		  JS (UI) → api.create_custody_settlement() → doc.create_settlement()

		Two pathways:
		  1. Advance Deduction  — PE: Internal Transfer
		                          paid_from = Custodian Advance Account (Asset)
		                          paid_to   = Custodian Payable Account (Liability)
		                          GL: Debit Payable / Credit Advance

		  2. Direct Payment     — PE: Pay
		                          paid_from = Bank/Cash Account
		                          paid_to   = Custodian Payable Account (Liability)
		                          GL: Debit Payable / Credit Bank/Cash

		The PE references all submitted PIs linked to this AC so ERPNext marks
		them as "Paid" automatically (same as the standard Make Payment flow).

		Returns the name of the primary Payment Entry created.
		"""
		advance_amount_allocated = flt(advance_amount_allocated)
		direct_payment_amount = flt(direct_payment_amount)
		total_settlement = advance_amount_allocated + direct_payment_amount

		def insert_settlement_row(
			claimed_amount,
			advance_allocated,
			direct_paid,
			total_amount,
			payment_entry,
			notes,
		):
			idx = (
				frappe.db.sql(
					"""
					select ifnull(max(idx), 0) + 1
					from `tabCustody Settlement Entry`
					where parent = %s and parenttype = 'Accountant Custody' and parentfield = 'settlements'
					""",
					(self.name,),
				)[0][0]
				or 1
			)

			row_name = frappe.generate_hash(length=10)
			ts = now()
			frappe.db.sql(
				"""
				insert into `tabCustody Settlement Entry`
				(
					name, creation, modified, modified_by, owner, docstatus, idx,
					parent, parentfield, parenttype,
					custody_request, custody_request_balance,
					claimed_amount, advance_amount_allocated, direct_payment_amount,
					total_settlement_amount, payment_entry, settlement_date, settlement_notes
				)
				values (%s, %s, %s, %s, %s, 0, %s, %s, 'settlements', 'Accountant Custody', %s, %s, %s, %s, %s, %s, %s, %s, %s)
				""",
				(
					row_name,
					ts,
					ts,
					frappe.session.user,
					frappe.session.user,
					idx,
					self.name,
					self.custody_request or "",
					flt(self.custody_request_balance or 0),
					flt(claimed_amount),
					flt(advance_allocated),
					flt(direct_paid),
					flt(total_amount),
					payment_entry,
					nowdate(),
					notes or "",
				),
			)

		def allocate_open_purchase_invoices(pe_doc, allocation_amount):
			remaining = flt(allocation_amount)
			if remaining <= 0:
				return

			open_pis = frappe.get_all(
				"Purchase Invoice",
				filters={
					"custom_accountant_custody": self.name,
					"docstatus": 1,
					"outstanding_amount": [">", 0],
				},
				fields=["name", "grand_total", "outstanding_amount", "due_date"],
				order_by="posting_date asc, name asc",
			)

			for pi in open_pis:
				if remaining <= 0:
					break

				outstanding = flt(pi.outstanding_amount)
				if outstanding <= 0:
					continue

				allocated = min(remaining, outstanding)
				pe_doc.append(
					"references",
					{
						"reference_doctype": "Purchase Invoice",
						"reference_name": pi.name,
						"due_date": pi.due_date,
						"total_amount": flt(pi.grand_total),
						"outstanding_amount": outstanding,
						"allocated_amount": allocated,
					},
				)
				remaining = flt(remaining) - flt(allocated)

			if remaining > 0.01:
				frappe.throw(
					_("Unable to allocate settlement amount {0}; outstanding Purchase Invoices are lower.").format(
						remaining
					),
					title=_("Allocation Error"),
				)

		def create_settlement_payment_entry(amount, paid_from_account, remark):
			pe = frappe.new_doc("Payment Entry")
			pe.payment_type = "Internal Transfer"
			pe.posting_date = nowdate()
			pe.company = self.company
			pe.party_type = "Custodian"
			pe.party = self.custodian
			pe.paid_from = paid_from_account
			pe.paid_to = payable_account
			pe.paid_amount = flt(amount)
			pe.received_amount = flt(amount)
			pe.reference_no = self.name
			pe.reference_date = nowdate()
			pe.remarks = remark
			pe.custom_source_document_type = "Custody"
			pe.custom_accountant_custody = self.name
			pe.custom_custodian = self.custodian
			pe.custom_custody_request = self.custody_request

			allocate_open_purchase_invoices(pe, amount)

			pe.flags.ignore_permissions = True
			pe.insert()
			pe.submit()
			return pe.name

		if total_settlement <= 0:
			frappe.throw(
				_("Settlement amount must be greater than zero."),
				title=_("Invalid Amount"),
			)

		settings = frappe.db.get_singles_dict("Treasury Settings")
		mode = settings.get("accounting_mode") or CONSOLIDATED
		series = settings.get("pe_series") or "AC-PAY-.YYYY.-.#####"
		advance_account, payable_account = self._get_custodian_accounts()
		primary_pe_name = None

		# Fetch all submitted PIs linked to this AC for the PE references table
		linked_pis = frappe.get_all(
			"Purchase Invoice",
			filters={"custom_accountant_custody": self.name, "docstatus": 1},
			fields=["name", "outstanding_amount", "party_account_currency"],
		)

		def _build_pe_references(pe_doc, amount_to_allocate):
			"""Allocate the settlement amount across linked PIs in the PE references table."""
			remaining = flt(amount_to_allocate)
			for pi in linked_pis:
				if remaining <= 0:
					break
				outstanding = flt(pi.outstanding_amount)
				if outstanding <= 0:
					continue
				allocated = min(outstanding, remaining)
				pe_doc.append("references", {
					"reference_doctype": "Purchase Invoice",
					"reference_name": pi.name,
					"allocated_amount": allocated,
					"total_amount": outstanding,
					"outstanding_amount": outstanding,
				})
				remaining -= allocated

		def _insert_settlement_row(pe_name, advance_amt, direct_amt):
			"""Insert a Custody Settlement Entry row directly (doc is submitted)."""
			frappe.db.sql(
				"""INSERT INTO `tabCustody Settlement Entry`
				   (name, parent, parenttype, parentfield, idx,
				    custody_request, custody_request_balance,
				    claimed_amount, advance_amount_allocated, direct_payment_amount,
				    total_settlement_amount, payment_entry,
				    settlement_date, settlement_notes,
				    creation, modified, modified_by, owner, docstatus)
				   VALUES (%s, %s, 'Accountant Custody', 'settlements',
				   (SELECT COALESCE(MAX(idx),0)+1 FROM `tabCustody Settlement Entry` t2
				    WHERE t2.parent = %s),
				   %s, %s, %s, %s, %s, %s, %s, %s, %s,
				   NOW(), NOW(), 'Administrator', 'Administrator', 0)""",
				(
					frappe.generate_hash(length=10),
					self.name,
					self.name,
					self.custody_request or "",
					flt(self.custody_request_balance or 0),
					advance_amt,
					advance_amt,
					direct_amt,
					advance_amt + direct_amt,
					pe_name,
					nowdate(),
					settlement_notes or "",
				),
			)

		# ── Path 1: Advance Deduction (Internal Transfer) ─────────────────────
		if advance_amount_allocated > 0:
			pe = frappe.new_doc("Payment Entry")
			pe.naming_series = series
			pe.payment_type = "Internal Transfer"
			pe.posting_date = nowdate()
			pe.company = self.company
			pe.paid_amount = advance_amount_allocated
			pe.received_amount = advance_amount_allocated
			pe.paid_from = advance_account          # Asset account (reduces advance)
			pe.paid_to = payable_account            # Liability account (clears payable)
			pe.custom_accountant_custody = self.name
			pe.custom_custodian = self.custodian
			pe.custom_source_document_type = "Custody Settlement"
			if self.custody_request:
				pe.custom_custody_request = self.custody_request
			pe.remarks = (
				f"Advance deduction settlement for Accountant Custody {self.name}. "
				f"{settlement_notes}"
			).strip()

			# In Consolidated mode, set the Custodian as the Party
			if mode == CONSOLIDATED:
				pe.party_type = "Custodian"
				pe.party = self.custodian

			# Reference the linked PIs so ERPNext marks them as Paid
			_build_pe_references(pe, advance_amount_allocated)

			pe.flags.ignore_permissions = True
			pe.insert()
			pe.submit()
			primary_pe_name = pe.name

			_insert_settlement_row(pe.name, advance_amount_allocated, 0)

		# ── Path 2: Direct Payment (Bank/Cash → Payable) ─────────────────────
		if direct_payment_amount > 0:
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
			pe.naming_series = series
			pe.payment_type = "Pay"
			pe.posting_date = nowdate()
			pe.company = self.company
			pe.paid_amount = direct_payment_amount
			pe.received_amount = direct_payment_amount
			pe.paid_from = pay_from                 # Bank/Cash account
			pe.paid_to = payable_account            # Liability account (clears payable)
			pe.custom_accountant_custody = self.name
			pe.custom_custodian = self.custodian
			pe.custom_source_document_type = "Custody Settlement"
			if self.custody_request:
				pe.custom_custody_request = self.custody_request
			pe.remarks = (
				f"Direct payment settlement for Accountant Custody {self.name}. "
				f"{settlement_notes}"
			).strip()

			# In Consolidated mode, set the Custodian as the Party
			if mode == CONSOLIDATED:
				pe.party_type = "Custodian"
				pe.party = self.custodian

			# Reference the linked PIs so ERPNext marks them as Paid
			_build_pe_references(pe, direct_payment_amount)

			pe.flags.ignore_permissions = True
			pe.insert()
			pe.submit()
			if not primary_pe_name:
				primary_pe_name = pe.name

			_insert_settlement_row(pe.name, 0, direct_payment_amount)

		# ── Update totals and status (doc is submitted — use db_set) ─────────
		new_settled = flt(
			frappe.db.get_value("Accountant Custody", self.name, "total_settled_amount") or 0
		) + total_settlement
		frappe.db.set_value("Accountant Custody", self.name, "total_settled_amount", new_settled)

		# Reload and recalculate status from fresh DB state
		fresh_doc = frappe.get_doc("Accountant Custody", self.name)
		fresh_doc.recalculate_status()

		# Update Custody Request claimed amounts if advance was used
		if advance_amount_allocated > 0 and self.custody_request:
			cr_doc = frappe.get_doc("Custody Request", self.custody_request)
			cr_doc.update_claimed_amount()

		return primary_pe_name

	def _get_payable_account(self):
		"""Backward-compatibility wrapper."""
		_advance, payable = self._get_custodian_accounts()
		return payable

	# ── PR/PI Callbacks ──────────────────────────────────────────────────────
	def update_received_quantities(self):
		"""
		Called after a linked PR is submitted or cancelled.
		Updates accepted_qty/rejected_qty on child items using direct DB writes
		(safe for submitted documents).
		"""
		prs = frappe.get_all(
			"Purchase Receipt",
			filters={"custom_accountant_custody": self.name, "docstatus": 1},
			fields=["name"],
		)

		# Aggregate received/rejected qty per item_code across all submitted PRs
		received = {}
		rejected = {}
		for pr_record in prs:
			pr_doc = frappe.get_doc("Purchase Receipt", pr_record.name)
			for pr_item in pr_doc.items:
				code = pr_item.item_code
				received[code] = flt(received.get(code, 0)) + flt(pr_item.qty)
				rejected[code] = flt(rejected.get(code, 0)) + flt(pr_item.rejected_qty)

		# Write directly to child table rows (bypasses docstatus check)
		for custody_item in self.custody_items:
			code = custody_item.item_code
			new_accepted = received.get(code, 0)
			new_rejected = rejected.get(code, 0)
			frappe.db.set_value(
				"Accountant Custody Item",
				custody_item.name,
				{"accepted_qty": new_accepted, "rejected_qty": new_rejected},
				update_modified=False,
			)
			# Keep in-memory copy in sync
			custody_item.accepted_qty = new_accepted
			custody_item.rejected_qty = new_rejected

		# Recalculate totals and persist via db_set
		self._calculate_totals()
		frappe.db.set_value(
			"Accountant Custody",
			self.name,
			{"total_amount": flt(self.total_amount)},
			update_modified=False,
		)
		# Always reload from DB before recalculating status so that
		# the status engine sees the freshly written qty values.
		from cash_and_securities_management.treasury.balances import (
			recalculate_accountant_custody_status,
		)
		recalculate_accountant_custody_status(self.name)

	def update_billed_quantities(self, pi_name=None):
		"""
		Called after a linked PI is submitted or cancelled.
		Updates billed_qty on child items using direct DB writes
		(safe for submitted documents).
		"""
		all_pis = frappe.get_all(
			"Purchase Invoice",
			filters={"custom_accountant_custody": self.name, "docstatus": 1},
			fields=["name"],
		)

		# Aggregate billed qty per item_code across all submitted PIs
		billed = {}
		for pi_record in all_pis:
			pi = frappe.get_doc("Purchase Invoice", pi_record.name)
			for pi_item in pi.items:
				code = pi_item.item_code
				billed[code] = flt(billed.get(code, 0)) + flt(pi_item.qty)

		# Write directly to child table rows (bypasses docstatus check)
		for custody_item in self.custody_items:
			code = custody_item.item_code
			new_billed = billed.get(code, 0)
			frappe.db.set_value(
				"Accountant Custody Item",
				custody_item.name,
				{"billed_qty": new_billed},
				update_modified=False,
			)
			custody_item.billed_qty = new_billed

		# Recalculate totals and persist via db_set
		self._calculate_totals()
		frappe.db.set_value(
			"Accountant Custody",
			self.name,
			{"total_amount": flt(self.total_amount)},
			update_modified=False,
		)
		# Always reload from DB before recalculating status so that
		# the status engine sees the freshly written qty values.
		from cash_and_securities_management.treasury.balances import (
			recalculate_accountant_custody_status,
		)
		recalculate_accountant_custody_status(self.name)
