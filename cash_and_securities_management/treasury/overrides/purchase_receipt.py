import frappe
from frappe import _

from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt


class CustodyPurchaseReceipt(PurchaseReceipt):
    def _is_custody_mode(self):
        return (
            self.get("custom_source_document_type") == "Custody"
            or bool(self.get("custom_accountant_custody"))
        )

    def before_validate(self):
        if self._is_custody_mode():
            # Supplier is a core mandatory field on standard PR. For custody mode,
            # we bypass mandatory checks and drive party/accounting via Custodian.
            self.flags.ignore_mandatory = True
            if self.get("custom_custodian") and not self.get("supplier_name"):
                self.supplier_name = self.custom_custodian
            self.supplier = None

        return super().before_validate()

    def validate_with_previous_doc(self):
        if self._is_custody_mode():
            # Custody PR can be generated without supplier-linked previous buying docs.
            return
        return super().validate_with_previous_doc()
