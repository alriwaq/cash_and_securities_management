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
                    "custom_accountant_custody",
                    "custom_source_document_type",
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
    # ── Script Reports: Custody ───────────────────────────────────────────────
    {
        "doctype": "Report",
        "filters": [
            ["name", "in", [
                "Custody Ledger",
                "Custody Purchased Items",
                "Custodian Balance Summary",
            ]],
        ],
    },
    # ── V4: workflow_state custom field on Payment Entry (exported from DB after first install)
    # The actual field is created via fixtures/pe_workflow_custom_fields.json on first migrate
    {
        "doctype": "Custom Field",
        "filters": [
            ["dt", "=", "Payment Entry"],
            ["fieldname", "=", "workflow_state"],
        ],
    },
    # NOTE: Treasury Vault User role and Cash Payment Vault Approval workflow are
    # imported from fixtures/treasury_vault_user_role.json and
    # fixtures/cash_payment_vault_approval.json respectively.
    # They do NOT need filter-based export entries here.
]

# ─── Client Scripts on Standard Doctypes ────────────────────────────────────
# Keep PR/PI in standard lists; custody mode changes only the form behavior.
doctype_js = {
    "Purchase Receipt": "public/js/purchase_receipt_custody.js",
    "Purchase Invoice": "public/js/purchase_invoice_custody.js",
}

# ─── Whitelisted Method Overrides ────────────────────────────────────────────
override_whitelisted_methods = {
    "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice":
        "cash_and_securities_management.api.make_purchase_invoice",
}

# ─── Doctype Class Overrides ────────────────────────────────────────────────
# Custody mode uses standard PR/PI/PE doctypes with conditional server behavior.
override_doctype_class = {
    "Purchase Receipt": "cash_and_securities_management.treasury.overrides.purchase_receipt.CustodyPurchaseReceipt",
    "Purchase Invoice": "cash_and_securities_management.treasury.overrides.purchase_invoice.CustodyPurchaseInvoice",
    "Payment Entry": "cash_and_securities_management.treasury.overrides.payment_entry.CustodyPaymentEntry",
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
        "before_submit": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_payment_before_submit",
        "on_submit": [
            "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_payment_submit",
            # V4: fallback VPI creation for non-workflow cash PEs
            "cash_and_securities_management.treasury.doctype.vault_pending_item.vault_pending_hooks.on_payment_entry_submit",
        ],
        "on_cancel": [
            "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_payment_cancel",
            # V4: cancel linked Vault Pending Item
            "cash_and_securities_management.treasury.doctype.vault_pending_item.vault_pending_hooks.on_payment_entry_cancel",
        ],
        # V4: workflow action hook — fires when AP clerk sends PE for vault approval
        "on_workflow_action": "cash_and_securities_management.treasury.doctype.vault_pending_item.vault_pending_hooks.on_payment_entry_workflow_action",
    },
    "Expense Claim": {
        # V4: create Outbound Vault Pending Item for cash expense claims
        "on_submit": "cash_and_securities_management.treasury.doctype.vault_pending_item.vault_pending_hooks.on_expense_claim_submit",
    },
    "Journal Entry": {
        "on_submit": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_journal_submit",
        "on_cancel": "cash_and_securities_management.treasury.doctype.accountant_custody.pr_hooks.on_journal_cancel",
    },
    "GL Entry": {
        "before_insert": "cash_and_securities_management.api.fix_custody_gl_entry",
    },
}

# ─── Scheduled Tasks ──────────────────────────────────────────────────────────
# (Add scheduled tasks here if needed in future phases)

# ─── Website ──────────────────────────────────────────────────────────────────
# No website routes needed for this module

# ─── Permissions ──────────────────────────────────────────────────────────────
# Additional permission rules can be added here if needed
