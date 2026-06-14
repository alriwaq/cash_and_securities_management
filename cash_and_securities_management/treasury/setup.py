"""
Setup functions for Cash and Securities Management app.
Called by Frappe during app installation and migration.

Install sequence:
  1. _cleanup_old_records()           — remove stale DocType / Workspace / Module Def
  2. _ensure_module_def()             — create 'Treasury' Module Def if missing
  3. _sync_all_doctypes()             — reload all DocType JSONs into the DB
  4. _sync_workspace()                — reload the Treasury workspace
  5. _install_fixtures()              — import Custom Fields, Number Cards, Charts
  6. _initialize_settings()           — create Treasury Settings singleton
  7. _create_custody_account_groups() — auto-create GL account groups and
                                        populate Treasury Settings fields

Account groups created (based on the ERPNext standard chart of accounts):

  Application of Funds (Assets)
    └── Current Assets
          └── Loans and Advances (Assets)       ← existing ERPNext group
                └── Employee Custody Advances   ← NEW  [root_type: Asset,
                                                         account_type: Custody]

  Source of Funds (Liabilities)
    └── Current Liabilities
          └── Accounts Payable                  ← existing ERPNext group
                └── Custodian Payables          ← NEW  [root_type: Liability,
                                                         account_type: Payable]

The account_type 'Custody' is a dedicated neutral type.
ERPNext normally only allows party_type/party on Receivable/Payable accounts,
but the CustodyGLEntry override (treasury/overrides/gl_entry.py) extends
validate_account() to also permit party entries on Custody accounts.
This lets a single account serve as both the advance (asset debit) and the
invoice settlement (credit), self-clearing without extra Settlement Entries.
"""
import os
import json
import frappe
from frappe import _


# ─── Public entry points ──────────────────────────────────────────────────────

def after_install():
    """Called once after the app is installed on a site via bench install-app."""
    _cleanup_old_records()
    _ensure_module_def()
    _sync_all_doctypes()
    _sync_workspace()
    _install_fixtures()
    _initialize_settings()
    _create_custody_account_groups()
    _fix_custody_account_types()
    frappe.db.commit()


def after_migrate():
    """Called after every bench migrate."""
    _cleanup_old_records()
    _ensure_module_def()
    _sync_all_doctypes()
    _sync_workspace()
    _install_fixtures()
    _initialize_settings()
    _create_custody_account_groups()
    _fix_custody_account_types()
    frappe.db.commit()


# ─── Account Group Auto-Creation ──────────────────────────────────────────────

def _create_custody_account_groups():
    """
    Auto-create the two GL account groups required by the Treasury module and
    populate the corresponding fields in Treasury Settings.

    Runs per-company so that multi-company sites get the groups in every
    company's chart of accounts. The function is fully idempotent — it skips
    creation when the groups already exist and only writes Treasury Settings
    when the fields are still blank.
    """
    if not frappe.db.exists("DocType", "Account"):
        # ERPNext not installed yet — skip silently
        return

    companies = frappe.get_all("Company", pluck="name")
    if not companies:
        return

    for company in companies:
        advance_group = _ensure_advance_group(company)
        payable_group = _ensure_payable_group(company)
        _populate_treasury_settings(advance_group, payable_group)


