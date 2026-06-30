"""
One-time patch: Fix Payment Entry records with invalid status values.

Old module code (before v15 commit 4845e95) wrote "Partly Reconciled",
"Reconciled", or "Unreconciled" to PE.status. ERPNext v15 only accepts:
"", "Draft", "Submitted", "Cancelled".

This patch resets all invalid statuses to the correct value based on docstatus.
"""
import frappe


def execute():
    count = frappe.db.sql("""
        SELECT COUNT(*) FROM `tabPayment Entry`
        WHERE status NOT IN ('', 'Draft', 'Submitted', 'Cancelled')
    """)[0][0]

    if not count:
        return

    frappe.db.sql("""
        UPDATE `tabPayment Entry`
        SET status = CASE
            WHEN docstatus = 2 THEN 'Cancelled'
            WHEN docstatus = 1 THEN 'Submitted'
            ELSE 'Draft'
        END
        WHERE status NOT IN ('', 'Draft', 'Submitted', 'Cancelled')
    """)
    frappe.db.commit()

    frappe.log_error(
        f"Fixed {count} Payment Entry records with invalid status values.",
        "Patch: fix_pe_invalid_status",
    )
