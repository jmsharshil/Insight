# Onboarding & Admissions Module — Full Walkthrough & API Reference Guide

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>` (most endpoints; payment submit is public/AllowAny)  
> **Content-Type:** `application/json` or `multipart/form-data` for uploads  
> All responses follow: `{ "success": true/false, "message": "...", "data": {...} }` (with errors where applicable).

---

## Key Utility Functions (`onboarding/utils.py`)

Core business logic (views delegate to these):

### New `admissions.Admission` Model (in `admissions/models.py`)
Full student onboarding record with:
- Personal, family, qualification, address, category, reference fields.
- Bank account round-robin (`assigned_bank` via new `fees.utils` or admission service).
- Razorpay fields (`razorpay_order_id`, `razorpay_payment_id`, `razorpay_signature` for seamless integration).
- Status workflow + `AdmissionStatusHistory` (immutable log).
- Links to Lead, FeeStructure, Batch (on enrollment).

### Updated `AdmissionService` (now in `admissions/services.py` or views)
- `create_admission(...)`: Creates with `form_pending`, logs history, triggers bank round-robin (not counsellor RR — moved to leads).
- `update_status(...)`: Atomic + history entry. On `enrolled`: creates Users, Student, fees.
- Bank selection now uses enhanced `fees.utils.select_bank_accounts_for_payment()` (respects org/branch, max limits, round-robin).
- Razorpay webhook/verify support added for payment confirmation.

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

### Core Models (New in `admissions/models.py`)
| Model | Purpose |
|-------|---------|
| `Admission` | Complete onboarding record (all student fields: personal/family/qualification/address/bank details, docs, Razorpay fields, linked Lead/FeeStructure/Batch). Full status workflow. |
| `AdmissionStatusHistory` | Immutable audit trail of every status change, note, `changed_by` user, timestamp. |

### Admission Statuses (Workflow)
- `form_pending` (initial after creation from Lead/CRM)
- `payment_pending` (bank round-robin assigned, email/QR payment link sent)
- `payment_submitted` / `payment_verified` (screenshot or Razorpay callback)
- `approval_pending`
- `approved`
- `enrolled` (triggers User/Student/fee creation)
- `rejected` (terminal)
- Additional states for document verification, interview if needed.

**New Fields:** `razorpay_*` fields, full bank details, `admission_number`, `assigned_to` (counsellor from lead), `organization`/`branch` scoping.

**Key Fields:**
- `fee_structure` (FK to the normal CSEET `fees.FeeStructure`)
- `combo_offer` (when `true`, this admission is a CSEET + CS Executive combo)
- Combo fee structures use the same `fee_structure` field and are identified by `is_combo=true`
- `combo_future_batch` (resolved future CS Executive batch)
- `assigned_bank_id` (from `fees.BankAccount`, respects `max_payment_amount` thresholds)
- `payment_screenshot`, `transaction_id`, `payment_amount`, `payment_submitted_at`
- `assigned_counsellor`, `note`, `status_history`

### CSEET + CS Executive Combo Offer

For a combo admission, send:

```json
{
  "combo_offer": true,
  "course": "cseet",
  "batch_attempt": "june",
  "attempt_year": 2026,
  "fee_structure": "fs-combo-uuid"
}
```

`fee_structure` contains the selected fee structure for the admission. For a combo admission it should be the CSEET + CS Executive structure marked with `is_combo=true`; it does not need to equal the sum of the separate course prices. The API resolves and stores `combo_future_batch`; the future attempt and year are read from that batch's `batch_attempt` and `attempt_year` fields.

Future CS Executive mapping:

| CSEET attempt | Future Executive attempt/year |
|---|---|
| June | June of the following year |
| October | December of the same year |
| February | December of the same year |

---

## Architecture & Workflow Diagram

```text
LEAD (converted via CRM) ──► Admission (form_pending, full fields)
          │
          ▼
**Bank round-robin** (`select_bank_accounts_for_payment()`) + Razorpay order creation + email with payment link/QR
          │
          ▼
Student submits full form/docs (POST /admissions/<admission_code>/ or /form/) + payment (screenshot or Razorpay callback)
          │
          ▼
`payment_pending` → `payment_verified` (Razorpay signature verify or manual)
          │
          ▼
Admin review: PATCH /status/ (logs to `AdmissionStatusHistory`) or POST /approve/
          │
          ▼
