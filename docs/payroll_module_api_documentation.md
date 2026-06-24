# Payroll Module — Full Walkthrough & API Reference Guide

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `application/json`  
> Role-based access: `super_admin`, `accountant`, `branch_manager`, `faculty`, and all employee roles.  
> Responses: `{ "success": true/false, "message": "...", "data": {...} }`.

---

## Key Utility Functions (`payroll/utils.py`)

### `compute_payslip_for_faculty(faculty_profile, month, year, payroll_run)`
- Core calculator for **faculty** payslips.
- Base = `basic_salary`.
- Hour-based = sessions from `timetable.SessionReport` (rate * hours).
- Late penalties: uses `LateEntryPolicy` (grace_period, deduction_per_minute, auto_halfday).
- Leave deductions, absence, bonuses, extra hours (from `ExtraHoursApproval`).
- Creates/updates `PaySlip` (with `faculty` FK) + `SessionLatePenaltyLog`.
- Handles `PayrollRun` totals.

### `compute_payslip_for_user(user, month, year, payroll_run)`
- **NEW:** Simplified calculator for **non-faculty employees** (all staff roles).
- Uses `User` model fields directly (`salary`, `hourly_rate`, `employment_type`).
- No session reports or chapter-based hour tracking.
- Accounts for:
  - Base salary / hourly attendance (from `EmployeeAttendanceRecord`)
  - Leave deductions (unpaid only, from `LeaveApplication`)
  - Late penalty (from `LateEntryRecord`)
  - Absence deductions
  - Retention deduction, attendance bonus, leave encashment
- Creates `PaySlip` (with `user` FK, `faculty=null`).

### `preview_payslip_for_faculty(faculty_profile, month, year)`
- Read-only preview for faculty (no DB write).

### `EMPLOYEE_ROLES` (Constant)
All non-student, non-parent, non-super_admin roles eligible for payroll:
```python
EMPLOYEE_ROLES = [
    'branch_manager', 'admin_senior_executive', 'admin_executive',
    'front_desk', 'counsellor', 'sales_senior_executive', 'sales_executive',
    'tele_caller', 'exam_supervisor', 'paper_checker', 'accountant',
    'house_keeping', 'security',
]
```

**Integration:** Pulls from `timetable` (SessionReport for faculty), `leave` module, `attendance` module (EmployeeAttendanceRecord for staff), `faculty` profiles. Auto-generates `ExtraHoursApproval` if teaching time exceeds chapter allocation (faculty only).

---

## Data Models & Statuses

### Core Models
| Model | Purpose |
|-------|---------|
| `PayrollRun` | Monthly batch (per branch/month/year). Status drives workflow. |
| `PaySlip` | Per-employee slip (basic, hours, penalties, net_salary, is_disbursed). Links to **either** `faculty` FK or `user` FK. |
| `LateEntryPolicy` | Branch config for penalties (grace, rates, thresholds). |
| `SessionLatePenaltyLog` | Audit for each late session applied (faculty only). |
| `ExtraHoursApproval` | Auto-generated for overtime; requires super_admin approval (faculty only). |

### PaySlip FK Strategy
| Employee Type | `faculty` FK | `user` FK | Source of Data |
|---------------|-------------|-----------|----------------|
| Faculty (with FacultyProfile) | ✅ Set | null | SessionReport, FacultyQRScanLog |
| Non-faculty staff (all other roles) | null | ✅ Set | EmployeeAttendanceRecord, LateEntryRecord |

Both types produce identical payslip fields (`basic_salary`, `hour_based_amount`, `late_penalty`, `net_salary`, etc.).

### PayrollRun.status
- `draft` (editable, auto-regenerates on GET/POST)
- `pending_approval`
- `approved` (locked)
- `disbursed` (final, notifications sent)

**PaySlip** has `net_salary` recalc on adjustments. `is_disbursed` flag prevents edits.

---

## Architecture & Workflow Diagram

```text
FACULTY PATH:                            STAFF PATH:
  SessionReports + FacultyQRScanLog        EmployeeAttendanceRecord + LateEntryRecord
           │                                        │
           ▼                                        ▼
  compute_payslip_for_faculty()            compute_payslip_for_user()
           │                                        │
           └──────────────┬─────────────────────────┘
                          │
                          ▼
  LateEntryPolicy (branch rules) + Leave deductions (both paths)
                          │
                          ▼
  GET/POST /payroll/  (auto-generates PayrollRun + PaySlips for ALL employees)
                          │
                          ▼
  PayrollRun (draft) ── adjustments (bonus/deduction) ──► pending_approval
                          │
                          ▼
  POST /approve/ (branch_manager/super_admin) ──► approved
                          │
                          ▼
  POST /disburse/ (super_admin/accountant) ──► disbursed
                          │
                          ▼
  Notifications to ALL employees (in-app: net_salary, sessions)
```

**Auto Behaviors:**
- GET /payroll/ auto-creates/regenerates for current month if missing/draft — includes **all employees** (faculty + staff).
- Extra hours detected from SessionReport vs chapter duration (faculty only).
- Faculty can preview own salary.
- Non-faculty staff can view their payslips via `/payroll/my/`.
- Role guards throughout.

