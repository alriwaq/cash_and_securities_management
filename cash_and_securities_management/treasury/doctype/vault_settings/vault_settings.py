import frappe
from frappe.model.document import Document


class VaultSettings(Document):
	"""
	Single DocType holding global configuration for the Treasury Cash Journal
	(FBCJ) vault operations.
	"""

	def validate(self):
		self._validate_accounts()

	def _validate_accounts(self):
		"""Ensure the selected accounts belong to the correct root types."""
		if self.default_vault_account:
			root_type = frappe.db.get_value("Account", self.default_vault_account, "root_type")
			if root_type != "Asset":
				frappe.throw(
					frappe._("Default Vault Cash Account must be an Asset account. "
					         "'{0}' has root type '{1}'.").format(self.default_vault_account, root_type)
				)

		if self.default_shortage_account:
			root_type = frappe.db.get_value("Account", self.default_shortage_account, "root_type")
			if root_type not in ("Asset", "Expense", "Liability"):
				frappe.throw(
					frappe._("Default Shortage / Overage Account must be an Asset, Expense, or "
					         "Liability account. '{0}' has root type '{1}'.").format(
					             self.default_shortage_account, root_type)
				)
