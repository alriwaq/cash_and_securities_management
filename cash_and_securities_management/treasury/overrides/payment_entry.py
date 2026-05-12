import frappe
from frappe import _

from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry


class CustodyPaymentEntry(PaymentEntry):
	"""
	Override Payment Entry to accept Custodian party on Payable accounts
	for custody settlement transactions.
	"""

	def _is_custody_mode(self):
		"""Check if this PE is linked to a Custody context."""
		return (
			self.get("custom_source_document_type") == "Custody"
			or bool(self.get("custom_accountant_custody"))
		)

	def before_validate(self):
		"""
		Pre-validate setup for custody PEs.
		Set flags to bypass mandatory checks for custody-linked PEs.
		"""
		if self._is_custody_mode():
			self.flags.ignore_mandatory = True

	def validate(self):
		"""
		Override validate to suppress party-type-account validation for custody PEs.
		ERPNext validates that Payable accounts must have Supplier party,
		but custody PEs use Custodian party instead.
		"""
		if self._is_custody_mode():
			# For custody PEs, skip party-type-account validation
			# by temporarily disabling the validate_party_type_account method
			self.validate_party_type_account = lambda: None
		
		try:
			super().validate()
		finally:
			# Restore the method for non-custody operations
			if self._is_custody_mode():
				# Restore to the parent class method
				self.validate_party_type_account = PaymentEntry.validate_party_type_account.__get__(self, type(self))

	def validate_party_type_account(self):
		"""
		Override ERPNext's party type validation to allow Custodian party
		on Payable accounts for custody settlement PEs.
		"""
		if self._is_custody_mode():
			# Custody PEs use Custodian party on Payable accounts
			# Skip ERPNext's supplier-only validation
			return

		# For non-custody PEs, run the standard validation
		super().validate_party_type_account()
