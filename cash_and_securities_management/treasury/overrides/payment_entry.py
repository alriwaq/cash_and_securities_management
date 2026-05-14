import frappe
from frappe import _

from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry


class CustodyPaymentEntry(PaymentEntry):
	"""
	Override Payment Entry for custody settlement transactions.

	GL balance analysis for Advance Deduction (Internal Transfer):
	  Correct GL:
	    DR  payable_account  (Liability — clears the PI payable)
	    CR  advance_account  (Asset — reduces the custodian advance)

	  ERPNext's build_gl_map() calls:
	    1. add_party_gl_entries()  → DR party_account (= paid_to = payable_account)
	    2. add_bank_gl_entries()   → CR paid_from (advance_account)
	                                  DR paid_to  (payable_account)  ← DUPLICATE!

	  Result: payable_account debited TWICE → debit/credit imbalance.

	Fix: override add_party_gl_entries() to skip for custody Internal Transfer PEs.
	The bank GL entries from add_bank_gl_entries() are correct and sufficient.
	"""

	# ── helpers ──────────────────────────────────────────────────────────────

	def _is_custody_mode(self):
		"""Return True for any PE created by the custody module."""
		source = self.get("custom_source_document_type") or ""
		return (
			source in ("Custody", "Custody Settlement")
			or bool(self.get("custom_accountant_custody"))
		)

	# ── GL building overrides ─────────────────────────────────────────────────

	def setup_party_account_field(self):
		"""
		For custody Internal Transfer PEs, do NOT set party_account.
		We skip add_party_gl_entries() entirely (see below), so party_account
		must remain None to avoid ERPNext attempting to create a party GL entry.
		For all other PEs, use the standard logic.
		"""
		if self._is_custody_mode() and self.payment_type == "Internal Transfer":
			# Clear party_account — we don't want add_party_gl_entries() to fire
			self.party_account = None
			self.party_account_currency = None
			self.party_account_field = None
		else:
			super().setup_party_account_field()

	def add_party_gl_entries(self, gl_entries):
		"""
		Skip party GL entries for custody Internal Transfer PEs.

		For custody advance deduction:
		  - add_bank_gl_entries() already creates:
		      CR advance_account  (paid_from)
		      DR payable_account  (paid_to)
		  - add_party_gl_entries() would create an ADDITIONAL:
		      DR payable_account  (party_account = paid_to)
		  → This doubles the debit on payable_account → imbalance.

		Skipping add_party_gl_entries() gives the correct balanced GL:
		  DR payable_account  (from add_bank_gl_entries paid_to entry)
		  CR advance_account  (from add_bank_gl_entries paid_from entry)
		"""
		if self._is_custody_mode() and self.payment_type == "Internal Transfer":
			return  # skip — bank GL entries are sufficient
		super().add_party_gl_entries(gl_entries)

	# ── validation overrides ──────────────────────────────────────────────────

	def before_validate(self):
		if self._is_custody_mode():
			self.flags.ignore_mandatory = True
			self.flags.ignore_validate_update_after_submit = True

	def validate(self):
		"""
		For custody PEs, bypass ERPNext's strict party-type / account-type
		validation before calling the standard validate chain.
		"""
		if self._is_custody_mode():
			# Ensure party fields are always set for custody PEs
			if not self.get("party_type"):
				self.party_type = "Custodian"
			if not self.get("party") and self.get("custom_custodian"):
				self.party = self.custom_custodian
			# Ensure account currencies are set (prevents currency mismatch errors)
			if self.get("paid_from") and not self.get("paid_from_account_currency"):
				self.paid_from_account_currency = (
					frappe.get_cached_value("Account", self.paid_from, "account_currency")
					or frappe.db.get_value("Company", self.company, "default_currency")
				)
			if self.get("paid_to") and not self.get("paid_to_account_currency"):
				self.paid_to_account_currency = (
					frappe.get_cached_value("Account", self.paid_to, "account_currency")
					or frappe.db.get_value("Company", self.company, "default_currency")
				)
		super().validate()

	def set_missing_values(self):
		"""
		Preserve custody accounts, party, and references for Internal Transfer mode.

		ERPNext's standard set_missing_values() for payment_type='Internal Transfer'
		clears paid_from, paid_to, party, and references — replacing them with the
		company's default accounts. For custody settlement PEs we must preserve the
		custodian advance account (paid_from) and payable account (paid_to) that were
		explicitly set by create_settlement().
		"""
		if not self._is_custody_mode() or self.payment_type != "Internal Transfer":
			super().set_missing_values()
			return

		# Snapshot all fields we need to preserve before super() overwrites them
		preserved = {
			"paid_from":                  self.get("paid_from"),
			"paid_to":                    self.get("paid_to"),
			"paid_from_account_currency": self.get("paid_from_account_currency"),
			"paid_to_account_currency":   self.get("paid_to_account_currency"),
			"party_type":                 self.get("party_type"),
			"party":                      self.get("party"),
		}
		preserved_references = [
			{
				"reference_doctype":         row.get("reference_doctype"),
				"reference_name":            row.get("reference_name"),
				"due_date":                  row.get("due_date"),
				"bill_no":                   row.get("bill_no"),
				"payment_term":              row.get("payment_term"),
				"payment_term_outstanding":  row.get("payment_term_outstanding"),
				"account":                   row.get("account"),
				"account_type":              row.get("account_type"),
				"payment_type":              row.get("payment_type"),
				"reconcile_effect_on":       row.get("reconcile_effect_on"),
				"total_amount":              row.get("total_amount"),
				"outstanding_amount":        row.get("outstanding_amount"),
				"allocated_amount":          row.get("allocated_amount"),
				"exchange_rate":             row.get("exchange_rate"),
				"payment_request":           row.get("payment_request"),
			}
			for row in (self.get("references") or [])
		]

		super().set_missing_values()

		# Restore everything ERPNext may have overwritten
		for field, value in preserved.items():
			if value:
				setattr(self, field, value)

		if preserved_references and not self.get("references"):
			self.set("references", [])
			for ref in preserved_references:
				self.append("references", ref)

	def validate_party_accounts(self):
		"""Skip party-type/account-type matching check for custody PEs."""
		if self._is_custody_mode():
			return
		super().validate_party_accounts()

	def get_gl_dict(self, args, account_currency=None, item=None):
		"""
		Inject Custodian party into GL entries for Payable/Receivable accounts.

		For Internal Transfer PEs, ERPNext does not populate party_type/party on
		the individual GL dicts, causing GL-level validation to raise
		"Supplier is required against Payable account".  We intercept every GL
		dict and add the Custodian party when the account is Payable/Receivable.
		"""
		gl_dict = super().get_gl_dict(args, account_currency=account_currency, item=item)

		if self._is_custody_mode() and gl_dict:
			account = gl_dict.get("account")
			if account and not gl_dict.get("party_type"):
				account_type = frappe.get_cached_value("Account", account, "account_type")
				if account_type in ("Payable", "Receivable"):
					gl_dict["party_type"] = "Custodian"
					gl_dict["party"] = self.get("custom_custodian") or self.party

		return gl_dict
