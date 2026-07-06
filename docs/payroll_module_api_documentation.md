# Payroll Module — Full Walkthrough & API Reference Guide

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `application/json`  
> Role-based access: `super_admin`, `accountant`, `branch_manager`, `faculty`, and all employee roles.  
> Responses: `{ "success": true/false, "message": "...", "data": {...} }`.

---

## Key Utility Functions (`payroll/utils.py`)

### `compute_payslip_for_faculty(faculty_profile, month, year, payroll_run)`
- **Core calculator for faculty** (full_time/part_time/visiting).
- Reconciles `SessionReport` (with chapters) + `FacultyQRScanLog` for hours.
- Per-subject hourly rates via `SubjectHourlyRate` (effective_from) or fallback to `faculty.hourly_rate` / `user.hourly_rate`.
- **Extra hours logic**: Compares monthly chapter minutes vs allocated (`Chapter.duration_hours`); auto-creates `ExtraHoursApproval` (pending); only payable if approved.
- Late penalties: aggregates daily delays from QR + sessions; uses `LateEntryPolicy` (grace, deduction_per_minute, max_deduction, absence_deduction_per_day, late_entry_threshold, auto_halfday_deduction); Sundays exempt; 15min+ counts toward half-day threshold (3x15min=0.5 day).
- Absence = (working_days - attended) + half-days; Sunday attendance counts as full day.
- Deductions: unpaid leaves, salary_retention_percentage, other.
- Bonuses: attendance (>80%), leave_encashment (March only, from LeaveBalance).
- Creates `PaySlip` (faculty FK), `SessionLatePenaltyLog`s; updates `PayrollRun.total_amount` via signal.
- **Regenerates** on draft payroll access.

### `compute_payslip_for_user(user, month, year, payroll_run)`
- **Simplified calculator for non-faculty** (all `EMPLOYEE_ROLES`).
- **Special case for `paper_checker`** (v2 recheck/CheckerQuery integration):
  - Counts `MarkSheet` where `paper_checker=user`, `is_submitted=True`, `checked_at` in month, **excluding** open `queries` (CheckerQuery.status='open') or recheck_requests with status in ['approval_pending', 'approved'].
  - Uses `user.per_paper_rate` (default 50); `sessions_conducted` = papers_checked.
  - Late penalty: 5 days grace after `exam.scheduled_date`; bracketed % penalty (5%,10%,15%...) folded into `late_penalty`.
  - No attendance/leave/sunday/absence for this role; payment = (papers * rate) - penalties - retention.
- For other staff (`house_keeping`/`security` have Sunday rules: 2 required; <2 = deduction, >=3 = bonus day).
- Uses `EmployeeAttendanceRecord`, `LateEntryRecord`, `LeaveApplication`.
- Handles base/hourly, unpaid leaves, late penalties (via policy or implicit), absence, retention (`salary_retention_percentage`), attendance_bonus (>80%), leave_encashment (March).
- Deletes old payslip on regen; creates new with `user` FK (`faculty=null`); updates run total via signal.
- **Blocks payment** for unresolved CheckerQuery/RecheckRequest (per results v2 + answer-key gate).

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

**Integration:** 
- `timetable`/`faculty`: SessionReport, FacultyQRScanLog, SubjectHourlyRate, Chapter (for extra hours).
- `attendance`: EmployeeAttendanceRecord, LateEntryRecord.
- `leave`: LeaveApplication, LeaveBalance, LateEntryRecord.
- `results` (v2): MarkSheet + RecheckRequest + CheckerQuery (excludes open queries/rechecks from paper_checker payroll; answer-key mandatory for rechecks).
- `batches`/`exams`: for scheduled times, per-paper late calc.
- Auto `ExtraHoursApproval` + signal-driven total recalc. Drafts auto-regenerate. Matches Exam v2, session_type flows, role constants, `{success, data}`.

---

## Data Models & Statuses

### Core Models
| Model | Purpose |
|-------|---------|
| `PayrollRun` | Monthly batch (per branch/month/year). Status + `total_amount`, `notes`. Auto-regen on draft. |
| `PaySlip` | Per-employee (fields: basic_salary, total_session_hours, hour_based_amount, late_penalty, absence_deductions, leave_deductions, retention_deduction, other_deductions, bonus, attendance_bonus, leave_encashment, net_salary, sessions_conducted, deduction_note, working_days, leaves_taken, is_disbursed). Links to **either** `faculty` or `user`. |
| `LateEntryPolicy` | Branch config (grace_period_minutes, deduction_per_minute, max_deduction_per_session, absence_deduction_per_day, late_entry_threshold, auto_halfday_deduction). |
| `SessionLatePenaltyLog` | Audit trail for faculty late sessions (linked to SessionReport). |
| `ExtraHoursApproval` | Auto-created for faculty overtime vs chapter allocation; status=pending/approved/rejected. |
| `CheckerQuery` (in results) | Raised by paper_checker on MarkSheet; open status blocks payroll count until resolved (recheck v2 gate). |

