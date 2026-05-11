import frappe
from frappe import _

from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice


class CustodyPurchaseInvoice(PurchaseInvoice):
    def _is_custody_mode(self):
        return (
            self.get("custom_source_document_type") == "Custody"
            or bool(self.get("custom_accountant_custody"))
        )

    def _normalize_custody_totals(self):
        if not self._is_custody_mode():
            return

        if self.get("grand_total") is None:
            self.grand_total = 0
        if self.get("base_grand_total") is None:
            self.base_grand_total = 0
        if self.get("rounded_total") is None:
            self.rounded_total = 0
        if self.get("base_rounded_total") is None:
            self.base_rounded_total = 0
        if self.get("write_off_amount") is None:
            self.write_off_amount = 0
        if self.get("base_write_off_amount") is None:
            self.base_write_off_amount = 0
        if self.get("total_advance") is None:
            self.total_advance = 0

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
            self._normalize_custody_totals()
            self.flags.ignore_mandatory = True
            # Keep supplier empty string (falsy) instead of None to avoid
            # frappe.get_doc("Supplier", None) errors in the parent validate chain.
            if not self.supplier:
                self.supplier = ""
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

    # ---------------------------------------------------------------------------
    # Override AccountsController methods that unconditionally try to load
    # self.supplier as a Supplier document even when it is empty/None.
    # ---------------------------------------------------------------------------

    def ensure_supplier_is_not_blocked(self):
        """Skip supplier-block check for custody invoices (no supplier)."""
        if self._is_custody_mode():
            return
        return super().ensure_supplier_is_not_blocked()

    def po_required(self):
        """Skip PO-required check for custody invoices."""
        if self._is_custody_mode():
            return
        return super().po_required()

    def pr_required(self):
        """Skip PR-required check for custody invoices."""
        if self._is_custody_mode():
            return
        return super().pr_required()

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

    def set_payment_schedule(self):
        if not self._is_custody_mode():
            return super().set_payment_schedule()

        self._normalize_custody_totals()
        return super().set_payment_schedule()

    def validate_payment_schedule_amount(self):
        if not self._is_custody_mode():
            return super().validate_payment_schedule_amount()

        self._normalize_custody_totals()
        return super().validate_payment_schedule_amount()

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

    # ---------------------------------------------------------------------------
    # GL entry overrides — custody PI uses Custodian party, not Supplier.
    # ---------------------------------------------------------------------------

    def add_supplier_gl_entry(
        self, gl_entries, base_grand_total, grand_total, against_account=None, remarks=None, skip_merge=False
    ):
        if not self._is_custody_mode():
            return super().add_supplier_gl_entry(
                gl_entries, base_grand_total, grand_total,
                against_account=against_account, remarks=remarks, skip_merge=skip_merge
            )

        # Custody mode: book against Custodian, not Supplier.
        against_voucher = self.name
        if self.is_return and self.return_against and not self.update_outstanding_for_self:
            against_voucher = self.return_against

        gl = {
            "account": self.credit_to,
            "party_type": "Custodian",
            "party": self.get("custom_custodian") or self.party,
            "due_date": self.due_date,
            "against": against_account or self.against_expense_account,
            "credit": base_grand_total,
            "credit_in_account_currency": (
                base_grand_total
                if self.party_account_currency == self.company_currency
                else grand_total
            ),
            "credit_in_transaction_currency": grand_total,
            "against_voucher": against_voucher,
            "against_voucher_type": self.doctype,
            "project": self.project,
            "cost_center": self.cost_center,
            "_skip_merge": skip_merge,
        }
        if remarks:
            gl["remarks"] = remarks

        gl_entries.append(self.get_gl_dict(gl, self.party_account_currency, item=self))

    def update_supplier_outstanding(self, update_outstanding):
        if not self._is_custody_mode():
            return super().update_supplier_outstanding(update_outstanding)

        if update_outstanding == "No":
            from erpnext.accounts.utils import update_voucher_outstanding
            update_voucher_outstanding(
                voucher_type=self.doctype,
                voucher_no=(
                    self.return_against
                    if self.get("is_return") and self.return_against
                    else self.name
                ),
                account=self.credit_to,
                party_type="Custodian",
                party=self.get("custom_custodian") or self.party,
            )
