# Onboarding & Admissions Module — Full Walkthrough & API Reference Guide

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>` (most endpoints; payment submit is public/AllowAny)  
> **Content-Type:** `application/json` or `multipart/form-data` for uploads  
> All responses follow: `{ "success": true/false, "message": "...", "data": {...} }` (with errors where applicable).

---

## Key Utility Functions (`onboarding/utils.py`)

Core business logic (views delegate to these):

### `AdmissionService.get_next_counsellor()`
Round-robin assignment from active `counsellor` users (uses last assigned from recent admissions to cycle fairly).

### `AdmissionService.create_admission(validated_data, user=None)`
- Creates `Admission` (status=`form_pending`).
- Auto-assigns counsellor.
- Handles document fields.
- Logs initial `AdmissionStatusHistory`.
- **Post-creation (in view):** Calls `fees.utils.select_bank_accounts_for_payment()` to set `assigned_bank_id`, transitions to `payment_pending`, sends payment email with shuffled eligible banks + frontend upload link.

### `AdmissionService.update_status(admission, new_status, note='', user=None)`
- Atomic update + `AdmissionStatusHistory` entry.
- **On transition to `enrolled`**: Calls `_create_user_accounts()` to create student/parent `User`s, send credential emails (using `auth_user.utils`).
- Downstream: `students.utils.StudentService.create_from_admission()` (copies data, generates `DigitalIDCard` if photo present, calls `fees.services.create_student_fee()`).

### `_create_user_accounts(admission)`
- Creates/updates `auth_user.User` (role=student/parents, temp password via `generate_temporary_password()`).
- Sends login emails (`send_student_login_credentials`, `send_parent_login_credentials`).
- Skips duplicate parent email.

**Fee/Installment Integration:** Handled in `students/utils.py` (calls `create_student_fee` which uses `get_installment_plan_status(level.name, num_installments)` — CSEET >2 or Exec/Prof >4 = `pending_approval`). See `fees_module_api_documentation.md` for `update_student_fee_status()`, `mark_installment_paid()`, `has_overdue_installment()` (used by attendance).

---

## Data Models & Statuses

### Core Models
| Model | Purpose |
|-------|---------|
| `Admission` | Complete application record (personal, docs, payment proof, status, linked lead/fee_structure/bank) |
| `AdmissionStatusHistory` | Immutable log of all status changes, notes, changed_by |

### Admission Statuses
- `form_pending` (initial)
- `payment_pending` (bank assigned, email sent)
- `payment_submitted` (proof uploaded)
- `approval_pending`
- `approved`
- `enrolled` (triggers full chain)
- `rejected` (terminal, cannot approve directly)

**Key Fields:**
- `fee_structure` (FK to `fees.FeeStructure` — used for auto StudentFee)
- `assigned_bank_id` (from `fees.BankAccount`, respects `max_payment_amount` thresholds)
- `payment_screenshot`, `transaction_id`, `payment_amount`, `payment_submitted_at`
- `assigned_counsellor`, `note`, `status_history`

---

## Architecture & Workflow Diagram

```text
LEAD ──convert──► Admission (form_pending)
          │
          ▼
Student submits detailed form (POST /admissions/<id>/)
          │
          ▼
select_bank_accounts_for_payment() + email with bank details + payment link
          │
          ▼
payment_pending ──(POST /payment/)──► payment_submitted (screenshot + txn_id)
          │
          ▼
Admin review: PATCH /status/ or POST /approve/
          │
          ▼
enrolled
    ├── AdmissionService.update_status() → _create_user_accounts() (student/parent Users + credential emails)
    ├── StudentService.create_from_admission() → Student profile, DigitalIDCard (QR), BatchHistory
    └── create_student_fee() → StudentFee + InstallmentPlan (pending_approval rules per level) + verified Payment if admission fee present
          │
          ▼
