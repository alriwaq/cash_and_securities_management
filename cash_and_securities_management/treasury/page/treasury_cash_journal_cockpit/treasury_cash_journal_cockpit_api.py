"""
Backend API for the Treasury Cash Journal FBCJ page.
All methods are whitelisted and called from the page JS.
"""
import frappe
from frappe import _
from frappe.utils import flt, nowdate


def _infer_linked_doctype(linked_document):
	if not linked_document:
		return ""
	if frappe.db.exists("Payment Entry", linked_document):
		return "Payment Entry"
	if frappe.db.exists("Journal Entry", linked_document):
		return "Journal Entry"
	return ""


@frappe.whitelist()
def get_station_list():
	"""
	Return Treasury Stations the current user can access.
	- Accounts Manager, System Manager, Administrator → see all submitted stations
	- All other users → only stations where responsible_user = current user
	Only submitted (docstatus=1) stations are returned (draft stations are not operational).
	"""
	user = frappe.session.user
	roles = frappe.get_roles(user)
	manager_roles = {"System Manager", "Accounts Manager"}

	base_filters = {"docstatus": 1}  # Only submitted stations

	if user != "Administrator" and not manager_roles.intersection(roles):
		base_filters["responsible_user"] = user

	return frappe.get_all(
		"Treasury Station",
		filters=base_filters,
		fields=["name", "station_name", "vault_account", "current_balance", "company",
				"responsible_employee", "responsible_user", "status"],
		order_by="station_name asc",
	)


@frappe.whitelist()
def get_station_data(station, posting_date=None):
	"""
	Return the station's opening balance and any existing Draft/Pending journal
	for the given date so the page can pre-populate rows.
	"""
	if not posting_date:
		posting_date = nowdate()

	station_doc = frappe.get_doc("Treasury Station", station)

	existing = frappe.db.get_value(
		"Treasury Cash Journal",
		{
			"treasury_station": station,
			"posting_date": posting_date,
			"posting_status": ["in", ["Draft", "Pending Review"]],
		},
		["name", "opening_balance", "total_inflows", "total_outflows",
		 "expected_balance", "actual_balance", "variance", "posting_status"],
		as_dict=True,
	)

	lines = []
	journal_name = None
	if existing:
		journal_name = existing.name
		lines = frappe.get_all(
			"Treasury Journal Line",
			filters={"parent": existing.name, "parenttype": "Treasury Cash Journal"},
			fields=["name", "idx", "direction", "transaction_category", "party_type",
			        "party", "reference_doctype", "reference_name", "expense_account",
			        "amount", "narration", "is_posted", "linked_document", "voucher_serial"],
			order_by="idx asc",
		)
		for l in lines:
			l["linked_doctype"] = _infer_linked_doctype(l.get("linked_document"))

	return {
		"station": station_doc.as_dict(),
		"journal_name": journal_name,
		"opening_balance": flt(station_doc.current_balance),
		"existing": existing,
		"lines": lines,
		"posting_date": posting_date,
	}


@frappe.whitelist()
def get_open_references(party_type, party, reference_doctype):
	"""
	Fetch open documents (invoices, custody requests, etc.) for a given party.
	Returns a list of {name, outstanding_amount, grand_total} dicts.
	"""
	if not party_type or not party or not reference_doctype:
		return []

	if reference_doctype == "Sales Invoice":
		return frappe.get_all(
			"Sales Invoice",
			filters={
				"customer": party,
				"docstatus": 1,
				"outstanding_amount": [">", 0],
			},
			fields=["name", "grand_total", "outstanding_amount", "posting_date"],
			order_by="posting_date desc",
			limit=50,
		)

	elif reference_doctype == "Purchase Invoice":
		return frappe.get_all(
			"Purchase Invoice",
			filters={
				"supplier": party,
				"docstatus": 1,
				"outstanding_amount": [">", 0],
			},
			fields=["name", "grand_total", "outstanding_amount", "posting_date"],
			order_by="posting_date desc",
			limit=50,
		)

	elif reference_doctype == "Custody Request":
		return frappe.get_all(
			"Custody Request",
			filters={
				"custodian": party,
				"docstatus": 1,
				"status": ["in", ["Approved", "Pending Payment"]],
			},
			fields=["name", "advance_amount as grand_total",
			        "advance_amount as outstanding_amount", "request_date as posting_date"],
			order_by="request_date desc",
			limit=50,
		)

	elif reference_doctype == "Accountant Custody":
		return frappe.get_all(
			"Accountant Custody",
			filters={
				"custodian": party,
				"docstatus": 1,
				"status": ["in", ["Fully Invoiced", "Partly Settled"]],
			},
			fields=["name", "total_billed_amount as grand_total",
			        "total_billed_amount as outstanding_amount", "date as posting_date"],
			order_by="date desc",
			limit=50,
		)

	return []


