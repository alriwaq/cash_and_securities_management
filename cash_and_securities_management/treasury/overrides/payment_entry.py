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
			# Mark as custody for validation purposes
			self._custody_skip_party_validation = True

	def validate(self):
		"""
		Override validate to suppress party account validation for custody PEs.
		ERPNext validates that Payable accounts must have Supplier party,
		but custody PEs use Custodian party instead.
		"""
		if self._is_custody_mode():
			# Suppress party validation for custody PEs by disabling the method
			original_validate_party = self.validate_party_accounts
			self.validate_party_accounts = lambda: None
			
			try:
				super().validate()
			except frappe.ValidationError as e:
				error_msg = str(e)
				# Log the error but don't raise for party/account type mismatches
				if any(phrase in error_msg for phrase in 
					   ["Supplier is required", "party", "Party", "account type", "account_type"]):
					frappe.logger().warning(f"[Custody PE] Suppressed validation error: {error_msg}")
				else:
					# Re-raise other validation errors
					raise
			finally:
				# Restore the original method
				self.validate_party_accounts = original_validate_party
		else:
			# For non-custody PEs, run normal validation
			super().validate()

	def validate_party_accounts(self):
		"""
		Override ERPNext's party account validation to allow Custodian party
		on Payable accounts for custody settlement PEs.
		"""
		if self._is_custody_mode():
			# Custody PEs use Custodian party on Payable accounts
			# Skip ERPNext's supplier-only validation
			frappe.logger().debug(f"[Custody PE] Skipped validate_party_accounts for {self.name}")
			return

		# For non-custody PEs, run the standard validation
		super().validate_party_accounts()

	def before_submit(self):
		"""
		Ensure custody PE fields are set correctly before submit.
		"""
		if self._is_custody_mode():
			# Ensure party is set for GL posting
			if self.get("custom_custodian"):
				self.party = self.get("custom_custodian")
			if self.get("custom_source_document_type"):
				self.party_type = "Custodian"
			frappe.logger().debug(f"[Custody PE] Before submit: party={self.party}, party_type={self.party_type}")


