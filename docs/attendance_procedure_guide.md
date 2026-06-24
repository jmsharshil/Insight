# Attendance & Analytics — Full API Reference Guide

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `application/json`  
> All responses are wrapped in `{ "success": true/false, "data": ... }`.

---

## Architecture & Workflow Diagram

```text
                              ┌─────────────────────────────┐
                              │     ATTENDANCE MARKING      │
                              └──────────────┬──────────────┘
                                             │
               ┌─────────────────────────────┼─────────────────────────────┐
               ▼                             ▼                             ▼
    [Mobile App / Web App]         [Mobile App]                  [Mobile App / Web App]
  Manual Batch Marking          Student scans Class QR        Employee Self Check-In/Out
  by Admin/Faculty               (student attendance)         (staff attendance via scan)
               │                             │                             │
               ▼                             ▼                             ▼
    POST /attendance/           POST /attendance/qr-scan/     POST /attendance/employee/scan/
               │                             │                             │
               ▼                             ▼                             ▼
  ┌───────────────────────┐   ┌───────────────────────┐   ┌───────────────────────────────┐
  │ Creates multiple      │   │ Validates Location,   │   │ Creates/updates               │
  │ AttendanceRecord      │   │ Time, Device, and     │   │ EmployeeAttendanceRecord      │
  │ (student-based)       │   │ logs QRScanLog        │   │ (user-based, per date)        │
  └───────────┬───────────┘   └───────────┬───────────┘   └───────────────┬───────────────┘
              │                           │                               │
              └───────────────┬───────────┘                               │
                              ▼                                           │
               ┌─────────────────────────────┐                            │
               │   STUDENT ATTENDANCE DB     │                            │
               └──────────────┬──────────────┘                            │
                              │                                           ▼
        ┌─────────────────────┴─────────────────────┐  ┌─────────────────────────────────┐
        ▼                                           ▼  │   EMPLOYEE ATTENDANCE DB        │
  [Web App - Dashboards]                 [Violations]  │   (for payroll integration)     │
  Role-based Reports,                  Proxy scans,    └─────────────────────────────────┘
  Registers, Defaulters               flagged auto
```

---

## Data Models

### Student Attendance Models
| Model | Purpose |
|-------|---------|
| `AttendanceRecord` | One record per student per date per batch (status, check-in/out times) |
| `QRScanLog` | Raw QR scan audit trail (device, location, time) |
| `AlertLog` | Low-attendance alerts sent to parents/admin |
| `ViolationRecord` | Proxy scans, location mismatches, missing checkouts |

### Employee Attendance Model (NEW)
| Model | Purpose |
|-------|---------|
| `EmployeeAttendanceRecord` | One record per employee (User) per date. Tracks status + check-in/out timestamps for ALL non-student staff. Feeds into payroll computation. |

**EmployeeAttendanceRecord Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `user` | FK → User | The employee |
| `branch` | FK → Branch | Branch where attendance was recorded |
| `date` | Date | Attendance date |
| `status` | Choice | `present`, `absent`, `late`, `half_day`, `on_leave`, `checkout_pending` |
| `checked_in_at` | DateTime | Check-in timestamp (nullable) |
| `checked_out_at` | DateTime | Check-out timestamp (nullable) |
| `marked_by` | FK → User | Admin who marked (null for self-scan) |
| `is_corrected` | Boolean | Whether record was manually corrected |
| `corrected_by` | FK → User | Who corrected it |
| `correction_note` | Text | Reason for correction |

**Unique constraint:** `(user, date)` — one record per employee per day.

---

## Appendix A: System Choice Values

### A.1 Student Attendance Statuses (`status`)
| Value | Display | Notes |
| :--- | :--- | :--- |
| `present` | Present | Fully attended |
| `absent` | Absent | Did not attend |
| `late` | Late | Arrived after grace period |
| `half_day` | Half Day | Attended partial session |
| `on_leave` | On Leave | Approved leave |

