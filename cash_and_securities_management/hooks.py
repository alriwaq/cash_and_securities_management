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
# Both ensure the Treasury Settings singleton record is always present
# and clean up any old records from previous module names.
after_install = "cash_and_securities_management.treasury.setup.after_install"
after_migrate = "cash_and_securities_management.treasury.setup.after_migrate"

# ─── Fixtures ─────────────────────────────────────────────────────────────────
# NOTE: DocTypes are force-synced via setup.py (after_install / after_migrate)
# using import_file_by_path() to ensure they are imported even when
# Developer Mode is off (e.g., on Frappe Cloud production sites).
# Fixtures below are for data records (Custom Fields, Workspaces, etc.)
fixtures = [
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
            ["module", "=", "Treasury"]
        ]
    },
    # Number Cards — dashboard KPI tiles
    {
        "doctype": "Number Card",
        "filters": [
            ["module", "=", "Treasury"]
        ]
    },
    # Dashboard Charts — visual charts on the workspace
    {
        "doctype": "Dashboard Chart",
        "filters": [
            ["module", "=", "Treasury"]
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
