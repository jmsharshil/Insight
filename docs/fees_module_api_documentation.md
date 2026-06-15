# Fees Module — API Documentation

The `fees` module handles all financial workflows for enrolled students — from defining course fee structures to recording payments, tracking installments, and processing refunds.

---

## Data Model

| Model | Purpose |
|---|---|
| `FeeStructure` | Defines the fee for a course or batch |
| `StudentFee` | A student's individual fee record derived from a `FeeStructure` |
| `InstallmentPlan` | Optional installment structure on top of a `StudentFee` |
| `InstallmentItem` | Individual installments within an `InstallmentPlan` |
| `Payment` | Records each payment made by a student |
| `Refund` | Partial or full refund against a verified payment |
| `BankAccount` | Bank accounts mapping for fee deposits |

---

## Admission-to-Fees Integration

The most critical workflow is the **automatic fee creation on enrollment** and recording of the admission payment. The full chain is:

### 1. Enrollment Trigger
When an `Admission` status is changed to `enrolled`:
1. `onboarding.signals` intercepts the status change.
2. An `auth_user.User` (role=student) is created.
3. A `students.Student` profile is created and linked to the admission.
4. A `fees.Payment` record is created (if an `admission_fee` was provided during admission creation) to record the admission processing/registration fee.

### 2. Auto-Creation of StudentFee
Once the `Student` profile is created:
1. `students.signals` fires a `post_save` on the `Student` model.
2. It calls `fees.services.create_student_fee(student)`.
3. The service looks up the `fee_structure` pinned on the `Admission`.
4. (Fallback) If not explicitly set, it falls back to the latest active `FeeStructure` matching the course type.
5. A `StudentFee` is created with status=`approval_pending` and `total_amount` matching the structure.

> [!IMPORTANT]
> The `Admission.fee_structure` FK should ideally be set before enrolling. Without it, `create_student_fee` falls back to any active `FeeStructure` for the course. If none exists, enrollment proceeds but **no student fee is created** (the error is logged, not raised).

---

## API Endpoints

### 1. Fee Structures
**`GET /api/v1/fee-structures/`**
**`POST /api/v1/fee-structures/`**
**`GET /api/v1/fee-structures/<uuid>/`**
**`PATCH /api/v1/fee-structures/<uuid>/`**
**`DELETE /api/v1/fee-structures/<uuid>/`**

### 2. Student Fees
**`GET /api/v1/student-fees/`**
- Query Parameters: `student_id`, `status`, `fee_structure_id`

**`POST /api/v1/student-fees/`**
**`GET /api/v1/student-fees/<uuid>/`**
**`PATCH /api/v1/student-fees/<uuid>/`**
**`DELETE /api/v1/student-fees/<uuid>/`**

### 3. Student Fee Summaries
**`GET /api/v1/student-fees/summary/`**
- Returns aggregated fee summary by status across all records.

**`GET /api/v1/fees/student/<uuid>/`**
- Retrieves all fee records and a personalized fee summary for a specific student.

### 4. Installments
**`GET /api/v1/installments/`**
**`POST /api/v1/installments/`**

**`POST /api/v1/installments/create/`**
- High-level endpoint to create an installment plan alongside multiple `InstallmentItem` records.

**`POST /api/v1/installments/<uuid>/approve/`**
- Approve or reject an installment plan.

### 5. Payments
**`GET /api/v1/payments/`**
- Query Parameters: `student_id`, `status`, `payment_mode`, `date_from`, `date_to`

**`POST /api/v1/payments/`**
- Submitting a payment automatically updates the status of the related `StudentFee`.

**`GET /api/v1/payments/<uuid>/`**

**`POST /api/v1/payments/<uuid>/verify/`**
- Verify or reject a payment.

### 6. Refunds
**`GET /api/v1/refunds/`**
**`POST /api/v1/refunds/create/`**
- Creates a new refund request against a verified payment.

**`PATCH /api/v1/refunds/<uuid>/`**
- Update refund status.

### 7. Bank Accounts
**`GET /api/v1/bank-accounts/`**
**`POST /api/v1/bank-accounts/`**
**`GET /api/v1/bank-accounts/<uuid>/`**
**`PATCH /api/v1/bank-accounts/<uuid>/`**
**`DELETE /api/v1/bank-accounts/<uuid>/`**

### 8. Reporting
**`GET /api/v1/fees/report/`**
- Query Parameters: `course_id`, `month` (YYYY-MM), `year`
- Generates a fee collection report for administrative analytics.

---

## Status Transitions

### StudentFee Status
```text
approval_pending  ──(first payment verified)──►  partial
    partial       ──(all paid)──────────────────►  paid
    partial       ──(due date passed + unpaid)──►  overdue
```

Status is recalculated dynamically by `fees/utils.py:update_student_fee_status()`, which is triggered automatically upon any change to linked Payments.