def _ensure_advance_group(company):
    """
    Ensure 'Employee Custody Advances' exists as a group account under
    'Loans and Advances (Assets)' in the given company's chart of accounts.

    This mirrors the placement of ERPNext's own 'Employee Advances' account.

    account_type = "Custody" is a dedicated type that excludes this group from
    standard AP/AR reports. In Consolidated mode the Party sub-ledger still
    works correctly because ERPNext allows any account_type to carry a party.

    Parent search order:
      1. 'Loans and Advances (Assets) - {abbr}'   (standard with abbreviation)
      2. 'Loans and Advances (Assets)'             (standard without abbreviation)
      3. Any Asset group whose name contains 'Loans and Advances'
      4. Any Asset group whose name contains 'loan' or 'advance'
      5. Root Current Assets group (last resort)

    Returns the account name (str) or None if creation failed.
    """
    abbr = frappe.db.get_value("Company", company, "abbr") or ""
    group_label = "Employee Custody Advances"
    group_name_with_abbr = f"{group_label} - {abbr}" if abbr else group_label

    # Already exists?
    if frappe.db.exists("Account", group_name_with_abbr):
        frappe.logger().info(
            f"[Treasury Setup] '{group_name_with_abbr}' already exists — skipping."
        )
        return group_name_with_abbr

    # ── Find the best parent ──────────────────────────────────────────────
    parent = _find_account_by_candidates(
        company=company,
        candidates=[
            f"Loans and Advances (Assets) - {abbr}",
            "Loans and Advances (Assets)",
        ],
    )

    if not parent:
        # Fallback: any Asset group whose name contains 'Loans and Advances'
        parent = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "root_type": "Asset",
                "is_group": 1,
                "account_name": ["like", "%Loans and Advances%"],
            },
            "name",
        )

    if not parent:
        # Fallback: any Asset group whose name contains 'loan' or 'advance'
        parent = frappe.db.sql(
            """SELECT name FROM `tabAccount`
               WHERE company = %s AND root_type = 'Asset' AND is_group = 1
                 AND (LOWER(account_name) LIKE '%%loan%%'
                      OR LOWER(account_name) LIKE '%%advance%%')
               LIMIT 1""",
            (company,),
        )
        parent = parent[0][0] if parent else None

    if not parent:
        # Absolute fallback: root Current Assets group
        parent = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "root_type": "Asset",
                "is_group": 1,
                "account_name": ["like", "%Current Asset%"],
            },
            "name",
        )

    if not parent:
        frappe.logger().warning(
            f"[Treasury Setup] Could not find 'Loans and Advances (Assets)' or any "
            f"suitable Asset parent for company '{company}'. "
            f"Skipping Employee Custody Advances creation."
        )
        return None

    try:
        acc = frappe.new_doc("Account")
        acc.account_name = group_label
        acc.parent_account = parent
        acc.is_group = 1
        acc.root_type = "Asset"
        acc.account_type = "Custody"   # Dedicated neutral type — see gl_entry.py override
        acc.company = company
        acc.flags.ignore_permissions = True
        acc.flags.ignore_mandatory = True
        acc.insert()
        frappe.logger().info(
            f"[Treasury Setup] Created '{acc.name}' under '{parent}' "
            f"for company '{company}'."
        )
        return acc.name
    except Exception as e:
        frappe.logger().error(
            f"[Treasury Setup] Failed to create Employee Custody Advances "
            f"for company '{company}': {e}"
        )
        return None


