"""
Patch: migrate_to_v2
Version: 2.0.0
Date: 2026-05-10

Migrates existing data from v1 to v2 schema:
  1. Backfills remaining_to_pay on all submitted Custody Requests
  2. Backfills total_settled_amount on all submitted Accountant Custodies
  3. Recalculates granular status on all submitted Accountant Custodies
  4. Recalculates Custodian balance summaries
  5. Creates liability sub-ledger accounts for Custodians that are missing one
     (requires default_payable_group to be set in Treasury Settings)
"""
import frappe
from frappe import _
from frappe.utils import flt


def execute():
	frappe.logger().info("v2 migration patch: starting")

	# ── 1. Backfill remaining_to_pay on Custody Requests ─────────────────
	_backfill_custody_request_remaining()

	# ── 2. Backfill total_settled_amount on Accountant Custodies ─────────
	_backfill_ac_settled_amount()

	# ── 3. Recalculate AC granular statuses ───────────────────────────────
	_recalculate_ac_statuses()

	# ── 4. Recalculate all Custodian balances ─────────────────────────────
	_recalculate_all_custodian_balances()

	# ── 5. Create missing liability accounts ─────────────────────────────
	_create_missing_liability_accounts()

	frappe.logger().info("v2 migration patch: complete")


def _backfill_custody_request_remaining():
	"""Set remaining_to_pay = advance_amount - paid_amount for all submitted CRs."""
	crs = frappe.get_all(
		"Custody Request",
		filters={"docstatus": 1},
		fields=["name", "advance_amount", "paid_amount"],
	)
	updated = 0
	for cr in crs:
		remaining = flt(cr.advance_amount) - flt(cr.paid_amount)
		frappe.db.set_value(
			"Custody Request",
			cr.name,
			"remaining_to_pay",
			remaining,
			update_modified=False,
		)
		updated += 1
	frappe.logger().info(f"  Backfilled remaining_to_pay on {updated} Custody Requests")


def _backfill_ac_settled_amount():
	"""
	Compute total_settled_amount for each submitted Accountant Custody
	from its settlements child table rows.
	"""
	acs = frappe.get_all(
		"Accountant Custody",
		filters={"docstatus": 1},
		fields=["name"],
	)
	updated = 0
	for ac in acs:
		total = flt(frappe.db.sql(
			"""SELECT COALESCE(SUM(total_settlement_amount), 0)
			   FROM `tabCustody Settlement Entry`
			   WHERE parent = %s""",
			(ac.name,),
		)[0][0] or 0)
		frappe.db.set_value(
			"Accountant Custody",
			ac.name,
			"total_settled_amount",
			total,
			update_modified=False,
		)
		updated += 1
	frappe.logger().info(f"  Backfilled total_settled_amount on {updated} Accountant Custodies")


def _recalculate_ac_statuses():
	"""Recalculate granular status for all submitted Accountant Custodies."""
	from cash_and_securities_management.treasury.balances import (
		recalculate_accountant_custody_status,
	)
	acs = frappe.get_all(
		"Accountant Custody",
		filters={"docstatus": 1},
		fields=["name"],
	)
	updated = 0
	for ac in acs:
		try:
			recalculate_accountant_custody_status(ac.name)
			updated += 1
		except Exception as e:
			frappe.log_error(str(e), f"v2 patch: recalculate AC status {ac.name}")
	frappe.logger().info(f"  Recalculated status on {updated} Accountant Custodies")


def _recalculate_all_custodian_balances():
	"""Recalculate balance summaries for all submitted Custodians."""
	from cash_and_securities_management.treasury.balances import (
		recalculate_custodian_balances,
	)
	custodians = frappe.get_all(
		"Custodian",
		filters={"docstatus": 1},
		fields=["name"],
	)
	updated = 0
	for cust in custodians:
		try:
			recalculate_custodian_balances(cust.name)
			updated += 1
		except Exception as e:
			frappe.log_error(str(e), f"v2 patch: recalculate custodian {cust.name}")
	frappe.logger().info(f"  Recalculated balances on {updated} Custodians")


def _create_missing_liability_accounts():
	"""
	For each submitted Custodian that has a custody_account but no liability_account,
	attempt to create the liability sub-ledger if default_payable_group is configured.
	"""
	settings = frappe.db.get_singles_dict("Treasury Settings")
	payable_group = settings.get("default_payable_group")
	if not payable_group:
		frappe.logger().info(
			"  Skipping liability account creation: default_payable_group not configured"
		)
		return

	custodians = frappe.get_all(
		"Custodian",
		filters={"docstatus": 1, "custody_account": ["!=", ""], "liability_account": ["in", ["", None]]},
		fields=["name", "company"],
	)
	created = 0
	for cust in custodians:
		try:
			cust_doc = frappe.get_doc("Custodian", cust.name)
			cust_doc._create_custody_accounts()
			created += 1
		except Exception as e:
			frappe.log_error(str(e), f"v2 patch: create liability account for {cust.name}")

	frappe.logger().info(f"  Created/verified liability accounts for {created} Custodians")