`enrolled`
    ├── `_create_user_accounts()` (student + parents via `auth_user.utils`)
    ├── `StudentService.create_from_admission()` → Student, DigitalIDCard (QR), BatchHistory
    ├── `create_student_fee()` (level-based installment rules via `CourseLevel.course_type`)
    └── Payroll/Attendance ready (no overdue block)
```

**Key Integrations (from recent updates):**
- **Leads signal disabled** — manual Admission creation preferred.
- Enhanced bank round-robin in `fees.utils` (org-scoped, respects `max_payment_amount`).
- Razorpay integration (order_id, payment_id, signature verification in views/webhooks).
- Full `Admission` model now lives in dedicated `admissions` app (moved from onboarding).
- `AdmissionStatusHistory` for complete audit.
- Ties to new faculty QR/session reports, sales odometer for field counsellors.
- Fees: `get_installment_plan_status()` now uses `CourseLevel` directly.
- No more commented conversion signal; explicit pipeline.

---

## FULL WALKTHROUGH: End-to-End Admission-to-Student Lifecycle

### Step 1: Admission Creation
From Lead (manual now) or POST `/admissions/` with full student data (`form_pending`, auto bank round-robin if amount known, Razorpay order if applicable). Logs initial history.

### Step 2: Form & Document Completion
Student/counsellor uses PATCH or dedicated form endpoint to fill all fields (qualification, bank details, docs). Triggers Razorpay if chosen.

### Step 3: Payment
- Screenshot upload or Razorpay payment (webhook verifies signature).
- Transitions status + history entry.

### Step 4: Admin Review
PATCH `/status/` for any state (with note). Full audit in `AdmissionStatusHistory`.

### Step 5: Approve & Enroll
POST `/approve/`:
- Sets `enrolled`.
- Creates `User` (student/parents), credentials emails.
- `create_from_admission()`: Student profile, QR DigitalIDCard, Batch allocation, StudentFee with level-aware installments.
- Triggers payroll readiness, faculty assignment eligibility.

**Note:** New `Admission` model supports all fields in one go; Razorpay fields enable seamless UPI/card flows.

### Step 7: Post-Enrollment Flows
- Student can regenerate ID card, upload more docs, get inventory issued.
- Fees module takes over (installments, payments, refunds, status recalc).
- Attendance uses `has_overdue_installment(student_id)` to block QR if >15 days overdue on approved plan.
- Reports across modules.

**Example Error (from fees integration):** If trying to verify payment on `pending_approval` InstallmentPlan: blocked with message.

---

## Complete API Reference

### List & Detail
- Admission records have a public immutable `admission_code` in the format `IIPS-000001`.
- API responses expose that code as `id`. The numeric database ID remains internal and is accepted by existing URLs for backward compatibility.
- **GET** `/api/v1/admissions/` — Paginated list. Filters: `status`, `course`, `branch`, `attempt_year`; search on name/email/phone. Uses `AdmissionListSerializer`.
- **GET** `/api/v1/admissions/<admission_code>/` — Full detail using a code such as `IIPS-000001`. Includes history. `AdmissionDetailSerializer`.
- **PATCH/PUT/POST** `/api/v1/admissions/<admission_code>/` — Update form (partial OK). Numeric IDs continue to work for existing integrations. Triggers bank assignment/email on first complete submit if `form_pending`. Uses `AdmissionUpdateSerializer`.

> [!IMPORTANT]
> **Phone Number Uniqueness Requirement**:
> In all new admission submissions and updates, `phone_student`, `phone_father`, and `mother_phone` / `phone_mother` (stored in `phone_father_2`) must all be **different from each other**. Both `mother_phone` and `phone_mother` are accepted and returned by all admission endpoints. If any two numbers match, the API rejects the request with HTTP 400 Bad Request:
> - `"Student phone number, father's phone number, and mother's phone number must all be different."`

#### Education Choices (Medium & Board):
- **`tenth_medium` / `twelfth_medium`** choices (Board choices):
  - `'gseb'` — Gujarat Board (GSEB)
  - `'cbse'` — CBSE Board
  - `'icse'` — ICSE Board
- **`tenth_board` / `twelfth_board`** choices (Medium choices):
  - `'english'` — English Medium
  - `'gujarati'` — Gujarati Medium
  - `'hindi'` — Hindi Medium
  - `'other'` — Other

**Example Request Body (form submission & completion):**
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
  "mother_phone": "9876543212",
  "dob": "2005-04-15",
  "category": "gen",
  "street": "123 MG Road",
  "city": "Ahmedabad",
  "state": "Gujarat",
  "pincode": "380001",
  "country": "India",
  "course": "cseet",
  "group_module": "full",
  "batch_attempt": "june",
  "qualification": "pass_12",
  "fee_structure": "fs-uuid-001",
  "payment_type": "token",
  "payment_choice": "cash",
  "reference": "google",
  "reference_name": "Friend Referral",
  "consent": true,

  "tenth_medium": "gseb",
  "tenth_board": "gujarati",
  "tenth_school": "ABC High School",
  "tenth_coaching": "XYZ Classes",
  "tenth_percentage": 85.50,
  "tenth_percentile": 92.00,

  "twelfth_medium": "cbse",
  "twelfth_board": "english",
  "twelfth_school": "National Higher Secondary",
  "twelfth_coaching": "Premier Coaching",
  "twelfth_percentage": 88.00,
  "twelfth_percentile": 95.00,

  "grad_university": "",
  "grad_college": "",
  "grad_last_sem": ""
}
```

