"""
Custody Request DocType controller — v2.1
Tracks the advance lifecycle for a custodian:
  Draft → Approved → Partly Paid → Paid → Partly Claimed → Claimed → Cancelled

Stage 1 of the three-step flow:
  Custody Request → Payment Entry (Advance disbursement)

GL entry produced by the Payment Entry:
  Debit:  Custodian Advance Account (Asset)   ← custody_account on Custodian
  Credit: Bank/Cash Account

In Consolidated mode the advance account is the shared group account and the
Custodian is set as the Party (Party Type = Custodian) on the Payment Entry to
isolate individual balances within the shared account.

paid_amount is strictly read-only, computed from submitted Payment Entries.
remaining_to_pay = advance_amount - paid_amount.
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

CONSOLIDATED = "Consolidated (Party-Based)"


class CustodyRequest(Document):
	# ── Lifecycle ─────────────────────────────────────────────────────────────
	def validate(self):
		self._sync_employee_from_custodian()
		self._lock_advance_account()
		self._calculate_remaining()

	def on_submit(self):
		self._validate_custodian_status()
		self._validate_custody_limit()
		self.db_set("status", "Approved")

	def on_cancel(self):
		self._validate_no_linked_documents()
		self.db_set("status", "Cancelled")
		self._refresh_custodian_balance()

	# ── Private helpers ───────────────────────────────────────────────────────
	def _sync_employee_from_custodian(self):
		"""Pull employee, employee_name, department, company from the linked Custodian."""
		if not self.custodian:
			return
		cust = frappe.db.get_value(
			"Custodian",
			self.custodian,
			["employee", "employee_name", "department", "company"],
			as_dict=True,
		)
		if cust:
			self.employee = cust.employee
			self.employee_name = cust.employee_name
			if not self.department:
				self.department = cust.department
			if not self.company:
				self.company = cust.company
			# Mirror custodian status for display
			self.custodian_status = frappe.db.get_value("Custodian", self.custodian, "status")

	def _lock_advance_account(self):
		"""Lock the advance account to the custodian's asset sub-ledger account."""
		if self.custodian:
			custody_account = frappe.db.get_value(
				"Custodian", self.custodian, "custody_account"
			)
			if custody_account:
				self.advance_account = custody_account

	def _calculate_remaining(self):
		"""remaining_to_pay = advance_amount - paid_amount."""
		self.remaining_to_pay = flt(self.advance_amount) - flt(self.paid_amount)

	def _validate_custodian_status(self):
		"""Custodian must exist and be Active."""
		if not self.custodian:
			# Try to find custodian for this employee
			custodian_name = frappe.db.get_value(
				"Custodian",
				{"employee": self.employee, "docstatus": 1},
				"name",
			)
			if not custodian_name:
				frappe.throw(
					_("A Custodian record is required. Please create an active Custodian "
					  "for employee {0} before raising a Custody Request.").format(
						self.employee_name or self.employee
					),
					title=_("No Custodian Found"),
				)
			self.custodian = custodian_name

		status = frappe.db.get_value("Custodian", self.custodian, "status")
		if status == "Suspended":
			frappe.throw(
				_("Custodian {0} is currently Suspended. New Custody Requests cannot "
				  "be created until the custodian is reactivated.").format(self.custodian),
				title=_("Custodian Suspended"),
			)
		if status == "Closed":
			frappe.throw(
				_("Custodian {0} is Closed. No further Custody Requests are allowed.").format(
					self.custodian
				),
				title=_("Custodian Closed"),
			)

	def _validate_custody_limit(self):
		"""Ensure the new request does not exceed the custodian's limit."""
		if not self.custodian or not self.advance_amount:
			return
		limit_val, outstanding = frappe.db.get_value(
			"Custodian",
			self.custodian,
			["custody_limit", "total_outstanding"],
		) or (0, 0)
		limit_val = flt(limit_val)
		outstanding = flt(outstanding)
		if limit_val > 0:
			projected = outstanding + flt(self.advance_amount)
			if projected > limit_val:
				frappe.throw(
					_("This request of {0} would push the custodian's outstanding balance "
					  "to {1}, exceeding the custody limit of {2}. "
					  "Please reduce the amount or increase the limit.").format(
						frappe.utils.fmt_money(self.advance_amount),
						frappe.utils.fmt_money(projected),
						frappe.utils.fmt_money(limit_val),
					),
					title=_("Custody Limit Exceeded"),
				)

	def _validate_no_linked_documents(self):
		"""Prevent cancellation if there are linked Accountant Custody records."""
		linked_custodies = frappe.get_all(
			"Accountant Custody",
			filters={"custody_request": self.name, "docstatus": ["!=", 2]},
			fields=["name"],
		)
		if linked_custodies:
			frappe.throw(
				_("Cannot cancel Custody Request {0} as it has linked Accountant "
				  "Custody records: {1}").format(
					self.name,
					", ".join([d.name for d in linked_custodies]),
				)
			)

	def _refresh_custodian_balance(self):
		"""Trigger a balance refresh on the linked Custodian."""
		if self.custodian:
			try:
				from cash_and_securities_management.treasury.balances import (
					update_custodian_dashboard,
				)
				update_custodian_dashboard(self.custodian)
			except Exception:
				pass  # Non-critical; balance can be refreshed manually

	# ── Public API ────────────────────────────────────────────────────────────
	def update_paid_amount(self):
		"""
		Recalculate paid_amount from all submitted Payment Entries linked to this
		Custody Request. Called from the centralized balance engine (balances.py).
		"""
		total_paid = frappe.db.sql(
			"""SELECT COALESCE(SUM(paid_amount), 0)
			   FROM `tabPayment Entry`
			   WHERE custom_custody_request = %s AND docstatus = 1""",
			(self.name,),
		)[0][0] or 0
		total_paid = flt(total_paid)

		self.db_set("paid_amount", total_paid)
		self.db_set("remaining_to_pay", flt(self.advance_amount) - total_paid)

		# Update status based on payment progress
		if total_paid <= 0:
			new_status = "Approved"
		elif total_paid < flt(self.advance_amount):
			new_status = "Partly Paid"
		else:
			new_status = "Paid"
		self.db_set("status", new_status)

		self._refresh_custodian_balance()

	def update_claimed_amount(self):
		"""
		Called when an Accountant Custody is settled against this request.
		Recalculates claimed_amount from submitted AC settlement entries.
		"""
		total_claimed = frappe.db.sql(
			"""
			SELECT COALESCE(SUM(cse.claimed_amount), 0)
			FROM `tabCustody Settlement Entry` cse
			JOIN `tabAccountant Custody` ac ON ac.name = cse.parent
			WHERE cse.custody_request = %s
			  AND ac.docstatus = 1
			""",
			self.name,
		)[0][0] or 0
		total_claimed = flt(total_claimed)

		self.db_set("claimed_amount", total_claimed)
		unallocated = flt(self.paid_amount) - total_claimed
		self.db_set("unallocated_amount", unallocated)

		# Update status based on claim progress
		if total_claimed >= flt(self.paid_amount) and flt(self.paid_amount) > 0:
			self.db_set("status", "Claimed")
		elif total_claimed > 0:
			self.db_set("status", "Partly Claimed")

		self._refresh_custodian_balance()

	@frappe.whitelist()
	def create_payment_entry(self):
		"""
		Stage 1 — Funding: Create a DRAFT Payment Entry to disburse the advance.

		GL Entry:
		  Debit:  Custodian Advance Account (Asset)   ← custody_account on Custodian
		  Credit: Bank/Cash Account

		Mode handling:
		  Consolidated — payment_type = "Internal Transfer"
		                 paid_to = shared advance group account
		                 party_type = "Custodian", party = self.custodian
		                 (Party field isolates the balance within the shared account)

		  Individual   — payment_type = "Internal Transfer"
		                 paid_to = custodian's dedicated leaf advance account
		                 No party needed — the account itself is the isolator.

		Returns the name of the created Payment Entry.
		"""
		if not self.advance_account:
			frappe.throw(
				_("Advance Account is not set. Please ensure the Custodian has a "
				  "valid sub-ledger account configured."),
				title=_("Missing Account"),
			)

		settings = frappe.db.get_singles_dict("Treasury Settings")
		series = settings.get("pe_series") or "AC-PAY-.YYYY.-.#####"
		mode = settings.get("accounting_mode") or CONSOLIDATED

		# Determine the bank/cash account to pay from
		pay_from_account = (
			frappe.db.get_value("Company", self.company, "default_bank_account")
			or frappe.db.get_value("Company", self.company, "default_cash_account")
		)

		if not pay_from_account:
			frappe.throw(
				_("Please set a Default Bank Account or Default Cash Account for company {0}.").format(
					self.company
				),
				title=_("Missing Bank Account"),
			)

		pe = frappe.new_doc("Payment Entry")
		pe.naming_series = series
		pe.payment_type = "Internal Transfer"
		pe.posting_date = nowdate()
		pe.company = self.company
		pe.paid_amount = flt(self.advance_amount)
		pe.received_amount = flt(self.advance_amount)
		pe.paid_from = pay_from_account
		pe.paid_to = self.advance_account
		pe.custom_custody_request = self.name
		pe.custom_custodian = self.custodian
		pe.remarks = f"Advance disbursement for Custody Request {self.name}"

		# In Consolidated mode, set the Custodian as the Party so that the shared
		# group account can carry individual balances per custodian.
		if mode == CONSOLIDATED:
			pe.party_type = "Custodian"
			pe.party = self.custodian

		pe.flags.ignore_permissions = True
		pe.insert()
		# Intentionally left as DRAFT — user must review and submit manually
		frappe.msgprint(
			_("Payment Entry {0} created as Draft. Please review and submit it.").format(
				frappe.bold(pe.name)
			),
			indicator="blue",
		)
		return pe.name
