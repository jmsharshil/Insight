# Fees Module — Full Walkthrough & API Reference Guide

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `application/json`  
> All responses follow the wrapper: `{ "success": true/false, "message": "...", "data": {...} }` (or errors).

---

## Key Utility Functions (`fees/utils.py`)

These core functions power the business logic:

### `get_installment_plan_status(level_or_course, num_installments)`
Determines initial `InstallmentPlan` status based on **level name** (CSEET, CS Executive, CS Professional). Supports legacy course strings.

**Rules:**
- **CSEET**: `pending_approval` if >2 installments, else `approved`
- **CS Executive / CS Professional**: `pending_approval` if >4 installments, else `approved`
- **Other**: always `approved`

**Used in:** `services.create_student_fee()`, `InstallmentPlanCreateView`, FeeStructure creation.

### `select_bank_accounts_for_payment(amount, limit=None)`
Returns shuffled list of active `BankAccount`s eligible for the payment amount (based on `is_under_threshold()` which checks financial year totals vs `max_payment_amount`).

### `update_student_fee_status(student_fee_id)`
**Central recalculator**. Called after every Payment/Refund.
- Sums verified payments minus completed refunds → `amount_paid`
- Auto-resolves `InstallmentItem.is_paid` and `InstallmentPlan.status` (`completed` vs `approved`)
- Sets `StudentFee.status`:
  - `paid` (if amount_due <= 0)
  - `partial` (if some paid)
  - `overdue` (if due_date passed)
  - `approval_pending` (default)

### `mark_installment_paid(installment_item_id)`
Marks `InstallmentItem` as paid if linked verified payments >= item amount. Updates plan status if all items paid.

### `has_overdue_installment(student_id)`
Returns `True` if any unpaid `InstallmentItem` is >15 days past due_date. **Used by Attendance module to block QR check-in.**

---

## Data Models & Statuses

### Core Models
| Model | Purpose |
|-------|---------|
| `FeeStructure` | Template for course/batch/level fees (auto-creates StudentFees on save) |
| `StudentFee` | Per-student fee record (one per student) |
| `InstallmentPlan` | Payment schedule linked to StudentFee |
| `InstallmentItem` | Individual due dates/amounts within a plan |
| `Payment` | Records deposits (approval_pending → verified/rejected) |
| `Refund` | Returns against verified payments |
| `BankAccount` | Configurable accounts with payment thresholds |

### Status Tables

**StudentFee.status**
- `approval_pending`
- `partial`
- `paid`
- `overdue`

**InstallmentPlan.status**
- `pending_approval`
- `approved`
- `completed`
- `rejected`

**Payment.status**
- `approval_pending`
- `verified`
- `rejected`

**Refund.status**
- `pending`
- `completed`
- `rejected`

---

## Architecture & Workflow Diagram

```text
                       ┌─────────────────────┐
                       │   ADMISSION/ENROLLMENT  │
                       └──────────┬──────────┘
                                  │
                                  ▼
                       ┌─────────────────────┐
                       │  create_student_fee() │ (services.py)
                       │  - Lookup FeeStructure │
                       │  - get_installment_plan_status() │
                       └──────────┬──────────┘
                                  │
            ┌─────────────────────┴─────────────────────┐
            ▼                                           ▼
InstallmentPlan (pending/approved)          StudentFee (approval_pending)
            │                                           │
            ▼                                           │
   POST /installments/create/                       Payments
            │                                           │
            ▼                                           ▼
   update_student_fee_status()  ◄────────────────── POST /payments/
            │                     (recalculates paid, installments, status)
            ▼
     has_overdue_installment() ──► Blocks Attendance QR
```

**Key Integration Points:**
- **onboarding/students signals** → `fees.services.create_student_fee()`
- **Payment created/verified** → `update_student_fee_status()` + `mark_installment_paid()`
- **Attendance QR** → calls `has_overdue_installment(student_id)`
- **FeeStructure save** → auto-assigns to existing students + creates default InstallmentPlans

