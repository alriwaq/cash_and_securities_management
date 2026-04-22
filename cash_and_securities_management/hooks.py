app_name = "cash_and_securities_management"
app_title = "Cash and Securities Management"
app_publisher = "Your Company"
app_description = "Custom ERPNext module for managing employee custody requests, accountant custody records, and procurement cycle integration."
app_email = "admin@yourcompany.com"
app_license = "MIT"
app_version = "1.0.0"

# ─── Required Apps ────────────────────────────────────────────────────────────
required_apps = ["frappe/erpnext"]

# ─── Install / Migrate Hooks ─────────────────────────────────────────────────
# after_install is called once after the app is installed on a site.
# after_migrate is called after every bench migrate.
# Both ensure DocTypes, Workspace, and Settings are properly synced
# even when Developer Mode is off (e.g., on Frappe Cloud production sites).
after_install = "cash_and_securities_management.treasury.setup.after_install"
after_migrate = "cash_and_securities_management.treasury.setup.after_migrate"

# ─── Fixtures ─────────────────────────────────────────────────────────────────
# Custom fields added to standard ERPNext doctypes.
# NOTE: Workspace, Number Cards, and Dashboard Charts are synced via
# setup.py (after_install / after_migrate) using frappe.reload_doc()
# to ensure they work on production sites without Developer Mode.
fixtures = [
    {
        "doctype": "Custom Field",
        "filters": [
            ["dt", "in", ["Purchase Receipt", "Purchase Invoice"]],
            [
                "fieldname",
                "in",
                [
                    "custom_accountant_custody",
                    "custom_source_document_type",
                ],
            ],
        ]
    },
]

# ─── Document Events ──────────────────────────────────────────────────────────
# Hook into Purchase Receipt and Purchase Invoice to keep Accountant Custody in sync
doc_events = {
    "Purchase Receipt": {
        "validate": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_pr_validate",
        "on_submit": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_pr_submit",
        "on_cancel": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_pr_cancel",
    },
    "Purchase Invoice": {
        "validate": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_pi_validate",
        "on_submit": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_pi_submit",
        "on_cancel": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_pi_cancel",
    },
}

# ─── Scheduled Tasks ──────────────────────────────────────────────────────────
# (Add scheduled tasks here if needed in future phases)

# ─── Website ──────────────────────────────────────────────────────────────────
# No website routes needed for this module

# ─── Permissions ──────────────────────────────────────────────────────────────
# Additional permission rules can be added here if needed
