"""
Custody Request controller.

A Custody Request is raised by an employee to request a cash advance for
business purchases. It must be linked to an active Custodian record.

The advance_account defaults from the Custodian's dedicated custody_account.
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class CustodyRequest(Document):

    # ── Frappe Lifecycle Hooks ────────────────────────────────────────────────

    def validate(self):
        self._auto_set_custodian()
        self._validate_custodian_status()
        self._validate_custody_limit()
        self._set_advance_account_from_custodian()
        self._calculate_remaining_balance()

    def on_submit(self):
        self.db_set("status", "Unpaid")
        # Update the custodian's outstanding balance
        self._refresh_custodian_balance()

    def on_cancel(self):
        self._validate_no_linked_documents()
        self.db_set("status", "Cancelled")
        self._refresh_custodian_balance()

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _auto_set_custodian(self):
        """
        Auto-set the custodian field when an employee is selected.
        Looks up the active (submitted, non-closed) Custodian for this employee.
        """
        if self.employee and not self.custodian:
            custodian = frappe.db.get_value(
                "Custodian",
                {
                    "employee": self.employee,
                    "docstatus": 1,
                    "status": ["in", ["Active", "Suspended"]],
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
        """
        If the custodian has a custody_limit > 0, ensure the new request does
        not push the outstanding balance over the limit.
        """
        if not self.custodian or not self.advance_amount:
            return

        limit, outstanding = frappe.db.get_value(
            "Custodian",
            self.custodian,
            ["custody_limit", "total_outstanding"],
        ) or (0, 0)

        limit = flt(limit)
        outstanding = flt(outstanding)

        if limit > 0:
            projected = outstanding + flt(self.advance_amount)
            if projected > limit:
                frappe.throw(
                    _("This request of {0} would push the custodian's outstanding balance "
                      "to {1}, exceeding the custody limit of {2}. "
                      "Please reduce the amount or increase the limit.").format(
                        frappe.utils.fmt_money(self.advance_amount),
                        frappe.utils.fmt_money(projected),
                        frappe.utils.fmt_money(limit),
                    ),
                    title=_("Custody Limit Exceeded"),
                )

    def _set_advance_account_from_custodian(self):
        """Default advance_account from the Custodian's dedicated custody_account."""
        if not self.advance_account and self.custodian:
            custody_account = frappe.db.get_value(
                "Custodian", self.custodian, "custody_account"
            )
            if custody_account:
                self.advance_account = custody_account

    def _calculate_remaining_balance(self):
        self.remaining_balance = flt(self.advance_amount) - flt(self.claimed_amount)

    def _validate_no_linked_documents(self):
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
            SELECT COALESCE(SUM(total_amount), 0)
            FROM `tabAccountant Custody`
            WHERE custody_request = %s AND docstatus = 1 AND status = 'Settled'
            """,
            self.name,
        )[0][0] or 0

        self.db_set("claimed_amount", flt(total_claimed))
        self.db_set(
            "remaining_balance",
            flt(self.advance_amount) - flt(total_claimed),
        )

        if flt(total_claimed) >= flt(self.advance_amount):
            self.db_set("status", "Claimed")
        elif flt(total_claimed) > 0:
            self.db_set("status", "Partly Claimed")

        self._refresh_custodian_balance()
