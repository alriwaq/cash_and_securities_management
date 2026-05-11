import frappe
from frappe import _

from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice


class CustodyPurchaseInvoice(PurchaseInvoice):
    def _is_custody_mode(self):
        return (
            self.get("custom_source_document_type") == "Custody"
            or bool(self.get("custom_accountant_custody"))
        )

    def _get_custody_payable_account(self):
        ac_name = self.get("custom_accountant_custody")
        if not ac_name:
            return None

        if not frappe.db.exists("Accountant Custody", ac_name):
            return None

        ac_doc = frappe.get_doc("Accountant Custody", ac_name)
        _advance_account, payable_account = ac_doc._get_custodian_accounts()
        return payable_account

    def before_validate(self):
        if self._is_custody_mode():
            self.flags.ignore_mandatory = True
            self.supplier = None
            if self.get("custom_custodian") and not self.get("supplier_name"):
                self.supplier_name = self.custom_custodian

            payable_account = self._get_custody_payable_account()
            if payable_account:
                self.credit_to = payable_account
                self.party_type = "Custodian"
                self.party = self.get("custom_custodian")
                self.party_account_currency = frappe.db.get_value(
                    "Account", payable_account, "account_currency"
                )

        return super().before_validate()

    def set_missing_values(self, for_validate=False):
        if not self._is_custody_mode():
            return super().set_missing_values(for_validate)

        if not self.due_date:
            self.due_date = self.posting_date

        # Keep stock/tax defaults from parent where possible without supplier dependency.
        super(PurchaseInvoice, self).set_missing_values(for_validate)

    def validate_with_previous_doc(self):
        if not self._is_custody_mode():
            return super().validate_with_previous_doc()

        return super().validate_with_previous_doc(
            {
                "Purchase Order": {
                    "ref_dn_field": "purchase_order",
                    "compare_fields": [["company", "="], ["currency", "="]],
                },
                "Purchase Order Item": {
                    "ref_dn_field": "po_detail",
                    "compare_fields": [["project", "="], ["item_code", "="], ["uom", "="]],
                    "is_child_table": True,
                    "allow_duplicate_prev_row_id": True,
                },
                "Purchase Receipt": {
                    "ref_dn_field": "purchase_receipt",
                    "compare_fields": [["company", "="], ["currency", "="]],
                },
                "Purchase Receipt Item": {
                    "ref_dn_field": "pr_detail",
                    "compare_fields": [["project", "="], ["item_code", "="], ["uom", "="]],
                    "is_child_table": True,
                },
            }
        )

    def validate_supplier_invoice(self):
        if self._is_custody_mode():
            return
        return super().validate_supplier_invoice()

    def validate_credit_to_acc(self):
        if not self._is_custody_mode():
            return super().validate_credit_to_acc()

        if not self.credit_to:
            frappe.throw(_("Credit To account is required for custody Purchase Invoice."))

        account = frappe.get_cached_value(
            "Account", self.credit_to, ["account_type", "report_type", "account_currency"], as_dict=True
        )

        if account.report_type != "Balance Sheet":
            frappe.throw(
                _(
                    "Please ensure that the Credit To account is a Balance Sheet account."
                ),
                title=_("Invalid Account"),
            )

        if account.account_type != "Payable":
            frappe.throw(
                _("Credit To must be a Payable account for custody invoices."),
                title=_("Invalid Account Type"),
            )

        self.party_account_currency = account.account_currency
