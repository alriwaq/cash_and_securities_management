"""
Accountant Custody controller.

An Accountant Custody records the actual purchases made by an employee using
custody funds. It is linked to a Custody Request (advance) and drives the
creation of Purchase Receipt → Purchase Invoice → Settlement.

Supplier Resolution Logic:
  - Mode A (use_single_dummy_supplier = ON):
      Supplier = Treasury Settings.default_cash_purchases_supplier
  - Mode B (use_single_dummy_supplier = OFF):
      Supplier = Custodian.dedicated_supplier (looked up via custodian)

The payable account is automatically resolved from the supplier — no user input needed.
The settlement_type is now a header-level field on the document.
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from cash_and_securities_management.treasury.utils import get_settings


class AccountantCustody(Document):

    # ─── Lifecycle Hooks ──────────────────────────────────────────────────────

    def validate(self):
        self._auto_link_custody_request()
        self._set_custodian_from_request()
        self._calculate_totals()
        self._update_custody_request_balance()
        self._validate_items()

    def on_submit(self):
        self.db_set("status", "Submitted")
        self._create_purchase_receipt()

    def on_cancel(self):
        self._validate_cancellation()
        self.db_set("status", "Cancelled")

    # ─── Supplier Resolution ──────────────────────────────────────────────────

    def _resolve_supplier(self):
        """
        Return the correct supplier based on Treasury Settings mode.

        Mode A: single dummy supplier from settings.
        Mode B: dedicated supplier from the Custodian record.
        """
        settings = get_settings()

        if settings.get("use_single_dummy_supplier"):
            supplier = settings.get("default_cash_purchases_supplier")
            if not supplier:
                frappe.throw(
                    _("Default Cash Purchases Supplier is not configured in Treasury Settings. "
                      "Please configure it or disable 'Use Single Dummy Supplier'."),
                    title=_("Missing Supplier Configuration"),
                )
            return supplier

        # Mode B — get dedicated supplier from Custodian
        custodian_name = self.custodian
        if not custodian_name and self.custody_request:
            custodian_name = frappe.db.get_value(
                "Custody Request", self.custody_request, "custodian"
            )

        if not custodian_name:
            frappe.throw(
                _("Cannot resolve supplier: no Custodian is linked to this record. "
                  "Please ensure a Custody Request with a valid Custodian is selected."),
                title=_("No Custodian"),
            )

        dedicated_supplier = frappe.db.get_value(
            "Custodian", custodian_name, "dedicated_supplier"
        )
        if not dedicated_supplier:
            frappe.throw(
                _("Custodian {0} does not have a Dedicated Supplier assigned. "
                  "Please assign one on the Custodian record.").format(custodian_name),
                title=_("Missing Dedicated Supplier"),
            )
        return dedicated_supplier

     def _get_payable_account(self):
      """Get payable account from Supplier Party Account, then Supplier Group Party Account."""
  
      supplier = self._resolve_supplier()
  
      supplier_group = frappe.db.get_value(
          "Supplier",
          supplier,
          "supplier_group"
      )
  
      # 1. Supplier Party Account
      payable = frappe.db.get_value(
          "Party Account",
          {
              "parenttype": "Supplier",
              "parent": supplier,
              "company": self.company
          },
          "account"
      )
  
      # 2. Supplier Group Party Account
      if not payable and supplier_group:
          payable = frappe.db.get_value(
              "Party Account",
              {
                  "parenttype": "Supplier Group",
                  "parent": supplier_group,
                  "company": self.company
              },
              "account"
          )
  
      # 3. Error if nothing found
      if not payable:
          frappe.throw(
              _(
                  "No default payable account configured for "
                  "Supplier <b>{0}</b> or Supplier Group <b>{1}</b> "
                  "for Company <b>{2}</b>."
              ).format(
                  supplier,
                  supplier_group or _("Not Set"),
                  self.company
              )
          )
  
      return payable

    # ─── Defaults & Setup ─────────────────────────────────────────────────────

    def _set_custodian_from_request(self):
        """Auto-set custodian from the linked Custody Request."""
        if self.custody_request and not self.custodian:
            custodian = frappe.db.get_value(
                "Custody Request", self.custody_request, "custodian"
            )
            if custodian:
                self.custodian = custodian

    def _auto_link_custody_request(self):
        """Auto-link to the first unpaid Custody Request for this employee if not set."""
        if self.custody_request or not self.employee:
            return
        first_unpaid = frappe.db.get_value(
            "Custody Request",
            {
                "employee": self.employee,
                "status": ["in", ["Paid", "Partly Claimed"]],
                "docstatus": 1,
            },
            "name",
            order_by="posting_date asc, creation asc",
        )
        if first_unpaid:
            self.custody_request = first_unpaid

    def _update_custody_request_balance(self):
        """Fetch the unallocated balance from the linked Custody Request."""
        if self.custody_request:
            balance = frappe.db.get_value(
                "Custody Request", self.custody_request, "unallocated_amount"
            )
            self.custody_request_balance = flt(balance)

    # ─── Calculations ─────────────────────────────────────────────────────────

    def _calculate_totals(self):
        total = 0
        accepted_total = 0
        billed_total = 0
        for item in self.custody_items:
            item.amount = flt(item.qty) * flt(item.rate)
            item.pending_qty = flt(item.qty) - flt(item.accepted_qty)
            total += flt(item.amount)
            accepted_total += flt(item.accepted_qty) * flt(item.rate)
            billed_total += flt(item.billed_qty) * flt(item.rate)
        self.total_amount = total
        self.total_accepted_amount = accepted_total
        self.total_billed_amount = billed_total

    # ─── Validations ──────────────────────────────────────────────────────────

    def _validate_items(self):
        for item in self.custody_items:
            if item.is_stock_item and not item.warehouse:
                frappe.throw(
                    _("Row {0}: Warehouse is required for stock item {1}").format(
                        item.idx, item.item_code
                    )
                )
            if item.is_fixed_asset and not item.asset_location:
                frappe.throw(
                    _("Row {0}: Asset Location is required for fixed asset {1}").format(
                        item.idx, item.item_code
                    )
                )

    def _validate_cancellation(self):
        if self.status == "Settled":
            frappe.throw(
                _("Cannot cancel a Settled Accountant Custody. Please cancel the settlement first.")
            )
        linked_prs = frappe.get_all(
            "Purchase Receipt",
            filters={"custom_accountant_custody": self.name, "docstatus": 1},
            fields=["name"],
        )
        if linked_prs:
            frappe.throw(
                _("Cannot cancel Accountant Custody {0}. Please cancel the linked "
                  "Purchase Receipt(s) first: {1}").format(
                    self.name, ", ".join([d.name for d in linked_prs])
                )
            )
        if self.purchase_invoice:
            pi_status = frappe.db.get_value(
                "Purchase Invoice", self.purchase_invoice, "docstatus"
            )
            if pi_status == 1:
                frappe.throw(
                    _("Cannot cancel Accountant Custody {0}. Please cancel the linked "
                      "Purchase Invoice {1} first.").format(self.name, self.purchase_invoice)
                )

    # ─── Purchase Receipt Creation ─────────────────────────────────────────────

    def _create_purchase_receipt(self):
        """Auto-create a draft Purchase Receipt for all stock/fixed asset items."""
        settings = get_settings()
        stock_items = [
            item for item in self.custody_items if item.is_stock_item or item.is_fixed_asset
        ]
        if not stock_items:
            self.db_set("status", "Fully Received")
            return

        existing_pr = frappe.db.get_value(
            "Purchase Receipt",
            {"custom_accountant_custody": self.name, "docstatus": ["!=", 2]},
            "name",
        )
        if existing_pr:
            frappe.msgprint(
                _("A Purchase Receipt {0} already exists for this Accountant Custody.").format(
                    existing_pr
                )
            )
            return

        supplier = self._resolve_supplier()

        pr = frappe.new_doc("Purchase Receipt")
        pr.supplier = supplier
        pr.project = self.project
        pr.cost_center = self.cost_center
        pr.set_warehouse = self.warehouse
        pr.posting_date = self.posting_date
        pr.company = self.company
        pr.custom_accountant_custody = self.name
        pr.custom_custodian = self.custodian
        pr.custom_source_document_type = "Custody"
        if settings.get("pr_series"):
            pr.naming_series = settings.pr_series

        for item in stock_items:
            pr.append(
                "items",
                {
                    "item_code": item.item_code,
                    "qty": item.qty,
                    "rate": item.rate,
                    "warehouse": item.warehouse,
                    "is_fixed_asset": item.is_fixed_asset,
                    "asset_location": item.asset_location,
                    "project": item.project,
                    "cost_center": item.cost_center,
                },
            )

        pr.flags.ignore_permissions = True
        pr.insert()
        frappe.msgprint(
            _("Purchase Receipt {0} created in Draft. Please review and submit.").format(
                frappe.bold(pr.name)
            ),
            alert=True,
        )
        self.db_set("status", "Receiving")

    # ─── Purchase Invoice Generation ──────────────────────────────────────────

    @frappe.whitelist()
    def generate_purchase_invoice(self):
        """
        Called from the 'Generate Invoice' button.
        Uses ERPNext's native make_purchase_invoice() to build the PI from submitted PRs.
        This ensures all accounting dimensions (project, cost_center), GRNVB clearing,
        and purchase_receipt/pr_detail linkage are handled natively by ERPNext.
        """
        if self.status not in ("Receiving", "Fully Received"):
            frappe.throw(
                _("Purchase Invoice can only be generated when status is "
                  "'Receiving' or 'Fully Received'.")
            )

        existing_pi = frappe.db.get_value(
            "Purchase Invoice",
            {"custom_accountant_custody": self.name, "docstatus": ["!=", 2]},
            "name",
        )
        if existing_pi:
            frappe.throw(
                _("A Purchase Invoice {0} already exists for this Accountant Custody.").format(
                    existing_pi
                )
            )

        # Get all submitted PRs linked to this Accountant Custody
        submitted_prs = frappe.get_all(
            "Purchase Receipt",
            filters={"custom_accountant_custody": self.name, "docstatus": 1},
            fields=["name"],
            order_by="creation asc",
        )

        # Check if there are service/non-stock items that need direct invoicing
        # (items not covered by any PR)
        has_service_items = any(
            not (item.is_stock_item or item.is_fixed_asset)
            for item in self.custody_items
        )

        settings = get_settings()
        supplier = self._resolve_supplier()

        if submitted_prs:
            # Use ERPNext's native make_purchase_invoice for the first PR
            # This correctly sets purchase_receipt, pr_detail, cost_center, project, etc.
            from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
                make_purchase_invoice as erpnext_make_pi,
            )

            pi_doc = erpnext_make_pi(submitted_prs[0].name)

            # If there are multiple PRs, merge their items into the same PI
            if len(submitted_prs) > 1:
                for pr_record in submitted_prs[1:]:
                    additional_pi = erpnext_make_pi(pr_record.name)
                    for item in additional_pi.get("items"):
                        pi_doc.append("items", item.as_dict())

            # Override supplier to the custody supplier (may differ from PR supplier
            # if dummy supplier mode is used)
            pi_doc.supplier = supplier

            # Add service items that have no PR
            if has_service_items:
                for item in self.custody_items:
                    if not (item.is_stock_item or item.is_fixed_asset):
                        pi_doc.append(
                            "items",
                            {
                                "item_code": item.item_code,
                                "qty": flt(item.qty),
                                "rate": item.rate,
                                "project": item.project,
                                "cost_center": item.cost_center,
                            },
                        )

        else:
            # No PRs exist — all items are service/non-stock, create PI directly
            if not has_service_items:
                frappe.throw(
                    _("No submitted Purchase Receipts found for this Accountant Custody. "
                      "Please create and submit a Purchase Receipt first for stock/fixed asset items.")
                )
            pi_doc = frappe.new_doc("Purchase Invoice")
            pi_doc.supplier = supplier
            pi_doc.posting_date = nowdate()
            pi_doc.company = self.company
            for item in self.custody_items:
                pi_doc.append(
                    "items",
                    {
                        "item_code": item.item_code,
                        "qty": flt(item.qty),
                        "rate": item.rate,
                        "project": item.project,
                        "cost_center": item.cost_center,
                    },
                )

        # Set our custom fields on the PI header
        pi_doc.custom_accountant_custody = self.name
        pi_doc.custom_custodian = self.custodian
        pi_doc.custom_source_document_type = "Custody"
        pi_doc.posting_date = nowdate()
        pi_doc.company = self.company

        if settings.get("pi_series"):
            pi_doc.naming_series = settings.pi_series

        pi_doc.flags.ignore_permissions = True
        pi_doc.insert()

        self.db_set("purchase_invoice", pi_doc.name)
        self.db_set("status", "Invoiced")

        frappe.msgprint(
            _("Purchase Invoice {0} created in Draft. Please review and submit.").format(
                frappe.bold(pi_doc.name)
            ),
            alert=True,
        )
        return pi_doc.name

    # ─── Settlement ───────────────────────────────────────────────────────────

    @frappe.whitelist()
    def create_settlement(
        self,
        advance_amount_allocated=0,
        direct_payment_amount=0,
        settlement_notes="",
    ):
        """
        Called from the 'Settle' button.
        Uses the settlement_type from the document header.
        Creates a JE and records the settlement entry.
        """
        if self.status != "Invoiced":
            frappe.throw(_("Settlement can only be done when status is 'Invoiced'."))

        if not self.settlement_type:
            frappe.throw(_("Please select a Settlement Type before settling."))

        settings = get_settings()
        advance_amount_allocated = flt(advance_amount_allocated)
        direct_payment_amount = flt(direct_payment_amount)
        total_settlement = advance_amount_allocated + direct_payment_amount

        if abs(total_settlement - flt(self.total_billed_amount)) > 0.01:
            frappe.throw(
                _("Settlement amount {0} does not match the billed amount {1}.").format(
                    total_settlement, self.total_billed_amount
                )
            )

        supplier = self._resolve_supplier()
        payable_account = self._get_payable_account()

        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.posting_date = nowdate()
        je.company = self.company
        je.user_remark = _("Settlement for Accountant Custody {0}").format(self.name)

        # Debit Supplier Payable
        je.append(
            "accounts",
            {
                "account": payable_account,
                "debit_in_account_currency": total_settlement,
                "party_type": "Supplier",
                "party": supplier,
                "reference_type": "Purchase Invoice",
                "reference_name": self.purchase_invoice,
            },
        )

        # Credit Custody Advance Account (from custodian)
        if advance_amount_allocated > 0:
            advance_account = None
            if self.custodian:
                advance_account = frappe.db.get_value(
                    "Custodian", self.custodian, "custody_account"
                )
            if not advance_account and self.custody_request:
                advance_account = frappe.db.get_value(
                    "Custody Request", self.custody_request, "advance_account"
                )
            if not advance_account:
                frappe.throw(
                    _("Cannot find the Custody Advance Account. Please ensure the "
                      "linked Custodian has a custody account set.")
                )
            je.append(
                "accounts",
                {
                    "account": advance_account,
                    "credit_in_account_currency": advance_amount_allocated,
                    "party_type": "Employee",
                    "party": self.employee,
                },
            )

        # Credit Cash/Bank for direct payment
        if direct_payment_amount > 0:
            direct_account = settings.get("settlement_expense_account") or ""
            if not direct_account:
                # Fallback to company default cash account
                direct_account = frappe.db.get_value(
                    "Company", self.company, "default_cash_account"
                )
            if not direct_account:
                frappe.throw(
                    _("Please set the Settlement Expense Account in Treasury Settings "
                      "or a Default Cash Account in Company settings.")
                )
            je.append(
                "accounts",
                {
                    "account": direct_account,
                    "credit_in_account_currency": direct_payment_amount,
                },
            )

        je.flags.ignore_permissions = True
        je.insert()
        je.submit()

        # Record settlement entry in the child table
        self.append(
            "settlements",
            {
                "custody_request": self.custody_request,
                "custody_request_balance": self.custody_request_balance,
                "claimed_amount": advance_amount_allocated,
                "advance_amount_allocated": advance_amount_allocated,
                "direct_payment_amount": direct_payment_amount,
                "total_settlement_amount": total_settlement,
                "settlement_je": je.name,
                "settlement_date": nowdate(),
                "settlement_notes": settlement_notes,
            },
        )
        self.db_set("status", "Settled")
        self.save(ignore_permissions=True)

        # Update the Custody Request claimed amounts
        if self.custody_request and advance_amount_allocated > 0:
            cr_doc = frappe.get_doc("Custody Request", self.custody_request)
            cr_doc.update_claimed_amount()

        frappe.msgprint(
            _("Settlement Journal Entry {0} created and submitted. "
              "Accountant Custody is now Settled.").format(frappe.bold(je.name))
        )
        return je.name

    # ─── PR/PI Callbacks ──────────────────────────────────────────────────────

    def update_received_quantities(self):
        """Called after a linked PR is submitted. Updates accepted_qty on items."""
        prs = frappe.get_all(
            "Purchase Receipt",
            filters={"custom_accountant_custody": self.name, "docstatus": 1},
            fields=["name"],
        )
        if not prs:
            return

        for item in self.custody_items:
            item.accepted_qty = 0
            item.rejected_qty = 0

        for pr_record in prs:
            pr_doc = frappe.get_doc("Purchase Receipt", pr_record.name)
            for pr_item in pr_doc.items:
                for custody_item in self.custody_items:
                    if custody_item.item_code == pr_item.item_code:
                        custody_item.accepted_qty = (
                            flt(custody_item.accepted_qty) + flt(pr_item.qty)
                        )
                        custody_item.rejected_qty = (
                            flt(custody_item.rejected_qty) + flt(pr_item.rejected_qty)
                        )
                        break

        self._calculate_totals()
        all_received = all(
            flt(item.qty) >= flt(item.qty)
            for item in self.custody_items
            if item.is_stock_item or item.is_fixed_asset
        )
        new_status = "Fully Received" if all_received else "Receiving"
        self.db_set("status", new_status)
        self.save(ignore_permissions=True)

    def update_billed_quantities(self, pi_name=None):
        """Called after the linked PI is submitted. Updates billed_qty on items.
        Accepts an optional pi_name parameter to handle PI created from PR button.
        """
        invoice_name = pi_name or self.purchase_invoice
        if not invoice_name:
            return
        # Set the purchase_invoice link if not already set
        if not self.purchase_invoice:
            self.db_set("purchase_invoice", invoice_name)
        pi_doc = frappe.get_doc("Purchase Invoice", invoice_name)
        # Reset billed qty first
        for custody_item in self.custody_items:
            custody_item.billed_qty = 0
        # Sum billed qty from all submitted PIs for this custody
        all_pis = frappe.get_all(
            "Purchase Invoice",
            filters={"custom_accountant_custody": self.name, "docstatus": 1},
            fields=["name"],
        )
        for pi_record in all_pis:
            pi = frappe.get_doc("Purchase Invoice", pi_record.name)
            for pi_item in pi.items:
                for custody_item in self.custody_items:
                    if custody_item.item_code == pi_item.item_code:
                        custody_item.billed_qty = flt(custody_item.billed_qty) + flt(pi_item.qty)
                        break
        self._calculate_totals()
        self.db_set("status", "Invoiced")
        self.save(ignore_permissions=True)
