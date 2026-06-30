"""
Accountant Custody DocType controller — v4  (Single Self-Settling Account)
Master document for the spending stage of the custody cycle.

Two-step flow:
  Stage 1: Custody Request → Payment Entry (advance disbursement)
           GL: Debit custody_account / Credit Cash|Bank
  Stage 2: Accountant Custody → Purchase Receipt → Purchase Invoice
           GL: Debit Expense / Credit custody_account  ← self-settles the advance

No separate Settlement step is needed.  When total_billed_amount >= total_amount
the AC is "Fully Invoiced" and the custodian's balance is zero.
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

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
		self._populate_item_flags()
		self._calculate_totals()
		self.recalculate_status()

	def on_submit(self):
		self.status = "Pending"
		self.db_set("status", "Pending")
		self.recalculate_status()

	def on_cancel(self):
		self._validate_no_open_invoices()
		self.db_set("status", "Cancelled")

	# ── Private helpers ───────────────────────────────────────────────────────
	def _sync_from_custody_request(self):
		"""Pull company, custodian, and purpose from the linked Custody Request.
		The custody_request field is hidden from the UI on v15 but may still be
		present on older documents or set programmatically — guard with getattr.
		"""
		custody_request = getattr(self, "custody_request", None)
		if not custody_request:
			return
		cr = frappe.db.get_value(
			"Custody Request",
			custody_request,
			["company", "custodian", "advance_amount", "paid_amount", "purpose"],
			as_dict=True,
		)
		if not cr:
			return
		if not self.company:
			self.company = cr.company
		if not self.custodian:
			self.custodian = cr.custodian
		if not self.purpose and cr.purpose:
			self.purpose = cr.purpose
		# custody_request_balance field is hidden on v15 UI but kept in schema
		if hasattr(self, "custody_request_balance"):
			self.custody_request_balance = flt(cr.paid_amount)

	def _populate_item_flags(self):
		"""Ensure is_stock_item and is_fixed_asset are populated server-side."""
		for item in self.custody_items:
			if not item.item_code:
				continue
			flags = frappe.db.get_value(
				"Item",
				item.item_code,
				["is_stock_item", "is_fixed_asset"],
				as_dict=True,
			) or {}
			item.is_stock_item = int(flags.get("is_stock_item") or 0)
			item.is_fixed_asset = int(flags.get("is_fixed_asset") or 0)

	def _validate_items(self):
		"""Ensure at least one item is present."""
		if not self.custody_items:
			frappe.throw(
				_("Please add at least one item to the Accountant Custody."),
				title=_("No Items"),
			)

	def _calculate_totals(self, persist=False):
		"""Recalculate all total fields on the AC and child row derived amounts."""
		# ── Recalculate per-item derived amounts ──────────────────────────────────
		for item in self.custody_items:
			item.amount          = flt(item.qty) * flt(item.rate)
			item.received_amount = flt(item.accepted_qty) * flt(item.rate)
			item.billed_amount   = flt(item.billed_qty) * flt(item.rate)
			item.pending_amount  = item.amount - item.billed_amount

		total = sum(flt(item.amount) for item in self.custody_items)
		self.total_amount = total

		if not self.name:
			return

		total_accepted = flt(
			frappe.db.sql(
				"""
				SELECT COALESCE(SUM(pr.grand_total), 0)
				FROM `tabPurchase Receipt` pr
				WHERE pr.custom_accountant_custody = %s AND pr.docstatus = 1
				""",
				(self.name,),
			)[0][0] or 0
		)
		self.total_accepted_amount = total_accepted

		total_billed = flt(
			frappe.db.sql(
				"""
				SELECT COALESCE(SUM(pi.grand_total), 0)
				FROM `tabPurchase Invoice` pi
				WHERE pi.custom_accountant_custody = %s AND pi.docstatus = 1
				""",
				(self.name,),
			)[0][0] or 0
		)
		self.total_billed_amount = total_billed

		if persist:
			frappe.db.set_value(
				"Accountant Custody",
				self.name,
				{
					"total_amount": total,
					"total_accepted_amount": total_accepted,
					"total_billed_amount": total_billed,
				},
				update_modified=False,
			)

	def _validate_no_open_invoices(self):
		"""Block cancellation if any submitted PIs exist."""
		submitted_pis = frappe.get_all(
			"Purchase Invoice",
			filters={"custom_accountant_custody": self.name, "docstatus": 1},
			fields=["name"],
		)
		if submitted_pis:
			frappe.throw(
				_("Cannot cancel Accountant Custody {0} — it has submitted Purchase "
				  "Invoices: {1}. Please cancel those first.").format(
					self.name,
					", ".join(d.name for d in submitted_pis),
				),
				title=_("Active Invoices Exist"),
			)

	def _get_custody_account(self):
		"""
		Single-Account Model: return the custodian's single custody_account (Receivable).
		Raises a clear error if not configured.
		"""
		if not self.custodian:
			frappe.throw(
				_("Custodian is not set on this Accountant Custody."),
				title=_("Missing Custodian"),
			)

		custody_account = frappe.db.get_value("Custodian", self.custodian, "custody_account")
		if not custody_account:
			frappe.throw(
				_("Custody Account is not configured for Custodian {0}. "
				  "Please submit the Custodian record to auto-create the account.").format(
					self.custodian
				),
				title=_("Missing Custody Account"),
			)
		return custody_account

	# ── Status Engine ─────────────────────────────────────────────────────────
	def recalculate_status(self):
		"""
		Derive status from the state of linked documents.

		Valid statuses (Single-Account Model):
		  Draft, Pending, Partly Received, Fully Received,
		  Partly Invoiced, Fully Invoiced, Closed, Cancelled
		"""
		if self.docstatus == 2:
			return

		total_billed = flt(self.total_billed_amount or 0)

		submitted_prs = frappe.db.count(
			"Purchase Receipt",
			{"custom_accountant_custody": self.name, "docstatus": 1},
		) if self.name else 0

		submitted_pis = frappe.db.count(
			"Purchase Invoice",
			{"custom_accountant_custody": self.name, "docstatus": 1},
		) if self.name else 0

		# Query Item master for stock/asset flags
		stock_item_data = frappe.db.sql(
			"""
			SELECT aci.item_code, aci.qty,
			       COALESCE(item.is_stock_item, 0) AS is_stock_item,
			       COALESCE(item.is_fixed_asset, 0) AS is_fixed_asset
			FROM `tabAccountant Custody Item` aci
			LEFT JOIN `tabItem` item ON item.name = aci.item_code
			WHERE aci.parent = %s AND aci.parenttype = 'Accountant Custody'
			""",
			(self.name,),
			as_dict=True,
		) if self.name else []

		stock_items = [d for d in stock_item_data if d.is_stock_item or d.is_fixed_asset]
		total_stock_qty = sum(flt(d.qty) for d in stock_items)
		total_all_qty = sum(flt(d.qty) for d in stock_item_data)

		if self.docstatus == 0:
			new_status = "Draft"
		elif submitted_prs == 0 and submitted_pis == 0:
			new_status = "Pending"
		elif submitted_pis == 0:
			if not stock_items:
				new_status = "Fully Received"
			else:
				received_qty = flt(frappe.db.sql(
					"""
					SELECT COALESCE(SUM(pri.qty), 0)
					FROM `tabPurchase Receipt Item` pri
					JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
					WHERE pr.custom_accountant_custody = %s AND pr.docstatus = 1
					""",
					(self.name,),
				)[0][0] or 0)
				if received_qty >= total_stock_qty - 0.001:
					new_status = "Fully Received"
				else:
					new_status = "Partly Received"
		else:
			# PIs exist — invoice status
			total_billed_qty = flt(frappe.db.sql(
				"""
				SELECT COALESCE(SUM(pii.qty), 0)
				FROM `tabPurchase Invoice Item` pii
				JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
				WHERE pi.custom_accountant_custody = %s AND pi.docstatus = 1
				""",
				(self.name,),
			)[0][0] or 0)
			fully_billed = (total_billed_qty >= total_all_qty - 0.001)

			if fully_billed:
				new_status = "Fully Invoiced"
			else:
				new_status = "Partly Invoiced"

		old_status = self.status
		if old_status != new_status:
			if self.docstatus == 1:
				frappe.db.set_value("Accountant Custody", self.name, "status", new_status)
			else:
				self.status = new_status

			# ── Perpetual Custody: auto-generate replenishment request ────────────
			if new_status == "Fully Invoiced" and self.docstatus == 1:
				try:
					self._auto_replenish_perpetual_custody()
				except Exception:
					frappe.log_error(
						frappe.get_traceback(),
						f"_auto_replenish_perpetual_custody: failed for AC {self.name}",
					)

	# ── Perpetual Custody Replenishment ──────────────────────────────────────────
	def _auto_replenish_perpetual_custody(self):
		"""
		Called when an Accountant Custody transitions to 'Fully Invoiced'.
		If the linked Custodian has is_perpetual_custody=1 and minimum_custody_balance > 0,
		creates a Draft Custody Request for the SHORTFALL amount so the custodian's
		advance is replenished back to the configured minimum.

		Shortfall = minimum_custody_balance - current_outstanding.
		Handles positive, zero, and negative outstanding (overspent) cases.

		All mandatory Custody Request fields are resolved before insert so that
		validate() passes without ignore_mandatory.
		Left as DRAFT — accountant must review and submit.
		"""
		if not self.custodian:
			return

		# Read perpetual-custody settings from the Custodian record
		cust_data = frappe.db.get_value(
			"Custodian",
			self.custodian,
			["is_perpetual_custody", "minimum_custody_balance", "employee", "company",
			 "department", "custody_account"],
			as_dict=True,
		)
		if not cust_data:
			return

		if not cust_data.get("is_perpetual_custody"):
			return

		min_balance = flt(cust_data.get("minimum_custody_balance") or 0)
		if min_balance <= 0:
			return

		# ── Shortfall calculation ────────────────────────────────────────────────
		# Force a fresh balance recalculation on the Custodian BEFORE reading
		# total_outstanding so we get the post-invoice figure.
		try:
			from cash_and_securities_management.treasury.balances import update_custodian_dashboard
			update_custodian_dashboard(self.custodian)
		except Exception:
			pass  # fall through — read whatever is in DB

		current_outstanding = flt(
			frappe.db.get_value("Custodian", self.custodian, "total_outstanding") or 0
		)

		# shortfall = amount needed to bring custodian back to minimum_custody_balance
		#   outstanding =  2000, min = 5000  → shortfall = 3000
		#   outstanding =  0,    min = 5000  → shortfall = 5000
		#   outstanding = -1000, min = 5000  → shortfall = 6000  (overspent)
		shortfall = min_balance - current_outstanding

		if shortfall <= 0:
			frappe.logger().info(
				f"[Perpetual Custody] No replenishment needed for {self.custodian}: "
				f"outstanding={current_outstanding} >= min={min_balance} (AC={self.name})"
			)
			return

		# Idempotency guard: skip if an open auto-generated CR already exists
		auto_marker = "\u062a\u062c\u062f\u064a\u062f \u062a\u0644\u0642\u0627\u0626\u064a \u0644\u0644\u0639\u0647\u062f\u0629 \u0627\u0644\u0645\u0633\u062a\u062f\u064a\u0645\u0629"
		existing = frappe.db.exists(
			"Custody Request",
			{
				"custodian": self.custodian,
				"docstatus": ["!=", 2],
				"purpose": ["like", f"%{auto_marker}%"],
			},
		)
		if existing:
			return

		# ── Build purpose text with balance details ──────────────────────────────
		if current_outstanding < 0:
			balance_note = (
				f"\u0631\u0635\u064a\u062f \u062d\u0627\u0644\u064a: {frappe.utils.fmt_money(current_outstanding)} "
				f"(\u0639\u062c\u0632) | \u062d\u062f \u0623\u062f\u0646\u0649: {frappe.utils.fmt_money(min_balance)} | "
				f"\u0645\u0628\u0644\u063a \u0627\u0644\u062a\u062c\u062f\u064a\u062f: {frappe.utils.fmt_money(shortfall)}"
			)
		elif current_outstanding == 0:
			balance_note = (
				f"\u0631\u0635\u064a\u062f \u062d\u0627\u0644\u064a: \u0635\u0641\u0631 | \u062d\u062f \u0623\u062f\u0646\u0649: {frappe.utils.fmt_money(min_balance)} | "
				f"\u0645\u0628\u0644\u063a \u0627\u0644\u062a\u062c\u062f\u064a\u062f: {frappe.utils.fmt_money(shortfall)}"
			)
		else:
			balance_note = (
				f"\u0631\u0635\u064a\u062f \u062d\u0627\u0644\u064a: {frappe.utils.fmt_money(current_outstanding)} | "
				f"\u062d\u062f \u0623\u062f\u0646\u0649: {frappe.utils.fmt_money(min_balance)} | "
				f"\u0645\u0628\u0644\u063a \u0627\u0644\u062a\u062c\u062f\u064a\u062f: {frappe.utils.fmt_money(shortfall)}"
			)

		purpose_text = f"{auto_marker} \u2014 {self.name} \u2014 {balance_note}"

		# ── Resolve all mandatory fields before insert ───────────────────────────
		# Mandatory: naming_series, employee, posting_date, company, custodian,
		#            purpose, advance_amount
		ns_field = next(
			(f for f in frappe.get_meta("Custody Request").fields
			 if f.fieldname == "naming_series"),
			None,
		)
		cr_naming_series = (
			ns_field.options.strip().splitlines()[0].strip()
			if ns_field and ns_field.options
			else "CR-.YYYY.-.#####"
		)

		cr_employee = cust_data.get("employee") or self.employee
		cr_company = cust_data.get("company") or self.company
		cr_employee_name = (
			frappe.db.get_value("Employee", cr_employee, "employee_name")
			if cr_employee else None
		)
		cr_department = cust_data.get("department") or (
			frappe.db.get_value("Employee", cr_employee, "department")
			if cr_employee else None
		)
		cr_advance_account = cust_data.get("custody_account")

		cr = frappe.new_doc("Custody Request")
		cr.naming_series = cr_naming_series
		cr.employee = cr_employee
		cr.employee_name = cr_employee_name
		cr.department = cr_department
		cr.company = cr_company
		cr.custodian = self.custodian
		cr.posting_date = nowdate()
		cr.advance_amount = shortfall
		cr.purpose = purpose_text
		if cr_advance_account:
			cr.advance_account = cr_advance_account

		cr.flags.ignore_permissions = True
		cr.flags.ignore_mandatory = False  # all mandatory fields explicitly set above
		cr.insert()
		# Intentionally left as DRAFT — accountant must review and submit

		# Notify connected users in real-time
		frappe.publish_realtime(
			"msgprint",
			{
				"message": _(
					"\u062a\u0645 \u0625\u0646\u0634\u0627\u0621 \u0637\u0644\u0628 \u0639\u0647\u062f\u0629 \u062a\u0644\u0642\u0627\u0626\u064a {0} \u0644\u0644\u0645\u0648\u0638\u0641 {1} \u0628\u0645\u0628\u0644\u063a \u062a\u062c\u062f\u064a\u062f {2} \u2014 \u064a\u0631\u062c\u0649 \u0627\u0644\u0645\u0631\u0627\u062c\u0639\u0629 \u0648\u0627\u0644\u0627\u0639\u062a\u0645\u0627\u062f."
				).format(
					frappe.bold(cr.name),
					frappe.bold(cr.employee),
					frappe.utils.fmt_money(shortfall),
				),
				"title": _("\u0639\u0647\u062f\u0629 \u0645\u0633\u062a\u062f\u064a\u0645\u0629 \u2014 \u062a\u062c\u062f\u064a\u062f \u062a\u0644\u0642\u0627\u0626\u064a"),
				"indicator": "blue",
			},
			user=frappe.session.user,
		)

		frappe.logger().info(
			f"[Perpetual Custody] Auto-generated Custody Request {cr.name} "
			f"for Custodian {self.custodian} (AC={self.name}, "
			f"outstanding={current_outstanding}, min={min_balance}, shortfall={shortfall})"
		)

	# ── Stage 2a: Purchase Receipt ────────────────────────────────────────────
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
		series = settings.get("pr_series") or "CST-PR-.YYYY.-.#####"
		mode = settings.get("accounting_mode") or CONSOLIDATED
		custody_account = self._get_custody_account()

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

		# Single-account: stock_received_but_not_billed → custody_account
		pr.stock_received_but_not_billed = custody_account

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

	# ── Stage 2b: Purchase Invoice ────────────────────────────────────────────
	@frappe.whitelist()
	def generate_purchase_invoice(self):
		"""
		Stage 2b — Create a Purchase Invoice.

		Single-Account GL Entry (via CustodyPurchaseInvoice override):
		  Debit:  Expense / Stock Account
		  Credit: custody_account (Receivable, party_type=Custodian)

		This credit self-settles the advance — no separate Settlement PE needed.
		"""
		settings = frappe.db.get_singles_dict("Treasury Settings")
		series = settings.get("pi_series") or "CST-PI-.YYYY.-.#####"
		mode = settings.get("accounting_mode") or CONSOLIDATED
		custody_account = self._get_custody_account()

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

		# Single-account: credit_to = custody_account (Receivable)
		pi_doc.credit_to = custody_account

		if mode == CONSOLIDATED:
			pi_doc.party_type = "Custodian"
			pi_doc.party = self.custodian
			pi_doc.party_account_currency = (
				frappe.db.get_value("Account", custody_account, "account_currency")
				or frappe.db.get_value("Company", self.company, "default_currency")
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

	# ── Quantity update helpers ───────────────────────────────────────────────
	def update_received_quantities(self):
		"""Recalculate total_accepted_amount and status after a PR event."""
		self._calculate_totals(persist=True)
		self.reload()
		self.recalculate_status()

	def update_billed_quantities(self, pi_name=None):
		"""Recalculate total_billed_amount and status after a PI event."""
		self._calculate_totals(persist=True)
		self.reload()
		self.recalculate_status()


# ── Module-level whitelisted queries ─────────────────────────────────────────

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_employees_with_custodian(doctype, txt, searchfield, start, page_len, filters):
	"""
	Server-side search query for the employee field in Accountant Custody.
	Returns only employees who have at least one submitted active Custodian record.
	"""
	employees_with_custodian = frappe.db.sql_list(
		"""
		SELECT DISTINCT employee
		FROM `tabCustodian`
		WHERE docstatus = 1
		  AND status = 'Active'
		  AND employee IS NOT NULL
		"""
	)

	if not employees_with_custodian:
		return []

	return frappe.db.sql(
		"""
		SELECT name, employee_name, department
		FROM `tabEmployee`
		WHERE status = 'Active'
		  AND name IN %(employees)s
		  AND (name LIKE %(txt)s OR employee_name LIKE %(txt)s)
		ORDER BY employee_name
		LIMIT %(start)s, %(page_len)s
		""",
		{
			"employees": employees_with_custodian,
			"txt": f"%{txt}%",
			"start": start,
			"page_len": page_len,
		},
	)


@frappe.whitelist()
def get_custodian_for_employee(employee):
	"""
	Return the name of the active submitted Custodian record for the given employee.
	Used by the Accountant Custody form to auto-fill the custodian field.
	"""
	if not employee:
		return None
	return frappe.db.get_value(
		"Custodian",
		{"employee": employee, "docstatus": 1, "status": "Active"},
		"name",
	)
