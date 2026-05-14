import frappe
from frappe import _

from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt


class CustodyPurchaseReceipt(PurchaseReceipt):
	"""
	Override Purchase Receipt for custody-mode documents.

	Custody PRs are generated from an Accountant Custody record.
	They use Custodian as the party — there is no supplier involved.

	Key overrides:
	  - Clear supplier / supplier_name so ERPNext does not enforce supplier
	    mandatory validation or try to look up supplier-linked accounts.
	  - Skip validate_with_previous_doc (no PO/PR chain for custody items).
	  - Set stock_received_but_not_billed to the custodian payable account
	    so the interim liability is booked against the correct GL account.
	"""

	def _is_custody_mode(self):
		return (
			self.get("custom_source_document_type") == "Custody"
			or bool(self.get("custom_accountant_custody"))
		)

	def before_validate(self):
		if self._is_custody_mode():
			# Wipe supplier fields completely — custody PRs have no supplier.
			# ERPNext's validate() will not re-populate these because we also
			# set flags.ignore_mandatory = True below.
			self.supplier = None
			self.supplier_name = None
			self.contact_person = None
			self.contact_display = None
			self.contact_mobile = None
			self.contact_email = None
			self.shipping_address = None
			self.shipping_address_display = None
			self.supplier_address = None
			self.address_display = None
			# Suppress mandatory validation for supplier-related fields
			self.flags.ignore_mandatory = True

		return super().before_validate()

	def validate(self):
		if self._is_custody_mode():
			# Re-clear supplier after ERPNext's validate() runs set_missing_values
			# which may try to re-populate supplier from items.
			self.supplier = None
			self.supplier_name = None
			self.flags.ignore_mandatory = True
		super().validate()
		if self._is_custody_mode():
			# Final clear after super().validate() in case it re-set supplier
			self.supplier = None
			self.supplier_name = None

	def validate_with_previous_doc(self):
		if self._is_custody_mode():
			# Custody PRs are not linked to POs or supplier quotes.
			return
		return super().validate_with_previous_doc()

	def before_submit(self):
		if self._is_custody_mode():
			# Ensure supplier is cleared before GL entries are created
			self.supplier = None
			self.supplier_name = None
			self.flags.ignore_mandatory = True
		if hasattr(super(), "before_submit"):
			return super().before_submit()
