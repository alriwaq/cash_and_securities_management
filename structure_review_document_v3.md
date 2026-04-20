# Cash and Securities Management - Structure Review Document v3

## 1. Executive Summary

This document outlines the architecture for the **Cash and Securities Management** custom app (v15.104), focusing on Phase 1.1: The integrated Custody Procurement Module. This module manages employee cash purchases, urgent field buying, mixed procurement (stock, assets, services), and settlement.

The solution uses custom business doctypes (`Custody Request` and `Accountant Custody`) while leveraging standard ERPNext Purchase Receipt, Purchase Invoice, Payment Entry, and Journal Entry documents for the accounting layer.

---

## 2. Core Doctypes

### 2.1 Custody Request (Independent Clone of Employee Advance)

**Purpose:** Allows an employee to request a cash advance for custody purchases before making them.

**Module:** Cash and Securities Management
**Is Submittable:** Yes
**Naming Series:** `CR-.YYYY.-.#####`

| Fieldname | Fieldtype | Label | Mandatory | Notes |
| :--- | :--- | :--- | :--- | :--- |
| `employee` | Link | Employee | Yes | Fetch: `employee_name` |
| `purpose` | Text | Purpose | Yes | |
| `advance_amount` | Currency | Advance Amount | Yes | |
| `advance_account` | Link | Advance Account | Yes | Options: Account (Asset) |
| `mode_of_payment` | Link | Mode of Payment | Yes | Options: Mode of Payment |
| `posting_date` | Date | Posting Date | Yes | Default: Today |
| `cost_center` | Link | Cost Center | Yes | Options: Cost Center |
| `project` | Link | Project | No | Options: Project |
| `status` | Select | Status | Yes | Draft, Unpaid, Paid, Claimed, Partly Claimed, Cancelled (Read Only) |
| `claimed_amount` | Currency | Claimed Amount | No | Auto-updated from settled Accountant Custody records (Read Only) |
| `remaining_balance` | Currency | Remaining Balance | No | `advance_amount - claimed_amount` (Read Only) |

### 2.2 Accountant Custody

**Purpose:** Records actual items purchased, manages the PR/PI cycle, and handles settlement against the Custody Request.

**Module:** Cash and Securities Management
**Is Submittable:** Yes
**Naming Series:** `AC-.YYYY.-.#####`

| Fieldname | Fieldtype | Label | Mandatory | Notes |
| :--- | :--- | :--- | :--- | :--- |
| `posting_date` | Date | Posting Date | Yes | Default: Today |
| `employee` | Link | Employee | Yes | Fetch: `employee_name` |
| `custody_request` | Link | Custody Request | No | Auto-links to first unpaid request |
| `project` | Link | Project | No | |
| `cost_center` | Link | Cost Center | Yes | |
| `accepted_warehouse` | Link | Accepted Warehouse | No | |
| `status` | Select | Status | Yes | Draft, Submitted, Receiving, Invoiced, Settled, Cancelled (Read Only) |
| `total_amount` | Currency | Total Amount | No | Sum of custody items (Read Only) |
| `purchase_invoice` | Link | Purchase Invoice | No | Link to generated PI (Read Only) |
| `custody_items` | Table | Custody Items | Yes | Options: Accountant Custody Item |
| `settlements` | Table | Settlements | No | Options: Custody Settlement Entry |

### 2.3 Accountant Custody Item (Child Table)

| Fieldname | Fieldtype | Label | Mandatory | Notes |
| :--- | :--- | :--- | :--- | :--- |
| `item_code` | Link | Item Code | Yes | Options: Item |
| `qty` | Float | Qty | Yes | Ordered Quantity |
| `rate` | Currency | Rate | Yes | |
| `amount` | Currency | Amount | Yes | `qty * rate` |
| `accepted_qty` | Float | Accepted Qty | No | Received from PR (Read Only) |
| `billed_qty` | Float | Billed Qty | No | Billed from PI (Read Only) |
| `warehouse` | Link | Warehouse | No | Mandatory if stock item |
| `asset_location` | Link | Asset Location | No | Mandatory if fixed asset |
| `is_stock_item` | Check | Is Stock Item | No | Fetch from item (Read Only) |
| `is_fixed_asset` | Check | Is Fixed Asset | No | Fetch from item (Read Only) |

### 2.4 Custody Settlement Entry (Child Table)

| Fieldname | Fieldtype | Label | Mandatory | Notes |
| :--- | :--- | :--- | :--- | :--- |
| `settlement_type` | Select | Settlement Type | Yes | Full Advance, Full Direct, Mixed |
| `settlement_date` | Date | Settlement Date | Yes | Default: Today |
| `advance_amount` | Currency | Advance Amount | No | Amount from Custody Request |
| `direct_payment_amount` | Currency | Direct Payment Amount| No | Amount paid directly |
| `total_settlement_amount`| Currency | Total Settlement Amount| Yes | `advance_amount + direct_payment_amount` |
| `settlement_je` | Link | Settlement JE | No | Options: Journal Entry (Read Only) |
| `settlement_notes` | Text | Settlement Notes | No | |

---

## 3. Custom Fields on Standard Doctypes

To link the standard accounting documents back to our custom flow, we will add the following custom fields via fixtures:

**Purchase Receipt & Purchase Invoice:**
- `custom_source_document_type` (Select: Standard, Custody)
- `custom_accountant_custody` (Link: Accountant Custody)

**Payment Entry:**
- `custom_accountant_custody` (Link: Accountant Custody)

---

## 4. Operational Rules and Workflows

### 4.1 Core Business Flow

1. **Custody Request** → Approval → Advance Payment (via Payment Entry).
2. **Accountant Custody** → Submitted → Auto-creates draft Purchase Receipt.
3. **Receiving** → Multiple Purchase Receipts allowed until stock/asset quantities are fully received. Status changes to "Receiving".
4. **Invoicing** → "Generate Invoice" button creates a single draft Purchase Invoice for cumulative receipted items + approved services. Status changes to "Invoiced".
5. **Settlement** → "Settle" button records settlement in child table and creates Journal Entry. Status changes to "Settled".

### 4.2 Service Items Handling
- Service lines do not require warehouse approval (PR).
- The accountant can adjust quantities/amounts for service items directly on the draft Purchase Invoice.
- Changes made on the PI automatically reflect back to the Accountant Custody (updating `billed_qty` and `amount`).

### 4.3 Settlement Options
- **Full Advance Settlement:** Entire PI amount paid from Custody Advance. JE: Dr. Supplier Payable — Cr. Custody Advance.
- **Full Direct Payment:** Entire PI amount paid directly. JE: Dr. Expense — Cr. Cash/Bank.
- **Mixed Settlement:** Part from Advance + Part direct. JE splits accordingly.
- Settlement auto-creates and auto-submits the Journal Entry.
- Fully allocated settlements update the linked Custody Request status to "Claimed".

### 4.4 Cancellation Governance
- Cancellation must be processed hierarchically from the latest step backward.
- Custody cancellation is only permitted if no downstream documents (PR, PI, JE) are active.
- Settlement cancellation reverses the JE and reopens the "Invoiced" status.
- PI cancellation reverses accounting entries and reopens invoiceable balances.
- PR cancellation reverses accepted quantities and reopens receivable balances.

### 4.5 Controls & Risk Reduction
- Only draft documents are auto-created; no accounting docs are auto-submitted.
- Duplicate prevention checks exist before creating PR/PI/JE.
- "Closed" status locks the document at the database level, preventing any further modifications or linked document creation.

---

**Please review this structure document. Once approved, I will generate all the JSON definitions, server scripts, and client scripts to complete the app.**