**Success Response (form submit):**
```json
{
  "success": true,
  "message": "Your admission form has been submitted successfully. We have sent you an email with bank details for fee payment. Please check your inbox...",
  "data": {
    "admission_id": "IIPS-000001",
    "status": "payment_pending",
    "status_display": "Payment Pending",
    "name": "Priya Shah",
    "payment_type": "token",
    "payment_choice": "cash",
    "payment_choice_display": "Cash",
    "total_fees": "35000.00",
    "paid_amount": "0.00",
    "remaining_fees": "35000.00",
    "is_paid": false,
    "tenth_medium_display": "Gujarat Board (GSEB)",
    "tenth_board_display": "Gujarati Medium",
    "twelfth_medium_display": "CBSE Board",
    "twelfth_board_display": "English Medium",
    "assigned_counsellor": {"id": "coun-uuid", "name": "Counsellor Name", "email": "..."}
  }
}
```

### Status, Approve, Reject
- **PATCH** `/api/v1/admissions/<admission_code>/status/` — General status update.

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
  "data": {"admission_id": "IIPS-000001", "status": "approval_pending", "note": "..."}
}
```

- **POST** `/api/v1/admissions/<admission_code>/approve/` — Payment verification & enrollment approval endpoint.

Supports the 2-level payment approval workflow:

1. **Level 1 Approval (Accountant Verification for Cash/Cheque):**
   - Triggered when an accountant verifies the physical cash or cheque payment.
   - Status updates to `level1_approved`.
   - **Notifications:** Dispatches immediate confirmation email and WhatsApp message to both student and parent:
     > *"We have received and verified your Cash/Cheque payment of ₹X. Your admission is now queued for final Super Admin enrollment approval."*

2. **Level 2 Approval (Super Admin Final Enrollment):**
   - Triggered by Super Admin to finalize admission and create the enrolled student.
   - Status updates to `enrolled`.
   - **User Accounts & Credentials:** Automatically creates or updates the student's `User` account, generating a secure temporary password (guaranteed even if an account already existed).
   - **Login Notification:** Credentials (username & temporary password) are dispatched via email and WhatsApp to the student and parent.
   - **StudentFee Synchronization:** Links `Payment.student_fee` to the student's fee record and invokes `update_student_fee_status()`, ensuring `amount_paid` and `amount_due` are accurately reflected on the student dashboard.
   - **Official Payment Receipt with PDF:** Generates and dispatches the payment receipt email with an attached PDF document (using WeasyPrint / Playwright or direct in-memory ReportLab fallback).

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
    "admission_id": "IIPS-000001",
    "admission_status": "enrolled",
    "student_id": "stu-uuid-001",
    "admission_number": "ADM-2026-001",
    "student_status": "active"
  }
}
```

- **POST** `/api/v1/admissions/<admission_code>/reject/`

**Request:**
```json
{
  "reason": "Documents incomplete and payment mismatch."
}
```

**Response:** Success with status=`rejected`.

### Documents & Payment (Student-Facing)
- **POST** `/api/v1/admissions/<admission_code>/documents/` — Upload by `field_name` (e.g. "doc_photo", "doc_signature", "doc_twelfth_marksheet").

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

- **POST** `/api/v1/admissions/<admission_code>/payment/` — **Public** (no auth).

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