@frappe.whitelist()
def check_prior_draft(station, today):
	"""
	Return the most recent prior-date Draft TCJ for this station (if any),
	so the cockpit JS can show a blocking banner without throwing an error.
	Returns {name, posting_date} or None.
	"""
	prior = frappe.db.get_value(
		"Treasury Cash Journal",
		{
			"treasury_station": station,
			"posting_date": ["<", today],
			"posting_status": "Draft",
		},
		["name", "posting_date"],
		order_by="posting_date desc",
		as_dict=True,
	)
	return prior or {}


def _assert_no_unsent_prior_draft(station, today):
	"""
	Block any new cockpit activity for `today` if the station already has
	a Treasury Cash Journal for a PRIOR date that is still in 'Draft' status
	(i.e. the vault user has not yet clicked 'Send for Review').
	Raises frappe.ValidationError with a descriptive Arabic/English message.
	"""
	prior_draft = frappe.db.get_value(
		"Treasury Cash Journal",
		{
			"treasury_station": station,
			"posting_date": ["<", today],
			"posting_status": "Draft",
		},
		["name", "posting_date"],
		order_by="posting_date desc",
		as_dict=True,
	)
	if prior_draft:
		frappe.throw(
			_(
				"لا يمكن فتح يومية اليوم قبل إرسال يومية {date} للمراجعة.\n"
				"يرجى فتح اليومية <b>{name}</b> والضغط على زر 'إرسال للمراجعة' أولاً.\n\n"
				"Cannot open today's journal until the draft journal for {date} "
				"({name}) has been sent for review."
			).format(date=prior_draft.posting_date, name=prior_draft.name),
			title=_("يومية سابقة لم تُرسل للمراجعة / Unsent Prior Draft"),
		)


@frappe.whitelist()
def save_journal_draft(station, posting_date, lines, journal_name=None):
	"""
	Save or update a Draft Treasury Cash Journal with the given lines.
	Creates a new journal if journal_name is None.
	Blocks creation if a prior-date Draft exists that was not sent for review.
	Returns the journal name.
	"""
	import json
	if isinstance(lines, str):
		lines = json.loads(lines)

	if journal_name:
		doc = frappe.get_doc("Treasury Cash Journal", journal_name)
		if doc.posting_status in ("Posted", "Closed"):
			frappe.throw(_("Cannot edit a Posted or Closed journal."))
		doc.journal_lines = []
	else:
		# Guard: block new journal if a prior-date Draft was not sent for review
		_assert_no_unsent_prior_draft(station, posting_date)
		doc = frappe.new_doc("Treasury Cash Journal")
		doc.treasury_station = station
		doc.posting_date = posting_date
		doc.posting_status = "Draft"

	for line in lines:
		doc.append("journal_lines", {
			"direction":             line.get("direction"),
			"transaction_category":  line.get("transaction_category"),
			"party_type":            line.get("party_type"),
			"party":                 line.get("party"),
			"expense_account":       line.get("expense_account"),
			"amount":                flt(line.get("amount", 0)),
			"narration":             line.get("narration", ""),
			"is_posted":             int(line.get("is_posted", 0)),
			"linked_document":       line.get("linked_document", ""),
		})

	doc.flags.ignore_permissions = True
	if journal_name:
		doc.save()
	else:
		doc.insert()

	return doc.name


@frappe.whitelist()
def send_for_review(journal_name):
	"""
	Called by the cockpit 'Post Journal' button.
	Sets the journal status to 'Pending Review' WITHOUT creating any GL entries.
	The accountant then reviews the Dr/Cr lines in the TCJ form and submits.
	"""
	doc = frappe.get_doc("Treasury Cash Journal", journal_name)

	if doc.posting_status in ("Posted", "Closed"):
		frappe.throw(_("Journal {0} is already {1}.").format(journal_name, doc.posting_status))

	if not doc.journal_lines:
		frappe.throw(_("Cannot send an empty journal for review."))

	doc.posting_status = "Pending Review"
	doc.flags.ignore_permissions = True
	doc.save()

	return {
		"journal_name": doc.name,
		"status": doc.posting_status,
		"url": frappe.utils.get_url_to_form("Treasury Cash Journal", doc.name),
	}