---

## FULL WALKTHROUGH: Monthly Payroll Process

### Step 1: Configure Late Policy (Admin)
POST or PATCH `/payroll/late-policy/` with branch-specific rules (grace_period_minutes=15, deduction_per_minute=10, etc.).

### Step 2: Generate Payroll
**GET** or **POST** `/payroll/?month=6&year=2026&branch_id=...`
- Auto-computes for **all active employees**:
  - Faculty via `compute_payslip_for_faculty()`
  - Non-faculty staff via `compute_payslip_for_user()`
- Creates `PayrollRun` (draft) + `PaySlip`s.
- Faculty path pulls hours from SessionReports, applies late penalties, leaves, extra hours.
- Staff path pulls from EmployeeAttendanceRecord, LateEntryRecord, LeaveApplication.

**Response includes** total_amount, employee_count.

### Step 3: Review & Adjust Payslips
- GET `/payroll/<run_id>/payslips/` — List with details (shows both faculty and staff payslips).
- PATCH `/payroll/<run_id>/payslips/<slip_id>/` — Adjust bonus, deductions, notes. Recalcs net_salary and run total.

### Step 4: Extra Hours Approvals (Faculty Only)
- GET `/payroll/extra-hours/` — List pending auto-detected overtime.
- PATCH `/payroll/extra-hours/<id>/` (super_admin only) with `status=approved/rejected`. If approved, updates related payslip on next compute.

### Step 5: Approve Payroll
**POST** `/payroll/<run_id>/approve/` — Changes to `approved`, sets approved_by/at, sends notification.

### Step 6: Disburse
**POST** `/payroll/<run_id>/disburse/` — Sets `disbursed`, marks all payslips `is_disbursed=True`, sends per-employee in-app notifications with salary summary.

### Step 7: Faculty Self-Service
- GET `/faculty/<id>/payslips/` — Historical slips.
- GET `/faculty/<id>/salary-preview/?month=6&year=2026` — Current estimate (uses `preview_payslip_for_faculty()`).

### Step 8: My Payroll (Any Employee)
- GET `/payroll/my/` — Personal payroll history for **any authenticated employee** (faculty or staff).

**Integration Notes:** 
- Faculty path depends on accurate `SessionReport` from timetable/attendance.
- Staff path depends on `EmployeeAttendanceRecord` from attendance module.
- Both paths tie to `leave` module (unpaid leave deductions, leave encashment).
- Draft runs regenerate automatically to reflect new sessions/leaves/attendance.

---

## Complete API Reference

### Payroll Runs
- **GET / POST** `/api/v1/payroll/` — List or generate. Auto-creates for current month on GET. Filters: `year`, `month`, `status`, `branch_id`.
  - POST body: `{"branch_id": "uuid", "month": 6, "year": 2026}`

**Success (generate):**
```json
{
  "success": true,
  "message": "Payroll generated.",
  "data": {
    "payroll_run_id": "pr-uuid-001",
    "status": "draft",
    "total_amount": "125000.00",
    "employee_count": 15,
    "generated_at": "2026-06-01T10:00:00Z"
  }
}
```

> **Note:** `employee_count` includes both faculty and non-faculty staff payslips (previously `faculty_count`).

- **GET** `/api/v1/payroll/<run_id>/` — Detail (with summary).
- **PATCH** `/api/v1/payroll/<run_id>/` — Update notes or status (limited transitions).
- **DELETE** `/api/v1/payroll/<run_id>/` — Only for draft/pending.

### Payslips & Adjustments
- **GET** `/api/v1/payroll/<run_id>/payslips/` — List slips for run (includes late_logs).

**Example PaySlip Data (Faculty):**
```json
{
  "id": "ps-uuid",
  "faculty": "faculty-uuid",
  "user_id": "user-uuid",
  "faculty_name": "Prof. Ramesh Kumar",
  "employee_id": "EMP-2026-0001",
  "basic_salary": 50000,
  "hour_based_amount": 15000,
  "late_penalty": 500,
  "leave_deductions": 2000,
  "bonus": 5000,
  "net_salary": 67500,
  "sessions_conducted": 45,
  "is_disbursed": false,
  "late_logs": [ ... ]
}
```

**Example PaySlip Data (Non-Faculty Staff):**
```json
{
  "id": "ps-uuid-002",
  "faculty": null,
  "user_id": "user-uuid-002",
  "faculty_name": "Priya Accountant",
  "employee_id": "EMP-HQ-0012",
  "basic_salary": 35000,
  "hour_based_amount": 0,
  "late_penalty": 200,
  "leave_deductions": 1000,
  "absence_deductions": 0,
  "bonus": 0,
  "net_salary": 33800,
  "sessions_conducted": 0,
  "is_disbursed": false,
  "late_logs": []
}
```

> **Note:** For non-faculty payslips, `faculty` is `null`, `sessions_conducted` is `0`, and `faculty_name` falls back to `user.name`.

- **PATCH** `/api/v1/payroll/<run_id>/payslips/<slip_id>/` — Adjust fields.

