"""
Treasury Settings controller.
Singleton document — one record per site.

accounting_mode controls how GL accounts are structured:
  Consolidated (Party-Based) — all custodians share the group account;
                                transactions are isolated by the Custodian Party.
  Individual (Account-Based) — each custodian gets a dedicated leaf account
                                created automatically on Custodian submit.

Single-Account Model (v4):
  Each custodian has ONE Receivable custody_account.
  custody_advance_group is the parent group under which per-custodian accounts
  are created.  No separate payable group is needed.
"""
import frappe
from frappe import _
from frappe.model.document import Document

CONSOLIDATED = "Consolidated (Party-Based)"
INDIVIDUAL = "Individual (Account-Based)"


class TreasurySettings(Document):
	def validate(self):
		self._validate_sub_ledger_groups()

	# ── Validation ────────────────────────────────────────────────────────────

	def _validate_sub_ledger_groups(self):
		"""
		custody_advance_group is required in Individual mode.
		In Consolidated mode it is optional but must be a group account if set.
		"""
		mode = self.accounting_mode or CONSOLIDATED

		if mode == INDIVIDUAL:
			if not self.get("custody_advance_group"):
				frappe.throw(
					_("Custody Account Group is required when Accounting Mode is "
					  "'Individual (Account-Based)'."),
					title=_("Missing Account Group"),
				)

		account = self.get("custody_advance_group")
		if account:
			is_group = frappe.db.get_value("Account", account, "is_group")
			if not is_group:
				frappe.msgprint(
					_("Custody Account Group should be a Group account so that "
					  "per-custodian sub-accounts can be created under it."),
					indicator="orange",
					alert=True,
				)
