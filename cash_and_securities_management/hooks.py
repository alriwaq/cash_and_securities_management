app_name = "cash_and_securities_management"
app_title = "Cash and Securities Management"
app_publisher = "Your Company"
app_description = "Custom ERPNext module for managing employee custody requests, accountant custody records, and procurement cycle integration."
app_email = "admin@yourcompany.com"
app_license = "MIT"
app_version = "1.0.0"

# ─── Required Apps ────────────────────────────────────────────────────────────
required_apps = ["frappe/erpnext"]

# ─── Install / Uninstall Hooks ────────────────────────────────────────────────
# after_install is called once after the app is installed on a site.
# We use it to auto-initialize the Cash and Securities Settings singleton so
# it is always present in the database and never raises DoesNotExistError.
after_install = "cash_and_securities_management.custody_management.setup.after_install"

# ─── Fixtures ─────────────────────────────────────────────────────────────────
# These fixtures are installed automatically when the app is installed on a site.
# They create the Workspace (sidebar module), Number Cards, and Dashboard Charts.
fixtures = [
    # Custom DocTypes — MUST be listed first so they exist before fixtures that depend on them
    {
        "doctype": "DocType",
        "filters": [
            ["module", "=", "Custody Management"]
        ]
    },
    # Custom fields added to standard ERPNext doctypes
    {
        "doctype": "Custom Field",
        "filters": [
            ["dt", "in", ["Purchase Receipt", "Purchase Invoice"]]
        ]
    },
    # Workspace — registers the module in the Frappe sidebar
    {
        "doctype": "Workspace",
        "filters": [
            ["module", "=", "Custody Management"]
        ]
    },
    # Number Cards — dashboard KPI tiles
    {
        "doctype": "Number Card",
        "filters": [
            ["module", "=", "Custody Management"]
        ]
    },
    # Dashboard Charts — visual charts on the workspace
    {
        "doctype": "Dashboard Chart",
        "filters": [
            ["module", "=", "Custody Management"]
        ]
    },
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
