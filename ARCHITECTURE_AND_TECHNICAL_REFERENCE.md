# Architecture and Technical Reference
**App:** Cash and Securities Management (v1.0.0)
**Framework:** Frappe / ERPNext v15
**Module:** Custody Management

This document provides a comprehensive technical breakdown of the custom app, detailing the architecture, data flow, custom scripts, and integration points with standard ERPNext modules. It serves as the primary reference for developers maintaining or extending the system.

---

## 1. System Architecture

The application is built as a standalone Frappe app that integrates tightly with the standard ERPNext Buying and Accounting modules. It introduces a two-tier custody workflow designed to replace standard Employee Advances and Expense Claims with a system specifically tailored for procurement and cash purchases.

### 1.1 Core Doctypes

| DocType | Type | Purpose |
| :--- | :--- | :--- |
| **Cash and Securities Settings** | Single | Global configuration for default accounts, dummy supplier, and naming series. |
| **Custody Request** | Document | Replaces Employee Advance. Tracks cash requested by an employee, the amount paid out, and the remaining balance available for purchases. |
| **Accountant Custody** | Document | Replaces Expense Claim. Records actual items purchased. Acts as the central hub that auto-generates Purchase Receipts (PR) and Purchase Invoices (PI). |
| **Accountant Custody Item** | Child Table | Tracks individual items, comparing ordered quantity against accepted (PR) and billed (PI) quantities. |
| **Custody Settlement Entry** | Child Table | Records the final settlement of an Accountant Custody, splitting payments between the Custody Advance and direct cash/bank payments. |

### 1.2 Data Flow Diagram

1. **Request Phase:** Employee submits a `Custody Request`. Accountant approves and creates a Payment Entry to disburse cash.
2. **Purchase Phase:** Employee purchases items and submits an `Accountant Custody`.
3. **Receiving Phase:** System auto-creates a draft `Purchase Receipt`. Warehouse team receives items, updating `accepted_qty` on the Custody.
4. **Invoicing Phase:** Accountant clicks "Generate Invoice", creating a draft `Purchase Invoice`. Edits to service items on the PI update `billed_qty` and `rate` on the Custody.
5. **Settlement Phase:** Accountant clicks "Settle". System generates a `Journal Entry` crediting the advance account and debiting the supplier payable, closing the loop.

---

## 2. Server-Side Logic (Python)

The backend logic is entirely encapsulated within the custom app, avoiding any modifications to core ERPNext files.

### 2.1 Shared Utilities (`utils.py`)
Because Frappe Single doctypes raise a `DoesNotExistError` if they have never been saved, the app uses a safe wrapper function:
- `get_settings()`: Checks if the `Cash and Securities Settings` record exists. If not, it auto-initializes it with empty defaults. This prevents crashes when users open forms before configuring the app.

### 2.2 Custody Request Controller (`custody_request.py`)
- **`set_defaults_from_settings()`**: Auto-populates advance account and cost center from global settings.
- **`update_claimed_amount()`**: Called by Accountant Custody upon settlement. Calculates the total settled amount across all linked custodies and updates the `remaining_balance` and `status` (Paid → Partly Claimed → Claimed).
- **`validate_no_linked_documents()`**: Prevents cancellation if any active Accountant Custody records are linked.

### 2.3 Accountant Custody Controller (`accountant_custody.py`)
This is the heaviest controller in the app, managing the orchestration of standard ERPNext buying documents.
- **`auto_link_custody_request()`**: Automatically finds and links the oldest unpaid Custody Request for the selected employee.
- **`create_purchase_receipt()`**: Triggered `on_submit`. Filters out service items and generates a draft PR for stock/asset items.
- **`generate_purchase_invoice()`**: Whitelisted method called via UI button. Generates a draft PI for all items based on their `accepted_qty` (for stock) or `qty` (for services).
- **`create_settlement()`**: Whitelisted method called via UI button. Generates a Journal Entry to clear the PI liability against the Custody Advance account, and appends a record to the `settlements` child table.
- **`update_received_quantities()` / `update_billed_quantities()`**: Callbacks triggered by standard ERPNext document events to keep the Custody Item table synchronized with actual PR/PI states.