**Request:**
```json
{
  "bonus": 7500,
  "other_deductions": 1000,
  "deduction_note": "Adjusted for special project"
}
```

- Faculty payslips: **GET** `/api/v1/faculty/<faculty_id>/payslips/`

### My Payroll (Self-Service)
**`GET /api/v1/payroll/my/`**  
Returns all payroll history for the currently authenticated **employee** (faculty or non-faculty staff). Auto-resolves from the auth token — tries FacultyProfile first, falls back to User-based payslip lookup.

**Query params:** `?year=2026` `?month=6` `?status=disbursed`

**Response (Faculty):**
```json
{
  "success": true,
  "employee": {
    "id": "fp-uuid",
    "employee_id": "EMP-2026-0001",
    "name": "Prof. Ramesh Kumar",
    "email": "ramesh@institute.com",
    "role": "faculty"
  },
  "summary": {
    "total_payslips": 3,
    "total_net_earned": "125000.00",
    "total_disbursed": "80000.00"
  },
  "payslips": [ ... ]
}
```

**Response (Non-Faculty Staff):**
```json
{
  "success": true,
  "employee": {
    "id": "user-uuid",
    "employee_id": "EMP-HQ-0012",
    "name": "Priya Verma",
    "email": "priya@institute.com",
    "role": "accountant"
  },
  "summary": {
    "total_payslips": 2,
    "total_net_earned": "68000.00",
    "total_disbursed": "35000.00"
  },
  "payslips": [ ... ]
}
```

> **Note:** Response key changed from `faculty` to `employee`. Now includes `role` field. Works for all employee roles.

### Late Policy
- **GET / POST** `/api/v1/payroll/late-policy/` 
- **PATCH / DELETE** `/api/v1/payroll/late-policy/<id>/`

**Example Policy:**
```json
{
  "branch": "branch-uuid",
  "grace_period_minutes": 10,
  "deduction_per_minute": 50,
  "max_deduction_per_session": 1000,
  "auto_halfday_deduction": true,
  "is_active": true
}
```

### Extra Hours & Preview
- **GET** `/api/v1/payroll/extra-hours/` — Filtered list (faculty only).
- **PATCH** `/api/v1/payroll/extra-hours/<id>/` with `{"status": "approved"}`.

- **GET** `/api/v1/faculty/<faculty_id>/salary-preview/?month=6&year=2026`

**Preview Response:**
```json
{
  "success": true,
  "message": "Salary preview calculated successfully.",
  "data": {
    "faculty_id": "...",
    "month": 6,
    "year": 2026,
    "payslip_preview": {
      "basic_salary": 50000,
      "expected_hours_amount": 18000,
      "estimated_net": 67000,
      "late_penalty_estimate": 250,
      ...
    }
  }
}
```

### Approve / Disburse
- **POST** `/api/v1/payroll/<run_id>/approve/`
- **POST** `/api/v1/payroll/<run_id>/disburse/`

**Disburse Success:**
```json
{
  "success": true,
  "message": "Payroll disbursed.",
  "data": {
    "disbursed": true,
    "employee_count": 15,
    "total_amount": "425000.00"
  }
}
```

**Notifications:** In-app to **all employees** (faculty and staff) with net salary, sessions count.

---

## Status Transition Logic

```text
draft (auto-generated) ──(adjustments)──► pending_approval
pending_approval ──(approve)──► approved
approved ──(disburse)──► disbursed (final, no edits)
```

- Drafts auto-regenerate on access to reflect new SessionReports/attendance records.
- Extra hours approval can trigger payslip recalc (faculty only).
- Permissions strictly enforced per role.

**Common Errors:**
- 403: Role not allowed (e.g. faculty can't approve).
- 400: Invalid transition, disbursed slip can't be edited, missing branch.
- 404: No payslips found for this user (My Payroll).
- 409: Payroll already exists in final state with all employees covered.

---

## Cross-Module Integration

```text
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  ATTENDANCE  │     │    LEAVE     │     │   PAYROLL    │
│              │     │              │     │              │
│ Student:     │     │ Staff Leave: │     │ Faculty:     │
│  QR Scan     │     │  applied_by  │◄───►│  PaySlip     │
│  Batch Mark  │     │  = User      │     │  (faculty FK)│
│              │     │              │     │              │
│ Employee:    │     │ Student      │     │ Staff:       │
│  Employee    │◄───►│ Leave:       │     │  PaySlip     │
│  Attendance  │     │  = Student   │     │  (user FK)   │
│  Record      │     │              │     │              │
│              │     │ Late Entries │◄───►│ Penalties    │
│ Faculty:     │     │  = User      │     │ applied in   │
│  QRScanLog   │◄───►│              │     │ both paths   │
└──────────────┘     └──────────────┘     └──────────────┘
```

**Related Modules:**
- `faculty` (profiles, hourly_rate, SessionReport from timetable) — faculty payslips
- `attendance` (EmployeeAttendanceRecord) — staff payslips
- `timetable` (source of hours and late data for faculty)
- `leave` (deductions for both faculty and staff)
- `core` (notifications)

This guide fully documents the current payroll implementation, auto-generation logic, utils, role guards, and integrations for **all employee types**.
