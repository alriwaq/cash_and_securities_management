# Custody & Vault — Workflow Reference

> Module: `cash_and_securities_management` | ERPNext v14/v15  
> Last reviewed: 2026-06-07

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Setup & Configuration](#2-setup--configuration)
3. [Custody Workflow](#3-custody-workflow)
   - 3.1 [Custodian Setup](#31-custodian-setup)
   - 3.2 [Stage 1 — Custody Request (Advance)](#32-stage-1--custody-request-advance)
   - 3.3 [Stage 2 — Accountant Custody (Spending)](#33-stage-2--accountant-custody-spending)
   - 3.4 [Stage 3 — Settlement](#34-stage-3--settlement)
   - 3.5 [Custody Status State Machine](#35-custody-status-state-machine)
4. [Vault / Treasury Cash Journal Workflow](#4-vault--treasury-cash-journal-workflow)
   - 4.1 [Treasury Station Setup](#41-treasury-station-setup)
   - 4.2 [Vault Pending Items — How They Are Created](#42-vault-pending-items--how-they-are-created)
   - 4.3 [Daily Cash Journal Cycle](#43-daily-cash-journal-cycle)
   - 4.4 [Cockpit — The Teller's Workspace](#44-cockpit--the-tellers-workspace)
   - 4.5 [End-of-Day Close & GL Posting](#45-end-of-day-close--gl-posting)
5. [How the Two Modules Interact](#5-how-the-two-modules-interact)
6. [GL Accounting Reference](#6-gl-accounting-reference)
7. [Document Hierarchy & Cancellation Order](#7-document-hierarchy--cancellation-order)
8. [Roles & Permissions Summary](#8-roles--permissions-summary)

---

## 1. System Overview

The app contains two intertwined modules:

| Module | Purpose | Key Documents |
|---|---|---|
| **Custody** | Employee advance → procurement → settlement cycle | Custodian, Custody Request, Accountant Custody, Payment Entry |
| **Vault / Treasury** | Physical cash vault management and daily journal | Treasury Station, Vault Pending Item, Treasury Cash Journal, Cockpit page |

The two modules share the **Payment Entry** doctype as their integration point. A cash payment entry (Pay or Receive via a vault account) automatically generates a **Vault Pending Item** so the teller can record the physical cash exchange before the GL entry is created.

---

## 2. Setup & Configuration

### Treasury Settings (Singleton)

Controls how GL sub-ledger accounts are structured across the entire site.

| Field | Effect |
|---|---|
| `accounting_mode = Consolidated (Party-Based)` | All custodians share a single group advance account and a single payable group account. Individual balances are isolated by setting **Custodian** as the Party on Payment Entries. |
| `accounting_mode = Individual (Account-Based)` | Each Custodian gets two dedicated leaf GL accounts created automatically on Custodian submit: `E-{ID}-{Name} - Advance` (Asset) and `E-{ID}-{Name} - Payable` (Liability). |
| `custody_advance_group` | Parent account under which advance sub-accounts are created (Individual mode). |
| `custodian_payable_group` | Parent account under which payable sub-accounts are created (Individual mode). |

### Vault Settings (Singleton)

Global defaults for vault operations.

| Field | Effect |
|---|---|
| `default_vault_account` | Fallback cash account if a station has none configured. |
| `default_shortage_account` | GL account used to post end-of-day cash variance (shortage/overage). |

---

## 3. Custody Workflow

### 3.1 Custodian Setup

Before any custody transaction can happen, an active **Custodian** record must exist for the employee.

```
Employee (HR) ──submit──▶ Custodian (Draft) ──submit──▶ Custodian (Active)
                                                               │
                              ┌─────────── auto-creates ───────┘
                              ▼
              Individual mode: two leaf GL accounts
              Consolidated mode: assigns shared group accounts
```

- The Custodian name is auto-generated as `E-{attendance_device_id}-{employee_name}`.
- A custodian can be **Suspended** (blocks new requests) or **Closed** (blocks everything).
- A `custody_limit` can be set; the system blocks requests that would exceed it.

---

### 3.2 Stage 1 — Custody Request (Advance)

The employee (or their manager) raises a **Custody Request** to draw an advance.

```
Custody Request (Draft)
        │
        ▼  [Submit]
Custody Request (Approved)
        │
        ▼  [Accountant creates Payment Entry via "Make Advance Payment"]
Payment Entry  ──submit──▶  GL: DR Custodian Advance Account / CR Cash/Bank
        │
        └──▶ Custody Request status → Partly Paid / Paid
             Custodian dashboard: total_disbursed ↑, total_outstanding ↑
```

**Series:** `CR-.YYYY.-.#####`

**Key rules:**
- `advance_account` is locked to the custodian's `custody_account` on the Custodian record.
- `paid_amount` is read-only — computed from submitted Payment Entries.
- `remaining_to_pay = advance_amount - paid_amount`.
- Cannot cancel a Custody Request if Accountant Custody records exist against it.

**GL produced by the advance Payment Entry:**

| Account | Dr | Cr |
|---|---|---|
| Custodian Advance Account (Asset) | ✓ | |
| Bank / Cash Account | | ✓ |

---

### 3.3 Stage 2 — Accountant Custody (Spending)

The accountant creates an **Accountant Custody** record to document what was purchased/spent with the advance.

```
Accountant Custody (Draft)
   └── custody_items: item list with qty, rate, warehouse, project
        │
        ▼  [Submit]
Accountant Custody (Pending)
        │
        ├──▶ [Create Purchase Receipt]
        │         Purchase Receipt submitted
        │         GL: DR Stock / Expense   / CR stock_received_but_not_billed
        │                                     (= Custodian Payable Account)
        │         AC status → Partly Received / Fully Received
        │
        └──▶ [Create Purchase Invoice from PR]
                  Purchase Invoice submitted
                  GL: DR stock_received_but_not_billed  / CR Custodian Payable Account
                  (interim liability clears; net effect: DR Stock / CR Payable)
                  AC status → Partly Invoiced / Fully Invoiced
```

**Important overrides active for custody PRs and PIs:**
- `CustodyPurchaseReceipt` — clears `supplier`/`supplier_name` fields; ERPNext's supplier mandatory validation is bypassed; `stock_received_but_not_billed` is redirected to the Custodian Payable account.
- `CustodyPurchaseInvoice` — normalizes totals; sets credit account to Custodian Payable; applies warehouse/project/cost-center from the AC item list.
- `CustodyPaymentEntry` — skips duplicate party GL entries for Internal Transfer mode; preserves custody accounts through ERPNext's `set_missing_values`.

---

### 3.4 Stage 3 — Settlement

After procurement is fully invoiced, the accountant runs the settlement to square the advance against the actual spend.

```
Accountant Custody (Fully Invoiced)
        │
        ▼  [Create Settlement via "إنشاء تسوية" button → api.create_custody_settlement()]
Settlement Payment Entry (Internal Transfer)
   paid_from = Custodian Payable Account
   paid_to   = Custodian Advance Account
        │
        ▼  [Submit]
GL: DR Custodian Payable / CR Custodian Advance
   (advance is reduced; payable is cleared)

If spend > advance → difference paid from Bank:
   Additional PE: DR Custodian Payable / CR Bank

AC status → Partly Settled / Fully Settled
Custodian dashboard: total_outstanding ↓
```

**Custody Settlement Entry** is a child table inside `Accountant Custody` that links each settlement PE and records:
- `advance_amount_allocated` — how much of the advance was consumed.
- `payment_entry` — the PE name.

---

### 3.5 Custody Status State Machine

```
Custody Request:
  Draft → Approved → Partly Paid → Paid → Cancelled

Accountant Custody:
  Draft → Pending
       → Partly Received → Fully Received
       → Partly Invoiced → Fully Invoiced
       → Partly Settled  → Fully Settled
       → Closed / Cancelled
```

Status is re-derived from linked documents every time a PR, PI, or PE is submitted or cancelled. The `recalculate_accountant_custody_status()` function in `balances.py` is the single source of truth.

---

## 4. Vault / Treasury Cash Journal Workflow

### 4.1 Treasury Station Setup

A **Treasury Station** represents a physical cash vault (e.g., "Main Vault", "Branch A Teller").

```
Treasury Station (Draft)
   └── configure: vault_account, responsible_employee, company
        │
        ▼  [Submit]
Treasury Station (Open)
   └── opening_balance read from GL on submit
   └── Responsibility Log entry created
```

**Key rules:**
- `vault_account` and `company` are locked after submit.
- `responsible_employee` can only be changed via the **"نقل المسؤولية" (Transfer Responsibility)** action button — not by direct field edit.
- Status can only be changed via "فتح الخزينة / إغلاق الخزينة" buttons — not by direct field edit.
- A station with `status = Closed` blocks new Payment Entries that use its vault account.

---

### 4.2 Vault Pending Items — How They Are Created

A **Vault Pending Item (VPI)** is the queue record that tells the vault teller "a cash transaction is waiting to be physically executed."

VPIs are created automatically through these two routes:

#### Route A — Workflow Action on Payment Entry

The AP clerk creates a cash Payment Entry and clicks **"إرسال للموافقة" (Send for Vault Approval)**. The workflow action hook fires:

```
AP Clerk: Payment Entry (Draft, mode_of_payment = Cash)
        │
        ▼  [workflow action: "إرسال للموافقة"]
on_payment_entry_workflow_action()
        │
        ├── Identifies the matching Treasury Station by vault_account
        ├── Creates Vault Pending Item (status = Pending)
        │      direction = Outbound (Pay) or Inbound (Receive)
        │      expected_amount = paid_amount
        │      source_document = Payment Entry name
        └── PE stays at docstatus=0 (Draft) — NOT yet in GL
```

#### Route B — PE Submit Fallback

If a cash PE is submitted directly without going through the workflow (e.g., admin bypass), the `on_payment_entry_submit` hook creates the VPI with status `Executed` immediately.

#### Route C — Expense Claim

When an Expense Claim is submitted, `on_expense_claim_submit` creates an Outbound VPI for the reimbursement payment.

#### Route D — Cockpit Direct Entry (Manual)

The vault teller registers an ad-hoc cash movement (inbound receipt or direct expense) directly from the cockpit via the wizard. The API `create_and_execute_immediate()` creates the VPI and immediately marks it `Executed`.

**Station Routing Logic:**

The system matches the PE's cash account to a station `vault_account`:
1. Exact match: PE's `paid_to`/`paid_from` account = station's `vault_account`.
2. Cross-company fallback: same account, any company.
3. Default station for the company (`is_default = 1`).
4. Any submitted station for the company.

---

### 4.3 Daily Cash Journal Cycle

Each vault station has exactly one **Treasury Cash Journal (TCJ)** per calendar day.

```
Day Start
   │
   ▼
Teller opens Cockpit → selects station → date locked to today
   │
   ├── [prior-date Draft check]
   │   If a prior-day TCJ is still Draft → BLOCKED until that is sent for review
   │
   ▼
TCJ (Draft) — rows added throughout the day
   │
   ├── Via Cockpit wizard (Inbound / Direct Expense) → VPI created + Executed immediately
   │                                                   → row added to TCJ
   │
   ├── Via Pending Items panel → teller executes VPI → row added to TCJ
   │                                                   → serial assigned
   │
   └── Via "Save Draft" button → TCJ lines persisted to DB
   │
   ▼  [Teller: "إرسال للمراجعة" / Send for Review]
TCJ (Pending Review)
   │
   ▼  [Accountant: reviews Dr/Cr preview → submits TCJ form]
TCJ (Closed)  +  GL entries created  +  station balance updated
```

**Serial numbers** are assigned to each VPI at execution time:
- Inbound: `IN-YYYY-NNNN` (sequential per station per year)
- Outbound: `OUT-YYYY-NNNN` (sequential per station per year)

---

### 4.4 Cockpit — The Teller's Workspace

The **Treasury Cash Journal Cockpit** (`/treasury-cash-journal-cockpit`) is an FBCJ-style (SAP-inspired) single-page interface. The teller's daily workflow:

1. **Select station** — dropdown shows only stations the teller is responsible for (managers see all).
2. **Date** — locked to today; the cockpit only accepts same-day entries.
3. **KPI cards** — Opening Balance, Total Inflows, Total Outflows, Expected Balance (live-updated).
4. **Tab filter** — Outbound / Inbound / Bank Transfer / All.
5. **Transaction grid** — read-only; shows all rows with voucher serial, direction, category, party, reference, amount, status, and links to source documents.
6. **"تسجيل حركة خزينة" (Register Transaction)** wizard:
   - **Path A: استلام نقدي (Inbound Cash Receipt)** — party, reference invoice, amount, narration → VPI created + Executed → row appears in grid.
   - **Path C: مصروف مباشر (Direct Expense)** — expense account, beneficiary, amount → VPI created + Executed → row appears in grid.
7. **Pending Items panel** — shows all VPIs still in `Pending` status for this station (created by workflow or hooks). Each row displays:
   - Source document number (linked)
   - Date badge
   - Transaction type & direction arrow (color-coded)
   - Party type badge
   - Party name (linked to party record)
   - Reference document (linked)
   - Bank / expense account (for transfers)
   - Expected amount
   - Narration
   - **Execute** button → opens rich confirm dialog with all transaction details pre-filled; teller enters actual amount if different, confirms → VPI marked Executed, row added to TCJ, voucher printed.
   - **Cancel** button → cancels VPI with a reason.
8. **Denomination drawer** — end-of-day physical count of banknotes; calculates variance automatically.
9. **"إرسال للمراجعة" (Send for Review)** → sets TCJ to `Pending Review`; no GL entries yet.

---

### 4.5 End-of-Day Close & GL Posting

When the accountant submits the TCJ form, `post_journal_transactions()` runs:

| Journal Line Category | DR | CR |
|---|---|---|
| Inbound — Invoice Collection | Vault Cash Account | Receivable / AR Account |
| Inbound — Custody Return | Vault Cash Account | Custodian Advance Account |
| Outbound — Supplier Payment | Payable / AP Account | Vault Cash Account |
| Outbound — Custody Advance | Custodian Advance Account | Vault Cash Account |
| Outbound — Direct Expense | Expense Account | Vault Cash Account |
| Bank Transfer — Deposit | Bank Account | Vault Cash Account |
| Bank Transfer — Withdrawal | Vault Cash Account | Bank Account |
| Variance (shortage) | Shortage/Overage Account | Vault Cash Account |
| Variance (overage) | Vault Cash Account | Shortage/Overage Account |

After all lines post successfully:
- TCJ `posting_status` → `Closed`
- Treasury Station `current_balance` updated to `expected_balance`
- Treasury Station `status` → `Closed`
- Treasury Station `last_closing_date` updated

---

## 5. How the Two Modules Interact

```
┌──────────────────────────────────────────────────────────────────────┐
│  CUSTODY MODULE                                                       │
│                                                                       │
│  Custody Request ──▶ Advance Payment Entry ──▶ GL (DR Advance / CR Vault) │
│                                │                                      │
│                                ▼                                      │
│                    Accountant Custody                                 │
│                         │         │                                   │
│                    PR ──┘     Settlement PE ──▶ GL                   │
│                    PI ──┘                                             │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ Payment Entry uses vault_account
                                 │ as paid_from or paid_to
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│  VAULT MODULE                                                         │
│                                                                       │
│  PE workflow action / PE submit hook                                  │
│       │                                                               │
│       ▼                                                               │
│  Vault Pending Item (Pending)                                         │
│       │                                                               │
│       ▼  [Teller executes in Cockpit]                                 │
│  Vault Pending Item (Executed)  ──▶  TCJ row added                   │
│                                                                       │
│  Treasury Cash Journal (Draft)  ──▶  (Pending Review)  ──▶  (Closed) │
│       │                                                               │
│       ▼  [on_submit]                                                  │
│  Payment Entries submitted to GL  +  Station balance updated          │
└──────────────────────────────────────────────────────────────────────┘
```

**Integration rules:**
- A PE created by the custody module that uses a vault account (e.g., advance cash disbursement) will generate a VPI — the teller must execute it before the day can close.
- When a TCJ submits a line that originated from a Payment Entry VPI, the PE is marked `vault_approved` via `frappe.db.set_value` before GL submission to bypass the "before_submit guard" that would otherwise re-queue it.
- Custody settlement PEs use `payment_type = Internal Transfer` (between GL accounts) and therefore do **not** create VPIs (no physical cash moves through the vault counter).

---

## 6. GL Accounting Reference

### Consolidated Mode (Party-Based)

All custodians share the same group accounts. The Custodian party isolates balances.

| Event | DR | CR | Party |
|---|---|---|---|
| Advance disbursement | Custody Advance Group | Bank/Cash | Custodian |
| PR received | Expense/Stock | Custodian Payable Group | Custodian |
| PI billed | Custodian Payable Group | Custodian Payable Group | Custodian |
| Settlement (advance deduction) | Custodian Payable (leaf) | Custody Advance Group | Custodian |

### Individual Mode (Account-Based)

Each custodian has dedicated leaf accounts (`E-{ID}-{Name} - Advance`, `E-{ID}-{Name} - Payable`).

| Event | DR | CR |
|---|---|---|
| Advance disbursement | `E-{ID} - Advance` | Bank/Cash |
| PR received | Expense/Stock | `E-{ID} - Payable` |
| PI billed | `E-{ID} - Payable` (clearing) | `E-{ID} - Payable` |
| Settlement (advance deduction) | `E-{ID} - Payable` | `E-{ID} - Advance` |

---

## 7. Document Hierarchy & Cancellation Order

Documents must be cancelled in reverse-creation order (strict enforcement):

```
Custody Request
  └── Accountant Custody
        ├── Purchase Receipt  ←── cancel last PR first
        ├── Purchase Invoice  ←── cancel PI before PR
        └── Settlement Payment Entry  ←── cancel settlement PE first
              └── (then PI → PR → AC → CR)

Treasury Cash Journal
  └── Journal Lines (linked Payment Entries)
        └── Vault Pending Items
```

**Key guards:**
- Cannot cancel a Custody Request if any Accountant Custody records exist.
- Cannot cancel an Accountant Custody if settlement PEs exist.
- Cannot cancel a Purchase Invoice if a settlement PE references it.
- Cannot cancel a Purchase Receipt if a Purchase Invoice was created from it.
- Cannot cancel an advance PE if Accountant Custody records have been submitted against the Custody Request.

---

## 8. Roles & Permissions Summary

| Role | What they do |
|---|---|
| **System Manager / Accounts Manager** | Full access to all documents; see all Treasury Stations; can open/close stations; can change responsible employee. |
| **Accounts User** | Can access Cockpit and stations they are responsible for; can submit TCJ for review. |
| **Treasury Vault User** | Teller role; can see and execute Vault Pending Items in the Cockpit. |
| **AP Clerk (no special role)** | Creates Payment Entries, sends them for vault approval via workflow. |

**Cockpit station visibility:**
- Accounts Manager / System Manager → all submitted stations.
- Other users → only stations where `responsible_user = frappe.session.user`.
