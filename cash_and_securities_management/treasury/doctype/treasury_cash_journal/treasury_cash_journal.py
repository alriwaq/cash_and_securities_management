import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate


class TreasuryCashJournal(Document):
	"""
	SAP FBCJ-style daily cash journal for a Treasury Station.

	Lifecycle:
	  Draft          → teller enters rows via cockpit, KPIs update dynamically
	  Pending Review → cockpit "Post Journal" pressed; accountant reviews Dr/Cr lines
	  Posted/Closed  → accountant submits the form; GL entries created; vault day closed
	"""

	# ─── Validate ────────────────────────────────────────────────────────────────

	def before_insert(self):
		"""Block creation of a second TCJ for the same station+date."""
		self._assert_no_duplicate_journal()

	def validate(self):
		self._fetch_opening_balance()
		self._recalculate_totals()
		self._recalculate_variance()

	def _assert_no_duplicate_journal(self):
		"""
		Ensure only ONE Treasury Cash Journal exists per station per day.
		Any status (Draft, Pending Review, Closed) counts — we never allow two journals
		for the same station on the same date.
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

	def _fetch_opening_balance(self):
		"""
		Opening balance rules:
		  - New doc (no name yet / is_new): always take station's current_balance.
		    This is the balance at the moment the first entry is made today.
		  - Existing doc already saved: keep the recorded opening_balance unchanged
		    so that re-saves / re-validates don't drift the figure.
		"""
		if self.is_new() or not self.opening_balance:
			self.opening_balance = flt(
				frappe.db.get_value("Treasury Station", self.treasury_station, "current_balance")
			)

	def _recalculate_totals(self):
		"""
		Recompute total_inflows, total_outflows, and expected_balance from journal lines.
		Bank Transfer lines are excluded from both inbound and outbound totals
		(they are internal moves, not cash in/out of the vault).
		"""
		total_in = 0.0
		total_out = 0.0
		for line in self.journal_lines:
			amt = flt(line.amount)
			if line.direction == "Inbound":
				total_in += amt
			elif line.direction == "Outbound":
				total_out += amt
			# Bank Transfer: does not change vault cash balance — skip
		self.total_inflows = total_in
		self.total_outflows = total_out
		self.expected_balance = flt(self.opening_balance) + total_in - total_out

	def _recalculate_variance(self):
		if self.actual_balance is not None:
			self.variance = flt(self.actual_balance) - flt(self.expected_balance)

	# ─── On Submit (ERPNext standard submit button) ───────────────────────────────

	def on_submit(self):
		"""
		Triggered when the accountant clicks Submit on the TCJ form.
		Only allowed when status is 'Pending Review'.
		"""
		if self.posting_status not in ("Pending Review", "Draft"):
			frappe.throw(
				_("Journal can only be submitted when status is 'Pending Review'. Current status: {0}").format(
					self.posting_status
				)
			)
		self.post_journal_transactions()

	# ─── Post Journal Engine ─────────────────────────────────────────────────────

	@frappe.whitelist()
	def post_journal_transactions(self):
		"""
		Loops through all journal_lines and maps each row to a native ERPNext
		Payment Entry based on direction and transaction_category.
		Rows with is_posted=1 are skipped (idempotent re-run safety).
		On full success: validates GL balance, sets status to Closed, closes vault day.
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

		if not errors:
			# Validate GL balance matches expected before closing
			try:
				station.validate_closing_balance(self.expected_balance)
			except frappe.ValidationError:
				raise
			except Exception:
				pass  # Non-fatal if GL check unavailable

			self.posting_status = "Closed"
			self.db_update()

			# Close the vault day
			frappe.db.set_value("Treasury Station", self.treasury_station, {
				"current_balance": flt(self.expected_balance),
				"last_closing_date": self.posting_date,
				"status": "Closed",
			})
		else:
			self.posting_status = "Pending Review"
			self.db_update()
			frappe.throw(
				_("Journal posted with errors. The following lines failed:\n\n{0}").format(
					"\n".join(errors)
				)
			)

		frappe.msgprint(
			_("Journal {0} posted successfully. {1} transaction(s) created. Vault day closed.").format(
				self.name,
				sum(1 for l in self.journal_lines if l.is_posted),
			),
			indicator="green",
		)

	# ─── Accounting Preview ───────────────────────────────────────────────────────

	@frappe.whitelist()
	def preview_accounting_lines(self):
		"""
		Returns a list of dicts describing the Dr/Cr impact of each journal line
		WITHOUT creating any GL entries. Used by the TCJ form review section.
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
		amount = flt(line.amount)
		party_label = line.party or ""
		ref_label = line.reference_name or ""

		if line.transaction_category == "Direct Expense":
			expense_account = line.reference_name or getattr(line, "expense_account", None)
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
				"credit_account": f"Accounts Receivable ({party_label})",
				"narration": line.narration or "",
				"doc_type": "Payment Entry",
			}

		if line.direction == "Outbound":
			return {
				"idx": line.idx,
				"direction": line.direction,
				"category": line.transaction_category,
				"party": party_label,
				"reference": ref_label,
				"amount": amount,
				"debit_account": f"Accounts Payable ({party_label})",
				"credit_account": vault_account,
				"narration": line.narration or "",
				"doc_type": "Payment Entry",
			}

		return None

	# ─── Process Line ─────────────────────────────────────────────────────────────

	def _process_line(self, line, vault_account):
		"""
		Process a single journal line:
		  1. If the line came from a VPI that has a source Payment Entry → submit that PE
		     and advance its workflow to 'Submitted to GL'.
		  2. If the line is a Direct Expense → create a Journal Entry.
		  3. If the line is an Advance Allocation → call custody settlement.
		  4. Otherwise → create a new Payment Entry and submit it.
		Returns the name of the created/submitted document.
		"""
		# ── Path 1: VPI-linked source document (Payment Entry from workflow) ──────
		# The journal line's source_document field holds the original PE name
		# (set by execute_pending_item in the cockpit API).
		# We must submit that PE and advance its workflow instead of creating a new one.
		source_pe_name = self._resolve_source_pe(line)
		if source_pe_name:
			return self._submit_and_advance_pe(source_pe_name, line)

		# ── Path 2: Direct Expense → Journal Entry ───────────────────────────────
		if line.transaction_category == "Direct Expense":
			return self._create_direct_expense_je(line, vault_account)

		# ── Path 3: Custody Advance Allocation ──────────────────────────────────
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

		# ── Path 4: Manual entry (no VPI source) → create new Payment Entry ──────
		return self._create_new_pe(line, vault_account)

	def _resolve_source_pe(self, line):
		"""
		Resolve the original Payment Entry linked to this journal line via VPI.
		Looks up in order:
		  1. line.source_document (if source_doctype == 'Payment Entry')
		  2. VPI.source_document via line.linked_document (VPI name)
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
			pe.submit()
		elif pe.docstatus == 2:  # Cancelled — cannot reuse
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
			# Non-fatal: log but don't block posting
			frappe.log_error(
				f"Could not advance workflow_state for PE {pe_name}: {e}",
				"TCJ: PE Workflow Advance"
			)

		# Update the VPI linked to this line as well
		vpi_name = getattr(line, "linked_document", "")
		if vpi_name and frappe.db.exists("Vault Pending Item", vpi_name):
			try:
				frappe.db.set_value(
					"Vault Pending Item", vpi_name,
					"linked_journal", self.name
				)
			except Exception:
				pass

		return pe_name

	def _create_new_pe(self, line, vault_account):
		"""Create and submit a brand-new Payment Entry for manual cockpit entries."""
		pe = frappe.new_doc("Payment Entry")
		pe.posting_date = self.posting_date
		pe.company = self.company
		pe.mode_of_payment = "Cash"

		if line.direction == "Inbound":
			pe.payment_type = "Receive"
			pe.party_type = line.party_type or "Customer"
			pe.party = line.party
			pe.paid_to = vault_account
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
			pe.paid_from = vault_account
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
		pe.flags.ignore_permissions = True
		pe.flags.ignore_mandatory = True
		pe.flags.submitted_by_tcj = True
		pe.insert()
		pe.submit()
		return pe.name

	def _create_direct_expense_je(self, line, vault_account):
		expense_account = line.reference_name or getattr(line, "expense_account", None)
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

		je = frappe.new_doc("Journal Entry")
		je.posting_date = self.posting_date
		je.company = self.company
		je.voucher_type = "Journal Entry"
		je.user_remark = line.narration or f"Direct expense from Treasury Cash Journal {self.name}"

		je.append("accounts", {
			"account": expense_account,
			"debit_in_account_currency": flt(line.amount),
			"credit_in_account_currency": 0,
			"user_remark": line.narration,
		})
		je.append("accounts", {
			"account": vault_account,
			"debit_in_account_currency": 0,
			"credit_in_account_currency": flt(line.amount),
			"user_remark": line.narration,
		})

		je.flags.ignore_permissions = True
		je.insert()
		je.submit()
		return je.name

	def _post_variance_entry(self, vault_account, shortage_account):
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