### PaySlip FK Strategy
| Employee Type | `faculty` FK | `user` FK | Source of Data | Special Notes |
|---------------|-------------|-----------|----------------|---------------|
| Faculty | ✅ Set | null | SessionReport + QRScanLog + Chapter | Extra hours, per-subject rates, Sunday exempt |
| Non-faculty (staff roles) | null | ✅ Set | EmployeeAttendanceRecord + LateEntryRecord | Sunday rules for HK/security |
| `paper_checker` | null | ✅ Set | MarkSheet + CheckerQuery + RecheckRequest | Per-paper pay, 5-day grace + bracketed late penalty, excludes open queries/rechecks (v2) |

All produce standardized `PaySlip` fields. `net_salary` recalculated on adjustments; signal updates `PayrollRun.total_amount`.

### PayrollRun.status
- `draft` (editable, auto-regenerates on GET/POST)
- `pending_approval`
- `approved` (locked)
- `disbursed` (final, notifications sent)

**PaySlip** has `net_salary` recalc on adjustments. `is_disbursed` flag prevents edits.

---

## Architecture & Workflow Diagram

```text
FACULTY PATH:                                 PAPER_CHECKER / STAFF PATH:
  SessionReport + FacultyQRScanLog + Chapter     MarkSheet + CheckerQuery + RecheckRequest
           │                                             │
           ▼                                             ▼
  compute_payslip_for_faculty()               compute_payslip_for_user() (special for paper_checker)
           │                                             │
           └──────────────────────┬──────────────────────┘
                                  │
                                  ▼
  LateEntryPolicy + Leave + Attendance + Results(v2) blocking (open queries/rechecks excluded)
                                  │
                                  ▼
  GET/POST /payroll/ (auto-gen for ALL via EMPLOYEE_ROLES; draft=regenerate)
                                  │
                                  ▼
  PayrollRun(draft) ── adjust(PATCH payslip) ──► pending_approval
                                  │
  (branch_manager/super) approve ──► approved ──(accountant/super) disburse ──► disbursed
                                  │
                                  ▼
  In-app Notifications (all employees) + ExtraHoursApproval (super_admin review)
```

**Auto Behaviors (aligned with live codebase + Exam v2):**
- GET/POST `/payroll/` auto-creates/regenerates **draft** runs for current month (all active faculty + staff via `EMPLOYEE_ROLES`; skips if final status).
- For missing employees in approved runs → adds + sets pending_approval.
- Paper checker payroll uses results v2 (MarkSheet.is_submitted, excludes open CheckerQuery or pending rechecks; answer-key gate).
- Extra hours auto-detected only for faculty (creates pending ExtraHoursApproval).
- Drafts **regenerate on every GET/POST/detail/payslips access** to reflect latest attendance/queries/leaves.
- Faculty self-preview; `/my/` works for **all** roles (faculty or user-based payslip).
- Strict role guards (`PAYROLL_*_ROLES` constants in views.py); `{success, data}` everywhere.

---

## Role Constants (`views.py` + `utils.py`)
```python
PAYROLL_GENERATE_ROLES = ['accountant', 'super_admin']
PAYROLL_VIEW_ROLES = ['accountant', 'super_admin', 'branch_manager']
PAYROLL_APPROVE_ROLES = ['branch_manager', 'super_admin']
PAYROLL_DISBURSE_ROLES = ['super_admin', 'accountant']
LATE_POLICY_VIEW_ROLES = ['super_admin', 'branch_manager', 'accountant']
LATE_POLICY_EDIT_ROLES = ['super_admin', 'branch_manager']
# EMPLOYEE_ROLES from utils (14 roles incl. paper_checker, exam_supervisor, house_keeping, security)
```
Cross-references `auth_user_procedure_guide.md` (role matrix, exam_supervisor/paper_checker added for payroll).

## FULL WALKTHROUGH: Monthly Payroll Process (Synchronized to Live Codebase)

### Step 1: Late Policy Config
- GET/POST/PATCH/DELETE `/payroll/late-policy/` (and detail).
- Supports all fields from model (incl. absence_deduction_per_day, auto_halfday, threshold). Branch-unique.

