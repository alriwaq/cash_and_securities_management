import frappe
from frappe import _
from frappe.utils import flt

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

    def _apply_custody_item_defaults(self):
        if not self._is_custody_mode() or not self.get("custom_accountant_custody"):
            return

        def _composite_key(item):
            return (
                item.get("item_code"),
                item.get("warehouse") or "",
                item.get("project") or "",
                item.get("cost_center") or "",
                item.get("uom") or "",
                flt(item.get("rate") or 0),
            )

        ac_doc = frappe.get_doc("Accountant Custody", self.custom_accountant_custody)
        custody_items_by_key = {}
        custody_items_by_code = {}
        for custody_item in ac_doc.get("custody_items"):
            custody_items_by_key.setdefault(_composite_key(custody_item), []).append(custody_item)
            custody_items_by_code.setdefault(custody_item.item_code, []).append(custody_item)

        pr_item_map = {}
        pr_detail_names = [d.get("pr_detail") for d in self.get("items") if d.get("pr_detail")]
        if pr_detail_names:
            for pr_item in frappe.get_all(
                "Purchase Receipt Item",
                filters={"name": ["in", pr_detail_names]},
                fields=["name", "item_code", "warehouse", "project", "cost_center", "uom", "rate"],
            ):
                pr_item_map[pr_item.name] = pr_item

        for item in self.get("items"):
            custody_item = None
            pr_item = pr_item_map.get(item.get("pr_detail"))
            if pr_item and custody_items_by_key.get(_composite_key(pr_item)):
                custody_item = custody_items_by_key[_composite_key(pr_item)].pop(0)
            elif custody_items_by_code.get(item.item_code):
                custody_item = custody_items_by_code[item.item_code].pop(0)

            if not custody_item:
                continue

            if not item.get("warehouse") and custody_item.get("warehouse"):
                item.warehouse = custody_item.warehouse

            if not item.get("project") and custody_item.get("project"):
                item.project = custody_item.project

            if not item.get("cost_center") and custody_item.get("cost_center"):
                item.cost_center = custody_item.cost_center

    def before_validate(self):
        if self._is_custody_mode():
            self._normalize_custody_totals()
            self._apply_custody_item_defaults()
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

    def set_supplier_from_item_default(self):
        if self._is_custody_mode():
            return
        return super().set_supplier_from_item_default()

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

        self._apply_custody_item_defaults()

        # Keep stock/tax defaults from parent where possible without supplier dependency.
        super().set_missing_values(for_validate)

    def validate_with_previous_doc(self):
        if not self._is_custody_mode():
            return super().validate_with_previous_doc()

        self._validate_custody_previous_documents()

        if (
            frappe.db.get_single_value("Buying Settings", "maintain_same_rate")
            and not self.is_return
            and not self.is_internal_supplier
        ):
            self.validate_rate_with_reference_doc(
                [
                    ["Purchase Order", "purchase_order", "po_detail"],
                    ["Purchase Receipt", "purchase_receipt", "pr_detail"],
                ]
            )

        return None

    def _validate_custody_previous_documents(self):
        seen_purchase_orders = set()
        seen_purchase_receipts = set()

        for row in self.get("items"):
            if row.purchase_order and row.purchase_order not in seen_purchase_orders:
                seen_purchase_orders.add(row.purchase_order)
                purchase_order = frappe.get_doc("Purchase Order", row.purchase_order)
                if purchase_order.company != self.company:
                    frappe.throw(
                        _("Purchase Order {0} does not belong to Company {1}").format(
                            frappe.bold(row.purchase_order), frappe.bold(self.company)
                        )
                    )
                if purchase_order.currency != self.currency:
                    frappe.throw(
                        _("Purchase Order {0} currency must match the invoice currency").format(
                            frappe.bold(row.purchase_order)
                        )
                    )

            if row.purchase_receipt and row.purchase_receipt not in seen_purchase_receipts:
                seen_purchase_receipts.add(row.purchase_receipt)
                purchase_receipt = frappe.get_doc("Purchase Receipt", row.purchase_receipt)
                if purchase_receipt.company != self.company:
                    frappe.throw(
                        _("Purchase Receipt {0} does not belong to Company {1}").format(
                            frappe.bold(row.purchase_receipt), frappe.bold(self.company)
                        )
                    )
                if purchase_receipt.currency != self.currency:
                    frappe.throw(
                        _("Purchase Receipt {0} currency must match the invoice currency").format(
                            frappe.bold(row.purchase_receipt)
                        )
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