def _ensure_payable_group(company):
    """
    Ensure 'Custodian Payables' exists as a group account under
    'Accounts Payable' in the given company's chart of accounts.

    Parent search order:
      1. 'Accounts Payable - {abbr}'   (standard with abbreviation)
      2. 'Accounts Payable'            (standard without abbreviation)
      3. Any Liability group with account_type = 'Payable'
      4. Root Current Liabilities group (last resort)

    Returns the account name (str) or None if creation failed.
    """
    abbr = frappe.db.get_value("Company", company, "abbr") or ""
    group_label = "Custodian Payables"
    group_name_with_abbr = f"{group_label} - {abbr}" if abbr else group_label

    # Already exists?
    if frappe.db.exists("Account", group_name_with_abbr):
        frappe.logger().info(
            f"[Treasury Setup] '{group_name_with_abbr}' already exists — skipping."
        )
        return group_name_with_abbr

    # ── Find the best parent ──────────────────────────────────────────────
    parent = _find_account_by_candidates(
        company=company,
        candidates=[
            f"Accounts Payable - {abbr}",
            "Accounts Payable",
        ],
    )

    if not parent:
        # Fallback: any Liability group with account_type Payable
        parent = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "root_type": "Liability",
                "account_type": "Payable",
                "is_group": 1,
            },
            "name",
        )

    if not parent:
        # Fallback: any Liability group whose name contains 'payable'
        parent = frappe.db.sql(
            """SELECT name FROM `tabAccount`
               WHERE company = %s AND root_type = 'Liability' AND is_group = 1
                 AND LOWER(account_name) LIKE '%%payable%%'
               LIMIT 1""",
            (company,),
        )
        parent = parent[0][0] if parent else None

    if not parent:
        # Absolute fallback: root Current Liabilities group
        parent = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "root_type": "Liability",
                "is_group": 1,
                "account_name": ["like", "%Current Liabilit%"],
            },
            "name",
        )

    if not parent:
        frappe.logger().warning(
            f"[Treasury Setup] Could not find 'Accounts Payable' or any suitable "
            f"Liability parent for company '{company}'. "
            f"Skipping Custodian Payables creation."
        )
        return None

    try:
        acc = frappe.new_doc("Account")
        acc.account_name = group_label
        acc.parent_account = parent
        acc.is_group = 1
        acc.root_type = "Liability"
        acc.account_type = "Payable"
        acc.company = company
        acc.flags.ignore_permissions = True
        acc.flags.ignore_mandatory = True
        acc.insert()
        frappe.logger().info(
            f"[Treasury Setup] Created '{acc.name}' under '{parent}' "
            f"for company '{company}'."
        )
        return acc.name
    except Exception as e:
        frappe.logger().error(
            f"[Treasury Setup] Failed to create Custodian Payables "
            f"for company '{company}': {e}"
        )
        return None


def _fix_custody_account_types():
    """
    Idempotent repair that runs on every migrate.
    Ensures all accounts used as custody sub-ledgers have account_type = 'Custody'.

    Covers two cases:
      1. Individual-mode leaf accounts linked via tabCustodian.custody_account
         that may have 'Receivable', 'Payable', or blank type from earlier versions.
      2. The shared 'Employee Custody Advances' group account(s) which may have
         been created with a different type on older installs.

    The CustodyGLEntry override (treasury/overrides/gl_entry.py) handles ERPNext's
    restriction that party_type/party is normally only allowed on Receivable/Payable
    accounts, so the 'Custody' type works correctly for all GL entries.
    """
    if not frappe.db.exists("DocType", "Account"):
        return

    fixed = 0

    # ── Fix individual custodian leaf accounts ────────────────────────────────
    custodian_accounts = frappe.db.sql(
        """
        SELECT c.custody_account
        FROM `tabCustodian` c
        WHERE c.custody_account IS NOT NULL
          AND c.custody_account != ''
        """,
        as_dict=True,
    )
    for row in custodian_accounts:
        acct = row.get("custody_account")
        if not acct:
            continue
        current_type = frappe.db.get_value("Account", acct, "account_type")
        if current_type != "Custody":
            frappe.db.set_value(
                "Account", acct, "account_type", "Custody", update_modified=False
            )
            frappe.logger().info(
                f"[Treasury Setup] _fix_custody_account_types: '{acct}' "
                f"'{current_type}' → 'Custody'"
            )
            fixed += 1

    # ── Fix Employee Custody Advances group account(s) ────────────────────────
    advance_groups = frappe.db.get_all(
        "Account",
        filters={
            "account_name": "Employee Custody Advances",
            "is_group": 1,
            "root_type": "Asset",
        },
        fields=["name", "account_type"],
    )
    for row in advance_groups:
        if row.account_type != "Custody":
            frappe.db.set_value(
                "Account", row.name, "account_type", "Custody", update_modified=False
            )
            frappe.logger().info(
                f"[Treasury Setup] _fix_custody_account_types: group '{row.name}' "
                f"'{row.account_type}' → 'Custody'"
            )
            fixed += 1

    if fixed:
        frappe.logger().info(
            f"[Treasury Setup] _fix_custody_account_types: fixed {fixed} account(s)."
        )


def _find_account_by_candidates(company, candidates):
    """
    Try each name in `candidates` as an exact match in the Account table
    for the given company. Returns the first match found, or None.
    """
    for candidate in candidates:
        result = frappe.db.get_value(
            "Account",
            {"name": candidate, "company": company},
            "name",
        )
        if result:
            return result
    return None


