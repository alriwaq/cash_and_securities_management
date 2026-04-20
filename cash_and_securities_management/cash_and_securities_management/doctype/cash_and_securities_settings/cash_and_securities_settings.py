import frappe
from frappe import _
from frappe.model.document import Document


class CashAndSecuritiesSettings(Document):

	def validate(self):
		self.validate_accounts()

	def validate_accounts(self):
		"""Ensure the custody advance account is an asset-type account."""
		if self.custody_advance_account:
			account_type = frappe.db.get_value(
				"Account", self.custody_advance_account, "account_type"
			)
			if account_type not in ("Receivable", "Current Asset", None):
				frappe.msgprint(
					_(
						"Custody Advance Account should ideally be a Receivable or Current Asset account. "
						"Current type: {0}"
					).format(account_type),
					indicator="orange",
					alert=True,
				)
