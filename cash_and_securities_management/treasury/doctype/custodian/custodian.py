"""
Custodian DocType controller — v3.0  (Single Self-Settling Account Model)
Manages the lifecycle of an employee custodian:
  Draft → Active → Suspended → Closed

On submit: auto-creates ONE sub-ledger account per custodian based on
accounting_mode in Treasury Settings.

  Consolidated (Party-Based):
    - custody_account ← custody_advance_group (shared group account).
    - No individual leaf accounts are created.
    - All GL entries use the group account + party_type=Custodian + party=self.name.

  Individual (Account-Based):
    - Creates ONE dedicated leaf account per custodian:
        "{self.name} - Custody"  (Receivable, under custody_advance_group)
    - custody_account ← the newly created leaf account.

Single-Account Model:
  Both advances (Custody Request PE) and expenses (Purchase Invoice) post
  to the SAME custody_account with party_type=Custodian.
    • Advance paid out  → Debit  custody_account  (positive balance = employee owes)
    • Invoice submitted → Credit custody_account  (balance reduces automatically)
    • Zero balance      → fully settled — no manual Settlement Entry needed.

Naming: E-{attendance_device_id}-{employee_name} via autoname() method.
"""
import re
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

CONSOLIDATED = "Consolidated (Party-Based)"
INDIVIDUAL   = "Individual (Account-Based)"


class Custodian(Document):
	# ── Naming ────────────────────────────────────────────────────────────────
	def autoname(self):
		"""
		Generate the document name as: E-{attendance_device_id}-{employee_name}
		Fallback: E-{employee_id} if attendance_device_id is not set.
		The name is slugified (spaces → hyphens, special chars stripped) to keep
		it URL-safe and consistent with Frappe naming conventions.
		"""
		employee      = self.employee or ""
		employee_name = self.employee_name or ""

		attendance_device_id = None
		if employee:
			attendance_device_id = frappe.db.get_value(
				"Employee", employee, "attendance_device_id"
			)

		if attendance_device_id:
			raw = f"E-{attendance_device_id}-{employee_name}"
		else:
			raw = f"E-{employee}-{employee_name}" if employee_name else f"E-{employee}"

		slug = re.sub(r"[\s_]+", "-", raw)
		slug = re.sub(r"[^A-Za-z0-9\-]", "", slug)
		slug = re.sub(r"-{2,}", "-", slug).strip("-")
		self.name = slug

	# ── Lifecycle ─────────────────────────────────────────────────────────────
	def before_submit(self):
		self._validate_employee()

	def on_submit(self):
		self._create_custody_account()
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

	def _create_custody_account(self):
		"""
		Create or assign the single self-settling custody sub-ledger account.

		Consolidated (Party-Based):
		  custody_account ← custody_advance_group (shared group account).
		  No leaf account is created; the Party field isolates transactions.

		Individual (Account-Based):
		  Creates ONE leaf account named "{self.name} - Custody"
		  under custody_advance_group with account_type = Receivable.
		  This allows party_type = Custodian on all GL entries.

		Both advances (PE) and invoices (PI) post to this single account:
		  • Advance  → Debit  custody_account  (employee owes company)
		  • Invoice  → Credit custody_account  (balance self-settles)
		"""
		settings     = frappe.db.get_singles_dict("Treasury Settings")
		mode         = settings.get("accounting_mode") or CONSOLIDATED
		advance_group = settings.get("custody_advance_group")

		# Determine company
		company = self.company
		if not company and advance_group:
			company = frappe.db.get_value("Account", advance_group, "company")
		if not company:
			frappe.throw(
				_("Company is required on the Custodian record to create sub-ledger accounts."),
				title=_("Missing Company"),
			)

		if not advance_group:
			frappe.throw(
				_("Please configure 'Custody Advance Account Group' "
				  "in Treasury Settings before submitting a Custodian."),
				title=_("Configuration Missing"),
			)

		if mode == CONSOLIDATED:
			# ── Consolidated: assign shared group account directly ────────
			self.custody_account = advance_group
			self.db_set("custody_account", advance_group, notify=True)
			frappe.logger().info(
				f"Custodian {self.name} [Consolidated]: custody_account={advance_group}"
			)

		else:
			# ── Individual: create ONE dedicated Custody leaf account ──
			# account_type = "Custody" is a dedicated type that:
			#   • Is naturally excluded from standard AP/AR reports
			#     (those filter on Payable/Receivable only)
			#   • Is accepted by our PI override (validate_credit_to_acc)
			#   • Requires no custom checkbox flag on the Account doctype
			custody_account = self._get_or_create_leaf_account(
				account_name=f"{self.name} - Custody",
				parent_account=advance_group,
				company=company,
				account_type="Custody",   # Dedicated type — excluded from AP/AR reports
				root_type="Asset",        # Placed under Assets (advance = asset)
			)
			self.custody_account = custody_account
			self.db_set("custody_account", custody_account, notify=True)
			frappe.logger().info(
				f"Custodian {self.name} [Individual]: custody_account={custody_account}"
			)

	def _get_or_create_leaf_account(
		self, account_name, parent_account, company, account_type, root_type
	):
		"""
		Return the full account name of an existing leaf account,
		or create it if it does not exist.
		"""
		existing = frappe.db.get_value(
			"Account",
			{
				"account_name": account_name,
				"company":      company,
				"parent_account": parent_account,
			},
			"name",
		)
		if existing:
			return existing

		account = frappe.new_doc("Account")
		account.account_name   = account_name
		account.parent_account = parent_account
		account.company        = company
		account.account_type   = account_type
		account.root_type      = root_type
		account.report_type    = "Balance Sheet"
		account.is_group       = 0
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
			update_custodian_dashboard,
		)
		update_custodian_dashboard(self.name)
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
		Manually trigger sub-ledger account creation/assignment.
		Useful if Treasury Settings were configured after the Custodian was submitted,
		or if the accounting_mode was changed.
		"""
		self._create_custody_account()
		frappe.msgprint(
			_("Sub-ledger account has been created/verified for Custodian {0}.").format(
				self.name
			),
			indicator="green",
		)
