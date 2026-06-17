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

    @frappe.whitelist()
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

    @frappe.whitelist()
    def reconcile(self, args=None):
        """
        Called by the UI Reconcile button.
        Gate: only active when party_type == 'Custodian'.
        For Custodian: fix allocation rows before delegating to super().reconcile().
        """
        if self.party_type != "Custodian":
            return super().reconcile(args)

        # Custodian branch:
        # The standard reconcile_allocations() reads row.get("reference_type") for
        # voucher_type and self.receivable_payable_account for account.
        # Our payments table uses payment_type instead of reference_type, and
        # receivable_payable_account may be the custody account (account_type=Custody).
        # Fix both before calling super().reconcile().

        # 1. Ensure each allocation row has reference_type set
        for row in self.get("allocation"):
            if not row.get("reference_type") and row.get("reference_name"):
                # Determine type from the reference_name prefix or by DB lookup
                ref = row.get("reference_name") or ""
                if frappe.db.exists("Payment Entry", ref):
                    row.reference_type = "Payment Entry"
                elif frappe.db.exists("Journal Entry", ref):
                    row.reference_type = "Journal Entry"

        # 2. Ensure receivable_payable_account is set to the custody account
        if not self.receivable_payable_account and self.party:
            custody_account = frappe.db.get_value("Custodian", self.party, "custody_account")
            if custody_account:
                self.receivable_payable_account = custody_account

        # 3. Override dr_or_cr: Custodian is Payable direction = debit_in_account_currency
        # We patch reconcile_allocations to use the correct dr_or_cr by temporarily
        # making erpnext.get_party_account_type return 'Payable' for Custodian.
        # Simpler: call reconcile_allocations directly with our own implementation.
        self.reconcile_allocations_for_custody()

        # 4. Run post-reconcile steps from super (status update, etc.) without
        #    calling reconcile_allocations again
        self.set_invoice_outstanding()

    def reconcile_allocations_for_custody(self, skip_ref_details_update_for_pe=False):
        """
        Custom reconcile_allocations for Custodian party.
        Uses debit_in_account_currency (Payable direction) and
        calls reconcile_against_document directly.
        """
        from erpnext.accounts.utils import reconcile_against_document

        entry_list = []
        for row in self.get("allocation"):
            if not row.invoice_number or not row.allocated_amount:
                continue
            if not row.get("reference_type"):
                continue

            payment_details = frappe._dict({
                "voucher_type": row.get("reference_type"),          # "Payment Entry"
                "voucher_no": row.get("reference_name"),            # PE name
                "voucher_detail_no": row.get("reference_row"),
                "against_voucher_type": row.get("invoice_type"),    # "Purchase Invoice"
                "against_voucher": row.get("invoice_number"),       # PI name
                "account": self.receivable_payable_account,
                "exchange_rate": row.get("exchange_rate") or 1.0,
                "party_type": self.party_type,
                "party": self.party,
                "is_advance": row.get("is_advance"),
                "dr_or_cr": "debit_in_account_currency",            # Payable direction
                "unreconciled_amount": flt(
                    frappe.db.get_value("Payment Entry", row.get("reference_name"), "unallocated_amount") or 0
                ),
                "unadjusted_amount": flt(row.get("amount")),
                "allocated_amount": flt(row.get("allocated_amount")),
                "difference_amount": flt(row.get("difference_amount")),
                "difference_account": row.get("difference_account"),
                "difference_posting_date": row.get("gain_loss_posting_date"),
            })
            entry_list.append(payment_details)

        if entry_list:
            reconcile_against_document(entry_list, skip_ref_details_update_for_pe)

    def set_invoice_outstanding(self):
        """
        Update outstanding_amount on custody PIs after reconciliation.
        Called after reconcile_allocations_for_custody.
        """
        for row in self.get("allocation"):
            if not row.invoice_number or not row.allocated_amount:
                continue
            pi = frappe.db.get_value(
                "Purchase Invoice", row.invoice_number,
                ["outstanding_amount", "grand_total"], as_dict=True
            )
            if pi:
                new_outstanding = flt(pi.outstanding_amount) - flt(row.allocated_amount)
                frappe.db.set_value(
                    "Purchase Invoice", row.invoice_number,
                    "outstanding_amount", max(0, new_outstanding)
                )

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