def _populate_treasury_settings(advance_group, payable_group):
    """
    Write advance_group → custody_advance_group and
    payable_group → custodian_payable_group in Treasury Settings.

    Only writes when the field is currently blank — never overwrites
    a value the user has already configured.
    """
    if not frappe.db.exists("DocType", "Treasury Settings"):
        return

    try:
        current_advance = frappe.db.get_single_value(
            "Treasury Settings", "custody_advance_group"
        )
        current_payable = frappe.db.get_single_value(
            "Treasury Settings", "custodian_payable_group"
        )

        updates = {}
        if advance_group and not current_advance:
            updates["custody_advance_group"] = advance_group
        if payable_group and not current_payable:
            updates["custodian_payable_group"] = payable_group

        if updates:
            for field, value in updates.items():
                frappe.db.set_single_value("Treasury Settings", field, value)
            frappe.logger().info(
                f"[Treasury Setup] Populated Treasury Settings: {updates}"
            )
    except Exception as e:
        frappe.logger().error(
            f"[Treasury Setup] Failed to populate Treasury Settings: {e}"
        )


# ─── Existing helpers (unchanged) ────────────────────────────────────────────

def _cleanup_old_records():
    """Remove old DocType, Workspace, and Module Def records from previous module names."""
    if frappe.db.exists("DocType", "Cash and Securities Settings"):
        try:
            frappe.delete_doc(
                "DocType", "Cash and Securities Settings",
                force=True, ignore_permissions=True
            )
        except Exception:
            pass

    old_workspaces = frappe.get_all(
        "Workspace",
        filters={"module": ["in", ["Custody Management", "Cash and Securities Management"]]},
        pluck="name",
    )
    for ws_name in old_workspaces:
        try:
            frappe.delete_doc(
                "Workspace", ws_name, force=True, ignore_permissions=True
            )
        except Exception:
            pass

    for old_module in ["Custody Management", "Cash and Securities Management"]:
        if frappe.db.exists("Module Def", old_module):
            try:
                frappe.delete_doc(
                    "Module Def", old_module, force=True, ignore_permissions=True
                )
            except Exception:
                pass

    frappe.db.commit()


def _ensure_module_def():
    """Ensure the 'Treasury' Module Def record exists in the database."""
    if not frappe.db.exists("Module Def", "Treasury"):
        try:
            module_def = frappe.new_doc("Module Def")
            module_def.module_name = "Treasury"
            module_def.app_name = "cash_and_securities_management"
            module_def.flags.ignore_permissions = True
            module_def.flags.ignore_mandatory = True
            module_def.insert()
            frappe.db.commit()
            frappe.logger().info("Created Module Def: Treasury")
        except Exception as e:
            frappe.logger().error(f"Could not create Module Def Treasury: {e}")
    else:
        try:
            frappe.db.set_value(
                "Module Def", "Treasury", "app_name",
                "cash_and_securities_management"
            )
        except Exception:
            pass


def _sync_all_doctypes():
    """
    Force-sync all DocType JSON files from the app's doctype folder into the database.
    Uses frappe.reload_doc() which is the standard Frappe mechanism for syncing
    DocTypes from JSON files, even when Developer Mode is off.
    """
    doctypes_to_sync = [
        "treasury_settings",
        "custodian",
        "accountant_custody_item",
        "custody_settlement_entry",
        "custody_request",
        "accountant_custody",
    ]

    for dt_name in doctypes_to_sync:
        try:
            frappe.reload_doc(
                "treasury",
                "doctype",
                dt_name,
                force=True,
            )
            frappe.logger().info(f"reload_doc succeeded for: {dt_name}")
        except Exception as e:
            frappe.logger().error(f"reload_doc failed for {dt_name}: {e}")
            _sync_doctype_by_path(dt_name)

    frappe.db.commit()