@frappe.whitelist()
def post_journal(journal_name, actual_balance=None, variance_narration=None):
	"""
	Legacy method kept for backward compatibility.
	Now delegates to send_for_review (sets Pending Review, no GL).
	Actual GL posting happens when the accountant submits the TCJ form.
	"""
	return send_for_review(journal_name)


# ─── V4: Vault Pending Items API ──────────────────────────────────────────────

@frappe.whitelist()
def get_pending_items(station, posting_date=None):
	"""
	V4: Return ALL Pending/Draft Vault Pending Items for the given station,
	regardless of posting_date or source_document_type.
	Uses raw SQL to avoid any ORM filtering issues.
	"""
	items = frappe.db.sql("""
		SELECT
			name, direction, transaction_category, posting_date,
			party_type, party, reference_doctype, reference_name,
			expense_account, expected_amount, actual_amount,
			narration, source_document_type, source_document,
			inbound_serial, outbound_serial, status, creation
		FROM `tabVault Pending Item`
		WHERE treasury_station = %(station)s
		  AND status = 'Pending'
		ORDER BY
			FIELD(direction, 'Inbound', 'Outbound', 'Bank Transfer', '') ASC,
			posting_date ASC,
			creation ASC
	""", {"station": station}, as_dict=True)

	# Enrich with party_name for display
	for item in items:
		if item.get("party_type") and item.get("party"):
			try:
				party_name = frappe.db.get_value(
					item["party_type"], item["party"],
					"supplier_name" if item["party_type"] == "Supplier"
					else "customer_name" if item["party_type"] == "Customer"
					else "employee_name" if item["party_type"] == "Employee"
					else "name"
				)
				item["party_name"] = party_name or item["party"]
			except Exception:
				item["party_name"] = item["party"]
		else:
			item["party_name"] = item.get("party") or ""

		# Ensure direction has a value for JS grouping
		if not item.get("direction"):
			item["direction"] = "Outbound"

	return items


@frappe.whitelist()
def execute_pending_item(item_name, actual_amount=None, narration=None):
	"""
	V4: Called when the vault teller physically executes a pending item.
	Marks the item as Executed, assigns serial number, records execution time.
	Also adds the item as a row in the current day's Draft journal.
	"""
	item = frappe.get_doc("Vault Pending Item", item_name)
	executed_name = item.execute(actual_amount=actual_amount, narration=narration)

	# Auto-add to today's journal draft (use today's date = cockpit date, not VPI creation date)
	station = item.treasury_station
	posting_date = frappe.utils.today()

	existing_journal = frappe.db.get_value(
		"Treasury Cash Journal",
		{
			"treasury_station": station,
			"posting_date": posting_date,
			"posting_status": ["in", ["Draft"]],
		},
		"name",
	)

	if existing_journal:
		jdoc = frappe.get_doc("Treasury Cash Journal", existing_journal)
	else:
		# Guard: block creation of a new journal if a prior-date Draft was not sent for review
		_assert_no_unsent_prior_draft(station, posting_date)
		jdoc = frappe.new_doc("Treasury Cash Journal")
		jdoc.treasury_station = station
		jdoc.posting_date = posting_date
		jdoc.posting_status = "Draft"

	serial = item.inbound_serial or item.outbound_serial or ""
	jdoc.append("journal_lines", {
		"direction":            item.direction,
		"transaction_category": item.transaction_category,
		"party_type":           item.party_type or "",
		"party":                item.party or "",
		"expense_account":      item.expense_account or "",
		"amount":               flt(item.actual_amount or item.expected_amount),
		"narration":            item.narration or "",
		"is_posted":            0,
		"linked_document":      item.source_document or "",
	})

	jdoc.flags.ignore_permissions = True
	if existing_journal:
		jdoc.save()
	else:
		jdoc.insert()

	# Link the pending item to the journal
	frappe.db.set_value("Vault Pending Item", item_name, {
		"linked_journal": jdoc.name,
		"linked_journal_line": len(jdoc.journal_lines),
	})

	# V4: If this VPI came from a Payment Entry, mark it as Vault Approved
	# so the TCJ can submit it to GL without triggering the before_submit guard.
	if item.source_document_type == "Payment Entry" and item.source_document:
		pe_exists = frappe.db.exists("Payment Entry", item.source_document)
		if pe_exists:
			pe_docstatus = frappe.db.get_value("Payment Entry", item.source_document, "docstatus")
			if pe_docstatus == 0:  # Still draft — update workflow state
				frappe.db.set_value(
					"Payment Entry",
					item.source_document,
					"workflow_state",
					"Vault Approved",
				)

	return {
		"item_name": executed_name,
		"journal_name": jdoc.name,
		"serial": serial,
		"actual_amount": flt(item.actual_amount or item.expected_amount),
	}


