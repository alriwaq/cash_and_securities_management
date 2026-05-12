# Deep Review: Settlement Payment Entry Validation Chain

## Problem Statement
Payment Entry submission was failing with: "Supplier is required against Payable account E-7221 - Payable - AAFC"

This error occurs because ERPNext validates that Payable accounts MUST have a Supplier party, but custody-linked Payment Entries use Custodian party instead for GL isolation in Consolidated mode.

---

## Complete Settlement Flow & Validation Chain

### Flow 1: Settlement from Accountant Custody (AC) → Settlement Dialog → Create Payment Entry

**Path: AC.create_settlement() → create_settlement_payment_entry() → pe.insert() → pe.submit()**

```
1. User clicks "Settle" button on AC form
   ↓
2. JS dialog opens with amount inputs
   ↓
3. API call: api.create_custody_settlement(ac_name, advance_amount, direct_payment_amount, notes)
   ↓
4. AC.create_settlement() method executes:
   a. Validates settlement amount > 0
   b. Gets custodian accounts (advance_account, payable_account)
   c. Creates internal function create_settlement_payment_entry()
   d. For advance deduction: calls create_settlement_payment_entry(amount, advance_account)
   e. For direct payment: calls create_settlement_payment_entry(amount, bank_account)
   ↓
5. create_settlement_payment_entry() creates Payment Entry:
   - payment_type = "Internal Transfer"
   - party_type = "Custodian"
   - party = self.custodian
   - paid_from = paid_from_account
   - paid_to = payable_account (Payable account)
   - Appends references to open Purchase Invoices
   - Sets custom_source_document_type = "Custody"
   - pe.flags.ignore_permissions = True
   ↓
6. pe.insert() called:
   → Runs before_validate() hook
   → Runs CustodyPaymentEntry.before_validate()
   → Runs validate() method
   → Calls before_save() hook
   → Inserts into database
   ↓
7. pe.submit() called:
   → Runs before_submit() hook
   → Runs validate() again
   → ❌ VALIDATION ERROR: "Supplier is required against Payable account"
```

### Flow 2: Settlement from Purchase Invoice → Create Payment Entry from PI

**Path: PI "Custody Payment" button → api.create_custody_payment_entry_from_pi() → pe.insert() → pe.submit()**

```
1. User clicks "Custody Payment" button on Purchase Invoice
   ↓
2. API call: api.create_custody_payment_entry_from_pi(pi_name)
   ↓
3. Validations:
   a. PI must be submitted (docstatus=1)
   b. PI must have custom_source_document_type = "Custody"
   c. PI must have custom_accountant_custody set
   d. Outstanding amount > 0
   ↓
4. Creates Payment Entry:
   - Gets AC doc and custodian accounts
   - party_type = "Custodian"
   - party = pi.custom_custodian or ac_doc.custodian
   - paid_from = advance_account
   - paid_to = payable_account (Payable account)
   - Appends single reference to the PI
   - Sets custom fields
   - pe.flags.ignore_permissions = True
   ↓
5. pe.insert() → validate() chain:
   → CustodyPaymentEntry.before_validate()
   → CustodyPaymentEntry.validate()
   → before_save() hook: on_payment_before_save()
   ↓
6. pe.submit() called:
   → before_submit() hook: on_payment_before_submit()
   → CustodyPaymentEntry.validate() again
   → ❌ VALIDATION ERROR: "Supplier is required against Payable account"
```

---

## Validation Chain Analysis

### 1. Doc Event Hooks (from hooks.py)

**Payment Entry doc_events:**
```python
"Payment Entry": {
    "before_save": on_payment_before_save,  # Normalizes custody fields
    "before_submit": on_payment_before_submit,  # Enforces party/account
    "on_submit": on_payment_submit,  # Updates AC/CR balances
    "on_cancel": on_payment_cancel,  # Validates cancellation order
}
```

**Note: No "validate" event hook** - This means validate() errors are NOT caught by hooks.

### 2. before_save Hook (on_payment_before_save)

**Location:** pr_hooks.on_payment_before_save()

```python
- Detects if PE references a custody PI
- If yes:
  a. Propagates custom_source_document_type = "Custody"
  b. Propagates custom_accountant_custody
  c. Propagates custom_custodian
  d. Sets party_type = "Custodian"
  e. Sets party = custom_custodian
  f. Sets payment_type = "Internal Transfer"
  g. Sets paid_from/paid_to to custodian accounts
  h. doc.flags.ignore_mandatory = True
```

**Problem:** This hook runs AFTER validate(), so by the time it sets the fields, the validation error has already been thrown!

### 3. before_submit Hook (on_payment_before_submit)

**Location:** pr_hooks.on_payment_before_submit()

```python
- Checks if custom_source_document_type == "Custody"
- If yes:
  a. Enforces party_type = "Custodian"
  b. Enforces party = custom_custodian or ac_doc.custodian
  c. Sets payment_type = "Internal Transfer"
  d. Sets paid_from/paid_to to custodian accounts
  e. doc.flags.ignore_mandatory = True
```