### A.2 Employee Attendance Statuses (`status`)
| Value | Display | Notes |
| :--- | :--- | :--- |
| `present` | Present | Checked in and out |
| `absent` | Absent | No check-in recorded |
| `late` | Late | Checked in after expected time |
| `half_day` | Half Day | Partial day |
| `on_leave` | On Leave | Approved leave |
| `checkout_pending` | Checkout Pending | Checked in but not yet out |

### A.3 QR Scan Types (`scan_type`)
| Value | Display | Notes |
| :--- | :--- | :--- |
| `check_in` | Check In | Entering the class/premises |
| `check_out` | Check Out | Leaving the class/premises |
| `exam_entry` | Exam Entry | Entry specifically for exams |

### A.4 Violation Types (`violation_type`)
| Value | Display | Notes |
| :--- | :--- | :--- |
| `proxy_scan` | Proxy Scan | Same device used for multiple students |
| `location_mismatch` | Location Mismatch | Scanned far from branch geofence |
| `missing_checkout` | Missing Checkout | Checked in but never checked out |
| `other` | Other | Custom admin logged violations |

---

## SECTION 1 — Mobile App APIs (Core Attendance Marking)

These APIs are primarily used by the **Mobile App** for daily operations by Faculty and Students.

---

### 1.1 Submit Batch Attendance (Manual)
**Used by:** Faculty, Admins (Mobile App & Web App)  
**`POST /api/v1/attendance/`**

Used by faculty to manually mark attendance for a whole batch.

#### Request Body
```json
{
  "batch_id": "batch-uuid-001",
  "branch_id": "branch-uuid-001",
  "date": "2026-06-13",
  "records": [
    {
      "student_id": "student-uuid-001",
      "status": "present"
    },
    {
      "student_id": "student-uuid-002",
      "status": "absent"
    }
  ]
}
```

#### Response (201 Created)
```json
{
  "success": true,
  "message": "2 records created.",
  "created_ids": ["record-uuid-001", "record-uuid-002"],
  "errors": []
}
```

---

### 1.2 QR Scan Check-In / Check-Out
**Used by:** Students (Mobile App only)  
**`POST /api/v1/attendance/qr-scan/`**

Students scan a Class/Batch QR code to mark themselves present. The backend performs multiple validations:
1. **Geofencing** (location within branch)
2. **Time window** (within class schedule)
3. **Device uniqueness** (prevent proxy)
4. **Fee Status** — Calls `fees.utils.has_overdue_installment(student_id)`. If student has any unpaid installment >15 days past due_date, scan is **blocked**.

#### Request Body
```json
{
  "qr_data": "batch-uuid-001",
  "scan_type": "check_in",
  "device_id": "dev-12345-abcde",
  "latitude": 19.0760,
  "longitude": 72.8777,
  "timetable_slot": "slot-uuid-001",
  "session_reports": [
    {
      "batch_id": "uuid",
      "subject_id": "uuid",
      "chapter_ids": ["uuid-1", "uuid-2"],
      "status": "continue",
      "topics_covered": "Introduction to accounting"
    }
  ]
}
```
*(Note: `timetable_slot` is optional but recommended if scanning for a specific lecture. `session_reports` is specifically used by faculty during `check_out` to automatically log session details.)*

#### Response — Success (201 Created)
```json
{
  "success": true,
  "student_name": "Rohan Sharma",
  "roll_number": "101",
  "scan_time": "2026-06-13T08:00:00Z",
  "scan_type": "check_in",
  "device_id": "dev-12345-abcde",
  "is_valid": true,
  "attendance_status": "present",
  "checked_in_at": "2026-06-13T08:00:00Z",
  "checked_out_at": null,
  "location_verified": true,
  "time_verified": true,
  "validation_reason": "Location within branch geofence.",
  "message": "Class QR check_in recorded successfully."
}
```

#### Response — Fee Overdue Block (403)
```json
{
  "success": false,
  "message": "Attendance blocked: Student has overdue installments (>15 days past due date). Please clear fees to continue.",
  "reason": "overdue_installment",
  "overdue_count": 1,
  "next_due_date": "2026-05-01"
}
```

