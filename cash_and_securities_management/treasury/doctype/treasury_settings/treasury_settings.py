"""
Treasury Settings controller.
Singleton document — one record per site.

accounting_mode controls how GL accounts are structured:
  Consolidated (Party-Based) — all custodians share the group accounts;
                                transactions are isolated by the Custodian Party.
  Individual (Account-Based) — each custodian gets dedicated leaf accounts
                                created automatically on Custodian submit.

Account groups (custody_advance_group, custodian_payable_group) are
auto-created by setup.py on after_install / after_migrate — no manual
action is required from the user.
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
		Both account groups are required in Individual mode.
		In Consolidated mode they are optional but must be group accounts if set.
		"""
		mode = self.accounting_mode or CONSOLIDATED

		if mode == INDIVIDUAL:
			for fieldname, label in [
				("custody_advance_group", _("Custody Advance Account Group")),
				("custodian_payable_group", _("Custodian Payable Account Group")),
			]:
				if not self.get(fieldname):
					frappe.throw(
						_("{0} is required when Accounting Mode is 'Individual (Account-Based)'.").format(
							label
						),
						title=_("Missing Account Group"),
					)

		for fieldname, label in [
			("custody_advance_group", _("Custody Advance Account Group")),
			("custodian_payable_group", _("Custodian Payable Account Group")),
		]:
			account = self.get(fieldname)
			if account:
				is_group = frappe.db.get_value("Account", account, "is_group")
				if not is_group:
					frappe.msgprint(
						_("{0} should be a Group account so that per-custodian "
						  "sub-accounts can be created under it.").format(label),
						indicator="orange",
						alert=True,
					)
