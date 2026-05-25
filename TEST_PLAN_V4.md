# Treasury Cash Journal Cockpit v4 - End-to-End Test Plan

## Overview
This document outlines the comprehensive end-to-end testing strategy for the v4 Treasury Cash Journal cockpit, covering all three main workflows: Inbound Receipt (Path A), Direct Expense (Path C), and Payment Entry Execution (Path B).

---

## Test Environment Setup

### Prerequisites
1. **User Roles**: Ensure test users have the following roles:
   - **Vault Teller**: Can access cockpit, execute transactions
   - **Accountant**: Can review and submit Treasury Cash Journal
   - **System Manager**: Can access all stations and journals

2. **Treasury Station Setup**:
   - Create at least one submitted Treasury Station with:
     - `responsible_user`: Set to the vault teller test user
     - `responsible_employee`: Set to a valid employee
     - `vault_account`: Set to a valid GL account (e.g., 1010 - Cash in Hand)
     - `company`: Set to the test company

3. **GL Accounts**:
   - Ensure the following accounts exist:
     - 1010 - Cash in Hand (Vault Account)
     - 5010 - Direct Expenses
     - 1020 - Customer Receivables
     - 2010 - Supplier Payables

4. **Sample Data**:
   - Create 2-3 Sales Invoices with outstanding amounts
   - Create 2-3 Purchase Invoices with outstanding amounts
   - Create 1-2 Expense Claims in draft status

---

## Test Scenarios

### Scenario 1: Inbound Receipt (Path A)
**Objective**: Verify that vault tellers can record inbound cash receipts directly from the cockpit.

#### Test Case 1.1: Add Inbound Receipt from Cockpit Wizard
1. **Setup**: Log in as vault teller
2. **Steps**:
   - Navigate to Treasury Cash Journal Cockpit
   - Select a Treasury Station and today's date
   - Click "تسجيل حركة خزينة" (Add Transaction)
   - Select Direction: "Inbound"
   - Select Category: "Invoice Collection"
   - Select Party Type: "Customer"
   - Select Party: Any customer
   - Select Reference: A Sales Invoice with outstanding balance
   - Verify amount is auto-filled
   - Enter narration: "Collection from customer"
   - Click "تأكيد" (Confirm)
3. **Expected Results**:
   - ✅ Transaction appears in grid with:
     - Serial: `IN-2026-0001` (or next sequential)
     - Direction: "وارد" (Inbound)
     - Amount: Correctly displayed
   - ✅ KPI cards update:
     - "إجمالي الوارد" increases
     - "الرصيد المتوقع" updates correctly
   - ✅ Journal name is created/updated
   - ✅ Print voucher dialog shows with correct serial and details

#### Test Case 1.2: Verify Serial Numbering
1. **Setup**: Complete Test Case 1.1
2. **Steps**:
   - Add another Inbound receipt
   - Verify serial is `IN-2026-0002`
   - Add an Outbound transaction
   - Verify serial is `OUT-2026-0001` (separate counter)
3. **Expected Results**:
   - ✅ Serials increment correctly per direction
   - ✅ Serials persist across sessions

#### Test Case 1.3: Print Voucher
1. **Setup**: Complete Test Case 1.1
2. **Steps**:
   - In the print dialog, click "طباعة / Print"
   - Verify print dialog appears with voucher details
   - Verify voucher shows:
     - Serial number
     - Station name
     - Date and time
     - Direction badge (green for Inbound)
     - Transaction category
     - Party and reference
     - Amount
     - Narration
3. **Expected Results**:
   - ✅ Print dialog opens without popup blocker interference
   - ✅ Voucher content is clearly formatted
   - ✅ Print dialog closes after printing

---

### Scenario 2: Direct Expense (Path C)
**Objective**: Verify that vault tellers can record direct expenses without referencing external documents.

#### Test Case 2.1: Add Direct Expense from Cockpit Wizard
1. **Setup**: Log in as vault teller
2. **Steps**:
   - Navigate to Treasury Cash Journal Cockpit
   - Select a Treasury Station and today's date
   - Click "تسجيل حركة خزينة" (Add Transaction)
   - Select Direction: "Outbound"
   - Select Category: "Direct Expense"
   - Select Expense Account: "5010 - Direct Expenses"
   - Enter Amount: 500
   - Enter Narration: "Office supplies purchase"
   - Click "تأكيد" (Confirm)
