import frappe
from frappe.model.document import Document


class TreasuryStation(Document):
	"""
	Represents a physical cash vault / cashier station.
	Holds the vault GL account and carries the running balance
	updated each time a Treasury Cash Journal is posted.
	"""

	def validate(self):
		self._validate_vault_account()

	def _validate_vault_account(self):
		if not self.vault_account:
			return
		account_type = frappe.db.get_value("Account", self.vault_account, "account_type")
		if account_type not in ("Cash", "Bank"):
			frappe.throw(
				frappe._("Vault Cash Account must be of type 'Cash' or 'Bank'. "
				         "Selected account '{0}' is of type '{1}'.").format(
					self.vault_account, account_type
				)
			)
