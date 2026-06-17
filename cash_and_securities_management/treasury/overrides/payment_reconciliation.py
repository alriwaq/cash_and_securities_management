"""
CustodyPaymentReconciliation — Override for Payment Reconciliation doctype.

Design principle: Every override is gated by `self.party_type == "Custodian"`.
All other party types (Supplier, Customer, Employee) go through the original
ERPNext methods unchanged via super(). We are adding a new conditional branch,
not changing the main function.

Why this override is needed:
  The standard Payment Reconciliation tool queries the Payment Ledger Entry
  table via get_outstanding_invoices() which filters:
    ple.account_type.isin(["Receivable", "Payable"])
  Custody accounts have account_type='Custody', so custody PLEs are invisible.
  This override adds a Custodian-specific query path that reads directly from
  tabPurchase Invoice and tabPayment Entry, bypassing the PLE query entirely
  for Custodian party — while leaving all other party types completely unchanged.
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

    def get_unreconciled_entries(self):
        """
        Entry point called by the UI 'Get Unreconciled Entries' button.
        Gate: only active when party_type == 'Custodian'.
        All other party types go through the original ERPNext method unchanged.
        """
        if self.party_type != "Custodian":
            return super().get_unreconciled_entries()

        # Custodian branch: call our own overridden methods directly
        # — bypasses check_mandatory_to_fetch which requires receivable_payable_account
        self.get_nonreconciled_payment_entries()
        self.get_invoice_entries()

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
        if not self.party:
            frappe.throw(frappe._("Please select a Custodian first"))

        filters = {
            "party_type": "Custodian",
            "party": self.party,
            "docstatus": 1,
        }
        if self.company:
            filters["company"] = self.company

        payments = frappe.db.get_all(
            "Payment Entry",
            filters=filters,
            fields=[
                "name",
                "posting_date",
                "paid_amount",
                "unallocated_amount",
                "paid_to as account",
                "paid_to_account_currency as currency",
                "payment_type",
            ],
        )

        # Filter to only PEs with unallocated amount > 0
        # Optionally filter by receivable_payable_account if set
        result = []
        for pe in payments:
            if flt(pe.unallocated_amount) <= 0.001:
                continue
            if self.receivable_payable_account and pe.account != self.receivable_payable_account:
                continue
            result.append(pe)

        # Populate the payments child table (same structure as standard tool)
        self.set("payments", [])
        for pe in result:
            row = self.append("payments", {})
            row.payment_type = "Payment Entry"
            row.reference_name = pe.name
            row.posting_date = pe.posting_date
            row.amount = flt(pe.paid_amount)
            row.currency = pe.currency
            row.unallocated_amount = flt(pe.unallocated_amount)

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
        if not self.party:
            frappe.throw(frappe._("Please select a Custodian first"))

        filters = {
            "custom_custodian": self.party,
            "custom_source_document_type": "Custody",
            "docstatus": 1,
        }
        if self.company:
            filters["company"] = self.company

        invoices = frappe.db.get_all(
            "Purchase Invoice",
            filters=filters,
            fields=[
                "name",
                "posting_date",
                "grand_total",
                "outstanding_amount",
                "credit_to as account",
                "currency",
            ],
        )

        # Filter to only invoices with outstanding > 0
        # Optionally filter by receivable_payable_account if set
        result = []
        for inv in invoices:
            if flt(inv.outstanding_amount) <= 0.001:
                continue
            if self.receivable_payable_account and inv.account != self.receivable_payable_account:
                continue
            result.append(inv)

        # Populate the invoices child table (same structure as standard tool)
        self.set("invoices", [])
        for inv in result:
            row = self.append("invoices", {})
            row.invoice_type = "Purchase Invoice"
            row.invoice_number = inv.name
            row.invoice_date = inv.posting_date
            row.amount = flt(inv.grand_total)
            row.currency = inv.currency
            row.outstanding_amount = flt(inv.outstanding_amount)