---

## FULL WALKTHROUGH: End-to-End Fee Lifecycle

### Step 1: Create Fee Structure (Admin)
**API:** `POST /api/v1/fee-structures/`

#### Request Body
```json
{
  "name": "CS Executive 2026 Full Course",
  "level": "level-uuid-for-cs-executive",
  "total_amount": 25000,
  "icsi_registration_fees": 5000,
  "icsi_exam_fees": 15000,
  "token_amount": 5000,
  "is_active": true,
  "description": "Includes all subjects"
}
```

#### Response (201)
```json
{
  "success": true,
  "message": "Fee structure created.",
  "data": {
    "id": "fs-uuid-001",
    "name": "CS Executive 2026 Full Course",
    "level_name": "CS Executive",
    "total_amount": 25000,
    ...
  }
}
```

**Effect:** Auto-creates `StudentFee` + default `InstallmentPlan` (1 item) for all matching active students using `get_installment_plan_status()`.

### Step 2: Student Enrollment → Auto Fee Creation
1. Admin changes Admission status to `enrolled`.
2. Signals create `User` + `Student`.
3. `fees.services.create_student_fee()` runs:
   - Looks up `FeeStructure` (by admission.fee_structure or level/course match).
   - Creates `StudentFee` (status=`approval_pending`).
   - Creates `InstallmentPlan` using `get_installment_plan_status(level_name, 1)`.
   - If admission had payment data → creates **verified** `Payment` and auto-approves plan.

### Step 3: Create Custom Installment Plan
**API:** `POST /api/v1/installments/create/`

#### Request Body
```json
{
  "student_fee_id": "sf-uuid-001",
  "items": [
    {
      "amount": 10000,
      "due_date": "2026-07-15"
    },
    {
      "amount": 15000,
      "due_date": "2026-09-15"
    }
  ]
}
```

**Note:** Backend validates total matches `amount_due`. Uses `get_installment_plan_status()` based on **CSEET (>2 items = pending)** or **others (>4 = pending)**. Returns `pending_approval` or `approved`.

#### Response (201)
```json
{
  "success": true,
  "message": "Installment plan created (pending approval).",
  "data": {
    "id": "plan-uuid-001",
    "status": "pending_approval",
    "items": [ ... ],
    "student_name": "Rohan Sharma"
  }
}
```

### Step 4: Approve Installment Plan (if pending)
**API:** `POST /api/v1/installments/<plan_uuid>/approve/`

#### Request Body
```json
{
  "status": "approved"
}
```

(or `"status": "rejected", "rejection_reason": "Insufficient documents"`)

### Step 5: Record a Payment
**API:** `POST /api/v1/payments/`

#### Request Body
```json
{
  "student": "student-uuid-001",
  "student_fee": "sf-uuid-001",
  "installment_item": "item-uuid-001",
  "amount": 10000,
  "payment_mode": "bank_transfer",
  "transaction_ref": "TXN123456",
  "payment_date": "2026-06-20",
  "note": "UPI transfer"
}
```

**Backend Flow:**
1. Validates against remaining due.
2. Creates `Payment` with `status=approval_pending`.
3. Calls `update_student_fee_status()` → updates `amount_paid`, installment items, StudentFee status.
4. If linked to installment → `mark_installment_paid()`.

#### Response (201)
```json
{
  "success": true,
  "message": "Payment recorded.",
  "data": {
    "id": "pay-uuid-001",
    "amount": 10000,
    "status": "approval_pending",
    "receipt_number": "RCPT-000123",
    "student_name": "Rohan Sharma",
    ...
  }
}
```

### Step 6: Verify/Reject Payment (Admin)
**API:** `POST /api/v1/payments/<payment_uuid>/verify/`

#### Request Body
```json
{
  "status": "verified",
  "note": "Verified via bank statement"
}
```

**Important Business Rule:** If payment is linked to an `InstallmentPlan` that is still `pending_approval`, verification is **blocked**.

