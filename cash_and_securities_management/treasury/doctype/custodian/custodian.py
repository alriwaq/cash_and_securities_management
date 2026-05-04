"""
Custodian DocType controller.

A Custodian is a formal, submittable record that designates an employee as
authorized to hold and spend custody funds. It serves as the central hub for
all custody-related activity for that employee.

Lifecycle:
    Draft → (Submit) → Active → (Suspend) → Suspended → (Reactivate) → Active
                                Active / Suspended → (Close) → Closed
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class Custodian(Document):

    # ── Frappe Lifecycle Hooks ────────────────────────────────────────────────

    def validate(self):
        self._validate_unique_active_custodian()
        self._validate_supplier_assignment()

    def on_submit(self):
        self._create_custody_account()
        self._set_status("Active")
        frappe.db.commit()

    def on_cancel(self):
        self._validate_no_open_transactions()

    # ── Custom Action Handlers (called from JS buttons) ───────────────────────

    @frappe.whitelist()
    def suspend(self):
        """Suspend an Active custodian. Blocks new Custody Requests."""
        if self.status != "Active":
            frappe.throw(_("Only an Active custodian can be suspended."))
        self._set_status("Suspended")
        self.add_comment("Info", _("Custodian suspended by {0}.").format(
            frappe.session.user
        ))
        frappe.db.commit()

    @frappe.whitelist()
    def reactivate(self):
        """Reactivate a Suspended custodian."""
        if self.status != "Suspended":
            frappe.throw(_("Only a Suspended custodian can be reactivated."))
        self._set_status("Active")
        self.add_comment("Info", _("Custodian reactivated by {0}.").format(
            frappe.session.user
        ))
        frappe.db.commit()

    @frappe.whitelist()
    def close(self):
        """
        Close a custodian permanently.
        Requires total_outstanding == 0.
        """
        if self.status not in ("Active", "Suspended"):
            frappe.throw(_("Only an Active or Suspended custodian can be closed."))
        self.refresh_outstanding()
        if flt(self.total_outstanding) > 0:
            frappe.throw(
                _("Cannot close this custodian while there is an outstanding balance of {0}. "
                  "Please settle all open Custody Requests first.").format(
                    frappe.utils.fmt_money(self.total_outstanding)
                ),
                title=_("Outstanding Balance"),
            )
        self._set_status("Closed")
        self.add_comment("Info", _("Custodian closed by {0}.").format(
            frappe.session.user
        ))
        frappe.db.commit()

    @frappe.whitelist()
    def change_limit(self, new_limit):
        """Change the custody limit and record the action in the timeline."""
        new_limit = flt(new_limit)
        old_limit = flt(self.custody_limit)
        if new_limit < 0:
            frappe.throw(_("Custody limit cannot be negative."))
        self.db_set("custody_limit", new_limit)
        self.add_comment(
            "Info",
            _("Custody limit changed from {0} to {1} by {2}").format(
                frappe.utils.fmt_money(old_limit),
                frappe.utils.fmt_money(new_limit),
                frappe.session.user,
            ),
        )
        frappe.msgprint(
            _("Custody limit updated to {0}").format(frappe.utils.fmt_money(new_limit))
        )

    # ── Balance Refresh ───────────────────────────────────────────────────────

    @frappe.whitelist()
    def refresh_outstanding(self):
        """
        Recalculate all financial summary fields based on actual payments
        and settlements rather than request amounts.
        """
        # Total Disbursed: sum of all Payment Entries linked to this custodian
        disbursed = frappe.db.sql(
            """
            SELECT COALESCE(SUM(pe.paid_amount), 0)
            FROM `tabPayment Entry` pe
            WHERE pe.custom_custodian = %s
              AND pe.docstatus = 1
              AND pe.payment_type = 'Pay'
            """,
            (self.name,),
        )
        self.total_disbursed = flt(disbursed[0][0]) if disbursed else 0.0

        # Total Settled: sum of settled Accountant Custody totals
        settled = frappe.db.sql(
            """
            SELECT COALESCE(SUM(ac.total_amount), 0)
            FROM `tabAccountant Custody` ac
            WHERE ac.custodian = %s
              AND ac.docstatus = 1
              AND ac.status = 'Settled'
            """,
            (self.name,),
        )
        total_settled = flt(settled[0][0]) if settled else 0.0

        # Total Outstanding = Disbursed - Settled
        self.total_outstanding = flt(self.total_disbursed) - total_settled

        # Pending Requests: sum of advance_amount from Custody Requests in Unpaid or Paid status
        pending_req = frappe.db.sql(
            """
            SELECT COALESCE(SUM(cr.advance_amount), 0)
            FROM `tabCustody Request` cr
            WHERE cr.custodian = %s
              AND cr.docstatus = 1
              AND cr.status IN ('Unpaid', 'Paid')
            """,
            (self.name,),
        )
        self.pending_requests = flt(pending_req[0][0]) if pending_req else 0.0

        # Pending Settlements: sum of unsettled Accountant Custody totals
        pending_sett = frappe.db.sql(
            """
            SELECT COALESCE(SUM(ac.total_amount), 0)
            FROM `tabAccountant Custody` ac
            WHERE ac.custodian = %s
              AND ac.docstatus = 1
              AND ac.status NOT IN ('Settled', 'Cancelled')
            """,
            (self.name,),
        )
        self.pending_settlements = flt(pending_sett[0][0]) if pending_sett else 0.0

        self.db_update()

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _validate_unique_active_custodian(self):
        """Ensure only one submitted (non-closed) Custodian exists per employee."""
        if self.docstatus == 1:
            return  # Already submitted — skip on re-save
        existing = frappe.db.get_value(
            "Custodian",
            {
                "employee": self.employee,
                "docstatus": 1,
                "status": ["in", ["Active", "Suspended"]],
                "name": ["!=", self.name],
            },
            "name",
        )
        if existing:
            frappe.throw(
                _("An active Custodian record already exists for employee {0}: {1}. "
                  "Please close the existing record before creating a new one.").format(
                    self.employee_name or self.employee, existing
                ),
                title=_("Duplicate Custodian"),
            )

    def _validate_supplier_assignment(self):
        """
        When single dummy supplier mode is OFF, dedicated_supplier is mandatory
        on submit.
        """
        use_single = frappe.db.get_single_value(
            "Treasury Settings", "use_single_dummy_supplier"
        )
        if not use_single and self.docstatus == 0 and not self.dedicated_supplier:
            # Allow saving draft without supplier; enforce on submit
            pass

    def _validate_no_open_transactions(self):
        """Prevent cancellation if there are linked submitted documents."""
        open_requests = frappe.db.count(
            "Custody Request",
            {"custodian": self.name, "docstatus": 1},
        )
        if open_requests:
            frappe.throw(
                _("Cannot cancel this Custodian because there are {0} submitted "
                  "Custody Request(s) linked to it. Please cancel those first.").format(
                    open_requests
                ),
                title=_("Linked Transactions Exist"),
            )

    def _create_custody_account(self):
        """
        Auto-create a child account under the Custody Parent Account
        configured in Treasury Settings.
        """
        settings = frappe.get_single("Treasury Settings")
        parent_account = settings.custody_parent_account

        if not parent_account:
            frappe.throw(
                _("Custody Parent Account is not configured in Treasury Settings. "
                  "Please configure it before submitting a Custodian."),
                title=_("Configuration Missing"),
            )

        # Validate dedicated supplier if not using single dummy supplier
        if not settings.use_single_dummy_supplier and not self.dedicated_supplier:
            frappe.throw(
                _("Dedicated Supplier is required for this custodian because "
                  "'Use Single Dummy Supplier' is disabled in Treasury Settings."),
                title=_("Missing Supplier"),
            )

        # Build account name
        account_name = "{0} - Custody".format(
            self.employee_name or self.employee
        )

        # Check if account already exists (e.g., re-submit after cancel)
        parent_account_doc = frappe.get_doc("Account", parent_account)
        company = self.company or parent_account_doc.company

        existing = frappe.db.get_value(
            "Account",
            {
                "account_name": account_name,
                "company": company,
                "parent_account": parent_account,
            },
            "name",
        )

        if existing:
            self.custody_account = existing
            self.db_set("custody_account", existing, notify=True)
            return

        # Create the account
        account = frappe.new_doc("Account")
        account.account_name = account_name
        account.parent_account = parent_account
        account.company = company
        account.account_type = "Receivable"
        account.is_group = 0
        account.flags.ignore_permissions = True
        account.insert()

        self.custody_account = account.name
        self.db_set("custody_account", account.name, notify=True)

        frappe.logger().info(
            f"Created custody account '{account.name}' for custodian {self.name}"
        )

    def _set_status(self, new_status):
        """Update status field directly in the database."""
        self.status = new_status
        self.db_set("status", new_status, notify=True)