@frappe.whitelist()
def cancel_pending_item(item_name, reason=None):
	"""
	V4: Cancel a pending vault item (e.g., teller rejects the transaction).
	"""
	item = frappe.get_doc("Vault Pending Item", item_name)
	if item.status == "Executed":
		frappe.throw(_("Cannot cancel an already executed item."))
	item.status = "Cancelled"
	if reason:
		item.narration = (item.narration or "") + f" [Cancelled: {reason}]"
	item.flags.ignore_permissions = True
	item.save()
	return item.name


@frappe.whitelist()
def create_and_execute_immediate(
	station, posting_date, direction, transaction_category,
	party_type="", party="", reference_doctype="", reference_name="",
	expense_account="", amount=0, narration=""
):
	"""
	V4 — Paths A & C (Inbound Receipt / Direct Expense).
	Creates a Vault Pending Item, immediately marks it Executed,
	assigns the correct serial number, and adds a row to the
	current day's Draft Treasury Cash Journal.
	Returns {serial, actual_amount, journal_name}.
	"""
	from frappe.utils import now_datetime

	if not posting_date:
		posting_date = nowdate()

	# Guard: block if a prior-date Draft was not sent for review
	_assert_no_unsent_prior_draft(station, posting_date)

	# Resolve company from station
	company = frappe.db.get_value("Treasury Station", station, "company")
	if not company:
		frappe.throw(_("Treasury Station {0} has no company set.").format(station))

	# Assign serial number — count existing executed items for this station/date/direction
	serial_prefix = "IN" if direction == "Inbound" else "OUT"
	existing_count = frappe.db.count(
		"Vault Pending Item",
		filters={
			"treasury_station": station,
			"posting_date": posting_date,
			"direction": direction,
			"status": "Executed",
		},
	)
	year = frappe.utils.getdate(posting_date).year
	serial = f"{serial_prefix}-{year}-{str(existing_count + 1).zfill(4)}"

	# Create the VPI
	vpi = frappe.new_doc("Vault Pending Item")
	vpi.treasury_station = station
	vpi.company = company
	vpi.posting_date = posting_date
	vpi.status = "Executed"
	vpi.direction = direction
	vpi.transaction_category = transaction_category
	vpi.party_type = party_type or ""
	vpi.party = party or ""
	vpi.reference_doctype = reference_doctype or ""
	vpi.reference_name = reference_name or ""
	vpi.expense_account = expense_account or ""
	vpi.expected_amount = flt(amount)
	vpi.actual_amount = flt(amount)
	vpi.narration = narration or ""
	vpi.execution_time = now_datetime()
	vpi.source_document_type = "Manual"
	vpi.source_document = ""

	if direction == "Inbound":
		vpi.inbound_serial = serial
	else:
		vpi.outbound_serial = serial

	vpi.flags.ignore_permissions = True
	vpi.insert()

	# Find or create today's Draft journal
	existing_journal = frappe.db.get_value(
		"Treasury Cash Journal",
		{
			"treasury_station": station,
			"posting_date": posting_date,
			"posting_status": "Draft",
		},
		"name",
	)

	if existing_journal:
		jdoc = frappe.get_doc("Treasury Cash Journal", existing_journal)
	else:
		jdoc = frappe.new_doc("Treasury Cash Journal")
		jdoc.treasury_station = station
		jdoc.posting_date = posting_date
		jdoc.posting_status = "Draft"

	jdoc.append("journal_lines", {
		"direction":            direction,
		"transaction_category": transaction_category,
		"party_type":           party_type or "",
		"party":                party or "",
		"expense_account":      expense_account or "",
		"amount":               flt(amount),
		"narration":            narration or "",
		"is_posted":            0,
		"linked_document":      vpi.name,
		"voucher_serial":       serial,
	})

	jdoc.flags.ignore_permissions = True
	if existing_journal:
		jdoc.save()
	else:
		jdoc.insert()

	# Link VPI back to the journal
	frappe.db.set_value("Vault Pending Item", vpi.name, {
		"linked_journal": jdoc.name,
		"linked_journal_line": len(jdoc.journal_lines),
	})

	return {
		"serial": serial,
		"actual_amount": flt(amount),
		"journal_name": jdoc.name,
		"vpi_name": vpi.name,
	}