Fees status updated (update_student_fee_status()) ──► Attendance QR blocked if has_overdue_installment()
```

**Key Integrations (updated in recent changes):**
- Fees utils for bank selection and installment status.
- Students utils for profile + fee creation (replaces commented code in approve view).
- No direct signals.py for enrollment anymore; handled in service methods.
- Guards: Payment verification blocked for `pending_approval` plans (in fees PaymentVerifyView).

---

## FULL WALKTHROUGH: End-to-End Admission-to-Student Lifecycle

### Step 1: Admission Creation (from Lead)
Admin converts lead or POST to create `Admission` with basic info (`form_pending`).

### Step 2: Student Form Completion
Student (or counsellor) PATCHes full details + documents. Backend auto-assigns bank using `select_bank_accounts_for_payment(total_amount)`, sets `payment_pending`, sends detailed email.

### Step 3: Document Uploads
Use `/documents/` for photo, signature, marksheets (updates Admission fields).

### Step 4: Payment Proof Submission (Student)
Public POST to `/payment/` with screenshot and `transaction_id`. Transitions to `approval_pending`. History logged.

### Step 5: Admin Verification & Status Updates
Use `/status/` PATCH for incremental changes or `/approve/` for final step.

### Step 6: Approve → Enroll
POST `/approve/` (when ready):
- Sets `enrolled`.
- Creates User accounts + emails credentials.
- `create_from_admission()`: copies data to Student, generates QR ID card (using PIL/qrcode if photo present), auto batch/fee creation.
- Fee creation uses updated `get_installment_plan_status()` (replaced course_type with level.name).

### Step 7: Post-Enrollment Flows
- Student can regenerate ID card, upload more docs, get inventory issued.
- Fees module takes over (installments, payments, refunds, status recalc).
- Attendance uses `has_overdue_installment(student_id)` to block QR if >15 days overdue on approved plan.
- Reports across modules.

**Example Error (from fees integration):** If trying to verify payment on `pending_approval` InstallmentPlan: blocked with message.

---

## Complete API Reference

### List & Detail
- **GET** `/api/v1/admissions/` — Paginated list. Filters: `status`, `course`, `branch`, `attempt_year`; search on name/email/phone. Uses `AdmissionListSerializer`.
- **GET** `/api/v1/admissions/<id>/` — Full detail (tries matching admission ID or linked `lead.id`). Includes history. `AdmissionDetailSerializer`.
- **PATCH/PUT/POST** `/api/v1/admissions/<id>/` — Update form (partial OK). Triggers bank assignment/email on first complete submit if `form_pending`. Uses `AdmissionUpdateSerializer`.

**Example Request Body (form completion):**
```json
{
  "first_name": "Priya",
  "surname": "Shah",
  "father_name": "Ramesh Shah",
  "mother_name": "Sneha Shah",
  "email": "priya@example.com",
  "email_parent": "ramesh@example.com",
  "phone_student": "9876543210",
  "phone_father": "9876543211",
  "dob": "2005-04-15",
  "category": "gen",
  "street": "123 MG Road",
  "city": "Ahmedabad",
  "state": "Gujarat",
  "pincode": "380001",
  "course": "cseet",
  "group_module": "full",
  "batch_attempt": "june",
  "qualification": "pass_12",
  "fee_structure": "fs-uuid-001",
  "reference": "google",
  "tenth_percentage": 89.5,
  ...
}
```

**Success Response (form submit):**
```json
{
  "success": true,
  "message": "Your admission form has been submitted successfully. We have sent you an email with bank details for fee payment. Please check your inbox...",
  "data": {
    "admission_id": "adm-uuid-001",
    "status": "payment_pending",
    "name": "Priya Shah",
    "assigned_counsellor": {"id": "coun-uuid", "name": "Counsellor Name", "email": "..."}
  }
}
```

### Status, Approve, Reject
- **PATCH** `/api/v1/admissions/<id>/status/` — General status update.

**Request:**
```json
{
  "status": "approval_pending",
  "note": "Payment verified, documents complete."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Admission status updated successfully.",
  "data": {"admission_id": "adm-uuid-001", "status": "approval_pending", "note": "..."}
}
```

- **POST** `/api/v1/admissions/<id>/approve/` — Main enrollment endpoint (handles `payment_submitted` → `enrolled` flow, user/student/fee creation).

**Request:**
```json
{
  "note": "Approved after payment verification. Fee structure assigned.",
  "fee_structure_id": "fs-uuid-001"
}
```

**Success (full enrollment):**
```json
{
  "success": true,
  "message": "Payment verified. Admission approved and student enrolled. Admission number: ADM-2026-001. Login credentials dispatched...",
  "data": {
    "admission_id": "adm-uuid-001",
    "admission_status": "enrolled",
    "student_id": "stu-uuid-001",
    "admission_number": "ADM-2026-001",
    "student_status": "active"
  }
}
```

- **POST** `/api/v1/admissions/<id>/reject/` 

**Request:**
```json
{
  "reason": "Documents incomplete and payment mismatch."
}
```

**Response:** Success with status=`rejected`.

### Documents & Payment (Student-Facing)
- **POST** `/api/v1/admissions/<id>/documents/` — Upload by `field_name` (e.g. "doc_photo", "doc_signature", "doc_twelfth_marksheet").

**Multipart:**
- `field_name`: "doc_photo"
- `file`: (image/pdf)

**Response:**
```json
{
  "success": true,
  "message": "Document 'doc_photo' uploaded successfully.",
  "data": {"admission_id": "...", "field_name": "doc_photo", "file_name": "photo.jpg"}
}
```

- **POST** `/api/v1/admissions/<id>/payment/` — **Public** (no auth). 

**Multipart Form:**
- `payment_screenshot`: file (proof)
- `transaction_id`: "UPI123456789"
- `payment_note`: "Paid via Google Pay"
- `payment_amount`: 5000 (optional)

**Success:**
```json
{
  "success": true,
  "message": "Payment proof submitted successfully! Your counsellor will verify the payment and complete your enrollment...",
  "data": {
    "admission_id": "...",
    "status": "approval_pending",
    "transaction_id": "UPI123456789"
  }
}
```

**Error Example (wrong status):**
```json
{
  "success": false,
  "message": "Payment upload is not expected at this stage. Current status: 'enrolled'."
}
```

### Additional Notes
- All status changes logged in `AdmissionStatusHistory`.
- ID card (QR) generated in students module post-enrollment (requires photo).
- Batch assignment happens in `students.utils.allocate_batch()` or signals.
- Fee summary available via `/fees/student/<id>/` (see fees docs).

---

## Status Transition Logic (from services)

```text
form_pending ──(complete form + bank auto-assign)──► payment_pending
payment_pending ──(POST /payment/ with proof)──► payment_submitted
payment_submitted ──(admin review/approve)──► approval_pending → enrolled
enrolled ──(service chain)──► User + Student + StudentFee(approval_pending) + InstallmentPlan(approved/pending_approval)
rejected (terminal from any pre-enrolled state)
```

**Triggers on enrolled:** Credential emails, Student profile (with QR if photo), `create_student_fee()` (respects CSEET vs Executive/Professional rules from `fees.utils`), possible auto-verified Payment.

**Cross-Module:** After enrollment, `has_overdue_installment()` blocks attendance QR scans. `update_student_fee_status()` recalcs on any Payment/Refund.

---

**Related Modules & Docs:**
- `leads_module_api_documentation.md` (lead conversion)
- `fees_module_api_documentation.md` (detailed utils, installment plans, payment verify guard, overdue checks)
- `students_module_api_documentation.md` (profile, QR, status, inventory — updated below)
- `attendance_procedure_guide.md` (QR integration with fee status)
- `auth_user` (credentials)

This updated guide reflects current implementation (signals moved to services, fees integration enhanced, level-based installment approval rules, bank threshold logic, ID card generation with PIL/QR). All endpoints, bodies, responses, errors, and flows documented.
