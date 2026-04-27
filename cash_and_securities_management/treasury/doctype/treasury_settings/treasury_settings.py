"""
Treasury Settings controller.
Singleton document — one record per site.
"""
import frappe
from frappe import _
from frappe.model.document import Document


class TreasurySettings(Document):

    def validate(self):
        self._validate_supplier_mode()
        self._validate_parent_account()

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_supplier_mode(self):
        """If single dummy supplier mode is on, the supplier must be set."""
        if self.use_single_dummy_supplier and not self.default_cash_purchases_supplier:
            frappe.throw(
                _("Please set the Default Cash Purchases Supplier when "
                  "'Use Single Dummy Supplier' is enabled."),
                title=_("Missing Supplier"),
            )

    def _validate_parent_account(self):
        """Custody parent account must be set and should be a group account."""
        if not self.custody_parent_account:
            frappe.throw(
                _("Custody Parent Account is required."),
                title=_("Missing Account"),
            )
        is_group = frappe.db.get_value(
            "Account", self.custody_parent_account, "is_group"
        )
        if not is_group:
            frappe.msgprint(
                _("Custody Parent Account should be a Group account so that "
                  "per-custodian sub-accounts can be created under it."),
                indicator="orange",
                alert=True,
            )
