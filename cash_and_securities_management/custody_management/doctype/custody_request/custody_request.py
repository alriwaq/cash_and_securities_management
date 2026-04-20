import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from cash_and_securities_management.custody_management.utils import get_settings


class CustodyRequest(Document):

	def validate(self):
		self.set_defaults_from_settings()
		self.calculate_remaining_balance()

	def on_submit(self):
		self.db_set("status", "Unpaid")

	def on_cancel(self):
		self.validate_no_linked_documents()
		self.db_set("status", "Cancelled")

	def set_defaults_from_settings(self):
		settings = get_settings()
		if not self.advance_account and settings.get("custody_advance_account"):
			self.advance_account = settings.custody_advance_account
		if not self.mode_of_payment and settings.get("default_mode_of_payment"):
			self.mode_of_payment = settings.default_mode_of_payment
		if not self.cost_center and settings.get("default_cost_center"):
			self.cost_center = settings.default_cost_center

	def calculate_remaining_balance(self):
		self.remaining_balance = flt(self.advance_amount) - flt(self.claimed_amount)

	def validate_no_linked_documents(self):
		linked_custodies = frappe.get_all(
			"Accountant Custody",
			filters={"custody_request": self.name, "docstatus": ["!=", 2]},
			fields=["name"],
		)
		if linked_custodies:
			frappe.throw(
				_(
					"Cannot cancel Custody Request {0} as it has linked Accountant Custody records: {1}"
				).format(
					self.name,
					", ".join([d.name for d in linked_custodies]),
				)
			)

	def update_claimed_amount(self):
		"""Called when an Accountant Custody is settled against this request."""
		total_claimed = frappe.db.sql(
			"""
			SELECT SUM(total_amount)
			FROM `tabAccountant Custody`
			WHERE custody_request = %s AND docstatus = 1 AND status = 'Settled'
		""",
			self.name,
		)[0][0] or 0

		self.db_set("claimed_amount", flt(total_claimed))
		self.db_set("remaining_balance", flt(self.advance_amount) - flt(total_claimed))

		if flt(total_claimed) >= flt(self.advance_amount):
			self.db_set("status", "Claimed")
		elif flt(total_claimed) > 0:
			self.db_set("status", "Partly Claimed")
