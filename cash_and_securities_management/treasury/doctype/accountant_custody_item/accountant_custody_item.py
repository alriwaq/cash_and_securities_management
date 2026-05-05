import frappe
from frappe.model.document import Document
def validate(self):
    self._set_child_defaults()


def _set_child_defaults(self):
    for item in self.custody_items:
        # Project fallback
        if not item.project:
            item.project = self.project

        # Cost center fallback
        if not item.cost_center:
            item.cost_center = self.cost_center

        # Warehouse fallback
        if not item.warehouse:
            item.warehouse = self.warehouse

class AccountantCustodyItem(Document):
	pass
