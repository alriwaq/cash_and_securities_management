"""
Custody Request controller.

A Custody Request is raised by an employee to request a cash advance for
business purchases. It must be linked to an active Custodian record.

The advance_account is locked to the Custodian's dedicated custody_account.

Lifecycle:
    Draft → (Submit) → Unpaid → (Payment created) → Paid → (Claims) → Partly Claimed / Claimed
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate


class CustodyRequest(Document):

    # ── Frappe Lifecycle Hooks ────────────────────────────────────────────────

    def validate(self):
        self._auto_set_custodian()
        self._validate_custodian_status()
        self._validate_custody_limit()
        self._lock_advance_account()
        self._calculate_unallocated()

    def on_submit(self):
        self.db_set("status", "Unpaid")
        self._refresh_custodian_balance()

    def on_cancel(self):
        self._validate_no_linked_documents()
        self.db_set("status", "Cancelled")
        self._refresh_custodian_balance()

    # ── Whitelisted Actions ───────────────────────────────────────────────────

    @frappe.whitelist()
    def create_payment_entry(self):
        """Create a Payment Entry to pay the employee for this custody request."""
        if self.status != "Unpaid":
            frappe.throw(_("Payment can only be created for Unpaid Custody Requests."))

        custodian = frappe.get_doc("Custodian", self.custodian)
        if not custodian.custody_account:
            frappe.throw(
                _("Custodian {0} does not have a custody account configured.").format(
                    self.custodian
                )
            )

        company = self.company
        default_bank = frappe.db.get_value("Company", company, "default_bank_account")
        if not default_bank:
            frappe.throw(
                _("Please set a Default Bank Account in Company {0} settings.").format(company)
            )

        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Pay"
        pe.posting_date = nowdate()
        pe.company = company
        pe.mode_of_payment = self.mode_of_payment
        pe.party_type = "Employee"
        pe.party = self.employee
        pe.party_name = self.employee_name
        pe.paid_from = default_bank
        pe.paid_to = custodian.custody_account
        pe.paid_amount = flt(self.advance_amount)
        pe.received_amount = flt(self.advance_amount)
        pe.reference_no = self.name
        pe.reference_date = nowdate()
        pe.custom_custodian = self.custodian
        pe.custom_custody_request = self.name

        pe.flags.ignore_permissions = True
        pe.insert()

        # Update paid_amount and status
        self.db_set("paid_amount", flt(self.advance_amount))
        self.db_set("status", "Paid")
        self._save_unallocated()

        # Refresh custodian balances
        self._refresh_custodian_balance()

        frappe.msgprint(
            _("Payment Entry {0} created successfully.").format(
                frappe.utils.get_link_to_form("Payment Entry", pe.name)
            ),
            alert=True,
        )
        return pe.name

    @frappe.whitelist()
    def refresh_amounts(self):
        """Recalculate paid_amount and claimed_amount from linked documents."""
        # Paid: sum of Payment Entries linked to this request
        paid = frappe.db.sql(
            """
            SELECT COALESCE(SUM(pe.paid_amount), 0)
            FROM `tabPayment Entry` pe
            WHERE pe.custom_custody_request = %s
              AND pe.docstatus = 1
              AND pe.payment_type = 'Pay'
            """,
            (self.name,),
        )
        self.paid_amount = flt(paid[0][0]) if paid else 0.0

        # Claimed: sum from Accountant Custody settlement entries
        claimed = frappe.db.sql(
            """
            SELECT COALESCE(SUM(cse.claimed_amount), 0)
            FROM `tabCustody Settlement Entry` cse
            JOIN `tabAccountant Custody` ac ON ac.name = cse.parent
            WHERE cse.custody_request = %s
              AND ac.docstatus = 1
            """,
            (self.name,),
        )
        self.claimed_amount = flt(claimed[0][0]) if claimed else 0.0

        # Unallocated
        self.unallocated_amount = flt(self.paid_amount) - flt(self.claimed_amount)

        # Update status
        if flt(self.paid_amount) == 0:
            status = "Unpaid"
        elif flt(self.claimed_amount) >= flt(self.paid_amount):
            status = "Claimed"
        elif flt(self.claimed_amount) > 0:
            status = "Partly Claimed"
        else:
            status = "Paid"

        self.status = status
        self.db_update()

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _auto_set_custodian(self):
        """Auto-set the custodian field from the employee's active Custodian."""
        if self.employee and not self.custodian:
            custodian = frappe.db.get_value(
                "Custodian",
                {
                    "employee": self.employee,
                    "docstatus": 1,
                    "status": "Active",
                },
                "name",
            )
            if custodian:
                self.custodian = custodian

    def _validate_custodian_status(self):
        """Block submission if the custodian is Suspended or Closed."""
        if not self.custodian:
            frappe.throw(
                _("A Custodian record is required. Please create an active Custodian "
                  "for employee {0} before raising a Custody Request.").format(
                    self.employee_name or self.employee
                ),
                title=_("No Custodian Found"),
            )

        status = frappe.db.get_value("Custodian", self.custodian, "status")
        if status == "Suspended":
            frappe.throw(
                _("Custodian {0} is currently Suspended. New Custody Requests cannot "
                  "be created until the custodian is reactivated.").format(self.custodian),
                title=_("Custodian Suspended"),
            )
        if status == "Closed":
            frappe.throw(
                _("Custodian {0} is Closed. No further Custody Requests are allowed.").format(
                    self.custodian
                ),
                title=_("Custodian Closed"),
            )

    def _validate_custody_limit(self):
        """Ensure the new request does not exceed the custodian's limit."""
        if not self.custodian or not self.advance_amount:
            return

        limit_val, outstanding = frappe.db.get_value(
            "Custodian",
            self.custodian,
            ["custody_limit", "total_outstanding"],
        ) or (0, 0)

        limit_val = flt(limit_val)
        outstanding = flt(outstanding)

        if limit_val > 0:
            projected = outstanding + flt(self.advance_amount)
            if projected > limit_val:
                frappe.throw(
                    _("This request of {0} would push the custodian's outstanding balance "
                      "to {1}, exceeding the custody limit of {2}. "
                      "Please reduce the amount or increase the limit.").format(
                        frappe.utils.fmt_money(self.advance_amount),
                        frappe.utils.fmt_money(projected),
                        frappe.utils.fmt_money(limit_val),
                    ),
                    title=_("Custody Limit Exceeded"),
                )

    def _lock_advance_account(self):
        """Lock the advance account to the custodian's dedicated account — always override."""
        if self.custodian:
            custody_account = frappe.db.get_value(
                "Custodian", self.custodian, "custody_account"
            )
            if custody_account:
                self.advance_account = custody_account

    def _calculate_unallocated(self):
        """Calculate unallocated_amount = paid_amount - claimed_amount."""
        self.unallocated_amount = flt(self.paid_amount) - flt(self.claimed_amount)

    def _save_unallocated(self):
        """Recalculate and persist unallocated_amount."""
        paid = flt(frappe.db.get_value("Custody Request", self.name, "paid_amount"))
        claimed = flt(frappe.db.get_value("Custody Request", self.name, "claimed_amount"))
        self.db_set("unallocated_amount", paid - claimed)

    def _validate_no_linked_documents(self):
        """Prevent cancellation if there are linked Accountant Custody records."""
        linked_custodies = frappe.get_all(
            "Accountant Custody",
            filters={"custody_request": self.name, "docstatus": ["!=", 2]},
            fields=["name"],
        )
        if linked_custodies:
            frappe.throw(
                _("Cannot cancel Custody Request {0} as it has linked Accountant "
                  "Custody records: {1}").format(
                    self.name,
                    ", ".join([d.name for d in linked_custodies]),
                )
            )

    def _refresh_custodian_balance(self):
        """Trigger a balance refresh on the linked Custodian."""
        if self.custodian:
            try:
                custodian_doc = frappe.get_doc("Custodian", self.custodian)
                custodian_doc.refresh_outstanding()
            except Exception:
                pass  # Non-critical; balance can be refreshed manually

    # ── Public API (called from Accountant Custody) ───────────────────────────

    def update_claimed_amount(self):
        """Called when an Accountant Custody is settled against this request."""
        total_claimed = frappe.db.sql(
            """
            SELECT COALESCE(SUM(cse.claimed_amount), 0)
            FROM `tabCustody Settlement Entry` cse
            JOIN `tabAccountant Custody` ac ON ac.name = cse.parent
            WHERE cse.custody_request = %s
              AND ac.docstatus = 1
            """,
            self.name,
        )[0][0] or 0

        self.db_set("claimed_amount", flt(total_claimed))
        self.db_set("unallocated_amount", flt(self.paid_amount) - flt(total_claimed))

        if flt(total_claimed) >= flt(self.paid_amount):
            self.db_set("status", "Claimed")
        elif flt(total_claimed) > 0:
            self.db_set("status", "Partly Claimed")

        self._refresh_custodian_balance()