**Implementation Note:** The check uses `fees.utils.has_overdue_installment(student_id)` which queries unpaid `InstallmentItem`s where `due_date < (today - 15 days)` and plan status is approved/active. This integrates the Fees module with Attendance.

---

### 1.3 Student's Own Attendance History
**Used by:** Students, Parents (Mobile App & Web App)  
**`GET /api/v1/attendance/student/<student_id>/`**

Shows a student's own attendance records, summary, and any active violations.

#### Query Params (Optional)
- `month=2026-06`
- `batch_id=uuid`

#### Response (200 OK)
```json
{
  "success": true,
  "summary": {
    "present": 18,
    "absent": 2,
    "total": 20,
    "percentage": 90.0
  },
  "data": [
    {
      "date": "2026-06-13",
      "status": "present",
      "checked_in_at": "2026-06-13T08:00:00Z",
      "checked_out_at": "2026-06-13T12:00:00Z",
      "marked_by_name": "Self (QR)"
    }
  ],
  "violations": []
}
```

---

## SECTION 2 — Employee (Staff) Attendance APIs (NEW)

These APIs handle attendance tracking for **all non-student users** (faculty, admin, accountant, security, etc.). Data feeds into the payroll module's `compute_payslip_for_user()`.

---

### 2.0 Employee Self Check-In / Check-Out
**Used by:** Any authenticated employee (Mobile App & Web App)  
**`POST /api/v1/attendance/employee/scan/`**

Self-service check-in or check-out. Creates an `EmployeeAttendanceRecord` for today. On check-in, status is set to `checkout_pending`. On check-out, status is updated to `present`.

#### Request Body
```json
{
  "scan_type": "check_in"
}
```

#### Response — Check-In Success (200 OK)
```json
{
  "success": true,
  "message": "Check In recorded.",
  "data": {
    "id": "ear-uuid-001",
    "user": "user-uuid",
    "user_name": "Priya Verma",
    "employee_id": "EMP-HQ-0012",
    "branch": "branch-uuid",
    "branch_name": "Main Campus",
    "date": "2026-06-24",
    "status": "checkout_pending",
    "status_display": "Checkout Pending",
    "checked_in_at": "2026-06-24T09:02:00Z",
    "checked_out_at": null,
    "marked_by": null,
    "marked_by_name": null,
    "marked_at": "2026-06-24T09:02:00Z",
    "is_corrected": false,
    "corrected_by": null,
    "correction_note": ""
  }
}
```

#### Response — Check-Out Success (200 OK)
```json
{
  "success": true,
  "message": "Check Out recorded.",
  "data": {
    "...same fields...",
    "status": "present",
    "status_display": "Present",
    "checked_out_at": "2026-06-24T18:00:00Z"
  }
}
```

#### Error Cases
- `409 Conflict` — "Already checked in today." or "Already checked out today."
- `400 Bad Request` — "Must check in first before checking out." or "No branch assigned to your account."

---

### 2.0b Bulk Mark Employee Attendance (Admin)
**Used by:** Admins only (Web App)  
**`POST /api/v1/attendance/employee/`**

Bulk mark attendance for multiple employees at once. Creates or updates `EmployeeAttendanceRecord` for each employee on the given date.

#### Request Body
```json
{
  "branch_id": "branch-uuid-001",
  "date": "2026-06-24",
  "records": [
    { "user_id": "user-uuid-001", "status": "present" },
    { "user_id": "user-uuid-002", "status": "absent" },
    { "user_id": "user-uuid-003", "status": "late" }
  ]
}
```

#### Response (201 Created)
```json
{
  "success": true,
  "message": "Created 2, updated 1 records.",
  "errors": []
}
```

---

### 2.0c List Employee Attendance Records
**Used by:** Admins (all in branch), Staff (own records only)  
**`GET /api/v1/attendance/employee/`**

#### Query Params (Optional)
- `date=2026-06-24` — single date
- `from_date=2026-06-01` & `to_date=2026-06-30` — date range
- `status=present` — filter by status
- `user_id=uuid` — filter by specific user (admin only)

#### Response (200 OK)
Paginated list of `EmployeeAttendanceRecord` objects.

---