def _sync_doctype_by_path(dt_name):
    """Fallback: import a DocType JSON directly by file path."""
    try:
        from frappe.modules.import_file import import_file_by_path

        app_path = frappe.get_app_path("cash_and_securities_management")
        json_path = os.path.join(app_path, "treasury", "doctype", dt_name, f"{dt_name}.json")

        if os.path.exists(json_path):
            import_file_by_path(json_path, force=True)
            frappe.logger().info(f"import_file_by_path succeeded for: {json_path}")
        else:
            frappe.logger().error(f"DocType JSON not found: {json_path}")
    except Exception as e:
        frappe.logger().error(f"import_file_by_path failed for {dt_name}: {e}")


def _sync_workspace():
    """Force-sync the Treasury workspace from the JSON file."""
    try:
        frappe.reload_doc(
            "treasury",
            "workspace",
            "treasury",
            force=True,
        )
        frappe.logger().info("reload_doc succeeded for Treasury workspace")
    except Exception as e:
        frappe.logger().error(f"reload_doc failed for Treasury workspace: {e}")
        try:
            from frappe.modules.import_file import import_file_by_path

            app_path = frappe.get_app_path("cash_and_securities_management")
            ws_path = os.path.join(
                app_path, "treasury", "workspace", "treasury", "treasury.json"
            )
            if os.path.exists(ws_path):
                import_file_by_path(ws_path, force=True)
                frappe.logger().info(f"import_file_by_path succeeded for workspace: {ws_path}")
        except Exception as e2:
            frappe.logger().error(f"Workspace import fallback also failed: {e2}")

    frappe.db.commit()


def _install_fixtures():
    """
    Import fixture JSON files (Custom Fields, Number Cards, Dashboard Charts).
    These are normally imported by Frappe's fixture mechanism, but we force-import
    them here as a safety net for production sites.
    """
    app_path = frappe.get_app_path("cash_and_securities_management")
    fixtures_dir = os.path.join(app_path, "fixtures")

    if not os.path.exists(fixtures_dir):
        return

    fixture_files = [
        "workflow_states.json",
        "treasury_vault_user_role.json",
        "cash_payment_vault_approval.json",
        "pe_workflow_custom_fields.json",
        "custom_field.json",
        "number_card.json",
        "dashboard_chart.json",
    ]

    for fixture_file in fixture_files:
        fixture_path = os.path.join(fixtures_dir, fixture_file)
        if not os.path.exists(fixture_path):
            continue

        try:
            with open(fixture_path, "r") as f:
                records = json.load(f)

            for record in records:
                doctype = record.get("doctype")
                name = record.get("name")
                if not doctype or not name:
                    continue

                if frappe.db.exists(doctype, name):
                    continue

                try:
                    doc = frappe.get_doc(record)
                    doc.flags.ignore_permissions = True
                    doc.flags.ignore_mandatory = True
                    doc.flags.ignore_links = True
                    doc.insert()
                    frappe.logger().info(f"Installed fixture: {doctype} - {name}")
                except Exception as e:
                    frappe.logger().warning(
                        f"Could not install fixture {doctype}/{name}: {e}"
                    )
        except Exception as e:
            frappe.logger().error(f"Error reading fixture file {fixture_file}: {e}")

    frappe.db.commit()


def _initialize_settings():
    """Initialize the Treasury Settings singleton if it does not exist."""
    doctype = "Treasury Settings"

    if not frappe.db.exists("DocType", doctype):
        frappe.logger().warning(
            f"DocType {doctype} not found in database after sync. "
            f"Check the treasury_settings.json file."
        )
        return

    try:
        existing = frappe.db.sql(
            "SELECT value FROM tabSingles WHERE doctype=%s AND field='creation' LIMIT 1",
            (doctype,),
        )
        if existing:
            return
    except Exception:
        pass

    try:
        doc = frappe.new_doc(doctype)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_mandatory = True
        doc.insert()
        frappe.db.commit()
        frappe.logger().info(f"Initialized {doctype} singleton.")
    except Exception as e:
        frappe.logger().warning(f"Could not initialize {doctype}: {e}")
