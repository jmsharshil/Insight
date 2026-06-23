# Payroll Module — Full Walkthrough & API Reference Guide

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `application/json`  
> Role-based access: `super_admin`, `accountant`, `branch_manager`, `faculty`.  
> Responses: `{ "success": true/false, "message": "...", "data": {...} }`.

---

## Key Utility Functions (`payroll/utils.py`)

### `compute_payslip_for_faculty(faculty_profile, month, year, payroll_run)`
- Core calculator.
- Base = `basic_salary`.
- Hour-based = sessions from `timetable.SessionReport` (rate * hours).
- Late penalties: uses `LateEntryPolicy` (grace_period, deduction_per_minute, auto_halfday).
- Leave deductions, absence, bonuses, extra hours (from `ExtraHoursApproval`).
- Creates/updates `PaySlip` + `SessionLatePenaltyLog`.
- Handles `PayrollRun` totals.

### `preview_payslip_for_faculty(faculty_profile, month, year)`
- Read-only preview for faculty (no DB write).

**Integration:** Pulls from `timetable` (SessionReport), `leave` module, `faculty` profiles. Auto-generates `ExtraHoursApproval` if teaching time exceeds chapter allocation. Links to `fees` indirectly via faculty payments if needed.

---

## Data Models & Statuses

### Core Models
| Model | Purpose |
|-------|---------|
| `PayrollRun` | Monthly batch (per branch/month/year). Status drives workflow. |
| `PaySlip` | Per-faculty slip (basic, hours, penalties, net_salary, is_disbursed). |
| `LateEntryPolicy` | Branch config for penalties (grace, rates, thresholds). |
| `SessionLatePenaltyLog` | Audit for each late session applied. |
| `ExtraHoursApproval` | Auto-generated for overtime; requires super_admin approval. |

### PayrollRun.status
- `draft` (editable, auto-regenerates on GET/POST)
- `pending_approval`
- `approved` (locked)
- `disbursed` (final, notifications sent)

**PaySlip** has `net_salary` recalc on adjustments. `is_disbursed` flag prevents edits.

---

## Architecture & Workflow Diagram

```text
TIMETABLE + SESSION REPORTS (faculty attendance)
          │
          ▼
LateEntryPolicy (branch rules) + Leave deductions
          │
          ▼
GET/POST /payroll/  (auto-generates PayrollRun + PaySlips via compute_payslip_for_faculty)
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
Notifications to faculty (in-app: net_salary, sessions) + ExtraHoursApproval workflow
```

**Auto Behaviors:**
- GET /payroll/ auto-creates/regenerates for current month if missing/draft.
- Extra hours detected from SessionReport vs chapter duration.
- Faculty can preview own salary.
- Role guards throughout.

---

## FULL WALKTHROUGH: Monthly Payroll Process

### Step 1: Configure Late Policy (Admin)
POST or PATCH `/payroll/late-policy/` with branch-specific rules (grace_period_minutes=15, deduction_per_minute=10, etc.).

### Step 2: Generate Payroll
**GET** or **POST** `/payroll/?month=6&year=2026&branch_id=...`
- Auto-computes for all active faculty using `compute_payslip_for_faculty()`.
- Creates `PayrollRun` (draft) + `PaySlip`s.
- Pulls hours from timetable SessionReports, applies late penalties, leaves, extra hours.

**Response includes** total_amount, faculty_count.

### Step 3: Review & Adjust Payslips
- GET `/payroll/<run_id>/payslips/` — List with details.
- PATCH `/payroll/<run_id>/payslips/<slip_id>/` — Adjust bonus, deductions, notes. Recalcs net_salary and run total.

### Step 4: Extra Hours Approvals
- GET `/payroll/extra-hours/` — List pending auto-detected overtime.
- PATCH `/payroll/extra-hours/<id>/` (super_admin only) with `status=approved/rejected`. If approved, updates related payslip on next compute.