### 2.0d Employee Attendance History (Personal)
**Used by:** Any authenticated employee  
**`GET /api/v1/attendance/employee/history/`**

Personal attendance history with summary statistics.

#### Query Params (Optional)
- `year=2026`
- `month=6`
- `from_date=2026-06-01`
- `to_date=2026-06-30`

#### Response (200 OK)
```json
{
  "success": true,
  "summary": {
    "total_days": 22,
    "present_days": 20,
    "absent_days": 1,
    "half_days": 1,
    "on_leave": 0,
    "attendance_percentage": 90.9
  },
  "records": [
    {
      "id": "ear-uuid-001",
      "user": "user-uuid",
      "user_name": "Priya Verma",
      "employee_id": "EMP-HQ-0012",
      "branch": "branch-uuid",
      "branch_name": "Main Campus",
      "date": "2026-06-24",
      "status": "present",
      "status_display": "Present",
      "checked_in_at": "2026-06-24T09:02:00Z",
      "checked_out_at": "2026-06-24T18:00:00Z",
      "marked_by": null,
      "marked_by_name": null,
      "is_corrected": false
    }
  ]
}
```

> **Payroll Integration:** The `EmployeeAttendanceRecord` data is consumed by `compute_payslip_for_user()` in the payroll module. `present`, `late`, and `half_day` records count as days attended. Actual hours worked are computed from `checked_in_at` / `checked_out_at` for hourly-rate employees.

---

## SECTION 3 — Web App APIs (Dashboards & Reports)

These APIs are exclusively for the **Web App** (Admin Panel) to view analytics, reports, registers, and resolve violations.

---

### 3.1 Dashboard Summary
**Used by:** Admins, Branch Managers (Web App)  
**`GET /api/v1/attendance/dashboard/`**

High-level summary of today's attendance for the organization or specific branch.

#### Query Params (Optional)
- `date=2026-06-13`
- `branch=uuid`
- `batch=uuid`

#### Response (200 OK)
```json
{
  "success": true,
  "data": {
    "total_students": 500,
    "present_today": 450,
    "absent_today": 40,
    "late_today": 10,
    "attendance_percentage": 91.83,
    "active_violations": 5,
    "faculty_attendance_summary": {
      "total_faculty": 20,
      "present": 19,
      "absent": 1
    },
    "branch_wise_attendance": [
      {
        "branch_id": "branch-uuid-001",
        "branch_name": "Main Campus",
        "percentage": 92.5
      }
    ]
  }
}
```

---

### 3.2 Batch-wise Attendance Summary
**Used by:** Admins, Branch Managers (Web App)  
**`GET /api/v1/attendance/batch-wise/`**

Summary of attendance aggregated by batch. Useful for plotting batch-wise attendance comparisons.

#### Query Params (Optional)
- `date_from=2026-06-01`
- `date_to=2026-06-13`
- `branch=uuid`
- `faculty=uuid`

#### Response (200 OK)
```json
{
  "success": true,
  "count": 2,
  "data": [
    {
      "batch_id": "batch-uuid-001",
      "batch_name": "CS Executive",
      "batch_code": "CSE-001",
      "total_students": 45,
      "present_count": 40,
      "absent_count": 5,
      "attendance_percentage": 88.89
    }
  ]
}
```

---

### 3.3 List Students (with Attendance Aggregates)
**Used by:** Admins, Branch Managers, Faculty (Web App)  
**`GET /api/v1/attendance/students/`**

Lists students along with their computed attendance percentages and basic stats for a given period.

#### Query Params (Optional)
- `branch_id=uuid`
- `batch_id=uuid`
- `date_from=2026-06-01`
- `date_to=2026-06-30`
- `attendance_percentage_min=75`
- `attendance_percentage_max=100`

#### Response (200 OK)
```json
{
  "success": true,
  "count": 1,
  "page_size": 50,
  "data": [
    {
      "id": "student-uuid-001",
      "student_profile": {
        "id": "student-uuid-001",
        "name": "Rohan Sharma",
        "roll_number": "101",
        "admission_number": "ADM2026001",
        "photo": null,
        "branch_name": "Main Campus",
        "batch_name": "CS Executive"
      },
      "attendance_percentage": 90.0,
      "present_count": 18,
      "absent_count": 2,
      "late_count": 0,
      "last_attendance_date": "2026-06-13"
    }
  ]
}
```

