import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate


class TreasuryCashJournal(Document):
	"""
	SAP FBCJ-style daily cash journal for a Treasury Station.

	Lifecycle:
	  Draft   → teller enters rows, KPIs update dynamically
	  Posted  → Post Journal button loops rows and creates Payment Entries
	  Closed  → end-of-day denomination verified, station balance updated
	"""

	# ─── Validate ────────────────────────────────────────────────────────────────

	def validate(self):
		self._fetch_opening_balance()
		self._recalculate_totals()
		self._recalculate_variance()

	def _fetch_opening_balance(self):
		"""
		Pull the opening balance from the station's current_balance field.
		Only set it when creating a new journal (don't overwrite on re-save).
		"""
		if not self.opening_balance:
			self.opening_balance = flt(
				frappe.db.get_value("Treasury Station", self.treasury_station, "current_balance")
			)

	def _recalculate_totals(self):
		total_in = 0.0
		total_out = 0.0
		for line in self.journal_lines:
			if line.direction == "Inbound":
				total_in += flt(line.amount)
			elif line.direction in ("Outbound", "Bank Transfer"):
				total_out += flt(line.amount)
		self.total_inflows = total_in
		self.total_outflows = total_out
		self.expected_balance = flt(self.opening_balance) + total_in - total_out

	def _recalculate_variance(self):
		if self.actual_balance is not None:
			self.variance = flt(self.actual_balance) - flt(self.expected_balance)

	# ─── On Submit ───────────────────────────────────────────────────────────────

	def on_submit(self):
		"""
		Called when the user submits the journal from the standard ERPNext form.
		Delegates to the same post_journal_transactions engine used by the page.
		"""
		self.post_journal_transactions()

	# ─── Post Journal Engine ─────────────────────────────────────────────────────

	@frappe.whitelist()
	def post_journal_transactions(self):
		"""
		Loops through all journal_lines and maps each row to a native ERPNext
		Payment Entry based on direction and transaction_category.

		Uses a single database transaction: if any row fails, all are rolled back.
		Rows with is_posted=1 are skipped (idempotent re-run safety).
		"""
		if self.posting_status == "Posted":
			frappe.throw(_("This journal has already been posted."))

		station = frappe.get_doc("Treasury Station", self.treasury_station)
		vault_account = station.vault_account
		shortage_account = station.shortage_account

		errors = []

		for line in self.journal_lines:
			if line.is_posted:
				continue
			try:
				pe_name = self._process_line(line, vault_account)
				line.linked_document = pe_name
				line.is_posted = 1
				line.posting_error = ""
			except Exception as e:
				line.posting_error = str(e)
				errors.append(f"Row {line.idx}: {e}")

		# Post variance entry if needed
		if flt(self.variance) != 0 and shortage_account:
			try:
				self._post_variance_entry(vault_account, shortage_account)
			except Exception as e:
				errors.append(f"Variance entry: {e}")

		self.posting_status = "Posted" if not errors else "Draft"
		self.db_update()

		# Update station balance
		if not errors:
			frappe.db.set_value("Treasury Station", self.treasury_station, {
				"current_balance": flt(self.expected_balance),
				"last_closing_date": self.posting_date,
			})

		if errors:
			frappe.throw(
				_("Journal posted with errors. The following lines failed:\n\n{0}").format(
					"\n".join(errors)
				)
			)

		frappe.msgprint(
			_("Journal {0} posted successfully. {1} transaction(s) created.").format(
				self.name,
				sum(1 for l in self.journal_lines if l.is_posted)
			),
			indicator="green",
		)

	def _process_line(self, line, vault_account):
		"""
		Fork logic: maps a single journal line to a Payment Entry.
		Returns the name of the created PE.
		"""
		pe = frappe.new_doc("Payment Entry")
		pe.posting_date = self.posting_date
		pe.company = self.company

		# ── FORK 1: Inbound — Customer cash receipt ──────────────────────────────
		if line.direction == "Inbound" and line.transaction_category == "Invoice Payment":
			pe.payment_type = "Receive"
			pe.party_type = line.party_type   # Customer
			pe.party = line.party
			pe.paid_to = vault_account
			pe.received_amount = flt(line.amount)
			pe.paid_amount = flt(line.amount)
			if line.reference_name:
				pe.append("references", {
					"reference_doctype": line.reference_doctype,
					"reference_name": line.reference_name,
					"allocated_amount": flt(line.amount),
				})

		# ── FORK 2: Inbound — Direct receipt (no invoice) ────────────────────────
		elif line.direction == "Inbound":
			pe.payment_type = "Receive"
			pe.party_type = line.party_type
			pe.party = line.party
			pe.paid_to = vault_account
			pe.received_amount = flt(line.amount)
			pe.paid_amount = flt(line.amount)

		# ── FORK 3: Outbound — Supplier/Custodian payment ────────────────────────
		elif line.direction == "Outbound":
			pe.payment_type = "Pay"
			pe.party_type = line.party_type   # Supplier or Custodian
			pe.party = line.party
			pe.paid_from = vault_account
			pe.paid_amount = flt(line.amount)
			pe.received_amount = flt(line.amount)
			if line.reference_name:
				pe.append("references", {
					"reference_doctype": line.reference_doctype,
					"reference_name": line.reference_name,
					"allocated_amount": flt(line.amount),
				})

		# ── FORK 4: Bank Transfer — Vault ↔ Bank ─────────────────────────────────
		elif line.direction == "Bank Transfer":
			pe.payment_type = "Internal Transfer"
			if line.transaction_category == "Bank Liquidity":
				# Bank Withdrawal → Fund Safe (Bank → Vault)
				pe.paid_from = line.party   # Bank GL Account
				pe.paid_to = vault_account
			else:
				# Bank Deposit → Drop Cash (Vault → Bank)
				pe.paid_from = vault_account
				pe.paid_to = line.party
			pe.paid_amount = flt(line.amount)
			pe.received_amount = flt(line.amount)

		else:
			frappe.throw(_("Unknown direction '{0}' on row {1}.").format(line.direction, line.idx))

		pe.remarks = line.narration or f"Treasury Cash Journal {self.name} — Row {line.idx}"
		pe.custom_source_document_type = "Treasury Cash Journal"
		pe.flags.ignore_permissions = True
		pe.flags.ignore_mandatory = True
		pe.insert()
		pe.submit()
		return pe.name

	def _post_variance_entry(self, vault_account, shortage_account):
		"""
		Creates a Journal Entry to record cash shortage (debit shortage account)
		or overage (credit shortage account).
		"""
		variance = flt(self.variance)
		je = frappe.new_doc("Journal Entry")
		je.posting_date = self.posting_date
		je.company = self.company
		je.voucher_type = "Journal Entry"
		je.user_remark = (
			self.variance_narration
			or f"Cash variance for Treasury Journal {self.name}"
		)

		if variance < 0:
			# Shortage: vault is short → debit shortage account, credit vault
			je.append("accounts", {
				"account": shortage_account,
				"debit_in_account_currency": abs(variance),
				"credit_in_account_currency": 0,
			})
			je.append("accounts", {
				"account": vault_account,
				"debit_in_account_currency": 0,
				"credit_in_account_currency": abs(variance),
			})
		else:
			# Overage: vault has extra → debit vault, credit shortage account
			je.append("accounts", {
				"account": vault_account,
				"debit_in_account_currency": variance,
				"credit_in_account_currency": 0,
			})
			je.append("accounts", {
				"account": shortage_account,
				"debit_in_account_currency": 0,
				"credit_in_account_currency": variance,
			})

		je.flags.ignore_permissions = True
		je.insert()
		je.submit()
		return je.name
