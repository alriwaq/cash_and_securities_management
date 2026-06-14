"""
GL Entry override — Custody account type support
=================================================

ERPNext's GLEntry.validate_account() hard-codes that only 'Receivable' and
'Payable' accounts may carry a party_type/party. This override extends that
check to also allow the dedicated 'Custody' account type.

Why 'Custody' instead of 'Receivable'/'Payable':
  The v5 single-account model uses ONE account per custodian (or one shared
  group account in Consolidated mode) for BOTH sides of every transaction:

    Advance disbursed  → DR custody_account  (balance rises  = employee owes)
    Invoice submitted  → CR custody_account  (balance falls  = self-settles)

  Using 'Receivable' would surface these accounts in standard AR aging reports
  and reconciliation tools (which filter on party_type = 'Customer').
  Using 'Payable' would surface them in AP reports (party_type = 'Supplier').
  'Custody' is a dedicated, neutral type that is invisible to both standard
  report filters yet still carries the party sub-ledger correctly.

Override strategy:
  When the account being validated has account_type = 'Custody' AND party_type
  is set, we temporarily clear party_type/party, delegate to ERPNext's original
  validate_account() (so all other checks — group account, company match, etc. —
  still run), then restore party_type/party.  This is the minimal, targeted
  bypass that keeps every other GL Entry validation intact.
"""

import frappe
from frappe import _

try:
    from erpnext.accounts.doctype.gl_entry.gl_entry import GLEntry as _ERPNextGLEntry
except ImportError:
    _ERPNextGLEntry = None


if _ERPNextGLEntry:
    class CustodyGLEntry(_ERPNextGLEntry):
        """
        Extended GL Entry that permits party_type/party on 'Custody' accounts.
        All other ERPNext validations are preserved unchanged.
        """

        def validate_account(self):
            """
            Allow 'Custody' account type to carry party_type/party entries.
            For all other account types, delegate entirely to ERPNext's original
            validate_account() so nothing else changes.
            """
            if self.party_type and self.account:
                account_type = frappe.db.get_cached_value(
                    "Account", self.account, "account_type"
                )
                if account_type == "Custody":
                    # Temporarily remove party so ERPNext's native check
                    # does not throw "Party Type and Party can only be set
                    # for Receivable / Payable account".
                    # All other checks in validate_account() (group account,
                    # company mismatch, frozen account, etc.) still run normally.
                    _party_type = self.party_type
                    _party      = self.party
                    self.party_type = None
                    self.party      = None
                    try:
                        super().validate_account()
                    finally:
                        # Always restore — even if super() throws for another reason
                        self.party_type = _party_type
                        self.party      = _party
                    return  # Custody account validated — no further action needed

            # Non-Custody account: run ERPNext's check unchanged
            super().validate_account()

else:
    # ERPNext not available (unit test / stub environment) — no-op class
    from frappe.model.document import Document as _FallbackBase

    class CustodyGLEntry(_FallbackBase):  # type: ignore[misc]
        pass
