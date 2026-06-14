import frappe
from frappe import _

from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry


class CustodyPaymentEntry(PaymentEntry):
	"""
	Override Payment Entry for custody settlement transactions.

	Root cause of "Supplier is required against Payable account":
	  ERPNext's make_gl_entries() for payment_type="Internal Transfer" creates
	  GL entries WITHOUT party_type/party. The Payable account GL entry then has
	  no party, and frappe's GL-level validation fires the error.

	Fix: override get_gl_dict() to inject party_type="Custodian" + party into
	any Payable/Receivable account GL entry created for a custody PE.
	"""

	def _is_custody_mode(self):
		"""Return True for any PE created by the custody module."""
		source = self.get("custom_source_document_type") or ""
		return (
			source in ("Custody", "Custody Settlement")
			or bool(self.get("custom_accountant_custody"))
		)

	def add_party_gl_entries(self, gl_entries):
		"""
		Skip party GL entries for custody Internal Transfer PEs.

		For custody advance deduction, add_bank_gl_entries() already creates:
		  CR advance_account (paid_from)
		  DR payable_account (paid_to)
		If add_party_gl_entries() also runs with party_account=paid_to, it creates
		an additional DR payable_account — doubling the debit and causing imbalance.
		Skipping it here gives the correct balanced GL.
		"""
		if self._is_custody_mode() and self.payment_type == "Internal Transfer":
			return
		super().add_party_gl_entries(gl_entries)

	def setup_party_account_field(self):
		"""
		ERPNext's standard setup_party_account_field() only sets party_account for
		payment_type='Receive' or 'Pay'. For 'Internal Transfer' it sets
		party_account=None, which causes 'Account is required' when build_gl_map()
		calls add_party_gl_entries().

		For custody Internal Transfer PEs, party_account must be the payable account
		(paid_to) so that the GL entry for the party side is created correctly.
		"""
		if self._is_custody_mode() and self.payment_type == "Internal Transfer":
			# Preserve any party_account already set (e.g. by create_settlement)
			existing = self.get("party_account")
			existing_currency = self.get("party_account_currency")
			super().setup_party_account_field()
			# Restore — super() clears party_account for Internal Transfer
			self.party_account = existing or self.get("paid_to")
			self.party_account_currency = (
				existing_currency
				or self.get("paid_to_account_currency")
				or frappe.db.get_value("Company", self.company, "default_currency")
			)
			self.party_account_field = "paid_to"
		else:
			super().setup_party_account_field()

	def before_validate(self):
		if self._is_custody_mode():
			self.flags.ignore_mandatory = True
			self.flags.ignore_validate_update_after_submit = True

	def validate(self):
		"""
		For custody PEs, bypass ERPNext's strict party-type / account-type
		validation before calling the standard validate chain.
		For vault cash PEs, block saving if the station is not Open.
		"""
		# ── Layer 2A: Vault station open guard ────────────────────────────────────
		if self._is_vault_cash_payment():
			paid_from_station = self._get_vault_station_for_account(self.get("paid_from"))
			paid_to_station = self._get_vault_station_for_account(self.get("paid_to"))
			station = paid_from_station or paid_to_station
			if station:
				status = frappe.db.get_value("Treasury Station", station, "status")
				if status != "Open":
					frappe.throw(
						_(
							"لا يمكن حفظ سند الدفع لأن خزينة المحطة '{station}' مغلقة حالياً.\n"
							"يرجى فتح الخزينة أولاً عبر زر 'فتح الخزينة' في سجل المحطة.\n\n"
							"Cannot save Payment Entry: Station '{station}' is currently Closed. "
							"Please open the station first."
						).format(station=station),
						title=_("الخزينة مغلقة / Station Closed"),
					)

			# ── Layer 2B: Lock pending PE against edits ───────────────────────
			# Block saves while the PE is awaiting vault approval.
			# Allows vault users and admins to still save (e.g. approve/reject).
			self._assert_not_locked_pending()

			# ── Layer 2C: Enforce role-based state transition rules ───────────
			# Prevents workflow_state from being tampered with via REST API
			# or direct form edits by unauthorized users.
			self._validate_vault_state_transition()

		if self._is_custody_mode():
			# Ensure party fields are always set for custody PEs
			if not self.get("party_type"):
				self.party_type = "Custodian"
			if not self.get("party") and self.get("custom_custodian"):
				self.party = self.custom_custodian
			# Ensure account currencies are set (prevents 'Account is required' from
			# currency mismatch checks in the standard validate chain)
			if self.get("paid_from") and not self.get("paid_from_account_currency"):
				self.paid_from_account_currency = frappe.get_cached_value(
					"Account", self.paid_from, "account_currency"
				) or frappe.db.get_value("Company", self.company, "default_currency")
			if self.get("paid_to") and not self.get("paid_to_account_currency"):
				self.paid_to_account_currency = frappe.get_cached_value(
					"Account", self.paid_to, "account_currency"
				) or frappe.db.get_value("Company", self.company, "default_currency")
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
		preserved_paid_from = self.get("paid_from")
		preserved_paid_to = self.get("paid_to")
		preserved_paid_from_currency = self.get("paid_from_account_currency")
		preserved_paid_to_currency = self.get("paid_to_account_currency")
		preserved_party_type = self.get("party_type")
		preserved_party = self.get("party")
		# party_account is used by make_advance_gl_entries for the second GL entry
		preserved_party_account = self.get("party_account")
		preserved_party_account_currency = self.get("party_account_currency")
		preserved_references = []

		if self._is_custody_mode() and self.payment_type == "Internal Transfer":
			for row in self.get("references") or []:
				preserved_references.append(
					{
						"reference_doctype": row.get("reference_doctype"),
						"reference_name": row.get("reference_name"),
						"due_date": row.get("due_date"),
						"bill_no": row.get("bill_no"),
						"payment_term": row.get("payment_term"),
						"payment_term_outstanding": row.get("payment_term_outstanding"),
						"account_type": row.get("account_type"),
						"payment_type": row.get("payment_type"),
						"reconcile_effect_on": row.get("reconcile_effect_on"),
						"total_amount": row.get("total_amount"),
						"outstanding_amount": row.get("outstanding_amount"),
						"allocated_amount": row.get("allocated_amount"),
						"exchange_rate": row.get("exchange_rate"),
						"payment_request": row.get("payment_request"),
					}
				)

		super().set_missing_values()

		if self._is_custody_mode() and self.payment_type == "Internal Transfer":
			# Restore accounts — ERPNext overwrites these with company defaults
			if preserved_paid_from:
				self.paid_from = preserved_paid_from
			if preserved_paid_to:
				self.paid_to = preserved_paid_to
			if preserved_paid_from_currency:
				self.paid_from_account_currency = preserved_paid_from_currency
			if preserved_paid_to_currency:
				self.paid_to_account_currency = preserved_paid_to_currency
			# Restore party
			if preserved_party_type and not self.get("party_type"):
				self.party_type = preserved_party_type
			if preserved_party and not self.get("party"):
				self.party = preserved_party
			# Restore party_account — used by make_advance_gl_entries for the second GL entry
			if preserved_party_account:
				self.party_account = preserved_party_account
			if preserved_party_account_currency:
				self.party_account_currency = preserved_party_account_currency
			# Restore PI references
			if preserved_references and not self.get("references"):
				self.set("references", [])
				for ref in preserved_references:
					self.append("references", ref)

	# ─── V4: Vault Workflow Guard ────────────────────────────────────────────────

	def _get_vault_station_for_account(self, account):
		"""
		Return the Treasury Station name whose vault_account matches `account`,
		or None if no match found.
		"""
		if not account:
			return None
		return frappe.db.get_value(
			"Treasury Station",
			{"vault_account": account, "docstatus": 1},
			"name",
		)

	def _is_vault_cash_payment(self):
		"""
		Return True if this PE is a cash payment that must go through the
		Vault Approval workflow before being submitted to the GL.
		Custody Internal Transfer PEs are exempt (handled by the custody module).
		"""
		if self._is_custody_mode():
			return False
		mode = (self.get("mode_of_payment") or "").strip().lower()
		return mode == "cash"

	def _is_privileged_user(self):
		"""Return True for Administrator or System Manager — bypass all vault guards."""
		if frappe.session.user == "Administrator":
			return True
		return "System Manager" in frappe.get_roles(frappe.session.user)

	def _assert_not_locked_pending(self):
		"""
		Layer 2B: Prevent a PE in 'Pending Vault Approval' state from being
		edited by anyone other than Treasury Vault User / System Manager.
		This stops a clerk from withdrawing or modifying a PE mid-approval.
		"""
		if self.is_new():
			return
		db_state = frappe.db.get_value("Payment Entry", self.name, "workflow_state") or "Draft"
		if db_state != "Pending Vault Approval":
			return
		# Vault users and admins may still save (to approve/reject)
		if self._is_privileged_user():
			return
		if "Treasury Vault User" in frappe.get_roles(frappe.session.user):
			return
		frappe.throw(
			_(
				"لا يمكن تعديل سند الدفع لأنه في حالة 'انتظار موافقة الخزينة'.\n"
				"يرجى انتظار قرار مسؤول الخزينة (موافقة أو رفض).\n\n"
				"This Payment Entry is locked — it is awaiting Vault Approval.\n"
				"Wait for the vault teller to approve or reject it before making changes."
			),
			title=_("السند مقفل / Entry Locked"),
		)

	def _validate_vault_state_transition(self):
		"""
		Layer 2C: Enforce role-based authorization on every workflow_state change.
		Fires on every save through validate() — catches form saves AND REST API
		(frappe.client.set_value triggers validate; only frappe.db.set_value skips it).

		Allowed transitions:
		  Draft → Pending Vault Approval : Accounts User / Accounts Manager only
		  Pending → Vault Approved        : Treasury Vault User only
		  Pending → Rejected              : Treasury Vault User only
		  Rejected → Pending              : Accounts User / Accounts Manager only
		  Any state → Any state           : System Manager / Administrator always allowed
		"""
		if self.is_new():
			return  # New docs always start at Draft

		db_state = frappe.db.get_value("Payment Entry", self.name, "workflow_state") or "Draft"
		new_state = (self.get("workflow_state") or "Draft").strip()

		if db_state == new_state:
			return  # No transition — nothing to validate

		# Privileged users bypass transition rules
		if self._is_privileged_user():
			return
		# TCJ programmatic submit — allowed
		if self.flags.get("submitted_by_tcj"):
			return

		user_roles = set(frappe.get_roles(frappe.session.user))
		CLERK_ROLES = {"Accounts User", "Accounts Manager"}
		VAULT_ROLES = {"Treasury Vault User"}

		transition = (db_state, new_state)

		if transition == ("Draft", "Pending Vault Approval"):
			if not (CLERK_ROLES & user_roles):
				frappe.throw(
					_("Only Accounts User / Accounts Manager can send a Cash Payment Entry for Vault Approval."),
					title=_("Unauthorized / غير مصرح"),
				)

		elif transition == ("Pending Vault Approval", "Vault Approved"):
			if not (VAULT_ROLES & user_roles):
				frappe.throw(
					_("Only Treasury Vault User can approve a Cash Payment Entry."),
					title=_("Unauthorized / غير مصرح"),
				)

		elif transition == ("Pending Vault Approval", "Rejected"):
			if not (VAULT_ROLES & user_roles):
				frappe.throw(
					_("Only Treasury Vault User can reject a Cash Payment Entry."),
					title=_("Unauthorized / غير مصرح"),
				)

		elif transition == ("Rejected", "Pending Vault Approval"):
			if not (CLERK_ROLES & user_roles):
				frappe.throw(
					_("Only Accounts User / Accounts Manager can resubmit a rejected Cash Payment Entry."),
					title=_("Unauthorized / غير مصرح"),
				)

		elif new_state == "Vault Approved":
			# Direct jump to Vault Approved skipping Pending — block entirely
			frappe.throw(
				_(
					"لا يمكن تعيين الحالة مباشرة إلى 'تمت الموافقة'. "
					"يجب أن يمر السند بمرحلة 'انتظار الموافقة' أولاً.\n\n"
					"Cannot set state directly to 'Vault Approved'. "
					"The entry must pass through 'Pending Vault Approval' first."
				),
				title=_("Invalid Transition / انتقال غير صالح"),
			)

		else:
			# Any other unrecognised transition
			frappe.throw(
				_("Invalid workflow state transition: '{0}' → '{1}'.").format(db_state, new_state),
				title=_("Invalid Transition / انتقال غير صالح"),
			)

	def before_submit(self):
		"""
		V4: Block direct GL submission of cash Payment Entries.
		Cash PEs must be approved by the vault responsible user first.
		The actual GL submission is triggered by the Treasury Cash Journal submit.
		"""
		if self._is_vault_cash_payment():
			wf_state = (self.get("workflow_state") or "").strip()

			# ── Fast-path bypasses ──────────────────────────────────────────
			if self.flags.get("submitted_by_tcj"):
				return  # TCJ-triggered submit — always allowed
			if self._is_privileged_user():
				return  # Administrator / System Manager bypass

			# ── Layer 2D: Require 'Vault Approved' state ────────────────────
			if wf_state != "Vault Approved":
				frappe.throw(
					_(
						"لا يمكن ترحيل قيد الدفع النقدي مباشرة إلى دفتر الأستاذ. "
						"يجب أن تتم الموافقة عليه من مسؤول الخزينة أولاً، "
						"ثم يُرحَّل عبر سجل يومية الخزينة النقدية في نهاية اليوم.\n\n"
						"Cash Payment Entry cannot be submitted directly to the GL. "
						"It must first be approved by the Vault Responsible User, "
						"then posted via the Treasury Cash Journal at end of day."
					),
					title=_("Vault Approval Required / مطلوب موافقة الخزينة"),
				)

			# ── Layer 2E: Verify teller actually executed the physical cash ──
			# Prevents someone from bypassing the cockpit by manually setting
			# workflow_state = 'Vault Approved' via frappe.db.set_value in Python.
			vpi_executed = frappe.db.exists(
				"Vault Pending Item",
				{
					"source_document_type": "Payment Entry",
					"source_document": self.name,
					"status": "Executed",
				},
			)
			if not vpi_executed:
				frappe.throw(
					_(
						"لا يوجد تأكيد من الخزينة على تسليم النقد لهذا السند.\n"
						"يجب على أمين الخزينة تنفيذ العملية في الكوكبيت أولاً.\n\n"
						"No executed Vault Pending Item found for this Payment Entry.\n"
						"The vault teller must confirm the physical cash handover in the cockpit first."
					),
					title=_("Vault Confirmation Required / مطلوب تأكيد الخزينة"),
				)

	def validate_party_accounts(self):
		"""Skip party-type/account-type matching check for custody PEs."""
		if self._is_custody_mode():
			return
		super().validate_party_accounts()

	def get_gl_dict(self, args, account_currency=None, item=None):
		"""
		Inject Custodian party into GL entries for Payable/Receivable/Custody accounts.

		For Internal Transfer PEs, ERPNext does not populate party_type/party on
		the individual GL dicts, causing GL-level validation to raise
		"Supplier is required against Payable account".  We intercept every GL
		dict and add the Custodian party when the account is Payable, Receivable,
		or the dedicated Custody type.
		"""
		gl_dict = super().get_gl_dict(args, account_currency=account_currency, item=item)

		if self._is_custody_mode() and gl_dict:
			account = gl_dict.get("account")
			if account and not gl_dict.get("party_type"):
				account_type = frappe.get_cached_value("Account", account, "account_type")
				if account_type in ("Payable", "Receivable", "Custody"):
					gl_dict["party_type"] = "Custodian"
					gl_dict["party"] = self.get("custom_custodian") or self.party

		return gl_dict
