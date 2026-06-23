# Faculty Module — Full Walkthrough & API Documentation

> **Base URL:** `{{BASE_URL}}/api/v1/faculty/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `application/json` (use `multipart/form-data` for photo uploads)  
> Most responses follow: `{ "success": true/false, "message": "...", "data": {...} }`.

---

## Data Models

| Model | Purpose |
|-------|---------|
| `FacultyProfile` | Core profile linked to `User`. Contains shift timings (`work_start_time`, `work_end_time`), salary/hourly rate, auto-generated `employee_id` and QR code. |
| `SubjectHourlyRate` | Subject-specific hourly pay rates that override the default `hourly_rate` in FacultyProfile. |
| `FacultyQRScanLog` | Records QR-based check-in/check-out. Automatically detects late arrivals and early departures based on timetable. |
| `SessionReport` | Detailed log of each teaching session (chapters covered, completion %, duration). Critical for payroll and performance tracking. |

### Key Fields in FacultyProfile
- `employee_id`: Auto-generated (format: `EMP-YYYY-XXXX`).
- `work_start_time` / `work_end_time`: Used for late/early penalty calculation during QR scans.
- `qr_code`: PNG image generated on creation.
- `hourly_rate` / `salary`: Base rates; subject rates take precedence where defined.
- `level`, `employment_type`: Executive/Professional and Full-time/Part-time/Contract.

---

## Key Workflows & Steps

### Faculty Onboarding (Steps)
1. **Create Faculty Profile** via POST `/faculty/` (admin only).
2. System creates linked `User` (role=`faculty`), generates `employee_id`, QR code, and saves profile.
3. Faculty can then use mobile app to scan their QR for attendance.

### Daily QR Check-in / Check-out
1. Faculty opens mobile app and scans their personal QR code (contains `employee_id`).
2. Backend validates QR, location (optional), and compares against timetable slots.
3. On **check_out**, optional `session_reports` array can be sent to auto-create `SessionReport` records.
4. Late/early flags trigger payroll adjustments and notifications.

### Session Reporting & Payroll
1. After each class, faculty (or admin) submits session report with chapters/topics covered and completion %.
2. `SessionSummaryView` aggregates data by month/subject/batch for payroll.
3. `FacultyExtraHoursView` identifies over-delivery on specific chapters.

### Subject Rate Configuration
1. Admin configures per-subject rates via POST to `/<faculty_id>/subject-rates/`.
2. Payroll utils use the most recent effective rate for calculations.

---

## Complete API Reference with Examples

### 1. List & Create Faculty
**`GET /faculty/`** — Paginated list (filters: `is_active`, `employment_type`, `level`; search on name/specialization).

**Example Response:**
```json
{
  "success": true,
  "count": 3,
  "data": [
    {
      "id": "fac-uuid-001",
      "employee_id": "EMP-2026-0001",
      "full_name": "Dr. Anita Sharma",
      "email": "anita@example.com",
      "phone": "9876543210",
      "branch_name": "Main Branch",
      "level": "professional",
      "employment_type": "full_time",
      "specialization": "Mathematics",
      "work_start_time": "09:00:00",
      "work_end_time": "17:00:00",
      "photo_url": "https://.../photo.jpg",
      "batch_count": 4,
      "subjects": ["Math", "Physics"]
    }
  ]
}
```

**`POST /faculty/`** — Create new faculty (requires branch_manager or super_admin role).

**Request Body:**
```json
{
  "email": "rajesh.kumar@example.com",
  "full_name": "Rajesh Kumar",
  "phone": "9123456789",
  "qualification": "M.Sc. Physics",
  "specialization": "Physics",
  "subject_expertise": "Mechanics, Quantum Physics",
  "level": "professional",
  "employment_type": "full_time",
  "joining_date": "2026-07-01",
  "salary": 65000.00,
  "hourly_rate": 750.00,
  "branch": "branch-uuid-here"
}
```

**Response (201):**
```json
{
  "success": true,
  "message": "Faculty created.",
  "data": {
    "faculty_id": "fac-uuid-002",
    "employee_id": "EMP-2026-0002",
    "user_id": "user-uuid-002",
    "photo_url": null,
    "qr_code_url": "https://api.example.com/media/qr/faculty/EMP-2026-0002.png"
  }
}
```

### 2. Faculty Detail / Update / Delete
**`GET /faculty/<faculty_id>/`** — Full profile with subjects, batches, QR URL, and current month hour-based pay preview.

**`PATCH /faculty/<faculty_id>/`** — Update profile (including photo upload, work times, rates, name/email).

**Example PATCH Body:**
```json
{
  "work_start_time": "08:45:00",
  "work_end_time": "16:45:00",
  "hourly_rate": 800.00,
  "full_name": "Dr. Anita Sharma (Updated)",
  "photo": "(multipart file)"
}
```

**Response:** Updated full detail object wrapped in success.

**`DELETE /faculty/<faculty_id>/`** — Soft delete: sets `is_active=false` on both profile and linked user.

### 3. QR Identity & Check-in/Check-out

**`GET /faculty/<faculty_id>/qr-id/`**
Returns QR code URL (generates on-demand if missing).

**Response:**
```json
{
  "success": true,
  "data": {
    "qr_code_url": "https://.../qr/EMP-2026-0001.png"
  }
}
```

**`POST /faculty/qr-checkin/`** — Faculty-only endpoint for mobile QR scan.

**Request Body (Check-out with Session Report):**
```json
{
  "qr_data": "EMP-2026-0001",
  "scan_type": "check_out",
  "latitude": 19.0760,
  "longitude": 72.8777,
  "session_reports": [
    {
      "batch_id": "batch-uuid-001",
      "subject_id": "subject-uuid-001",
      "chapter_ids": ["chapter-uuid-1", "chapter-uuid-2"],
      "topics_covered": "Newton's laws of motion and applications",
      "status": "completed",
      "completion_percentage": 90
    }
  ]
}
```

**Success Response:**
```json
{
  "success": true,
  "data": {
    "faculty_name": "Dr. Anita Sharma",
    "employee_id": "EMP-2026-0001",
    "scan_time": "2026-06-22T17:05:22Z",
    "scan_type": "check_out",
    "is_late": false,
    "late_minutes": 0
  },
  "message": "Check-out recorded."
}
```

**Note:** On check_out with session_reports, the system creates `SessionReport` records, links chapters, and computes duration. Late/early detection uses timetable slots + grace period from `LateEntryPolicy`.

### 4. Subject Hourly Rates
**`GET /faculty/<faculty_id>/subject-rates/`** — List rates for a faculty.

**`POST /faculty/<faculty_id>/subject-rates/`** — Add new rate.

**Request Body:**
```json
{
  "subject_id": "subject-uuid-001",
  "hourly_rate": 850.00,
  "effective_from": "2026-06-01"
}
```

**Response:** 
```json
{
  "success": true,
  "message": "Subject rate created.",
  "data": {
    "id": "rate-uuid",
    "subject": "subject-uuid-001",
    "subject_name": "Physics",
    "hourly_rate": "850.00",
    "effective_from": "2026-06-01"
  }
}
```

**`PATCH /faculty/<faculty_id>/subject-rates/<rate_id>/`** — Update rate.  
**`DELETE /faculty/<faculty_id>/subject-rates/<rate_id>/`** — Remove rate.

### 5. Faculty Sessions & Summary
**`GET /faculty/sessions/`** — List all sessions (filter by `faculty_id`, `batch_id`, `subject_id`, `month=2026-06`).

**`POST /faculty/sessions/`** — Create session report (admins can specify `faculty_id`; faculty defaults to self).

**Request Body:**
```json
{
  "batch_id": "batch-uuid-001",
  "subject_id": "subject-uuid-001",
  "session_date": "2026-06-22",
  "chapter_covered": "Chapter 3: Integration Techniques",
  "topics_covered": "Substitution, by parts, partial fractions",
  "completion_percentage": 85,
  "status": "completed",
  "start_time": "10:00:00",
  "end_time": "11:30:00",
  "notes": "Excellent student participation."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Session report created.",
  "data": {
    "id": "session-uuid",
    "faculty_name": "Dr. Anita Sharma",
    "batch_name": "MATH_ADV_01",
    "subject_name": "Mathematics",
    "session_date": "2026-06-22",
    "chapter_covered": "Chapter 3: Integration Techniques",
    "duration_minutes": 90,
    "completion_percentage": 85,
    "status_display": "Completed"
  }
}
```

**`GET /faculty/sessions/summary/?faculty_id=...&month=2026-06`** — Aggregate analytics.

**Example Summary Response:**
```json
{
  "success": true,
  "data": {
    "total_sessions": 45,
    "completed_sessions": 42,
    "in_progress_sessions": 3,
    "total_hours": 67.5,
    "avg_completion_percentage": 88.2,
    "by_subject": [...],
    "by_batch": [...]
  }
}
```

**`GET /faculty/<faculty_id>/sessions/`** — Sessions for specific faculty (paginated).

**`GET/PATCH/DELETE /faculty/sessions/<session_id>/`** — Detail view, edit (within 7 days), or delete session.

### 6. Extra Hours Report (Faculty Self-Service)
**`GET /faculty/extra-hours/`** — Shows chapters where the faculty has delivered more hours than allocated in timetable.

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "chapter_id": "chap-uuid",
      "chapter_name": "Quadratic Equations",
      "subject_name": "Mathematics",
      "allocated_hours": 8.0,
      "total_hours_given": 12.5,
      "extra_hours": 4.5,
      "message": "Great dedication! You have spent 4.5 extra hours ensuring students deeply understand this chapter."
    }
  ]
}
```

---

## Additional Notes
- **Permissions:** Faculty role can only view/update their own profile/sessions. Admins have broader access.
- **Integration:** Closely tied to `batches` (timetable slots), `payroll` (payslip computation), and `leave` (late entry records).
- **Auto-updates:** Changing salary/rates updates ALL related payslips (including disbursed ones).
- **Validation:** Session end_time must be after start_time. Cannot edit/delete sessions older than 7 days.
- Related documentation: `payroll_module_api_documentation.md`, `timetable_procedure_guide.md`, `inventory_api.md` (for faculty allocations).

This updated documentation reflects the current implementation in `faculty/views.py`, `serializers.py`, and `models.py`.
