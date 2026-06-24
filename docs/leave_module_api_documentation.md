# Leave Module — API Documentation

The `leave` module manages staff/faculty leave requests, student leave requests, leave policies, public holidays, and late entry records.

---

## Data Model

| Model | Purpose |
|---|---|
| `LeavePolicy` | Rules per leave type (e.g., Paid Leave, Sick Leave), quotas, and sandwich rules |
| `LeaveBalance` | Tracks a user's used and remaining days per leave type per year |
| `LeaveApplication` | A staff/faculty employee's request for leave (single, multi-day, or half-day) |
| `StudentLeaveApplication` | A student's leave request — uses student-specific leave types and form fields |
| `PublicHoliday` | Branch-level list of public holidays |
| `LateEntryRecord` | Tracks late arrivals. Can automatically trigger a half-day deduction based on policy |

---

## API Endpoints

### 1. Leave Policies
**`GET /api/v1/leave/policy/`**
**`GET / PATCH /api/v1/leave/policy/<uuid>/`**

### 2. Leave Balances
**`GET /api/v1/leave/balance/`**
**`GET /api/v1/leave/balance/<user_id>/`**
Check remaining leaves for the logged-in user or a specific user.

### 3. Staff / Faculty Leave Applications
**`GET /api/v1/leave/`**
**`POST /api/v1/leave/`**
Apply for a new leave.

**`GET /api/v1/leave/<uuid>/`**

**`POST /api/v1/leave/<uuid>/approve/`**
**`POST /api/v1/leave/<uuid>/reject/`**
Managerial endpoints to approve or reject leave requests.

### 4. Public Holidays
**`GET /api/v1/leave/public-holidays/`**
**`POST /api/v1/leave/public-holidays/`**
**`GET / PATCH / DELETE /api/v1/leave/public-holidays/<uuid>/`**

### 5. Late Entries
**`GET /api/v1/leave/late-entries/`**
**`POST /api/v1/leave/late-entries/`**
Record a late arrival.

**`GET /api/v1/leave/late-entries/<uuid>/`**

---

## Student Leave APIs

Student leave is a separate flow from staff/faculty leave. It mirrors the physical **Student Leave Application Form** and uses student-specific leave types.

### Leave Types (`leave_type` field)

| Key | Label |
|---|---|
| `casual` | Casual Leave |
| `medical` | Medical Leave |
| `emergency` | Emergency Leave |
| `exam` | Exam Leave |
| `mobile_usage` | Mobile Usage Permission |
| `uniform` | Uniform Leave |

### Endpoints

#### List / Apply
**`GET /api/v1/leave/student/`**
- **Admin** — sees all student leave applications for their branch/org (filters: `status`, `leave_type`, `from_date`, `to_date`).
- **Student** — sees only their own applications.

**`POST /api/v1/leave/student/`**

**Request body:**
```json
{
  "leave_type": "casual",
  "from_date": "2026-06-24",
  "to_date": "2026-06-24",
  "from_time": "09:00",
  "to_time": "13:00",
  "reason": "Family function",
  "is_capable_of_proof": true,
  "parent_consulted": true,
  "parent_signature_date": "2026-06-23",
  "proof_document": "<file upload>"
}
```

> **Note:** When a **student** submits, `student_id` is auto-resolved from their auth token.  
> When an **admin** creates on behalf of a student, `student_id` must be included in the body.

---

#### Detail / Edit / Cancel
**`GET /api/v1/leave/student/<uuid>/`**
Returns full detail including reviewer, parent info, and proof document URL.

**`PATCH /api/v1/leave/student/<uuid>/`**
- Only the owning student can edit.
- Only allowed while `status = pending`.
- Editable fields: `from_date`, `to_date`, `from_time`, `to_time`, `reason`, `is_capable_of_proof`, `parent_consulted`, `parent_signature_date`.

**`DELETE /api/v1/leave/student/<uuid>/`**
- Only the owning student can cancel (sets `status = cancelled`).
- Only allowed while `status = pending`.

---

#### Approve / Reject (Admin)
**`POST /api/v1/leave/student/<uuid>/approve/`**
Sets `status = approved`. Records `reviewed_by`, `reviewed_at`, and `received_by`.

**`POST /api/v1/leave/student/<uuid>/reject/`**
Body: `{ "rejection_reason": "Insufficient proof provided." }`
Sets `status = rejected`. Stores `rejection_reason`.

---

### Student Leave Status Flow

```
pending → approved (by admin)
pending → rejected (by admin, requires rejection_reason)
pending → cancelled (by student)
```

---

### Student Leave Response Example

```json
{
  "id": "uuid",
  "student": "student-uuid",
  "student_name": "Rahul Sharma",
  "batch_name": "JEE 2026",
  "leave_type": "medical",
  "leave_type_display": "Medical Leave",
  "from_date": "2026-06-24",
  "to_date": "2026-06-25",
  "from_time": null,
  "to_time": null,
  "reason": "Doctor visit",
  "is_capable_of_proof": true,
  "proof_document_url": "https://.../leave/student_proof/cert.pdf",
  "parent_consulted": true,
  "parent_signature_date": "2026-06-23",
  "status": "pending",
  "status_display": "Pending",
  "received_by": null,
  "reviewed_by": null,
  "reviewed_at": null,
  "rejection_reason": "",
  "created_at": "2026-06-23T07:45:00Z"
}
```

---

## Cross-Module Integration

```text
┌──────────────────────┐     ┌──────────────────────┐
│ Leave Module         │────►│ Payroll Module        │
│ Approved leaves      │     │ Unpaid leaves trigger │
│ LateEntryRecords     │     │ deductions. Leave     │
│ (tied to User)       │     │ encashment applied.   │
└──────────────────────┘     └──────────────────────┘

┌──────────────────────┐     ┌──────────────────────┐
│ Leave Module         │────►│ Attendance Module     │
│ Approved leaves      │     │ Attendance records    │
│                      │     │ auto-flagged as       │
│                      │     │ "on_leave" status.    │
└──────────────────────┘     └──────────────────────┘
```

**Key Integrations:**
- **Payroll**: `compute_payslip_for_user()` and `compute_payslip_for_faculty()` both query `LeaveApplication` for unpaid leaves to apply salary deductions, and query `LateEntryRecord` to apply late penalties according to branch `LateEntryPolicy`.
- **Attendance**: Approved leaves can automatically affect or justify attendance records for both students and employees.
