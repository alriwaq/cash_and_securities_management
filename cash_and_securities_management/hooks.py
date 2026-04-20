app_name = "cash_and_securities_management"
app_title = "Cash and Securities Management"
app_publisher = "Your Company"
app_description = "Custom ERPNext module for managing employee custody requests, accountant custody records, and procurement cycle integration."
app_email = "admin@yourcompany.com"
app_license = "MIT"
app_version = "1.0.0"

# ─── Required Apps ────────────────────────────────────────────────────────────
required_apps = ["frappe/erpnext"]

# ─── Fixtures ─────────────────────────────────────────────────────────────────
# Export custom fields on standard DocTypes for deployment
fixtures = [
    {
        "doctype": "Custom Field",
        "filters": [
            ["dt", "in", ["Purchase Receipt", "Purchase Invoice"]]
        ]
    }
]

# ─── Document Events ──────────────────────────────────────────────────────────
# Hook into Purchase Receipt and Purchase Invoice to keep Accountant Custody in sync
doc_events = {
    "Purchase Receipt": {
        "validate": "cash_and_securities_management.custody_management.doctype.accountant_custody.pr_hooks.on_pr_validate",
        "on_submit": "cash_and_securities_management.custody_management.doctype.accountant_custody.pr_hooks.on_pr_submit",
        "on_cancel": "cash_and_securities_management.custody_management.doctype.accountant_custody.pr_hooks.on_pr_cancel",
    },
    "Purchase Invoice": {
        "validate": "cash_and_securities_management.custody_management.doctype.accountant_custody.pr_hooks.on_pi_validate",
        "on_submit": "cash_and_securities_management.custody_management.doctype.accountant_custody.pr_hooks.on_pi_submit",
        "on_cancel": "cash_and_securities_management.custody_management.doctype.accountant_custody.pr_hooks.on_pi_cancel",
    },
}

# ─── Scheduled Tasks ──────────────────────────────────────────────────────────
# (Add scheduled tasks here if needed in future phases)
# scheduler_events = {
#     "daily": [
#         "cash_and_securities_management.tasks.daily"
#     ]
# }

# ─── Website ──────────────────────────────────────────────────────────────────
# No website routes needed for this module

# ─── Permissions ──────────────────────────────────────────────────────────────
# Additional permission rules can be added here if needed
