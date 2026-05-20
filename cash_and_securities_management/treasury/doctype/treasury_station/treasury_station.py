import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime, today

try:
	from erpnext.accounts.utils import get_balance_on
except ImportError:
	def get_balance_on(account=None, date=None, **kwargs):
		return 0.0


class TreasuryStation(Document):
	"""
	Submittable document representing a physical cash vault/station.

	Lifecycle:
	  Draft  → configure vault account, assign responsible employee
	  Submit → locks vault_account and company; sets Cash MoP default account;
	           initialises responsibility log; sets opening_balance from GL
	  Transfer Responsibility → custom action to hand over vault to another employee
	"""

	# ─── Validate ────────────────────────────────────────────────────────────────

	def validate(self):
		self._auto_create_vault_account()
		self._validate_vault_account()
		self._populate_responsible_user()
		self._enforce_single_default()

	def _auto_create_vault_account(self):
		"""Create a dedicated Cash GL account for this vault if requested."""
		if not self.create_vault_account:
			return
		if self.vault_account:
			return  # Already created

		if not self.parent_account:
			frappe.throw(_("Please select a Parent Account to create the vault account under."))
		if not self.company:
			frappe.throw(_("Please select a Company before creating a new vault account."))

		company_abbr = frappe.db.get_value("Company", self.company, "abbr") or ""
		account_name = f"Vault - {self.station_name}"
		full_name = f"{account_name} - {company_abbr}" if company_abbr else account_name

		if frappe.db.exists("Account", full_name):
			self.vault_account = full_name
			return

		parent_type = frappe.db.get_value("Account", self.parent_account, "account_type")
		if parent_type not in ("Cash", "Bank"):
			frappe.throw(
				_("Parent Account must be of type 'Cash' or 'Bank'. '{0}' is of type '{1}'.").format(
					self.parent_account, parent_type or "Unknown"
				)
			)

		acc = frappe.new_doc("Account")
		acc.account_name = account_name
		acc.company = self.company
		acc.parent_account = self.parent_account
		acc.account_type = "Cash"
		acc.root_type = "Asset"
		acc.is_group = 0
		acc.flags.ignore_permissions = True
		acc.insert()

		self.vault_account = acc.name
		frappe.msgprint(
			_("Vault GL Account '{0}' created and linked to this station.").format(acc.name),
			indicator="green",
			alert=True,
		)

	def _validate_vault_account(self):
		if self.create_vault_account:
			return  # Will be created on save
		if not self.vault_account:
			frappe.throw(
				_("Vault Cash Account is required. Either select an existing account or check 'Create New Vault Account'.")
			)
		account_type = frappe.db.get_value("Account", self.vault_account, "account_type")
		if account_type not in ("Cash", "Bank"):
			frappe.throw(
				_("Vault Cash Account must be of type 'Cash' or 'Bank'. Selected account '{0}' is of type '{1}'.").format(
					self.vault_account, account_type
				)
			)

	def _populate_responsible_user(self):
		"""Auto-populate responsible_user from the employee's user_id."""
		if not self.responsible_employee:
			return
		user_id = frappe.db.get_value("Employee", self.responsible_employee, "user_id")
		if not user_id:
			frappe.throw(
				_("Employee {0} does not have a linked User. Please set the User ID on the Employee record first.").format(
					frappe.bold(self.responsible_employee)
				)
			)
		self.responsible_user = user_id

	def _enforce_single_default(self):
		"""Ensure only one station is marked as default per company."""
		if not self.is_default:
			return
		others = frappe.get_all(
			"Treasury Station",
			filters={
				"company": self.company,
				"is_default": 1,
				"name": ["!=", self.name or "__new__"],
			},
			pluck="name",
		)
		for other in others:
			frappe.db.set_value("Treasury Station", other, "is_default", 0)

	# ─── On Submit ───────────────────────────────────────────────────────────────

	def on_submit(self):
		"""
		On submit:
		1. Validate vault account is set
		2. Set Cash Mode of Payment default account for this company (if is_default)
		3. Initialise the responsibility log with the first entry
		4. Set opening_balance from GL
		"""
		if not self.vault_account:
			frappe.throw(_("Vault Cash Account is mandatory before submitting a Treasury Station."))

		if not self.responsible_employee:
			frappe.throw(_("Responsible Employee is mandatory before submitting a Treasury Station."))

		if self.is_default:
			self._set_cash_mop_account()

		# Initialise responsibility log if empty
		if not self.responsibility_log:
			self.append("responsibility_log", {
				"employee": self.responsible_employee,
				"user": self.responsible_user,
				"from_date": now_datetime(),
				"to_date": None,
				"transferred_by": frappe.session.user,
				"handover_notes": _("Initial assignment on station submission."),
			})
			frappe.db.set_value("Treasury Station", self.name, "handover_date", now_datetime())
			self.db_update()

		# Set opening balance from GL
		self._refresh_opening_balance()

	def _set_cash_mop_account(self):
		"""Update the Cash Mode of Payment to use this vault's account for the company."""
		mop_name = frappe.db.get_value("Mode of Payment", {"type": "Cash"}, "name")
		if not mop_name:
			frappe.msgprint(
				_("No 'Cash' Mode of Payment found. Please create one and set the default account manually."),
				indicator="orange",
			)
			return

		mop = frappe.get_doc("Mode of Payment", mop_name)
		updated = False
		for row in mop.accounts:
			if row.company == self.company:
				row.default_account = self.vault_account
				updated = True
				break

		if not updated:
			mop.append("accounts", {
				"company": self.company,
				"default_account": self.vault_account,
			})

		mop.flags.ignore_permissions = True
		mop.save()
		frappe.msgprint(
			_("Cash Mode of Payment default account set to '{0}' for {1}.").format(
				self.vault_account, self.company
			),
			indicator="green",
		)

	def _refresh_opening_balance(self):
		"""Fetch the current GL balance of the vault account and store as opening_balance."""
		if not self.vault_account:
			return
		try:
			balance = flt(get_balance_on(account=self.vault_account, date=today()))
			frappe.db.set_value("Treasury Station", self.name, {
				"opening_balance": balance,
				"current_balance": balance,
			})
		except Exception:
			pass  # Non-fatal

	# ─── Transfer Responsibility ──────────────────────────────────────────────────

	@frappe.whitelist()
	def transfer_responsibility(self, new_employee, handover_notes=""):
		"""
		Transfer vault responsibility to a new employee.
		Only Accounts Manager, System Manager, and Administrator can call this.
		"""
		_assert_manager_role()

		if not new_employee:
			frappe.throw(_("New Employee is required for responsibility transfer."))

		new_user = frappe.db.get_value("Employee", new_employee, "user_id")
		if not new_user:
			frappe.throw(
				_("Employee {0} does not have a linked User. Please set the User ID on the Employee record first.").format(
					frappe.bold(new_employee)
				)
			)

		if new_employee == self.responsible_employee:
			frappe.throw(_("The new employee is already responsible for this station."))

		now = now_datetime()

		# Close the current open log row
		for row in self.responsibility_log:
			if not row.to_date:
				frappe.db.set_value("Vault Responsibility Log", row.name, {"to_date": now})
				break

		# Append new log row (direct DB insert since doc is submitted)
		new_log = frappe.new_doc("Vault Responsibility Log")
		new_log.parent = self.name
		new_log.parenttype = "Treasury Station"
		new_log.parentfield = "responsibility_log"
		new_log.employee = new_employee
		new_log.user = new_user
		new_log.from_date = now
		new_log.to_date = None
		new_log.transferred_by = frappe.session.user
		new_log.handover_notes = handover_notes
		new_log.flags.ignore_permissions = True
		new_log.insert()

		# Update station fields (submitted doc — use db_set)
		frappe.db.set_value("Treasury Station", self.name, {
			"responsible_employee": new_employee,
			"responsible_user": new_user,
			"handover_date": now,
		})

		frappe.msgprint(
			_("Vault responsibility transferred to {0} successfully.").format(
				frappe.bold(new_employee)
			),
			indicator="green",
		)

	# ─── Validate GL Balance at Day Close ────────────────────────────────────────

	@frappe.whitelist()
	def validate_closing_balance(self, expected_balance):
		"""
		Called by TCJ on_submit before closing the day.
		Compares expected_balance (from TCJ) against the live GL balance.
		Raises an error if they do not match (within 0.01 tolerance).
		"""
		if not self.vault_account:
			return
		try:
			gl_balance = flt(get_balance_on(account=self.vault_account, date=today()))
		except Exception:
			return  # Non-fatal if GL balance unavailable

		expected = flt(expected_balance)
		if abs(gl_balance - expected) > 0.01:
			frappe.throw(
				_(
					"Day-close validation failed for station {0}.\n"
					"Expected balance (from journal): {1}\n"
					"Actual GL balance of {2}: {3}\n\n"
					"Please post a variance entry or correct the journal lines before closing."
				).format(
					self.name,
					frappe.format_value(expected, {"fieldtype": "Currency"}),
					self.vault_account,
					frappe.format_value(gl_balance, {"fieldtype": "Currency"}),
				)
			)


# ─── Helper ──────────────────────────────────────────────────────────────────

def _assert_manager_role():
	"""Raise PermissionError if the current user is not a manager or admin."""
	user = frappe.session.user
	if user == "Administrator":
		return
	roles = frappe.get_roles(user)
	allowed = {"System Manager", "Accounts Manager"}
	if not allowed.intersection(roles):
		frappe.throw(
			_("Only Accounts Manager or System Manager can perform this action."),
			frappe.PermissionError,
		)
