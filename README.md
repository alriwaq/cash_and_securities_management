# Cash and Securities Management

A custom ERPNext (v15.x) application for managing employee custody requests, accountant custody records, and the full procurement cycle integration.

---

## Overview

This app introduces two new independent doctypes that replace the standard Employee Advance and Expense Claim workflows for custody-based procurement:

| Doctype | Cloned From | Purpose |
| :--- | :--- | :--- |
| **Custody Request** | Employee Advance | Employee requests a cash advance for custody purchases |
| **Accountant Custody** | Expense Claim | Records items purchased, links to PR/PI, and settles the advance |

---

## Workflow

```
Custody Request (Employee)
        ↓ [Submit + Pay]
Accountant Custody (Employee)
        ↓ [Submit]
Purchase Receipt (Auto-created Draft)
        ↓ [Warehouse submits PR]
        ↓ [Click "Generate Invoice"]
Purchase Invoice (Auto-created Draft)
        ↓ [Accountant reviews & submits PI]
        ↓ [Click "Settle"]
Journal Entry (Auto-created & submitted)
        ↓
Status: Settled
```

---

## Status Flow

### Custody Request
`Draft` → `Unpaid` → `Paid` → `Partly Claimed` → `Claimed` → `Cancelled`

### Accountant Custody
`Draft` → `Submitted` → `Receiving` → `Fully Received` → `Invoiced` → `Settled` → `Cancelled`

---

## Settlement Types

| Type | Description | GL Entry |
| :--- | :--- | :--- |
| **Full Advance Settlement** | Entire PI amount from Custody Advance | Dr. Supplier Payable — Cr. Custody Advance Account |
| **Full Direct Payment** | Entire PI amount paid directly | Dr. Supplier Payable — Cr. Cash/Bank Account |
| **Mixed Settlement** | Part advance + part direct | Combination of both entries above |

---

## Installation

### Prerequisites
- ERPNext v15.x (v15.104 or later)
- Frappe Framework v15.x
- Python 3.10+

### Step 1: Install the App

```bash
# On your Frappe bench
cd /path/to/frappe-bench
bench get-app https://github.com/alriwaq/cash_and_securities_management
bench --site your-site.com install-app cash_and_securities_management
bench --site your-site.com migrate
```

### Step 2: Configure Global Settings

Navigate to **Cash and Securities Management → Cash and Securities Settings** and configure:

| Field | Description | Example |
| :--- | :--- | :--- |
| **Default Cash Purchases Supplier** | Dummy supplier for all custody PIs | `Cash Purchases` |
| **Custody Advance Account** | Asset account for employee advances | `Advance to Employees - Custody` |
| **Settlement Cash / Bank Account** | Account for direct payment settlements | `Petty Cash` |
| **Custody PR Series** | Naming series for custody PRs | `AC-PRE-.YYYY.-.#####` |
| **Custody PI Series** | Naming series for custody PIs | `AC-PINV-.YYYY.-.#####` |
| **Default Cost Center** | Default cost center | `Main - Company` |

### Step 3: Create the Dummy Supplier

1. Go to **Buying → Supplier → New**
2. Name: `Cash Purchases` (or your preferred name)
3. Supplier Group: `All Supplier Groups`
4. Set the **Default Payable Account** to your accounts payable account
5. Save

### Step 4: Create the Custody Advance Account

1. Go to **Accounting → Chart of Accounts**
2. Under **Current Assets**, create a new account:
   - Account Name: `Advance to Employees - Custody`
   - Account Type: `Receivable`
   - Is Group: No
3. Save

### Step 5: Add Custom Fields to PR and PI

Run the following bench command to apply the fixtures:

```bash
bench --site your-site.com import-fixtures --app cash_and_securities_management
```

This adds two custom fields to Purchase Receipt and Purchase Invoice:
- `custom_accountant_custody` — Link to Accountant Custody
- `custom_source_document_type` — Internal identifier

---

## Usage Guide

### Creating a Custody Request

1. Go to **Cash and Securities Management → Custody Request → New**
2. Select the **Employee**
3. Enter the **Purpose** and **Advance Amount**
4. Submit → Status becomes `Unpaid`
5. Process payment to employee → Status becomes `Paid`

### Creating an Accountant Custody

1. Go to **Cash and Securities Management → Accountant Custody → New**
2. Select the **Employee** — the system auto-links the first unpaid Custody Request
3. Add **Custody Items** (stock items, fixed assets, or services)
4. Submit → Status becomes `Submitted`; a draft **Purchase Receipt** is auto-created for stock/asset items

### Processing the Purchase Receipt

1. Open the auto-created **Purchase Receipt**
2. Verify received quantities (warehouse team)
3. Submit → Accountant Custody status updates to `Receiving` or `Fully Received`

### Generating the Purchase Invoice

1. Return to the **Accountant Custody** record
2. Click **Actions → Generate Invoice**
3. A draft **Purchase Invoice** is created with accepted quantities for stock items and full quantities for service items
4. Accountant reviews and adjusts service item quantities/rates if needed
5. Submit the PI → Accountant Custody status updates to `Invoiced`

### Settling the Custody

1. Return to the **Accountant Custody** record
2. Click **Actions → Settle**
3. Select the **Settlement Type**:
   - **Full Advance Settlement**: Uses the linked Custody Request advance
   - **Full Direct Payment**: Uses cash/bank directly
   - **Mixed Settlement**: Allocate amounts between advance and direct payment
4. Click **Settle** → A Journal Entry is auto-created and submitted
5. Status becomes `Settled`; Custody Request status updates to `Claimed` or `Partly Claimed`

---

## Cancellation Rules

| Document | Can Cancel When |
| :--- | :--- |
| **Custody Request** | No linked Accountant Custody records |
| **Accountant Custody** | Status is not `Settled`; no submitted PR or PI |
| **Purchase Receipt** | Before PI is generated |
| **Purchase Invoice** | Before Settlement is done |

---

## Roles & Permissions

| Role | Permissions |
| :--- | :--- |
| **Employee** | Create, Read, Write Custody Request and Accountant Custody |
| **Expense Approver** | Submit, Cancel, Amend all custody documents |
| **Accounts Manager** | Full access including settlement |
| **System Manager** | Full access including settings |

---

## Frappe Cloud Deployment

This app is fully compatible with Frappe Cloud. To deploy:

1. Push this repository to your GitHub account
2. In Frappe Cloud, go to your site → **Apps → Install App**
3. Enter the GitHub repository URL
4. Click **Install**
5. Run migrations from the Frappe Cloud dashboard

---

## Changelog

### v1.0.0 (2024)
- Initial release
- Custody Request doctype (Employee Advance clone)
- Accountant Custody doctype (Expense Claim clone)
- Accountant Custody Item child table
- Custody Settlement Entry child table
- Cash and Securities Settings (Global Settings)
- Auto PR creation on Accountant Custody submit
- Generate Invoice button
- Settlement dialog with 3 settlement types
- Auto JE creation on settlement
- Custody Request balance tracking
- PR/PI quantity sync hooks

---

## License

MIT