### Step 5: Approve Payroll
**POST** `/payroll/<run_id>/approve/` — Changes to `approved`, sets approved_by/at, sends notification.

### Step 6: Disburse
**POST** `/payroll/<run_id>/disburse/` — Sets `disbursed`, marks all payslips `is_disbursed=True`, sends per-faculty in-app notifications with salary summary.

### Step 7: Faculty Self-Service
- GET `/faculty/<id>/payslips/` — Historical slips.
- GET `/faculty/<id>/salary-preview/?month=6&year=2026` — Current estimate (uses `preview_payslip_for_faculty()`).

### Step 8: My Payroll (Logged-in Faculty)
- GET `/payroll/my/` — Personal payroll history (see below).

**Integration Notes:** 
- Depends on accurate `SessionReport` from timetable/attendance.
- Ties to `faculty` module (profiles with basic_salary, hourly_rate).
- Can link to `fees` for any faculty fee recoveries if extended.
- Draft runs regenerate automatically to reflect new sessions/leaves.

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
    "faculty_count": 5,
    "generated_at": "2026-06-01T10:00:00Z"
  }
}
```

- **GET** `/api/v1/payroll/<run_id>/` — Detail (with summary).
- **PATCH** `/api/v1/payroll/<run_id>/` — Update notes or status (limited transitions).
- **DELETE** `/api/v1/payroll/<run_id>/` — Only for draft/pending.

### Payslips & Adjustments
- **GET** `/api/v1/payroll/<run_id>/payslips/` — List slips for run (includes late_logs).

**Example Payslip Data:**
```json
{
  "id": "ps-uuid",
  "faculty_name": "Prof. Ramesh Kumar",
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
Returns all payroll history for the currently authenticated faculty member — no admin role needed. Auto-resolves the faculty profile from the auth token.

**Query params:** `?year=2026` `?month=6` `?status=disbursed`

**Response:**
```json
{
  "success": true,
  "faculty": {
    "id": "fp-uuid",
    "employee_id": "EMP-2026-0001",
    "name": "Prof. Ramesh Kumar",
    "email": "ramesh@institute.com"
  },
  "summary": {
    "total_payslips": 3,
    "total_net_earned": "125000.00",
    "total_disbursed": "80000.00"
  },
  "payslips": [
    {
      "id": "ps-uuid",
      "payroll_month": 6,
      "payroll_year": 2026,
      "payroll_status": "Disbursed",
      "branch_name": "Main Branch",
      "basic_salary": "50000.00",
      "hour_based_amount": "15000.00",
      "late_penalty": "500.00",
      "absence_deductions": "0.00",
      "leave_deductions": "2000.00",
      "bonus": "5000.00",
      "net_salary": "67500.00",
      "sessions_conducted": 45,
      "is_disbursed": true,
      "late_logs": []
    }
  ]
}
```

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
- **GET** `/api/v1/payroll/extra-hours/` — Filtered list.
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
    "faculty_count": 5,
    "total_amount": "125000.00"
  }
}
```

**Notifications:** In-app to faculty with net salary, sessions count.

---

## Status Transition Logic

```text
draft (auto-generated) ──(adjustments)──► pending_approval
pending_approval ──(approve)──► approved
approved ──(disburse)──► disbursed (final, no edits)
```

- Drafts auto-regenerate on access to reflect new SessionReports.
- Extra hours approval can trigger payslip recalc.
- Permissions strictly enforced per role.

**Common Errors:**
- 403: Role not allowed (e.g. faculty can't approve).
- 400: Invalid transition, disbursed slip can't be edited, missing branch.
- 409: Payroll already exists in final state.

---

**Related Modules:**
- `faculty` (profiles, hourly_rate, SessionReport from timetable)
- `timetable` / `attendance` (source of hours and late data)
- `leave` (deductions)
- `core` (notifications stub)
- Links to `fees` possible for recoveries (future).

This guide fully documents the current payroll implementation, auto-generation logic, utils, role guards, and integrations. Matches updates in fees/students modules.
