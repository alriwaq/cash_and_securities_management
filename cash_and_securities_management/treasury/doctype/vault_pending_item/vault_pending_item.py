import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime, nowdate


class VaultPendingItem(Document):
	"""
	V4 Architecture: Represents a cash transaction that has been requested
	(via Payment Entry, Direct Expense, etc.) and is waiting for the vault
	teller to physically execute it.

	Lifecycle:
	  Pending   → created by hook from source document
	  Executed  → teller confirms physical cash exchange in cockpit
	  Cancelled → source document cancelled or teller rejects
	"""

	def validate(self):
		if not self.company:
			self.company = frappe.db.get_value(
				"Treasury Station", self.treasury_station, "company"
			)

	@frappe.whitelist()
	def execute(self, actual_amount=None, narration=None):
		"""
		Called when the vault teller physically executes this pending item.
		Assigns serial number, records execution time, and marks as Executed.
		"""
		if self.status == "Executed":
			frappe.throw(_("This item has already been executed."))
		if self.status == "Cancelled":
			frappe.throw(_("Cannot execute a cancelled item."))

		self.actual_amount = flt(actual_amount) if actual_amount is not None else flt(self.expected_amount)
		if narration:
			self.narration = narration
		self.execution_time = now_datetime()
		self.status = "Executed"

		# Assign direction-specific serial number
		self._assign_serial()

		self.flags.ignore_permissions = True
		self.save()
		return self.name

	def _assign_serial(self):
		"""Assign IN-YYYY-NNNN or OUT-YYYY-NNNN serial based on direction."""
		year = frappe.utils.getdate().year
		if self.direction == "Inbound":
			if not self.inbound_serial:
				last = frappe.db.sql("""
					SELECT inbound_serial FROM `tabVault Pending Item`
					WHERE treasury_station = %s
					  AND YEAR(posting_date) = %s
					  AND inbound_serial IS NOT NULL
					  AND inbound_serial != ''
					ORDER BY inbound_serial DESC
					LIMIT 1
				""", (self.treasury_station, year))
				if last and last[0][0]:
					try:
						n = int(last[0][0].split("-")[-1]) + 1
					except (ValueError, IndexError):
						n = 1
				else:
					n = 1
				self.inbound_serial = f"IN-{year}-{str(n).zfill(4)}"
		elif self.direction == "Outbound":
			if not self.outbound_serial:
				last = frappe.db.sql("""
					SELECT outbound_serial FROM `tabVault Pending Item`
					WHERE treasury_station = %s
					  AND YEAR(posting_date) = %s
					  AND outbound_serial IS NOT NULL
					  AND outbound_serial != ''
					ORDER BY outbound_serial DESC
					LIMIT 1
				""", (self.treasury_station, year))
				if last and last[0][0]:
					try:
						n = int(last[0][0].split("-")[-1]) + 1
					except (ValueError, IndexError):
						n = 1
				else:
					n = 1
				self.outbound_serial = f"OUT-{year}-{str(n).zfill(4)}"
