import frappe
from frappe import _
from frappe.model.document import Document


class TreasuryStation(Document):
	"""
	Represents a physical cash vault / cashier station.
	Holds the vault GL account and carries the running balance
	updated each time a Treasury Cash Journal is posted.

	V4 Enhancement:
	  - If `create_vault_account` is checked on first save, a dedicated
	    Cash GL account is auto-created under `parent_account` and stored
	    in `vault_account`.
	  - `is_default` marks this station as the default for its company,
	    used by the Payment Entry hook to route pending items correctly.
	"""

	def before_insert(self):
		if self.create_vault_account:
			self._auto_create_vault_account()

	def validate(self):
		# After auto-creation, vault_account will be set; validate it
		if not self.create_vault_account:
			self._validate_vault_account()
		# Ensure only one default station per company
		if self.is_default:
			self._enforce_single_default()

	def _auto_create_vault_account(self):
		"""
		Create a new Cash GL account for this vault under `parent_account`
		and store the result in `vault_account`.
		"""
		if not self.parent_account:
			frappe.throw(_("Please select a Parent Account before creating a new vault account."))
		if not self.company:
			frappe.throw(_("Please select a Company before creating a new vault account."))

		# Derive account name from station name
		account_name = f"Vault - {self.station_name}"

		# Check if it already exists (idempotent)
		existing = frappe.db.get_value(
			"Account",
			{"account_name": account_name, "company": self.company},
			"name",
		)
		if existing:
			self.vault_account = existing
			return

		# Validate parent is a Cash group account
		parent_type = frappe.db.get_value("Account", self.parent_account, "account_type")
		if parent_type not in ("Cash", "Bank"):
			frappe.throw(
				_("Parent Account must be of type 'Cash' or 'Bank'. "
				  "'{0}' is of type '{1}'.").format(self.parent_account, parent_type or "Unknown")
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
		if not self.vault_account:
			frappe.throw(_("Vault Cash Account is required. Either select an existing account or check 'Create New Vault Account'."))
		account_type = frappe.db.get_value("Account", self.vault_account, "account_type")
		if account_type not in ("Cash", "Bank"):
			frappe.throw(
				_("Vault Cash Account must be of type 'Cash' or 'Bank'. "
				  "Selected account '{0}' is of type '{1}'.").format(
					self.vault_account, account_type
				)
			)

	def _enforce_single_default(self):
		"""Unset is_default on all other stations for the same company."""
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