---

### 3.4 Detailed Student Analytics
**Used by:** Admins, Faculty (Web App)  
**`GET /api/v1/attendance/students/<student_id>/`**

Deep-dive into a single student's attendance, including subject-wise, session-wise, and monthly trends.

#### Response (200 OK)
```json
{
  "success": true,
  "data": {
    "student_profile": {
        "id": "student-uuid-001",
        "name": "Rohan Sharma",
        "roll_number": "101",
        "admission_number": "ADM2026001",
        "branch_name": "Main Campus",
        "batch_name": "CS Executive"
    },
    "attendance_percentage": 90.0,
    "summary": { "present_count": 18, "absent_count": 2, "late_count": 0 },
    "check_in_history": [
      { "date": "2026-06-13", "time": "2026-06-13T08:00:00Z", "status": "present" }
    ],
    "check_out_history": [
      { "date": "2026-06-13", "time": "2026-06-13T12:00:00Z" }
    ],
    "violations": [],
    "monthly_trend": [
      { "month": "2026-05", "percentage": 92.0 },
      { "month": "2026-06", "percentage": 90.0 }
    ],
    "subject_wise_attendance": [
      { "subject_id": "uuid", "subject_name": "Company Law", "percentage": 100.0 }
    ],
    "session_wise_attendance": [
      { "session": "P1", "percentage": 85.0 }
    ]
  }
}
```

---

### 3.5 Batch Attendance Register (Matrix View)
**Used by:** Admins, Faculty (Web App)  
**`GET /api/v1/attendance/batches/<batch_id>/register/`**

Returns a tabular matrix (Rows = Students, Columns = Dates) for rendering an attendance register/sheet in the web frontend.

#### Query Params
- `month=2026-06` (Optional, defaults to current month)

#### Response (200 OK)
```json
{
  "success": true,
  "data": {
    "month": "2026-06",
    "dates": ["2026-06-01", "2026-06-02"],
    "register": [
      {
        "student_id": "student-uuid-001",
        "student_name": "Rohan Sharma",
        "roll_number": "101",
        "attendance": {
          "2026-06-01": { "status": "present", "checked_in_at": "...", "checked_out_at": "..." },
          "2026-06-02": { "status": "absent", "checked_in_at": null, "checked_out_at": null }
        }
      }
    ]
  }
}
```

---

### 3.6 Flat Attendance History (Audit Logs)
**Used by:** Admins (Web App)  
**`GET /api/v1/attendance/history/`**

A flat list of all attendance logs, heavily filterable. Used for global audit tables.

#### Query Params
- `student_id`, `branch_id`, `batch_id`, `faculty_id`, `date_from`, `date_to`, `attendance_status`, `session`, `subject`, `page`, `page_size`

#### Response (200 OK)
```json
{
  "success": true,
  "count": 100,
  "page_size": 50,
  "data": [
    {
      "date": "2026-06-13",
      "check_in_time": "2026-06-13T08:00:00Z",
      "check_out_time": "2026-06-13T12:00:00Z",
      "status": "present",
      "late_status": "normal",
      "session": "P1",
      "subject": "Company Law",
      "scanner_device": "dev-12345-abcde"
    }
  ]
}
```

---

## SECTION 4 — Violations & Admin Corrections (Web App)

---

### 4.1 List Violations
**`GET /api/v1/attendance/violations/`**  
Lists all QR scan violations (e.g., location mismatch, proxy).

### 4.2 Create Manual Violation
**`POST /api/v1/attendance/violations/`**  
Admins can manually flag a student for a violation.
```json
{
  "student_id": "uuid",
  "violation_type": "other",
  "date": "2026-06-13",
  "description": "Caught bunking class."
}
```

### 4.3 Resolve Violation
**`PATCH /api/v1/attendance/violations/<violation_id>/`**  
Admins mark a violation as resolved after discussion with parents/student.
```json
{
  "is_resolved": true,
  "resolution_note": "Warning letter issued to parents."
}
```