3. **Expected Results**:
   - ✅ Transaction appears in grid with:
     - Serial: `OUT-2026-0001`
     - Direction: "صادر" (Outbound)
     - Amount: 500
   - ✅ KPI cards update:
     - "إجمالي الصادر" increases
     - "الرصيد المتوقع" decreases
   - ✅ Expense Account field is populated

#### Test Case 2.2: Verify Direct Expense GL Mapping
1. **Setup**: Complete Test Case 2.1 and save journal
2. **Steps**:
   - Submit the Treasury Cash Journal
   - Navigate to the GL and check posting
   - Verify GL entries:
     - Debit: 5010 (Direct Expenses) - 500
     - Credit: 1010 (Vault Account) - 500
3. **Expected Results**:
   - ✅ GL entries are correctly created
   - ✅ Both debit and credit are balanced

---

### Scenario 3: Payment Entry Execution (Path B)
**Objective**: Verify that pre-approved Payment Entries appear as pending items and can be executed.

#### Test Case 3.1: Create and Approve Payment Entry
1. **Setup**: Log in as accountant
2. **Steps**:
   - Create a new Payment Entry:
     - Payment Type: "Pay"
     - Party Type: "Supplier"
     - Party: Select a supplier
     - Paid From Account: Select vault account
     - Reference Document: Select a Purchase Invoice
     - Amount: Auto-filled from invoice
   - Submit the Payment Entry
   - Verify workflow_state is "Vault Pending"
3. **Expected Results**:
   - ✅ Payment Entry is submitted
   - ✅ workflow_state = "Vault Pending"
   - ✅ A Vault Pending Item is auto-created with status "Pending"

#### Test Case 3.2: Execute Pending Item from Cockpit
1. **Setup**: Complete Test Case 3.1
2. **Steps**:
   - Log in as vault teller
   - Navigate to Treasury Cash Journal Cockpit
   - Select the same station and date
   - Scroll to "الحركات المعلقة" (Pending Items) section
   - Verify the Payment Entry appears in the pending grid
   - Click "تنفيذ" (Execute)
   - Verify execution dialog shows:
     - Expected amount from Payment Entry
     - Option to enter actual amount
   - Enter actual amount (same as expected)
   - Click "تأكيد" (Confirm)
3. **Expected Results**:
   - ✅ Pending item disappears from pending grid
   - ✅ Item appears in main transaction grid with:
     - Serial: `OUT-2026-0001` (or next sequential)
     - Status: "Executed"
     - Amount: Actual amount entered
   - ✅ Item is added to today's Draft journal
   - ✅ Voucher is printed with correct serial

#### Test Case 3.3: Verify Payment Entry Workflow Update
1. **Setup**: Complete Test Case 3.2
2. **Steps**:
   - Navigate to the Payment Entry created in Test Case 3.1
   - Verify workflow_state is now "Vault Approved"
   - Verify the Payment Entry is linked to the Vault Pending Item
3. **Expected Results**:
   - ✅ workflow_state = "Vault Approved"
   - ✅ Vault Pending Item is linked

---

### Scenario 4: Cockpit Redirection from TCJ Form
**Objective**: Verify that opening the cockpit from a TCJ form redirects to the correct station and date.

#### Test Case 4.1: Redirect to Specific Station and Date
1. **Setup**: Create a Treasury Cash Journal for a specific station and date
2. **Steps**:
   - Open the Treasury Cash Journal form
   - Click "فتح الكوكبيت" (Open Cockpit)
   - Verify cockpit opens with:
     - Correct station selected
     - Correct date selected
     - Correct journal data loaded
3. **Expected Results**:
   - ✅ Station dropdown shows correct value
   - ✅ Date input shows correct date
   - ✅ Grid displays existing journal lines

---

### Scenario 5: Journal Save and Post Workflow
**Objective**: Verify the complete workflow from draft to pending review to posted.

