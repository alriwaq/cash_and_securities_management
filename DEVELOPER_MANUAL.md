# Developer Manual: Frappe App Customization

This manual provides a comprehensive guide for developers working with the **Cash and Securities Management** app and outlines the standard procedures for creating new custom Frappe/ERPNext applications from scratch.

## 1. Editing the Cash and Securities Management App

The Cash and Securities Management app is built on the Frappe framework and integrates with ERPNext v15.x. It follows the standard Frappe app directory structure.

### 1.1 App Structure Overview

When you navigate to the app directory (`cash_and_securities_management/`), you will find the following structure:

```text
cash_and_securities_management/
├── cash_and_securities_management/
│   ├── doctype/                  # Contains all custom DocTypes
│   │   ├── accountant_custody/
│   │   ├── custody_request/
│   │   └── ...
│   ├── fixtures/                 # Exported custom fields and configurations
│   ├── hooks.py                  # Event hooks, fixtures list, and app metadata
│   ├── modules.txt               # Declares the app's modules
│   └── patches.txt               # Database migration patches
├── requirements.txt              # Python dependencies
└── setup.py                      # Package installation script
```

### 1.2 Modifying DocTypes

To modify existing DocTypes like `Custody Request` or `Accountant Custody`, you can use the Frappe framework's built-in tools or edit the JSON files directly.

**Using the UI (Recommended):**
1. Log in to your ERPNext instance as an Administrator.
2. Ensure you are in Developer Mode. Add `"developer_mode": 1` to your `site_config.json`.
3. Navigate to **DocType List** and open the DocType you wish to edit.
4. Add, remove, or modify fields as needed.
5. Click **Save**. The changes will automatically sync to the corresponding `.json` file in the app directory.

**Editing JSON Directly:**
If you prefer editing the JSON files directly (e.g., `accountant_custody.json`), you must reload the DocType in the system after making changes. You can do this by running:
```bash
bench --site your-site.com migrate
```

### 1.3 Modifying Business Logic (Python & JavaScript)

**Server-Side Logic (Python):**
Server-side validation, state changes, and database operations are handled in the Python controller files (e.g., `accountant_custody.py`).

*   **Document Events:** Methods like `validate()`, `on_submit()`, and `on_cancel()` define the document lifecycle.
*   **External Hooks:** The app uses `hooks.py` to listen to events on standard ERPNext DocTypes. For example, when a `Purchase Receipt` is submitted, the `on_pr_submit` function in `pr_hooks.py` is triggered to update the corresponding `Accountant Custody` record.

**Client-Side Logic (JavaScript):**
UI interactions, field calculations, and button actions are managed in the JavaScript files (e.g., `accountant_custody.js`).

*   **Form Events:** Use `frappe.ui.form.on()` to bind functions to events like `refresh`, `setup`, or specific field changes.
*   **Server Calls:** Use `frappe.call()` to execute Python methods from the client side.

### 1.4 Exporting Custom Fields

If you add custom fields to standard ERPNext DocTypes (like `Purchase Receipt` or `Purchase Invoice`) via the UI, you must export them as fixtures so they are included in the app repository.

1. Ensure the DocType is listed in the `fixtures` array in `hooks.py`:
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
2. Run the export command:
   ```bash
   bench --site your-site.com export-fixtures
   ```
   This will update the `fixtures/custom_field.json` file.

---

## 2. Creating a New Custom Frappe App

When the requirements exceed simple customizations and require isolated business logic, creating a new custom app is the best practice.

### 2.1 Initializing the App

1. Navigate to your Frappe bench directory:
   ```bash
   cd /path/to/frappe-bench
   ```
2. Create the new app structure using the bench CLI:
   ```bash
   bench new-app my_custom_app
   ```
   The CLI will prompt you for the App Title, Description, Publisher, Email, and License.

### 2.2 Installing the App on a Site

Before you can develop within the app, it must be installed on your development site.

```bash
bench --site your-site.com install-app my_custom_app
```

### 2.3 Creating Custom DocTypes

1. Ensure Developer Mode is enabled in your `site_config.json`:
   ```json
   {
     "developer_mode": 1
   }
   ```
2. In the ERPNext UI, go to **DocType List** → **Add DocType**.
3. Name your DocType and select your custom app (`my_custom_app`) in the **Module** field.
4. Define your fields, naming rules, and permissions.
5. Check the **Is Submittable** box if the document requires an approval workflow.
6. Click **Save**. Frappe will generate the `.json`, `.py`, and `.js` files in your app's directory.

### 2.4 Implementing Hooks

To interact with standard ERPNext processes without modifying core files, use `hooks.py`.

1. Open `my_custom_app/my_custom_app/hooks.py`.
2. Locate the `doc_events` dictionary.
3. Map standard DocType events to your custom Python methods:
   ```python
   doc_events = {
       "Sales Invoice": {
           "on_submit": "my_custom_app.my_custom_app.overrides.sales_invoice.on_submit"
       }
   }
   ```

### 2.5 Version Control and Deployment

1. Initialize a Git repository in your app directory:
   ```bash
   cd apps/my_custom_app
   git init
   git add .
   git commit -m "Initial commit"
   ```
2. Push the repository to GitHub, GitLab, or your preferred Git host.
3. To deploy the app to a production server or Frappe Cloud:
   *   Fetch the app from the repository: `bench get-app https://github.com/yourusername/my_custom_app.git`
   *   Install it on the production site: `bench --site prod-site.com install-app my_custom_app`
   *   Run migrations: `bench --site prod-site.com migrate`

By following these guidelines, you can ensure that your customizations remain maintainable, upgrade-safe, and cleanly separated from the core ERPNext codebase.