### Step 2: Generate Payroll (Auto on GET)
- **GET/POST** `/payroll/?year=...&month=...&branch_id=...` or POST body.
- Auto for **current month** on GET; creates/regenerates draft for **all** active employees (faculty + staff via EMPLOYEE_ROLES, org/branch filtered).
- Uses both compute funcs; paper_checker uses results v2 (excludes open CheckerQuery or pending/approved RecheckRequest).
- Response example matches code: `{ "success": true, "message": "Payroll generated.", "data": { "payroll_run_id": "...", "status": "draft", "total_amount": "...", "employee_count": 15, ... } }`.
- Drafts fully regenerated on access (payslips deleted + recomputed); final runs add missing only.

### Step 3: Review, List & Adjust Payslips
- **GET** `/payroll/<run_id>/` — detail (regens draft).
- **GET** `/payroll/<run_id>/payslips/` — list with late_logs, derived fields (faculty_name, per_paper_rate, employment_type, total_salary_sum in response).
- **PATCH** `/payroll/<run_id>/payslips/<slip_id>/` — bonus/other_deductions/deduction_note/leave_deductions; auto net_salary + run total recalc (accountant/super only; not if disbursed).
- DELETE payslip (super only).

### Step 4: Extra Hours, Preview & Paper-Checker Specifics
- **GET/PATCH** `/payroll/extra-hours/<id>/` (list + update status=approved/rejected by super_admin; recalc on draft payroll).
- **GET** `/faculty/<id>/salary-preview/?month=&year=` — full preview dict (no DB write; includes all computed fields like total_session_hours, absence etc.).
- For paper_checkers: payroll driven purely by submitted MarkSheets in month (with query/recheck exclusion + scheduled_date-based late % penalty).

### Step 5-6: Approve & Disburse
- **POST** `/payroll/<run_id>/approve/` — to 'approved' (limited transitions), notify.
- **POST** `/payroll/<run_id>/disburse/` — to 'disbursed', set is_disbursed=True on slips, **per-employee notify** with net_salary/sessions (core notifications).
- Only specific roles; 400 on invalid state.

### Step 7-8: Self Service
- **GET** `/faculty/<id>/payslips/?year=...` — historical (faculty + admins).
- **GET** `/payroll/my/?year=...&month=...` — unified for **all employees** (tries FacultyProfile then User); uses MyPaySlipSerializer; includes summary totals, role in employee object. 404 if no payslips.

**Status Transitions & Errors:** See dedicated sections below. Draft auto-regen is key behavior (reflects live attendance/queries/sessions immediately).

**Integration Notes (Updated):** Faculty depends on timetable/faculty SessionReport + QR + chapters (Exam v2 session_type compatible). Staff on attendance/leave. **Results v2 critical for paper_checker**: MarkSheet + RecheckRequest (answer-key gate) + CheckerQuery (open status blocks count in payroll until resolved). Signals, on-the-fly computation, no extra models. Matches dashboard/results/batches docs.

---

## Complete API Reference (Live Endpoints & Responses)

All responses follow `{ "success": bool, "message": str, "data": {...} }` (or with `count`, `total_salary_sum`).

### Payroll Runs (`/payroll/`)
- **GET/POST** `/api/v1/payroll/` — list or generate (auto for current month on GET; filters by year/month/status/branch_id; org-aware).
  - POST: `{"branch_id": "uuid", "month": 6, "year": 2026}`.
- **GET/PATCH/DELETE** `/api/v1/payroll/<run_id>/` — detail (auto-regen draft), update notes/status (limited), delete draft/pending.
- **GET** `/api/v1/payroll/<run_id>/payslips/` — payslips list (with late_logs; regens draft; extra `total_salary_sum` in response).

**Payslip Serializer Fields:** id, faculty/user_id, faculty_name, employee_id, basic_salary, total_session_hours, hour_based_amount, late_penalty, absence_deductions, leave_deductions, retention_deduction, other_deductions, bonus, attendance_bonus, leave_encashment, net_salary, sessions_conducted, leaves_taken, working_days, is_disbursed, deduction_note, late_logs, hourly_rate, per_paper_rate, employment_type, salary, session_hours.

### Extra Hours & Late Policy
- **GET** `/payroll/extra-hours/` (paginated, filters); **PATCH** `/payroll/extra-hours/<id>/` `{status: "approved"}` (super only; triggers recalc if draft).
- Late policy CRUD as above (serializer includes branch_name, all policy fields).

### Faculty Endpoints
- **GET** `/faculty/<faculty_id>/payslips/` — historical payslips (filtered).
- **GET** `/faculty/<faculty_id>/salary-preview/?month=...&year=...` — preview dict with all keys from `preview_payslip_for_faculty()` (basic_salary, total_session_hours, hour_based_amount, late_penalty, absence_deductions, leave_deductions, retention_deduction, attendance_bonus, leave_encashment, bonus=0, other_deductions=0, net_salary, leaves_taken, working_days, sessions_conducted).

