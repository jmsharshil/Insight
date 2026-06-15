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
                       ┌─────────────────────┴─────────────────────┐
                       ▼                                           ▼
            [Mobile App / Web App]                       [Mobile App]
         Manual Batch Marking by Admin/Faculty         Student scans Class QR
                       │                                           │
                       ▼                                           ▼
            POST /api/v1/attendance/             POST /api/v1/attendance/qr-scan/
                       │                                           │
                       ▼                                           ▼
           ┌───────────────────────┐                 ┌───────────────────────┐
           │ Creates multiple      │                 │ Validates Location,   │
           │ AttendanceRecord      │                 │ Time, Device, and     │
           │ objects at once       │                 │ logs QRScanLog        │
           └───────────┬───────────┘                 └───────────┬───────────┘
                       │                                         │
                       └───────────────────┬─────────────────────┘
                                           ▼
                            ┌─────────────────────────────┐
                            │      ATTENDANCE DATABASE    │
                            └──────────────┬──────────────┘
                                           │
                     ┌─────────────────────┴─────────────────────┐
                     ▼                                           ▼
           [Web App - Dashboards]                     [Web App - Violations]
        Role-based access to Reports,                Proxy scans, location mismatches
        Registers, Defaulters, History               are flagged automatically
```

---

## Appendix A: System Choice Values

### A.1 Attendance Statuses (`status`)
| Value | Display | Notes |
| :--- | :--- | :--- |
| `present` | Present | Fully attended |
| `absent` | Absent | Did not attend |
| `late` | Late | Arrived after grace period |
| `half_day` | Half Day | Attended partial session |
| `on_leave` | On Leave | Approved leave |

### A.2 QR Scan Types (`scan_type`)
| Value | Display | Notes |
| :--- | :--- | :--- |
| `check_in` | Check In | Entering the class/premises |
| `check_out` | Check Out | Leaving the class/premises |
| `exam_entry` | Exam Entry | Entry specifically for exams |

### A.3 Violation Types (`violation_type`)
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

Students scan a Class/Batch QR code to mark themselves present. The backend validates geofencing and device IDs.

#### Request Body
```json
{
  "qr_data": "batch-uuid-001",
  "scan_type": "check_in",
  "device_id": "dev-12345-abcde",
  "latitude": 19.0760,
  "longitude": 72.8777,
  "timetable_slot": "slot-uuid-001" 
}
```
*(Note: `timetable_slot` is optional but recommended if scanning for a specific lecture)*

#### Response (201 Created)
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

## SECTION 2 — Web App APIs (Dashboards & Reports)

These APIs are exclusively for the **Web App** (Admin Panel) to view analytics, reports, registers, and resolve violations.

---

### 2.1 Dashboard Summary
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

### 2.2 Batch-wise Attendance Summary
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

### 2.3 List Students (with Attendance Aggregates)
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

### 2.3 Detailed Student Analytics
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

### 2.4 Batch Attendance Register (Matrix View)
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

### 2.5 Flat Attendance History (Audit Logs)
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

## SECTION 3 — Violations & Admin Corrections (Web App)

---

### 3.1 List Violations
**`GET /api/v1/attendance/violations/`**  
Lists all QR scan violations (e.g., location mismatch, proxy).

### 3.2 Create Manual Violation
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

### 3.3 Resolve Violation
**`PATCH /api/v1/attendance/violations/<violation_id>/`**  
Admins mark a violation as resolved after discussion with parents/student.
```json
{
  "is_resolved": true,
  "resolution_note": "Warning letter issued to parents."
}
```

### 3.4 Correct Single Attendance Record
**`GET / PATCH /api/v1/attendance/<record_id>/`**  
Used by admins to correct a mistakenly marked attendance (e.g. changing absent to present).

---

## SECTION 4 — Reporting & Alerts

### 4.1 Trigger Low Attendance Alerts
**Used by:** Admins (Web App)  
**`POST /api/v1/attendance/alert/`**

Checks all students in a branch and triggers an alert if their attendance is below the threshold.
```json
{
  "branch_id": "branch-uuid-001",
  "threshold": 75.0
}
```

### 4.2 Defaulters List
**`GET /api/v1/attendance/defaulters/`**  
Returns students whose attendance is below the institutional threshold.

### 4.3 Export Attendance
**`GET /api/v1/attendance/export/?format=csv&batch_id=uuid`**  
Generates and downloads a CSV/Excel export of the attendance register.
