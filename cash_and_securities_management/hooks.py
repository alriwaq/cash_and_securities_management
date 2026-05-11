app_name = "cash_and_securities_management"
app_title = "Cash and Securities Management"
app_publisher = "Your Company"
app_description = "Custom ERPNext module for managing employee custody requests, accountant custody records, and procurement cycle integration."
app_email = "admin@yourcompany.com"
app_license = "MIT"
app_version = "2.0.0"

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
    # ── Custom Fields on Purchase Receipt ────────────────────────────────────
    {
        "doctype": "Custom Field",
        "filters": [
            ["dt", "=", "Purchase Receipt"],
            [
                "fieldname",
                "in",
                [
                    "custom_accountant_custody",
                    "custom_custodian",
                    "custom_source_document_type",
                ],
            ],
        ],
    },
    # ── Custom Fields on Purchase Invoice ────────────────────────────────────
    {
        "doctype": "Custom Field",
        "filters": [
            ["dt", "=", "Purchase Invoice"],
            [
                "fieldname",
                "in",
                [
                    "custom_accountant_custody",
                    "custom_custodian",
                    "custom_custody_request",
                    "custom_source_document_type",
                ],
            ],
        ],
    },
    # ── Custom Fields on Payment Entry ───────────────────────────────────────
    {
        "doctype": "Custom Field",
        "filters": [
            ["dt", "=", "Payment Entry"],
            [
                "fieldname",
                "in",
                [
                    "custom_custody_request",
                    "custom_custodian",
                ],
            ],
        ],
    },
    # ── Custom Fields on Journal Entry ───────────────────────────────────────
    {
        "doctype": "Custom Field",
        "filters": [
            ["dt", "=", "Journal Entry"],
            [
                "fieldname",
                "in",
                [
                    "custom_accountant_custody",
                    "custom_custodian",
                ],
            ],
        ],
    },
    # ── Party Type: Custodian ─────────────────────────────────────────────────
    {
        "doctype": "Party Type",
        "filters": [
            ["name", "=", "Custodian"]
        ],
    },
]

# ─── Client Scripts on Standard Doctypes ────────────────────────────────────
# Keep PR/PI in standard lists; custody mode changes only the form behavior.
doctype_js = {
    "Purchase Receipt": "public/js/purchase_receipt_custody.js",
    "Purchase Invoice": "public/js/purchase_invoice_custody.js",
}

# ─── Doctype Class Overrides ────────────────────────────────────────────────
# Custody mode uses standard PR/PI doctypes with conditional server behavior.
override_doctype_class = {
    "Purchase Receipt": "cash_and_securities_management.treasury.overrides.purchase_receipt.CustodyPurchaseReceipt",
    "Purchase Invoice": "cash_and_securities_management.treasury.overrides.purchase_invoice.CustodyPurchaseInvoice",
}

# ─── Document Events ──────────────────────────────────────────────────────────
# Hook into Purchase Receipt, Purchase Invoice, Payment Entry, and Journal Entry
# to keep Accountant Custody, Custody Request, and Custodian balances in sync.
doc_events = {
    "Purchase Receipt": {
        "validate": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_pr_validate",
        "before_submit": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_pr_before_submit",
        "on_submit": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_pr_submit",
        "on_cancel": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_pr_cancel",
    },
    "Purchase Invoice": {
        "validate": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_pi_validate",
        "before_submit": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_pi_before_submit",
        "on_submit": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_pi_submit",
        "on_cancel": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_pi_cancel",
    },
    "Payment Entry": {
        "on_submit": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_payment_submit",
        "on_cancel": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_payment_cancel",
    },
    "Journal Entry": {
        "on_submit": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_journal_submit",
        "on_cancel": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_journal_cancel",
    },
}

# ─── Scheduled Tasks ──────────────────────────────────────────────────────────
# (Add scheduled tasks here if needed in future phases)

# ─── Website ──────────────────────────────────────────────────────────────────
# No website routes needed for this module

# ─── Permissions ──────────────────────────────────────────────────────────────
# Additional permission rules can be added here if needed