### My Payroll
**GET `/payroll/my/`** (any authenticated employee role).
- Resolves via FacultyProfile or User.
- Returns employee info (incl. role), summary (total_payslips, total_net_earned, total_disbursed), list of payslips (MyPaySlipSerializer with payroll_month/year/status/branch_name).
- Supports ?year=&month=&status= filters. 404 if no history.

### Approve / Disburse
- **POST** `/payroll/<run_id>/approve/` → approved + notify.
- **POST** `/payroll/<run_id>/disburse/` → disbursed, update slips, **individual notifications** to each recipient_user.

**Example Disburse Response:**
```json
{
  "success": true,
  "message": "Payroll disbursed.",
  "data": {
    "disbursed": true,
    "faculty_count": 15,  // actually payslips.count()
    "total_amount": "425000.00"
  }
}
```

**Payslips in /payslips/ response also includes `total_salary_sum` calculated from salary or (hourly*session_hours).**

---

## Status Transition Logic

```text
draft (auto-regen on access) <── adjustments/adjusted-by-accountant ──► pending_approval
pending_approval ──(branch_manager/super approve)──► approved
approved ──(accountant/super disburse)──► disbursed (final, is_disbursed=True on slips, no edits)
```

- PATCH on run allows limited status changes (draft <-> pending_approval).
- ExtraHoursApproval approval affects subsequent faculty computes.
- Permissions via role constants; branch/org filtering throughout.

**Common Errors (from views):**
- 403 Forbidden: role not in PAYROLL_*_ROLES (e.g. faculty cannot generate/approve).
- 400 Bad Request: invalid transition, editing disbursed slip, missing branch, invalid data.
- 404: payroll/payslip/policy not found, or no payslips for /my/.
- 409 Conflict: trying to regenerate final payroll when all employees already covered.

---

## Cross-Module Integration (Updated for v2)

```text
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│   TIMETABLE/ │   │  ATTENDANCE  │   │    LEAVE     │   │   RESULTS v2 │
│   BATCHES    │   │              │   │              │   │ (MarkSheet,  │
│ SessionReport│◄──►│ EmployeeAtt..│◄──►│ LeaveApp,    │◄──►│ RecheckReq,  │
│ Chapter, QR  │   │ LateEntryRec │   │ LateEntryRec,│   │ CheckerQuery,│
│ (session_type│   │ Record       │   │ Balance      │   │ answer-key)  │
└──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
                           │                       │
                           └──────────► PAYROLL ◄──┘
                                 (compute_*, PaySlip, PayrollRun, ExtraHoursApproval,
                                  LatePolicy, SessionLatePenaltyLog; paper_checker special path)
```

**Related Modules (synchronized):**
- `faculty`: FacultyProfile (salary, hourly_rate, session_hours, employment_type, salary_retention_percentage), SessionReport, SubjectHourlyRate, FacultyQRScanLog, ExtraHoursApproval.
- `attendance`: EmployeeAttendanceRecord (for staff), LateEntryRecord.
- `leave`: LeaveApplication (unpaid), LeaveBalance (encashment).
- `results`: MarkSheet (paper_checker count, checked_at, is_submitted), RecheckRequest (v2 with approval_pending/approved exclusion), CheckerQuery (open status blocks payroll; query_types incl. answer_key_not_available).
- `exams`: Exam.scheduled_date for paper late penalty calc; ties to Exam v2 fields (geo, proctoring not directly used here).
- `batches`: Chapter for extra hours allocation, Subject for rates.
- `core`: notifications (in-app on approve/disburse), pagination, role guards.
- `branch`: for policies/runs.
- Matches `results_module_api_documentation.md` (recheck v2, answer-key gate, on-the-fly), `exams_module_api_documentation.md`, `dashboard_api_documentation.md` (no payroll KPIs yet), `attendance_procedure_guide.md`.

This guide is now **fully synchronized** with live E4 codebase (utils compute logic, paper_checker + CheckerQuery blocking, extra hours, auto-regen, role constants, serializers with derived fields, view behaviors, signals, Exam v2 integration). No model changes needed. See `payroll/tests.py` for (placeholder) tests. Run `python manage.py test payroll` to verify.

**Migration Note:** No new migrations required (models already updated). All docs audited against live implementation (dual-path `compute_*` utils, `LateEntryPolicy` v2, `ExtraHoursApproval` auto-create + signal, results v2 blocking via `queries__status='open'` and `recheck_requests__status__in=['approval_pending','approved']`, draft auto-regen on every access, `{success, data}` wrappers, role constants, dynamic serializers, Sunday rules, per-paper late brackets, `MyPayrollView` for all `EMPLOYEE_ROLES`).

The payroll module now fully supports faculty + all staff roles with tight integration to Exam v2, results v2 (MarkSheet/CheckerQuery/RecheckRequest), attendance, leave, timetable, and batches.
