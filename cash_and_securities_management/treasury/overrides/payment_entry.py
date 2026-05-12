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
		
		return super().before_validate()

	def validate_party_type_account(self):
		"""
		Override ERPNext's party type validation to allow Custodian party
		on Payable accounts for custody settlement PEs.
		
		For custody-linked PEs, skip the supplier-only requirement.
		For regular PEs, call the parent validation.
		"""
		if self._is_custody_mode():
			# Custody PEs use Custodian party on Payable accounts
			# Skip ERPNext's supplier-only validation
			return

		# For non-custody PEs, run the standard validation
		super().validate_party_type_account()

	def validate(self):
		"""
		Override validate to skip party_type_account check for custody PEs.
		"""
		# For custody PEs, replace the party_type_account validation temporarily
		original_method = self.validate_party_type_account if hasattr(self, 'validate_party_type_account') else None
		
		if self._is_custody_mode():
			# Replace the method temporarily with a no-op
			self.validate_party_type_account = lambda: None
		
		try:
			super().validate()
		finally:
			# Restore original method if it existed
			if original_method:
				self.validate_party_type_account = original_method
