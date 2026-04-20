# Technical Guide: Cloning DocTypes and Building Custom Apps

This guide explains the technical process of cloning a standard Frappe/ERPNext DocType, building a custom app around it, and managing custom fields. It covers the exact commands needed and the architectural reasoning behind each step.

---

## Why Clone Instead of Customize?

When extending ERPNext, you generally have two options:
1. **Customize standard DocTypes** (e.g., adding fields to Employee Advance).
2. **Clone into a custom app** (e.g., creating Custody Request based on Employee Advance).

**Why Cloning is the Best Practice:**
- **Isolation:** Standard updates to ERPNext will not break your custom workflow. If Frappe changes how Employee Advance works, your Custody Request remains unaffected.
- **Security:** You can assign entirely different roles and permissions to the cloned DocType without compromising the standard HR workflow.
- **Portability:** A custom app with its own DocTypes can be installed on any Frappe Cloud site without worrying about conflicting customizations on the target site.

---

## Step 1: Initializing the Custom App

Before cloning, you need a custom app to hold your new DocTypes.

### 1.1 Create the App
```bash
# Navigate to your bench directory
cd /path/to/frappe-bench

# Create the new app structure
bench new-app cash_and_securities_management
```
*Why this is necessary:* `bench new-app` generates the required folder structure, `hooks.py`, and module definitions. This ensures the app is recognized by the Frappe framework.

### 1.2 Add Frappe v15 Compatibility
Frappe v15 and Frappe Cloud require `pyproject.toml` instead of `setup.py` for installation.
Create `pyproject.toml` in the app root:
```toml
[project]
name = "cash_and_securities_management"
requires-python = ">=3.10"
dynamic = ["version"]

[build-system]
requires = ["flit_core >=3.4,<4"]
build-backend = "flit_core.buildapi"
```
*Why this is necessary:* Frappe Cloud uses the PEP 517 standard (`pyproject.toml`) to build and install the Python package. Without it, the installation will fail with a "Not a valid Frappe App" error.

### 1.3 Install on Development Site
```bash
bench --site your-site.com install-app cash_and_securities_management
```
*Why this is necessary:* The app must be installed on a site before you can create DocTypes within it.

---

## Step 2: Cloning the Target DocType

Instead of writing a complex JSON file from scratch, the most efficient way to clone a DocType is through the ERPNext UI in Developer Mode.

### 2.1 Enable Developer Mode
Edit your site's `site_config.json`:
```json
{
  "developer_mode": 1
}
```
*Why this is necessary:* Developer Mode allows you to create new DocTypes and automatically generates the `.json`, `.py`, and `.js` files in your app's directory.

### 2.2 The Cloning Process
1. Navigate to **DocType List** in your ERPNext instance.
2. Open the target DocType (e.g., `Employee Advance`).
3. Click **Menu → Duplicate**.
4. Name the new DocType (e.g., `Custody Request`).
5. Change the **Module** to your custom app (`Cash and Securities Management`).
6. Save the DocType.

*Why this is necessary:* Duplicating through the UI copies all standard fields, field types, and layout configurations perfectly. By changing the Module, Frappe saves the new files directly into your custom app folder instead of the core ERPNext folder.

---

## Step 3: Managing Custom Fields on Standard DocTypes

Often, your custom workflow needs to interact with standard DocTypes (e.g., linking a `Purchase Receipt` to your `Accountant Custody`). You must add Custom Fields to the standard DocTypes and export them.

### 3.1 Create the Custom Field
1. Go to **Customize Form**.
2. Select the standard DocType (e.g., `Purchase Receipt`).
3. Add a new row:
   - Label: `Accountant Custody`
   - Fieldname: `custom_accountant_custody`
   - Fieldtype: `Link`
   - Options: `Accountant Custody`
4. Click Update.

### 3.2 Export Fixtures
Custom fields are stored in the database, not in code. To include them in your app repository, you must export them as fixtures.

Add to your app's `hooks.py`:
```python
fixtures = [
    {
        "doctype": "Custom Field",
        "filters": [
            ["dt", "in", ["Purchase Receipt", "Purchase Invoice"]]
        ]
    }
]
```

Run the export command:
```bash
bench --site your-site.com export-fixtures
```
*Why this is necessary:* `export-fixtures` generates a JSON file (`fixtures/custom_field.json`) containing the database records for your custom fields. When you install the app on a new site, Frappe automatically imports this JSON, recreating the custom fields on the target site.

---

## Step 4: Version Control with Git

Once your app structure, cloned DocTypes, and fixtures are ready, you must commit them to Git for deployment.

### 4.1 Initialize Git
```bash
cd apps/cash_and_securities_management
git init
git config user.name "Your Name"
git config user.email "your.email@example.com"
```

### 4.2 Stage and Commit
```bash
git add .
git commit -m "feat: Initial app structure with cloned DocTypes and fixtures"
```
*Why this is necessary:* Committing captures the exact state of your `.json` schema files, Python controllers, and JavaScript logic.

### 4.3 Push to Remote Repository
```bash
# Add your GitHub repository as the origin
git remote add origin https://github.com/yourusername/cash_and_securities_management.git

# Push the code
git push -u origin master
```
*Why this is necessary:* Frappe Cloud pulls directly from your Git repository. Pushing your code ensures Frappe Cloud has access to the latest `pyproject.toml`, DocType definitions, and fixtures required for installation.

---

## Summary Checklist

1. **`bench new-app`** → Creates the framework.
2. **Add `pyproject.toml`** → Ensures Frappe Cloud compatibility.
3. **Developer Mode = 1** → Enables code generation.
4. **Duplicate DocType in UI** → Clones the schema safely.
5. **Export Fixtures** → Packages custom fields for deployment.
6. **Git Push** → Delivers the app to Frappe Cloud.