#### Test Case 5.1: Save Draft Journal
1. **Setup**: Add 2-3 transactions to cockpit
2. **Steps**:
   - Click "حفظ مسودة" (Save Draft)
   - Verify success message shows journal name
   - Refresh page
   - Verify transactions are still present
3. **Expected Results**:
   - ✅ Journal is saved as Draft
   - ✅ Journal name is displayed
   - ✅ Data persists after refresh

#### Test Case 5.2: Send for Review
1. **Setup**: Complete Test Case 5.1
2. **Steps**:
   - Verify denomination card is visible (if rows exist)
   - Enter actual count for each denomination
   - Verify variance is calculated
   - If variance ≠ 0, enter variance narration
   - Click "إرسال للمراجعة" (Send for Review)
   - Verify success message with link to TCJ form
3. **Expected Results**:
   - ✅ Journal status changes to "Pending Review"
   - ✅ Cockpit buttons are disabled
   - ✅ TCJ form link is provided

#### Test Case 5.3: Accountant Review and Submit
1. **Setup**: Complete Test Case 5.2
2. **Steps**:
   - Log in as accountant
   - Open the TCJ form from the link
   - Verify all transactions are displayed
   - Verify GL preview shows correct entries
   - Click "Submit" (or equivalent)
   - Verify GL entries are posted
3. **Expected Results**:
   - ✅ Journal status changes to "Posted"
   - ✅ GL entries are created with correct debit/credit
   - ✅ Vault account balance is updated

---

### Scenario 6: Error Handling and Edge Cases

#### Test Case 6.1: Validation Errors
1. **Setup**: Open cockpit wizard
2. **Steps**:
   - Try to confirm without selecting direction
   - Verify error message appears
   - Try to confirm with amount = 0
   - Verify error message appears
   - Try to confirm without narration
   - Verify error message appears
3. **Expected Results**:
   - ✅ All validation errors are caught
   - ✅ User-friendly error messages are displayed

#### Test Case 6.2: Popup Blocker Bypass
1. **Setup**: Enable popup blocker in browser
2. **Steps**:
   - Add a transaction and trigger print
   - Verify print dialog appears (not blocked)
   - Verify print functionality works
3. **Expected Results**:
   - ✅ Print dialog appears despite popup blocker
   - ✅ Print dialog is not blocked by browser

#### Test Case 6.3: Concurrent User Access
1. **Setup**: Open cockpit in two browser windows with same station/date
2. **Steps**:
   - Add transaction in Window 1
   - Save draft in Window 1
   - Refresh Window 2
   - Verify transaction appears in Window 2
3. **Expected Results**:
   - ✅ Changes are visible across sessions
   - ✅ No data loss or conflicts

---

## Test Execution Checklist

- [ ] All test cases in Scenario 1 (Inbound Receipt) pass
- [ ] All test cases in Scenario 2 (Direct Expense) pass
- [ ] All test cases in Scenario 3 (Payment Entry) pass
- [ ] All test cases in Scenario 4 (Cockpit Redirection) pass
- [ ] All test cases in Scenario 5 (Journal Workflow) pass
- [ ] All test cases in Scenario 6 (Error Handling) pass
- [ ] Serial numbering is consistent across all scenarios
- [ ] Print functionality works without popup blocker issues
- [ ] GL entries are correctly created for all transaction types
- [ ] Arabic labels and RTL layout display correctly
- [ ] Performance is acceptable (< 2 seconds for page load)
- [ ] No console errors or warnings

---

## Known Issues and Workarounds

### Issue 1: Popup Blocker Interference
**Status**: FIXED in v4
**Solution**: Implemented iframe-based printing to bypass popup blockers

### Issue 2: Serial Number Persistence
**Status**: FIXED in v4
**Solution**: Serials are now assigned from the backend and persisted in VPI

### Issue 3: Cockpit Redirection
**Status**: FIXED in v4
**Solution**: Added route_options support to pass station and date from TCJ form

---

## Sign-Off

| Role | Name | Date | Status |
|------|------|------|--------|
| QA Lead | | | |
| Development Lead | | | |
| Product Owner | | | |

