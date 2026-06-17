"""
CustodyPaymentReconciliation — Override for Payment Reconciliation doctype.

Design principle: Every override is gated by `self.party_type == "Custodian"`.
All other party types (Supplier, Customer, Employee) go through the original
ERPNext methods unchanged via super(). We are adding a new conditional branch,
not changing the main function.

Why this override is needed:
  The standard Payment Reconciliation tool queries the Payment Ledger Entry
  table filtered by account_type IN ('Receivable', 'Payable'). Custody accounts
  have account_type='Custody', so custody PLEs are invisible to the standard
  tool. This override adds a Custodian-specific query path that reads from
  tabPurchase Invoice and tabPayment Entry directly, using the custom_custodian
  and custom_source_document_type fields as identifiers.
"""
import frappe
from frappe.utils import flt
from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import (
    PaymentReconciliation,
)


class CustodyPaymentReconciliation(PaymentReconciliation):
    """
    Extends Payment Reconciliation with Custodian-party support.
    All non-Custodian paths delegate to super() unchanged.
    """

    def get_invoice_entries(self):
        """
        Returns outstanding custody Purchase Invoices for the selected custodian.
        Gate: only active when party_type == 'Custodian'.
        All other party types go through the original ERPNext method unchanged.
        """
        if self.party_type != "Custodian":
            return super().get_invoice_entries()

        # Custodian branch: query tabPurchase Invoice directly.
        # Custody PIs are identified by custom_custodian + custom_source_document_type
        # since tabPurchase Invoice has no native party_type/party columns.
        conditions = {
            "custom_custodian": self.party,
            "custom_source_document_type": "Custody",
            "docstatus": 1,
        }
        if self.company:
            conditions["company"] = self.company

        invoices = frappe.db.get_all(
            "Purchase Invoice",
            filters=conditions,
            fields=[
                "name as voucher_no",
                "posting_date",
                "grand_total as invoice_amount",
                "outstanding_amount",
                "credit_to as account",
                "currency",
            ],
        )

        # Filter to only invoices with outstanding > 0 and matching account
        result = []
        for inv in invoices:
            if flt(inv.outstanding_amount) <= 0.001:
                continue
            if self.receivable_payable_account and inv.account != self.receivable_payable_account:
                continue
            inv["voucher_type"] = "Purchase Invoice"
            inv["party_type"] = "Custodian"
            inv["party"] = self.party
            result.append(inv)

        self.invoices = result
        return result

    def get_nonreconciled_payment_entries(self):
        """
        Returns unallocated custody Payment Entries for the selected custodian.
        Gate: only active when party_type == 'Custodian'.
        All other party types go through the original ERPNext method unchanged.
        """
        if self.party_type != "Custodian":
            return super().get_nonreconciled_payment_entries()

        # Custodian branch: query tabPayment Entry directly by party_type/party.
        # PE has native party_type and party columns, so this is straightforward.
        conditions = {
            "party_type": "Custodian",
            "party": self.party,
            "docstatus": 1,
        }
        if self.company:
            conditions["company"] = self.company

        payments = frappe.db.get_all(
            "Payment Entry",
            filters=conditions,
            fields=[
                "name as voucher_no",
                "posting_date",
                "paid_amount",
                "unallocated_amount",
                "paid_to as account",
                "paid_to_account_currency as currency",
                "payment_type",
            ],
        )

        # Filter to only PEs with unallocated amount > 0 and matching account
        result = []
        for pe in payments:
            if flt(pe.unallocated_amount) <= 0.001:
                continue
            if self.receivable_payable_account and pe.account != self.receivable_payable_account:
                continue
            pe["voucher_type"] = "Payment Entry"
            pe["party_type"] = "Custodian"
            pe["party"] = self.party
            result.append(pe)

        self.payments = result
        return result
