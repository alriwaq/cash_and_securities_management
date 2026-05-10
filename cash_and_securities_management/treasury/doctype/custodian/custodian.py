"""
Custodian DocType controller — v2
Manages the lifecycle of an employee custodian:
  Draft → Active → Suspended → Closed
On submit: auto-creates TWO sub-ledger accounts (Asset advance + Liability payable).
Naming: E-{attendance_device_id}-{employee_name} via autoname() method.
"""
import re
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class Custodian(Document):
	# ── Naming ────────────────────────────────────────────────────────────────
	def autoname(self):
		"""
		Generate the document name as: E-{attendance_device_id}-{employee_name}
		Fallback: E-{employee_id} if attendance_device_id is not set.
		The name is slugified (spaces → hyphens, special chars stripped) to keep
		it URL-safe and consistent with Frappe naming conventions.
		"""
		employee = self.employee or ""
		employee_name = self.employee_name or ""

		# Try to get attendance_device_id from the linked Employee record
		attendance_device_id = None
		if employee:
			attendance_device_id = frappe.db.get_value(
				"Employee", employee, "attendance_device_id"
			)

		if attendance_device_id:
			raw = f"E-{attendance_device_id}-{employee_name}"
		else:
			raw = f"E-{employee}-{employee_name}" if employee_name else f"E-{employee}"

		# Slugify: replace spaces/underscores with hyphens, strip special chars
		slug = re.sub(r"[\s_]+", "-", raw)
		slug = re.sub(r"[^A-Za-z0-9\-]", "", slug)
		slug = re.sub(r"-{2,}", "-", slug).strip("-")

		self.name = slug

	# ── Lifecycle ─────────────────────────────────────────────────────────────
	def before_submit(self):
		self._validate_employee()
		self._validate_supplier_if_required()

	def on_submit(self):
		self._create_custody_accounts()
		self._set_status("Active")

	def on_cancel(self):
		self._validate_no_open_transactions()
		self._set_status("Closed")

	def validate(self):
		if self.employee:
			self._sync_employee_fields()

	# ── Private helpers ───────────────────────────────────────────────────────
	def _sync_employee_fields(self):
		"""Pull employee_name, department, company from the linked Employee."""
		emp = frappe.db.get_value(
			"Employee",
			self.employee,
			["employee_name", "department", "company"],
			as_dict=True,
		)
		if emp:
			self.employee_name = emp.employee_name
			if not self.department:
				self.department = emp.department
			if not self.company:
				self.company = emp.company

	def _validate_employee(self):
		"""Employee must be set before submitting."""
		if not self.employee:
			frappe.throw(
				_("Employee is required before submitting a Custodian record."),
				title=_("Missing Employee"),
			)

	def _validate_supplier_if_required(self):
		"""Validate dedicated supplier if single-dummy-supplier mode is off."""
		settings = frappe.db.get_singles_dict("Treasury Settings")
		use_single = int(settings.get("use_single_dummy_supplier") or 0)
		if not use_single and not self.dedicated_supplier:
			frappe.throw(
				_("Dedicated Supplier is required for this custodian because "
				  "'Use Single Dummy Supplier' is disabled in Treasury Settings."),
				title=_("Missing Supplier"),
			)

	def _validate_no_open_transactions(self):
		"""Prevent cancellation if there are linked submitted documents."""
		open_requests = frappe.db.count(
			"Custody Request",
			{"custodian": self.name, "docstatus": 1},
		)
		if open_requests:
			frappe.throw(
				_("Cannot cancel this Custodian because there are {0} submitted "
				  "Custody Request(s) linked to it. Please cancel those first.").format(
					open_requests
				),
				title=_("Linked Transactions Exist"),
			)

	def _create_custody_accounts(self):
		"""
		Auto-create TWO sub-ledger accounts on first submit:
		  1. Asset advance account  — under default_advance_group
		  2. Liability payable account — under default_payable_group
		Both accounts are named after the Custodian ID for easy identification.
		"""
		settings = frappe.db.get_singles_dict("Treasury Settings")

		advance_group = settings.get("default_advance_group")
		payable_group = settings.get("default_payable_group")

		# Determine company
		company = self.company
		if not company and advance_group:
			company = frappe.db.get_value("Account", advance_group, "company")
		if not company:
			frappe.throw(
				_("Company is required on the Custodian record to create sub-ledger accounts."),
				title=_("Missing Company"),
			)

		# ── Asset advance account ─────────────────────────────────────────
		if not advance_group:
			frappe.throw(
				_("Please configure 'Default Advance Account Group' "
				  "in Treasury Settings before submitting a Custodian."),
				title=_("Configuration Missing"),
			)

		advance_account = self._get_or_create_leaf_account(
			account_name=f"{self.name} - Advance",
			parent_account=advance_group,
			company=company,
			account_type="",  # Plain current asset — NOT Receivable
			root_type="Asset",
		)
		self.custody_account = advance_account
		self.db_set("custody_account", advance_account, notify=True)

		# ── Liability payable account ─────────────────────────────────────
		if payable_group:
			payable_account = self._get_or_create_leaf_account(
				account_name=f"{self.name} - Payable",
				parent_account=payable_group,
				company=company,
				account_type="Payable",
				root_type="Liability",
			)
			self.liability_account = payable_account
			self.db_set("liability_account", payable_account, notify=True)
		else:
			# Payable group not configured — log a warning but do not block
			frappe.msgprint(
				_("Default Payable Account Group is not configured in Treasury Settings. "
				  "The liability sub-ledger account was not created. "
				  "You can configure it and re-run account creation from the Custodian record."),
				indicator="orange",
				alert=True,
			)

		frappe.logger().info(
			f"Custodian {self.name}: advance_account={self.custody_account}, "
			f"liability_account={self.liability_account}"
		)

	def _get_or_create_leaf_account(
		self, account_name, parent_account, company, account_type, root_type
	):
		"""
		Return the full account name (e.g., 'E-1234-John - Advance - Company') of
		an existing leaf account, or create it if it does not exist.
		"""
		existing = frappe.db.get_value(
			"Account",
			{
				"account_name": account_name,
				"company": company,
				"parent_account": parent_account,
			},
			"name",
		)
		if existing:
			return existing

		account = frappe.new_doc("Account")
		account.account_name = account_name
		account.parent_account = parent_account
		account.company = company
		account.account_type = account_type
		account.root_type = root_type
		account.report_type = "Balance Sheet"
		account.is_group = 0
		account.flags.ignore_permissions = True
		account.insert()
		return account.name

	def _set_status(self, new_status):
		"""Update status field directly in the database."""
		self.status = new_status
		self.db_set("status", new_status, notify=True)

	# ── Public API ────────────────────────────────────────────────────────────
	@frappe.whitelist()
	def refresh_outstanding(self):
		"""
		Recalculate and persist all financial summary fields on this Custodian.
		All figures are derived exclusively from submitted (docstatus=1) documents.
		"""
		from cash_and_securities_management.treasury.balances import (
			recalculate_custodian_balances,
		)
		recalculate_custodian_balances(self.name)
		self.reload()

	@frappe.whitelist()
	def change_limit(self, new_limit):
		"""Update the custody limit."""
		self.custody_limit = flt(new_limit)
		self.db_set("custody_limit", flt(new_limit), notify=True)
		frappe.msgprint(
			_("Custody limit updated to {0}.").format(
				frappe.utils.fmt_money(flt(new_limit))
			),
			indicator="green",
			alert=True,
		)

	@frappe.whitelist()
	def suspend(self):
		"""Suspend this custodian (prevents new Custody Requests)."""
		if self.status != "Active":
			frappe.throw(_("Only Active custodians can be suspended."))
		self._set_status("Suspended")
		frappe.msgprint(_("Custodian {0} has been suspended.").format(self.name), alert=True)

	@frappe.whitelist()
	def reactivate(self):
		"""Reactivate a suspended custodian."""
		if self.status != "Suspended":
			frappe.throw(_("Only Suspended custodians can be reactivated."))
		self._set_status("Active")
		frappe.msgprint(_("Custodian {0} has been reactivated.").format(self.name), alert=True)

	@frappe.whitelist()
	def close(self):
		"""Close this custodian permanently."""
		if self.status == "Closed":
			frappe.throw(_("Custodian is already Closed."))
		self._validate_no_open_transactions()
		self._set_status("Closed")
		frappe.msgprint(_("Custodian {0} has been closed.").format(self.name), alert=True)

	@frappe.whitelist()
	def recreate_accounts(self):
		"""
		Manually trigger sub-ledger account creation.
		Useful if Treasury Settings were configured after the Custodian was submitted.
		"""
		self._create_custody_accounts()
		frappe.msgprint(
			_("Sub-ledger accounts have been created/verified for Custodian {0}.").format(
				self.name
			),
			indicator="green",
		)
