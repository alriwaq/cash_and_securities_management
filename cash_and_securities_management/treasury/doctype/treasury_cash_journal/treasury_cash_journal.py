import frappe
from frappe import _
from frappe.utils import flt, nowdate


class TreasuryCashJournal(Document):
	"""
	SAP FBCJ-style daily cash journal for a Treasury Station.

	Lifecycle:
	  Draft          → teller enters rows via cockpit, KPIs update dynamically
	  Pending Review → cockpit "Post Journal" pressed; accountant reviews Dr/Cr lines
	  Closed         → accountant submits the form; GL entries created; vault day closed
	"""

	# ─── Hooks ───────────────────────────────────────────────────────────────────

	def before_insert(self):
		"""Block creation of a second TCJ for the same station+date."""
		self._assert_no_duplicate_journal()

	def validate(self):
		self._fetch_opening_balance()
		self._recalculate_totals()
		self._recalculate_variance()

	# ─── Guards ──────────────────────────────────────────────────────────────────

	def _assert_no_duplicate_journal(self):
		"""
		Ensure only ONE Treasury Cash Journal exists per station per day.
		Any status (Draft, Pending Review, Closed) counts.
		"""
		existing = frappe.db.get_value(
			"Treasury Cash Journal",
			{
				"treasury_station": self.treasury_station,
				"posting_date": self.posting_date,
				"name": ["!=", self.name or ""],
			},
			"name",
		)
		if existing:
			frappe.throw(
				_(
					"يوجد بالفعل يومية خزينة لهذه المحطة بتاريخ {date}: <b>{name}</b>.\n"
					"لا يُسمح بإنشاء أكثر من يومية واحدة لكل محطة في اليوم الواحد.\n\n"
					"A Treasury Cash Journal already exists for station '{station}' "
					"on {date}: {name}. Only one journal per station per day is allowed."
				).format(
					date=self.posting_date,
					name=existing,
					station=self.treasury_station,
				),
				title=_("يومية مكررة / Duplicate Journal"),
			)

	# ─── Balance Calculations ─────────────────────────────────────────────────

	def _fetch_opening_balance(self):
		"""
		Opening balance rules:
		  - New doc: always take station's current_balance at creation time.
		  - Existing doc: keep the recorded value — never overwrite it.
		  - Zero-balance vault: use explicit None check (not falsy) so that
		    a legitimate 0.0 opening balance is preserved.
		"""
		if self.is_new() or self.opening_balance is None:
			self.opening_balance = flt(
				frappe.db.get_value("Treasury Station", self.treasury_station, "current_balance")
			)

	def _recalculate_totals(self):
		"""
		Recompute total_inflows, total_outflows, and expected_balance from journal lines.
		Bank Transfer lines are excluded (internal moves, no net cash change).
		"""
		total_in = 0.0
		total_out = 0.0
		for line in self.journal_lines:
			amt = flt(line.amount)
			if line.direction == "Inbound":
				total_in += amt
			elif line.direction == "Outbound":
				total_out += amt
			# Bank Transfer: skip — does not change vault cash balance
		self.total_inflows = total_in
		self.total_outflows = total_out
		self.expected_balance = flt(self.opening_balance) + total_in - total_out

	def _recalculate_variance(self):
		if self.actual_balance is not None:
			self.variance = flt(self.actual_balance) - flt(self.expected_balance)

	# ─── On Submit ───────────────────────────────────────────────────────────────

	def on_submit(self):
		"""
		Triggered when the accountant clicks Submit on the TCJ form.
		Only allowed when status is 'Pending Review' or 'Draft'.
		post_journal_transactions() is NOT whitelisted to prevent API bypass.
		"""
		if self.posting_status not in ("Pending Review", "Draft"):
			frappe.throw(
				_("Journal can only be submitted when status is 'Pending Review'. Current status: {0}").format(
					self.posting_status
				)
			)
		self._post_journal_transactions_internal()

	# ─── Post Journal Engine ─────────────────────────────────────────────────────

	def _post_journal_transactions_internal(self):
		"""
		Internal posting engine — called only from on_submit.
		Uses savepoints per line so that partial failures don't roll back
		successfully committed lines.

		On full success:
		  - Sets posting_status = 'Closed'
		  - Updates station: current_balance, last_closing_date, status = 'Closed'
		On partial failure:
		  - Committed lines remain committed (savepoint pattern)
		  - Failed lines carry posting_error
		  - posting_status stays 'Pending Review'
		  - Raises a summary error so the user can see what failed
		"""
		# Re-entry guard: covers both "Posted" (legacy) and "Closed"
		if self.posting_status in ("Posted", "Closed"):
			frappe.throw(_("This journal has already been posted/closed."))

		station = frappe.get_doc("Treasury Station", self.treasury_station)
		vault_account = station.vault_account
		shortage_account = station.shortage_account

		errors = []
		committed_count = 0

		for line in self.journal_lines:
			if line.is_posted:
				committed_count += 1
				continue

			savepoint = f"tcj_line_{line.idx}"
			frappe.db.savepoint(savepoint)
			try:
				pe_name = self._process_line(line, vault_account)
				line.linked_document = pe_name
				line.is_posted = 1
				line.posting_error = ""
				# Commit this line's state immediately so it survives a later throw
				frappe.db.sql(
					"""UPDATE `tabTreasury Journal Line`
					   SET is_posted=1, linked_document=%s, posting_error=''
					   WHERE name=%s""",
					(pe_name or "", line.name),
				)
				committed_count += 1
			except Exception as e:
				frappe.db.rollback(save_point=savepoint)
				line.posting_error = str(e)
				frappe.db.sql(
					"UPDATE `tabTreasury Journal Line` SET posting_error=%s WHERE name=%s",
					(str(e)[:500], line.name),
				)
				errors.append(f"Row {line.idx}: {e}")

		# Post variance entry if needed
		if flt(self.variance) != 0 and shortage_account:
			savepoint = "tcj_variance"
			frappe.db.savepoint(savepoint)
			try:
				self._post_variance_entry(vault_account, shortage_account)
			except Exception as e:
				frappe.db.rollback(save_point=savepoint)
				errors.append(f"Variance entry: {e}")

		if not errors:
			# Validate GL balance matches expected before closing
			try:
				station.validate_closing_balance(self.expected_balance)
			except frappe.ValidationError:
				raise
			except Exception:
				pass  # Non-fatal if GL check unavailable

			# Mark journal as Closed — set on self so Frappe's submit commit picks it up
			self.posting_status = "Closed"
			# Also write directly so it's visible even if Frappe's commit is delayed
			frappe.db.set_value("Treasury Cash Journal", self.name, "posting_status", "Closed")

			# Close the vault station — use atomic update to avoid race condition
			frappe.db.sql(
				"""UPDATE `tabTreasury Station`
				   SET current_balance=%s,
				       last_closing_date=%s,
				       status='Closed'
				   WHERE name=%s""",
				(flt(self.expected_balance), self.posting_date, self.treasury_station),
			)

			frappe.msgprint(
				_("Journal {0} posted successfully. {1} transaction(s) created. Vault day closed.").format(
					self.name,
					committed_count,
				),
				indicator="green",
			)
		else:
			# Partial failure: keep status as Pending Review
			self.posting_status = "Pending Review"
			frappe.db.set_value(
				"Treasury Cash Journal", self.name, "posting_status", "Pending Review"
			)
			# Surface warning (not throw) so committed lines are not rolled back
			frappe.msgprint(
				_("Journal posted with {0} error(s). Successfully committed: {1} line(s).\n\nFailed lines:\n{2}").format(
					len(errors),
					committed_count,
					"\n".join(errors),
				),
				indicator="orange",
				title=_("Partial Posting / ترحيل جزئي"),
			)

	# ─── Accounting Preview ───────────────────────────────────────────────────────

	@frappe.whitelist()
	def preview_accounting_lines(self):
		"""
		Returns a list of dicts describing the Dr/Cr impact of each journal line
		WITHOUT creating any GL entries. Used by the TCJ form review section.
		Note: account names for PE-based lines are display labels, not actual GL accounts.
		"""
		station = frappe.get_doc("Treasury Station", self.treasury_station)
		vault_account = station.vault_account
		preview = []

		for line in self.journal_lines:
			entry = self._preview_line(line, vault_account)
			if entry:
				preview.append(entry)

		# Variance line
		if flt(self.variance) != 0 and station.shortage_account:
			variance = flt(self.variance)
			if variance < 0:
				preview.append({
					"idx": "V",
					"direction": "Outbound",
					"category": _("Cash Shortage / عجز نقدي"),
					"party": "",
					"reference": "",
					"amount": abs(variance),
					"debit_account": station.shortage_account,
					"credit_account": vault_account,
					"narration": self.variance_narration or _("Cash variance"),
					"doc_type": "Journal Entry",
				})
			else:
				preview.append({
					"idx": "V",
					"direction": "Inbound",
					"category": _("Cash Overage / زيادة نقدية"),
					"party": "",
					"reference": "",
					"amount": variance,
					"debit_account": vault_account,
					"credit_account": station.shortage_account,
					"narration": self.variance_narration or _("Cash variance"),
					"doc_type": "Journal Entry",
				})

		return preview

	def _preview_line(self, line, vault_account):
		"""
		Returns a display-only dict for the preview panel.
		Account names for PE lines are human-readable labels, not actual GL accounts.
		"""
		amount = flt(line.amount)
		party_label = line.party or ""
		ref_label = line.reference_name or ""
		cost_center = getattr(line, "cost_center", "") or ""
		project = getattr(line, "project", "") or ""

		if line.transaction_category == "Direct Expense":
			expense_account = getattr(line, "expense_account", None)
			if not expense_account:
				return None
			return {
				"idx": line.idx,
				"direction": line.direction,
				"category": "مصروف مباشر / Direct Expense",
				"party": party_label,
				"reference": ref_label,
				"amount": amount,
				"debit_account": expense_account,
				"credit_account": vault_account,
				"narration": line.narration or "",
				"doc_type": "Journal Entry",
				"cost_center": cost_center,
				"project": project,
			}

		if line.direction == "Inbound":
			return {
				"idx": line.idx,
				"direction": line.direction,
				"category": line.transaction_category,
				"party": party_label,
				"reference": ref_label,
				"amount": amount,
				"debit_account": vault_account,
				"credit_account": f"[Receivable: {party_label}]",  # display label only
				"narration": line.narration or "",
				"doc_type": "Payment Entry",
				"cost_center": cost_center,
				"project": project,
			}

		if line.direction == "Outbound":
			return {
				"idx": line.idx,
				"direction": line.direction,
				"category": line.transaction_category,
				"party": party_label,
				"reference": ref_label,
				"amount": amount,
				"debit_account": f"[Payable: {party_label}]",  # display label only
				"credit_account": vault_account,
				"narration": line.narration or "",
				"doc_type": "Payment Entry",
				"cost_center": cost_center,
				"project": project,
			}

		return None

	# ─── Process Line ─────────────────────────────────────────────────────────────

	def _process_line(self, line, vault_account):
		"""
		Process a single journal line:
		  1. VPI-linked source PE → submit that PE and advance workflow.
		  2. Direct Expense → create Journal Entry.
		  3. Advance Allocation → custody settlement.
		  4. Manual entry → create new Payment Entry.
		Returns the name of the created/submitted document.
		"""
		# Path 1: VPI-linked source Payment Entry
		source_pe_name = self._resolve_source_pe(line)
		if source_pe_name:
			return self._submit_and_advance_pe(source_pe_name, line)

		# Path 2: Direct Expense → Journal Entry
		if line.transaction_category == "Direct Expense":
			return self._create_direct_expense_je(line, vault_account)

		# Path 3: Custody Advance Allocation
		if (
			line.direction == "Outbound"
			and line.transaction_category == "Advance Allocation"
			and line.reference_doctype == "Accountant Custody"
			and line.reference_name
		):
			ac_doc = frappe.get_doc("Accountant Custody", line.reference_name)
			return ac_doc.create_settlement(
				advance_amount_allocated=flt(line.amount),
				direct_payment_amount=0,
				settlement_notes=line.narration or f"Settlement from Treasury Cash Journal {self.name}",
			)

		# Path 4: Manual entry → new Payment Entry
		return self._create_new_pe(line, vault_account)

	def _resolve_source_pe(self, line):
		"""
		Resolve the original Payment Entry linked to this journal line via VPI.
		Returns the PE name string, or None if not found.
		"""
		# Direct: source_document field on the journal line itself
		if (
			getattr(line, "source_doctype", "") == "Payment Entry"
			and getattr(line, "source_document", "")
			and frappe.db.exists("Payment Entry", line.source_document)
		):
			return line.source_document

		# Via VPI: linked_document holds the VPI name
		vpi_name = getattr(line, "linked_document", "")
		if vpi_name and frappe.db.exists("Vault Pending Item", vpi_name):
			vpi_source_type, vpi_source_doc = frappe.db.get_value(
				"Vault Pending Item", vpi_name,
				["source_document_type", "source_document"]
			) or ("", "")
			if vpi_source_type == "Payment Entry" and vpi_source_doc:
				if frappe.db.exists("Payment Entry", vpi_source_doc):
					return vpi_source_doc

		return None

	def _submit_and_advance_pe(self, pe_name, line):
		"""
		Submit an existing draft Payment Entry (from vault workflow) and
		advance its workflow_state to 'Submitted to GL'.
		Idempotent: if already submitted, just advances the workflow state.
		"""
		pe = frappe.get_doc("Payment Entry", pe_name)

		if pe.docstatus == 0:  # Draft — submit it
			pe.flags.ignore_permissions = True
			pe.flags.ignore_mandatory = True
			pe.flags.submitted_by_tcj = True
			# Apply cost_center and project to PE accounts if available
			cost_center = getattr(line, "cost_center", "") or ""
			project = getattr(line, "project", "") or ""
			if cost_center or project:
				for acc_row in pe.get("accounts", []):
					if cost_center:
						acc_row.cost_center = cost_center
					if project:
						acc_row.project = project
			pe.submit()
		elif pe.docstatus == 2:  # Cancelled
			frappe.throw(
				_("Payment Entry {0} linked to row {1} has been cancelled and cannot be posted.").format(
					pe_name, line.idx
				)
			)
		# docstatus == 1 → already submitted, just advance workflow

		# Advance workflow state to 'Submitted to GL'
		try:
			frappe.db.set_value("Payment Entry", pe_name, "workflow_state", "Submitted to GL")
		except Exception as e:
			# Surface as warning — not silent swallow
			frappe.msgprint(
				_("Warning: Could not advance workflow state for Payment Entry {0}: {1}").format(pe_name, e),
				indicator="orange",
			)

		# Update the VPI linked to this line
		vpi_name = getattr(line, "linked_document", "")
		if vpi_name and frappe.db.exists("Vault Pending Item", vpi_name):
			try:
				frappe.db.set_value("Vault Pending Item", vpi_name, "linked_journal", self.name)
			except Exception:
				pass

		return pe_name

	def _create_new_pe(self, line, vault_account):
		"""
		Create and submit a brand-new Payment Entry for manual cockpit entries.
		Properly sets paid_from / paid_to on both Inbound and Outbound.
		Applies cost_center and project to account rows.
		"""
		pe = frappe.new_doc("Payment Entry")
		pe.posting_date = self.posting_date
		pe.company = self.company
		pe.mode_of_payment = "Cash"

		cost_center = getattr(line, "cost_center", "") or ""
		project = getattr(line, "project", "") or ""

		if line.direction == "Inbound":
			pe.payment_type = "Receive"
			pe.party_type = line.party_type or "Customer"
			pe.party = line.party
			# paid_from = source (AR/receivable), paid_to = vault cash account
			pe.paid_to = vault_account
			pe.paid_to_account_currency = frappe.db.get_value("Account", vault_account, "account_currency") or "SAR"
			# paid_from: use party's receivable account or default AR
			pe.paid_from = self._get_receivable_account(pe.party_type, pe.company)
			pe.paid_from_account_currency = frappe.db.get_value("Account", pe.paid_from, "account_currency") or "SAR"
			pe.received_amount = flt(line.amount)
			pe.paid_amount = flt(line.amount)
			if line.reference_name:
				pe.append("references", {
					"reference_doctype": line.reference_doctype or "Sales Invoice",
					"reference_name": line.reference_name,
					"allocated_amount": flt(line.amount),
				})

		elif line.direction == "Outbound":
			pe.payment_type = "Pay"
			pe.party_type = line.party_type or "Supplier"
			pe.party = line.party
			# paid_from = vault cash account, paid_to = party's payable account
			pe.paid_from = vault_account
			pe.paid_from_account_currency = frappe.db.get_value("Account", vault_account, "account_currency") or "SAR"
			pe.paid_to = self._get_payable_account(pe.party_type, pe.company)
			pe.paid_to_account_currency = frappe.db.get_value("Account", pe.paid_to, "account_currency") or "SAR"
			pe.paid_amount = flt(line.amount)
			pe.received_amount = flt(line.amount)
			if line.reference_name:
				pe.append("references", {
					"reference_doctype": line.reference_doctype or "Purchase Invoice",
					"reference_name": line.reference_name,
					"allocated_amount": flt(line.amount),
				})
		else:
			frappe.throw(_("Unknown direction '{0}' on row {1}.").format(line.direction, line.idx))

		pe.remarks = line.narration or f"Treasury Cash Journal {self.name} — Row {line.idx}"
		pe.custom_source_document_type = "Treasury Cash Journal"

		# Apply cost_center and project to all account rows
		if cost_center or project:
			for acc_row in pe.get("accounts", []):
				if cost_center:
					acc_row.cost_center = cost_center
				if project:
					acc_row.project = project

		pe.flags.ignore_permissions = True
		pe.flags.ignore_mandatory = True
		pe.flags.submitted_by_tcj = True
		pe.insert()

		# Apply cost_center/project after insert (accounts rows are created on insert)
		if cost_center or project:
			frappe.db.sql(
				"""UPDATE `tabPayment Entry Account`
				   SET cost_center=%s, project=%s
				   WHERE parent=%s""",
				(cost_center or None, project or None, pe.name),
			)

		pe.submit()
		return pe.name

	def _get_receivable_account(self, party_type, company):
		"""Return the default receivable/payable account for the party type."""
		if party_type == "Customer":
			return frappe.db.get_value(
				"Company", company, "default_receivable_account"
			) or frappe.db.get_value(
				"Account",
				{"account_type": "Receivable", "company": company, "is_group": 0},
				"name",
			)
		if party_type == "Employee":
			# Use custody advance group if available, else AR
			from cash_and_securities_management.treasury.doctype.treasury_settings.treasury_settings import get_settings
			settings = get_settings()
			return settings.custody_advance_group or self._get_receivable_account("Customer", company)
		return frappe.db.get_value(
			"Account",
			{"account_type": "Receivable", "company": company, "is_group": 0},
			"name",
		)

	def _get_payable_account(self, party_type, company):
		"""Return the default payable account for the party type."""
		if party_type == "Supplier":
			return frappe.db.get_value(
				"Company", company, "default_payable_account"
			) or frappe.db.get_value(
				"Account",
				{"account_type": "Payable", "company": company, "is_group": 0},
				"name",
			)
		if party_type == "Employee":
			from cash_and_securities_management.treasury.doctype.treasury_settings.treasury_settings import get_settings
			settings = get_settings()
			return settings.custodian_payable_group or self._get_payable_account("Supplier", company)
		return frappe.db.get_value(
			"Account",
			{"account_type": "Payable", "company": company, "is_group": 0},
			"name",
		)

	def _create_direct_expense_je(self, line, vault_account):
		"""
		Create and submit a Journal Entry for a Direct Expense line.
		Applies cost_center and project to both account rows.
		"""
		expense_account = getattr(line, "expense_account", None)
		if not expense_account:
			frappe.throw(_("Direct Expense on row {0} requires an Expense Account.").format(line.idx))

		account_meta = frappe.db.get_value(
			"Account", expense_account, ["root_type", "is_group"], as_dict=True,
		)
		if not account_meta:
			frappe.throw(_("Expense account '{0}' does not exist.").format(expense_account))
		if account_meta.is_group:
			frappe.throw(_("Expense account '{0}' must be a ledger account.").format(expense_account))
		if account_meta.root_type != "Expense":
			frappe.throw(_("Account '{0}' must be an Expense account.").format(expense_account))

		cost_center = getattr(line, "cost_center", "") or ""
		project = getattr(line, "project", "") or ""

		je = frappe.new_doc("Journal Entry")
		je.posting_date = self.posting_date
		je.company = self.company
		je.voucher_type = "Journal Entry"
		je.user_remark = line.narration or f"Direct expense from Treasury Cash Journal {self.name}"

		je.append("accounts", {
			"account": expense_account,
			"debit_in_account_currency": flt(line.amount),
			"credit_in_account_currency": 0,
			"cost_center": cost_center or None,
			"project": project or None,
			"user_remark": line.narration,
		})
		je.append("accounts", {
			"account": vault_account,
			"debit_in_account_currency": 0,
			"credit_in_account_currency": flt(line.amount),
			"cost_center": cost_center or None,
			"project": project or None,
			"user_remark": line.narration,
		})

		je.flags.ignore_permissions = True
		je.insert()
		je.submit()
		return je.name

	def _post_variance_entry(self, vault_account, shortage_account):
		"""Create and submit a Journal Entry for cash variance (shortage/overage)."""
		variance = flt(self.variance)
		je = frappe.new_doc("Journal Entry")
		je.posting_date = self.posting_date
		je.company = self.company
		je.voucher_type = "Journal Entry"
		je.user_remark = (
			self.variance_narration or f"Cash variance for Treasury Journal {self.name}"
		)

		if variance < 0:
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