**Triggers:**
- `update_student_fee_status()`
- `mark_installment_paid()` (if applicable)
- Auto-completes plan if all items paid.

#### Response (200)
```json
{
  "success": true,
  "message": "Payment verified.",
  "data": { ... updated payment with status: "verified", verified_at, verified_by ... }
}
```

### Step 7: Process Refunds
**API:** `POST /api/v1/refunds/create/`

#### Request Body
```json
{
  "payment": "pay-uuid-001",
  "amount": 5000,
  "reason": "Student transferred to another batch"
}
```

**PATCH** `/api/v1/refunds/<uuid>/` with `{"status": "completed"}` to finalize.

Triggers `update_student_fee_status()` which subtracts from `net_paid`.

### Step 8: Check Overdue Status (Attendance Integration)
**Utility:** `has_overdue_installment(student_id)`

**Used in Attendance QR endpoint** to block students with installments overdue by >15 days.

**Example Response from Attendance (if blocked):**
```json
{
  "success": false,
  "message": "Attendance blocked: Student has overdue installments (>15 days).",
  "overdue_installments": 2
}
```

### Step 9: Bank Account Selection for Large Payments
**Utility:** `select_bank_accounts_for_payment(Decimal('25000'), limit=3)`

Returns shuffled eligible accounts that won't exceed their yearly threshold.

### Step 10: Reports & Summaries
- `GET /api/v1/student-fees/summary/` — Aggregated counts by status.
- `GET /api/v1/fees/report/?month=2026-06&course_id=...` — Full analytics (total_billed, collected, overdue, mode-wise, monthly trend).
- `GET /api/v1/fees/student/<student_id>/` — Personalized student fee overview.

---

## Complete API Reference

### Fee Structures
- **GET** `/api/v1/fee-structures/` — List with filters (`course_id`, `batch_id`, `is_active`)
- **POST** `/api/v1/fee-structures/` — (Body above)
- **GET/PATCH/DELETE** `/api/v1/fee-structures/<uuid>/`

### Student Fees
- **GET** `/api/v1/student-fees/` — Supports `student_id`, `status`
- **GET** `/api/v1/student-fees/summary/`
- **GET** `/api/v1/fees/student/<uuid>/` — Full overview + summary
- **POST/PATCH** `/api/v1/student-fees/<uuid>/` — Updates trigger `update_student_fee_status()`

### Installments
- **GET** `/api/v1/installments/` 
- **POST** `/api/v1/installments/create/` — (See Step 3)
- **POST** `/api/v1/installments/<uuid>/approve/` — (See Step 4)

### Payments
- **GET** `/api/v1/payments/` — Rich filters (`student_id`, `status=verified`, `date_from`, `payment_mode`)
- **POST** `/api/v1/payments/` — (See Step 5)
- **POST** `/api/v1/payments/<uuid>/verify/` — (See Step 6)

### Refunds & Bank Accounts
- **POST** `/api/v1/refunds/create/`
- **PATCH** `/api/v1/refunds/<uuid>/`
- **GET/POST** `/api/v1/bank-accounts/` (with `max_payment_amount` for threshold logic)

### Reports
- **GET** `/api/v1/fees/report/`

---

## Status Transition Logic (from `update_student_fee_status`)

```text
StudentFee:
  approval_pending ──(Payment verified)──► partial/paid
  partial ──(full payment)──► paid
  partial ──(due_date passed)──► overdue

InstallmentPlan:
  approved/pending_approval ──(all items paid via mark_installment_paid)──► completed
```

**Note:** `update_student_fee_status()` is called in:
- Payment create/verify
- Refund complete
- StudentFee PATCH
- Admission auto-payment

---

**Related Modules:**
- `onboarding` / `students` (signals)
- `attendance` (uses `has_overdue_installment()`)
- `core` (pagination, filters)

This document serves as both **walkthrough** and **API reference**. All business rules from `utils.py`, `services.py`, and views are documented above.
