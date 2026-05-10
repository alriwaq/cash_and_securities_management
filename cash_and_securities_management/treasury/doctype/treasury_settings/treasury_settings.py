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
		self._validate_sub_ledger_groups()

	# ── Validation ────────────────────────────────────────────────────────────
	def _validate_supplier_mode(self):
		"""If single dummy supplier mode is on, the supplier must be set."""
		if self.use_single_dummy_supplier and not self.default_cash_purchases_supplier:
			frappe.throw(
				_("Please set the Default Cash Purchases Supplier when "
				  "'Use Single Dummy Supplier' is enabled."),
				title=_("Missing Supplier"),
			)

	def _validate_sub_ledger_groups(self):
		"""If sub-ledger groups are set, they must be group accounts."""
		for fieldname, label in [
			("default_advance_group", _("Default Advance Account Group")),
			("default_payable_group", _("Default Payable Account Group")),
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

	# ── Action: Create Account Groups ─────────────────────────────────────────
	@frappe.whitelist()
	def create_account_groups(self):
		"""
		Auto-create the two standard account groups required for custodian
		sub-ledgers if they do not already exist:
		  - 'Advances to Custodians' under Current Assets / Cash In Hand
		  - 'Custodian Payables' under Current Liabilities / Accounts Payable

		The created groups are then set as default_advance_group and
		default_payable_group on this settings document.
		"""
		company = frappe.defaults.get_global_default("company")
		if not company:
			frappe.throw(
				_("Please set a default Company in Global Defaults before creating account groups."),
				title=_("No Default Company"),
			)

		results = []

		# ── Advance group (Asset side) ─────────────────────────────────────
		advance_group_name = "Advances to Custodians"
		advance_parent = (
			self._find_account("Cash In Hand", company)
			or self._find_account("Current Assets", company)
		)
		if not advance_parent:
			frappe.throw(
				_("Could not find 'Cash In Hand' or 'Current Assets' account for company {0}. "
				  "Please set the Default Advance Account Group manually.").format(company),
				title=_("Account Not Found"),
			)

		advance_group = self._get_or_create_group_account(
			advance_group_name, advance_parent, company, "Asset"
		)
		self.default_advance_group = advance_group
		results.append(_("Advance group: {0}").format(advance_group))

		# ── Payable group (Liability side) ────────────────────────────────
		payable_group_name = "Custodian Payables"
		payable_parent = (
			self._find_account("Accounts Payable", company)
			or self._find_account("Current Liabilities", company)
		)
		if not payable_parent:
			frappe.throw(
				_("Could not find 'Accounts Payable' or 'Current Liabilities' account for company {0}. "
				  "Please set the Default Payable Account Group manually.").format(company),
				title=_("Account Not Found"),
			)

		payable_group = self._get_or_create_group_account(
			payable_group_name, payable_parent, company, "Payable"
		)
		self.default_payable_group = payable_group
		results.append(_("Payable group: {0}").format(payable_group))

		self.save(ignore_permissions=True)

		frappe.msgprint(
			_("Account groups ready:<br>{0}").format("<br>".join(results)),
			title=_("Sub-Ledger Groups Created"),
			indicator="green",
		)
		return results

	def _find_account(self, account_name_fragment, company):
		"""Find a group account by partial name match for a given company."""
		return frappe.db.get_value(
			"Account",
			{
				"account_name": ["like", f"%{account_name_fragment}%"],
				"company": company,
				"is_group": 1,
			},
			"name",
		)

	def _get_or_create_group_account(self, account_name, parent_account, company, root_type):
		"""
		Return the name of an existing group account matching account_name under
		parent_account, or create it if it does not exist.
		"""
		existing = frappe.db.get_value(
			"Account",
			{
				"account_name": account_name,
				"company": company,
				"parent_account": parent_account,
				"is_group": 1,
			},
			"name",
		)
		if existing:
			return existing

		account = frappe.new_doc("Account")
		account.account_name = account_name
		account.parent_account = parent_account
		account.company = company
		account.is_group = 1
		account.root_type = root_type
		account.report_type = "Balance Sheet"
		account.flags.ignore_permissions = True
		account.insert()
		frappe.logger().info(
			f"Created account group '{account.name}' under '{parent_account}'"
		)
		return account.name