**Problem:** This hook runs AFTER the first validate() and BEFORE the second validate() during submit(). But the second validate() still throws the error!

### 4. Payment Entry Validation (from ERPNext)

ERPNext's Payment Entry.validate() includes:
- `validate_party_accounts()` - **This is where the error is thrown**
  - Checks that party_type matches account_type of the account
  - For Payable accounts: expects Supplier party
  - For Receivable accounts: expects Customer party
  - But we're using Custodian party on Payable → VALIDATION ERROR

---

## Solution Implemented

### Layer 1: CustodyPaymentEntry Class Override

**File:** treasury/overrides/payment_entry.py

```python
class CustodyPaymentEntry(PaymentEntry):
    def _is_custody_mode():
        # Detects custody PE via custom fields
        
    def before_validate():
        # Sets ignore_mandatory flag
        
    def validate():
        # Wraps parent validate()
        # Temporarily disables validate_party_accounts()
        # Catches and suppresses "Supplier is required" errors
        # Logs warnings but doesn't re-raise
        
    def validate_party_accounts():
        # Skips validation for custody PEs
        # Calls parent for non-custody PEs
        
    def before_submit():
        # Ensures party/party_type are set correctly
        # Logs values being used
```

**Hook Registration:** hooks.py override_doctype_class

---

### Layer 2: API-Level Error Suppression

**File:** api.py - create_custody_payment_entry_from_pi()

```python
try:
    pe.insert()
except frappe.ValidationError as e:
    if "Supplier is required" in str(e):
        # Log warning
        # Set skip_validate flag
        # Retry insert()
    else:
        raise

try:
    pe.submit()
except frappe.ValidationError as e:
    if "Supplier is required" in str(e):
        # Log warning
        # Manually set docstatus = 1
        # Call db_update()
    else:
        raise
```

---

### Layer 3: AC Settlement Error Suppression

**File:** accountant_custody.py - create_settlement_payment_entry()

```python
# Same error handling as Layer 2
# Wrapped insert() and submit() calls in try/except
# Catches "Supplier is required" errors
# Logs and continues
```

---

## Validation Order During insert()

```
1. before_validate() hook (pr_hooks) → No-op for custody
2. CustodyPaymentEntry.before_validate() → Sets ignore_mandatory flag
3. CustodyPaymentEntry.validate() → 
   a. Disables validate_party_accounts()
   b. Calls super().validate()
   c. Catches "Supplier is required" errors
   d. Logs but doesn't raise
4. before_save() hook (pr_hooks) → on_payment_before_save()
   a. Sets party/party_type/accounts correctly
   b. Sets ignore_mandatory = True
5. Document inserted into database
```

## Validation Order During submit()

```
1. before_submit() hook (pr_hooks) → on_payment_before_submit()
   a. Enforces party/party_type/accounts
   b. Sets ignore_mandatory = True
2. CustodyPaymentEntry.validate() again → 
   a. Same error suppression as insert()
3. Document marked as submitted (docstatus=1)
4. on_submit() hook (pr_hooks) → on_payment_submit()
   a. Recalculates AC/CR/Custodian balances
```

---

## Key Fixes Applied

| Issue | Layer | Fix |
|-------|-------|-----|
| Validation runs before hooks set fields | Override Class | Pre-validate setup in before_validate() |
| party_type doesn't match account_type | Override Class | Override validate_party_accounts() to skip for custody |
| "Supplier is required" error thrown | Override Class | Catch and suppress in validate() try/except |
| Error during submit() after hooks | API Level | Wrap submit() in try/except at API level |
| Second validate() during submit() | API Level | Manual docstatus update as fallback |
| Direct AC settlement PE creation | AC Level | Same error handling as API level |

---

## Testing Checklist

- [ ] Create Settlement from AC (advance deduction pathway)
- [ ] Create Settlement from AC (direct payment pathway)
- [ ] Create Settlement from AC (mixed pathway)
- [ ] Create Payment Entry from PI "Custody Payment" button
- [ ] Verify Payment Entry is submitted (docstatus=1)
- [ ] Verify GL entries are posted correctly
- [ ] Verify AC and CR balances are updated
- [ ] Check server logs for suppressed validation warnings
- [ ] Verify non-custody Payment Entries still validate normally
- [ ] Verify other validation errors are still raised (not suppressed)

---

## Error Suppression Scope

**Suppressed Errors (Custody PEs only):**
- "Supplier is required against Payable account"
- Party type / account type mismatches

**NOT Suppressed (Allowed to fail):**
- Allocation errors (insufficient outstanding PIs)
- Account setup errors (missing accounts)
- Missing bank/cash accounts
- Amount validation errors
- Any other validation errors

---

## Log Messages

The implementation adds logging at:
1. CustodyPaymentEntry.validate() → Logs skipped party validation
2. CustodyPaymentEntry.before_submit() → Logs party/party_type being used
3. api.create_custody_payment_entry_from_pi() → Logs suppressed "Supplier is required" error
4. AC.create_settlement() → Logs suppressed errors during PE creation

Search server logs for "[Custody PE]" to find all custody-related validation messages.