### 2.4 Document Hooks (`pr_hooks.py` & `hooks.py`)
The app uses Frappe `doc_events` to listen to standard ERPNext documents without modifying core code.
- **Purchase Receipt Events**: `on_submit` and `on_cancel` trigger `update_received_quantities()` on the linked Accountant Custody. `validate` ensures PR quantities do not exceed the remaining allowed custody quantities.
- **Purchase Invoice Events**: `on_submit` and `on_cancel` trigger `update_billed_quantities()`. `validate` pushes rate and quantity changes for service items back to the Accountant Custody.

---

## 3. Client-Side Logic (JavaScript)

The frontend logic manages UI state, button visibility, and user dialogs.

### 3.1 Accountant Custody (`accountant_custody.js`)
- **Status Formatting**: Uses `frappe.utils.guess_style` to color-code statuses (e.g., Green for Settled, Blue for Submitted).
- **Action Buttons**: 
  - "Generate Invoice": Visible only when status is Receiving or Fully Received.
  - "Settle": Visible only when status is Invoiced. Opens a custom Frappe Dialog.
- **Settlement Dialog**: Prompts the user to select a Settlement Type (Full Advance, Full Direct, Mixed) and dynamically shows/hides the advance and direct payment amount fields. Validates that the sum equals the total billed amount before calling the backend `create_settlement` method.

### 3.2 Custody Request (`custody_request.js`)
- **Read-Only Logic**: Makes the form read-only once the status progresses past Draft.
- **Calculations**: Auto-calculates `remaining_balance` whenever the advance amount changes.

---

## 4. Database Schema and Fixtures

### 4.1 Custom Fields (`fixtures/custom_field.json`)
The app injects custom fields into standard ERPNext Buying documents to establish foreign key relationships:
- `custom_accountant_custody` (Link): Added to Purchase Receipt and Purchase Invoice.
- `custom_source_document_type` (Data): Added to identify documents generated by the custody workflow.

### 4.2 Workspace and Dashboards
To ensure the module appears in the Frappe sidebar, the app includes several UI fixtures:
- **Workspace** (`custody_management.json`): Defines the sidebar entry, shortcuts, link cards, and layout.
- **Number Cards** (`number_card.json`): Defines the 4 KPI tiles (Open Custodies, Pending Settlement, etc.) using JSON filters.
- **Dashboard Charts** (`dashboard_chart.json`): Defines the Donut and Bar charts for visualizing custody statuses and monthly volumes.

---

## 5. GL Entry Mapping

Understanding the accounting impact is critical. The app relies on standard ERPNext for inventory ledgers and only manages the custody advance clearing.

| Action | Document | Debit | Credit |
| :--- | :--- | :--- | :--- |
| **Disburse Cash** | Payment Entry (Manual) | Custody Advance (Asset) | Cash / Bank |
| **Receive Items** | Purchase Receipt (Auto) | Stock In Hand | Stock Received But Not Billed |
| **Generate Invoice**| Purchase Invoice (Auto) | Stock Received But Not Billed | Supplier Payable (Liability) |
| **Settle (Advance)**| Journal Entry (Auto) | Supplier Payable (Liability) | Custody Advance (Asset) |
| **Settle (Direct)** | Journal Entry (Auto) | Supplier Payable (Liability) | Settlement Expense / Bank |

---

## 6. Troubleshooting Guide

**Issue:** "DocType Cash and Securities Settings not found"
**Cause:** The Single doctype record was never initialized in the database.
**Solution:** The app now uses `get_settings()` in `utils.py` to auto-initialize this. If it recurs, ensure `utils.py` is properly imported in the controller.

**Issue:** Cannot install on Frappe Cloud ("Not a valid Frappe App")
**Cause:** Missing `pyproject.toml`.
**Solution:** The app root must contain `pyproject.toml` configured with `flit_core` as the build backend, which is standard for Frappe v15.

**Issue:** Module does not appear in sidebar
**Cause:** Missing Workspace fixture.
**Solution:** Run `bench migrate` to ensure the Workspace, Number Card, and Dashboard Chart fixtures are imported into the database.

**Issue:** "Cannot create a Purchase Receipt against a Settled Accountant Custody"
**Cause:** The `pr_hooks.py` validation prevents modifying standard documents once the custody loop is closed.
**Solution:** Cancel the settlement Journal Entry and the Accountant Custody settlement row before modifying the PR/PI.