### 4.4 Correct Single Attendance Record
**`GET / PATCH /api/v1/attendance/<record_id>/`**  
Used by admins to correct a mistakenly marked attendance (e.g. changing absent to present).

---

## SECTION 5 — Reporting & Alerts

### 5.1 Trigger Low Attendance Alerts
**Used by:** Admins (Web App)  
**`POST /api/v1/attendance/alert/`**

Checks all students in a branch and triggers an alert if their attendance is below the threshold.
```json
{
  "branch_id": "branch-uuid-001",
  "threshold": 75.0
}
```

### 5.2 Defaulters List
**`GET /api/v1/attendance/defaulters/`**  
Returns students whose attendance is below the institutional threshold.

### 5.3 Export Attendance
**`GET /api/v1/attendance/export/?format=csv&batch_id=uuid`**  
Generates and downloads a CSV/Excel export of the attendance register.

---

## Full URL Reference

| Method | Endpoint | Purpose |
|--------|----------|---------|
| **Student Attendance** | | |
| `POST` | `/api/v1/attendance/` | Batch mark student attendance |
| `POST` | `/api/v1/attendance/qr-scan/` | Student QR scan |
| `GET/PATCH` | `/api/v1/attendance/<record_id>/` | Correction |
| `GET` | `/api/v1/attendance/student/<student_id>/` | Student history |
| `GET` | `/api/v1/attendance/batch/<batch_id>/` | Batch sheet |
| `GET` | `/api/v1/attendance/report/` | Report |
| `POST` | `/api/v1/attendance/alert/` | Trigger alerts |
| **Employee Attendance (NEW)** | | |
| `GET/POST` | `/api/v1/attendance/employee/` | List/bulk mark staff attendance |
| `POST` | `/api/v1/attendance/employee/scan/` | Self check-in/out |
| `GET` | `/api/v1/attendance/employee/history/` | Personal history with summary |
| **Analytics** | | |
| `GET` | `/api/v1/attendance/dashboard/` | Dashboard summary |
| `GET` | `/api/v1/attendance/students/` | Student list with stats |
| `GET` | `/api/v1/attendance/students/<id>/` | Student detail |
| `GET` | `/api/v1/attendance/history/` | Audit log |
| `GET` | `/api/v1/attendance/batches/<id>/register/` | Register matrix |
| `GET` | `/api/v1/attendance/faculty/` | Faculty attendance list |
| `GET` | `/api/v1/attendance/faculty/<id>/` | Faculty attendance detail |
| `GET` | `/api/v1/attendance/batch-wise/` | Batch-wise summary |
| `GET` | `/api/v1/attendance/analytics/` | Analytics |
| `GET` | `/api/v1/attendance/defaulters/` | Defaulter students |
| `GET/POST` | `/api/v1/attendance/violations/` | Violations |
| `GET/PATCH` | `/api/v1/attendance/violations/<id>/` | Violation detail |
| `GET` | `/api/v1/attendance/export/` | Export CSV/Excel |
| `GET` | `/api/v1/attendance/audit-logs/` | Audit logs |

---

## Cross-Module Integration

```text
┌──────────────────────┐     ┌──────────────────────┐
│ EmployeeAttendance   │────►│ Payroll Module        │
│ Record               │     │ compute_payslip_for_  │
│ (days_attended,      │     │ user() uses records   │
│  check-in/out hours) │     │ for absence/hour calc │
└──────────────────────┘     └──────────────────────┘

┌──────────────────────┐     ┌──────────────────────┐
│ Student Attendance   │────►│ Fees Module           │
│ QR Scan              │     │ Overdue check blocks  │
│                      │     │ QR scan if >15 days   │
└──────────────────────┘     └──────────────────────┘

┌──────────────────────┐     ┌──────────────────────┐
│ Leave Module         │────►│ Attendance (both)     │
│ Approved leaves      │     │ on_leave status auto  │
│                      │     │ set where applicable  │
└──────────────────────┘     └──────────────────────┘
```
