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
	"""Return all open Treasury Stations the current user can access."""
	return frappe.get_all(
		"Treasury Station",
		filters={"status": "Open"},
		fields=["name", "station_name", "vault_account", "current_balance", "company"],
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
			        "amount", "narration", "is_posted", "linked_document"],
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
def save_journal_draft(station, posting_date, lines, journal_name=None):
	"""
	Save or update a Draft Treasury Cash Journal with the given lines.
	Creates a new journal if journal_name is None.
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
			"reference_doctype":     line.get("reference_doctype"),
			"reference_name":        line.get("reference_name"),
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
