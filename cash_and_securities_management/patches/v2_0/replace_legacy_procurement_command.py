import frappe


TARGET = "procurement_customizations.api.validate_custody_receipt_qty"
REPLACEMENT = "cash_and_securities_management.api.validate_custody_receipt_qty"


def execute():
    updated = 0

    for doctype, fieldname in [
        ("Client Script", "script"),
        ("Server Script", "script"),
        ("Custom Script", "script"),
    ]:
        if not frappe.db.exists("DocType", doctype):
            continue

        rows = frappe.get_all(
            doctype,
            filters={fieldname: ["like", f"%{TARGET}%"]},
            fields=["name", fieldname],
            limit_page_length=0,
        )

        for row in rows:
            current = row.get(fieldname) or ""
            replaced = current.replace(TARGET, REPLACEMENT)
            if replaced != current:
                frappe.db.set_value(
                    doctype,
                    row.name,
                    fieldname,
                    replaced,
                    update_modified=False,
                )
                updated += 1

    if updated:
        frappe.db.commit()
        frappe.logger().info(
            "replace_legacy_procurement_command: updated %s script record(s)", updated
        )
    else:
        frappe.logger().info("replace_legacy_procurement_command: no legacy command references found")
