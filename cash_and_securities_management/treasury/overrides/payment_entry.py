import frappe
from frappe import _

from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry


class CustodyPaymentEntry(PaymentEntry):
	"""
	Override Payment Entry for custody settlement transactions.

	Root cause of "Supplier is required against Payable account":
	  ERPNext's make_gl_entries() for payment_type="Internal Transfer" creates
	  GL entries WITHOUT party_type/party. The Payable account GL entry then has
	  no party, and frappe's GL-level validation fires the error.

	Fix: override get_gl_dict() to inject party_type="Custodian" + party into
	any Payable/Receivable account GL entry created for a custody PE.
	"""

	def _is_custody_mode(self):
		return (
			self.get("custom_source_document_type") == "Custody"
			or bool(self.get("custom_accountant_custody"))
		)

	def before_validate(self):
		if self._is_custody_mode():
			self.flags.ignore_mandatory = True

	def validate_party_accounts(self):
		"""Skip party-type/account-type matching check for custody PEs."""
		if self._is_custody_mode():
			return
		super().validate_party_accounts()

	def get_gl_dict(self, args, account_currency=None, item=None):
		"""
		Inject Custodian party into GL entries for Payable/Receivable accounts.

		For Internal Transfer PEs, ERPNext does not populate party_type/party on
		the individual GL dicts, causing GL-level validation to raise
		"Supplier is required against Payable account".  We intercept every GL
		dict and add the Custodian party when the account is Payable/Receivable.
		"""
		gl_dict = super().get_gl_dict(args, account_currency=account_currency, item=item)

		if self._is_custody_mode() and gl_dict:
			account = gl_dict.get("account")
			if account and not gl_dict.get("party_type"):
				account_type = frappe.get_cached_value("Account", account, "account_type")
				if account_type in ("Payable", "Receivable"):
					gl_dict["party_type"] = "Custodian"
					gl_dict["party"] = self.get("custom_custodian") or self.party

		return gl_dict


