# Batches Module — Full Walkthrough & API Reference Guide

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `application/json`  
> All responses wrapped in `{ "success": true/false, "data": ... , "message": "..." }`.

**See Also:** `timetable_procedure_guide.md` for full TimetableSlot CRUD, **session_type matrix**, Exam v2 auto-creation (via `exam_data` with proctoring/geo/screen/`result_release_mode`/`selected_papers`), clash detection, M2M sync (`paper_checkers`, `ensure_paper_checkers()`), auto `total_marks` (signals), round-robin paper assignment, faculty/student personal timetables. Legacy `timetable_exam_type` removed.

---

## Data Models Summary

| Model | Purpose | Key Behaviors |
|-------|---------|---------------|
| `Course` | Top-level academic program (CSEET, CS Executive, etc.) | Auto `code` (CRS-0001); has multiple `CourseLevel`s |
| `CourseLevel` | Sub-levels (e.g. Module-1, Group-I) | Linked to Course; `order`, `fee_amount`, `course_type` (for fees rules); auto-creates fee structures |
| `Subject` | Subject within a level | Auto `code` (SUB-0001); `total_hours` auto-summed from chapters via signal |
| `Chapter` | Detailed topics | `order`, `duration_hours`; used in timetable sessions and exams |
| `Batch` | Specific class instance | Auto `batch_code` (BAT-2026-0001), smart `name` generation using `BatchSequenceCounter`; auto QR code generation |
| `BatchStudent` | Enrollment link | Unique per batch+student; immutable history via `BatchHistory` |
| `BatchFaculty` | Faculty assignment | Links faculty to batch + optional subject; unique constraint |
| `Classroom` | Physical/Virtual rooms | Capacity, active flag; used in timetable clash detection |
| `TimetableSlot` | Scheduled sessions | See `timetable_procedure_guide.md` for `session_type` matrix (regular/class_test/prelim/practice/custom), `exam_data` → Exam v2 (proctoring, `selected_papers` M2M, `result_release_mode`, auto `total_marks` via signals + `recalculate_total_marks()`), early `paper_checkers` sync, delayed Celery round-robin assignment, clash detection on faculty/classroom. OneToOne `exam`. |

**Auto Behaviors:** 
- Batch save generates QR, name, sequence.
- Subject `update_total_hours()` on chapter changes (signal).
- `CourseLevel` save can trigger fee structure creation.

---

## Key Workflows

### Academic Hierarchy Setup
1. Create **Course** (POST `/courses/`) → e.g. "CS Executive".
2. Add **CourseLevels** (`/courses/<id>/levels/`) with order, fees, course_type (affects installment approval rules in fees).
3. Create **Subjects** per level → auto code.
4. Add **Chapters** per subject (order, duration_hours) → auto updates subject total_hours.
5. Create **Batch** for a course/level → auto naming/QR.
6. Assign **Students** (`/batches/<id>/assign-students/`) and **Faculty** (`/assign-faculty/`) with subjects.
7. Create **Classrooms**.
8. Schedule **TimetableSlots** (see timetable guide for per-`session_type` payloads + `exam_data` for Exam v2 creation with proctoring/geo/screen config, `selected_papers`, auto `total_marks`, clash detection, early M2M sync for paper_checkers).

### Dropdowns for Forms

**Organization Constraint for Faculty Levels & Subjects (API + Admin)**: 
- Only `CourseLevel`s belonging to the **same `Organization`** as the faculty's `branch.organization` can be assigned.
- **Enforced in API**: `resolve_course_levels(levels_input, organization=branch.organization)` in `faculty/serializers.py`, `FacultyCreateSerializer`, `FacultyUpdateSerializer`, `FacultyListCreateView.post()`, and `FacultyDetailView.patch()`. Non-matching levels (by UUID/name/slug) are filtered out.
- **Enforced in Admin**: `formfield_for_manytomany` override in `FacultyProfileAdmin` (uses `object_id` lookup for edit forms or falls back to `request.user.organization`; superuser bypass). Similar scoping in `BatchFacultyAdmin.formfield_for_foreignkey` for `subject`.
- This is a core multi-tenant rule. See `API_DOCUMENTATION_FACULTY_LEVELS_CHAPTER_FACULTIES.md` for full examples.

**Leads / Sales Module Integration (@leads/)**:
- Round-robin auto-assignment via `leads/signals.auto_assign_lead` (based on `form_type`: contact→tele_caller, inquiry→counsellor using `get_role_filter_q`; does not override existing `assigned_to`).
- New models: `SalesDailyPlan`, `SalesDailyActivity`, `SalesActivityPhoto`, `OdometerReading` (payroll integration for field sales, vehicle rate claims, photo proof, approval workflow).
- `notify_new_lead_assignment` uses system notifications.
- Lead-to-Admission auto-conversion signal is now **commented out** (manual CRM → onboarding flow preferred).
- Update sales-facing dashboards/UI to log daily plans, activities, and odometer readings for accurate payroll.

Use `/batches/dropdowns/` for frontend selects (courses, levels, attempt types, days, session_types, slot_codes, etc.).

**Integration Notes:**
- Fees: CourseLevel `course_type` + `get_installment_plan_status()`.
- Students: Batch assignment creates `BatchHistory`.
- Timetable/Results/Exams: Chapters in sessions; Exam v2 integration for `total_marks` (from questions), rechecks (answer_key gate), on-the-fly analytics in results, proctoring events.
- Faculty: Assignments used in QR check-in, payroll, session reports.
- QR for batch used in attendance.

---

## Complete API Reference

### Courses & Levels

**`GET /api/v1/courses/`** — List with levels prefetched optional.

**`POST /api/v1/courses/`**

#### Request Body
```json
{
  "name": "CS Professional",
  "description": "Advanced company law program",
  "is_active": true
}
```

**Response:** Created object with auto `code`.

**Course Levels:**

**`GET/POST /api/v1/courses/<course_id>/levels/`**

**POST Example:**
```json
{
  "name": "Group I",
  "order": 1,
  "course_type": "cs_professional",
  "duration_months": 6,
  "fee_amount": 25000.00,
  "description": "..."
}
```

**Detail/PATCH/DELETE** on `/levels/<level_id>/`.

### Subjects & Chapters

**`GET /api/v1/subjects/`** — Filter by `level`.

**`POST /api/v1/subjects/`** — Requires `level`.

**Chapters:**

**`GET/POST /api/v1/subjects/<subject_id>/chapters/`**

**POST Example:**
```json
{
  "name": "Directors Responsibilities",
  "order": 3,
  "duration_hours": 12,
  "description": "Key sections from Companies Act"
}
```

Auto-updates subject's `total_hours`.

### Batches

**`GET /api/v1/batches/`** — Filters: `course`, `branch`, `is_active`, `batch_attempt`.

**`POST /api/v1/batches/`**

#### Request Body (auto name/QR)
```json
{
  "course": "course-uuid",
  "branch": "branch-uuid",
  "start_date": "2026-06-01",
  "end_date": "2026-12-31",
  "max_students": 40,
  "group_module": "group1",
  "batch_attempt": "june",
  "attempt_year": 2026
}
```

**Detail:** Includes student/faculty counts.

**Assign Students:**

**`POST /api/v1/batches/<batch_id>/assign-students/`**

#### Request Body
```json
{
  "student_ids": ["stu-uuid-1", "stu-uuid-2"],
  "reason": "New enrollment"
}
```

**`DELETE /api/v1/batches/<batch_id>/remove-student/<student_id>/`** — Removes with reason logged to history.

**Faculty Assignment similar:** `POST /assign-faculty/` with `faculty_ids` and optional `subject_id`.

### Classrooms

**`GET/POST /api/v1/classrooms/`**

#### Example
```json
{
  "name": "Lecture Hall A",
  "capacity": 60,
  "is_active": true
}
```

### Dropdowns

**`GET /api/v1/batches/dropdowns/`**

#### Response
```json
{
  "success": true,
  "data": {
    "courses": [...],
    "levels": [...],
    "attempt_types": ["june", "dec", ...],
    "day_of_week": [0,1,2,3,4,5,6],
    "session_types": ["regular", "class_test", ...],
    "slot_codes": ["P1", "P2", ...],
    "course_types": ["cseet", "cs_executive", ...]
  }
}
```

---

## Common Errors & Notes

- 400: Duplicate batch_code, invalid level order, clash on timetable (see timetable guide).
- Batch QR auto-generated on save (payload = batch UUID for attendance).
- Subject hours auto-maintained via signals on chapter CRUD.
- All list views support search, pagination, role/branch filtering.
- Timetable creation detailed in dedicated guide (includes 5 session types + `exam_data` for full Exam v2 with proctoring, auto-marks, delayed assignment, legacy removal).

**Migrations:** Run `python manage.py makemigrations admissions batches faculty leads payroll && python manage.py migrate` after updates (new `Admission` + history, org FKs on Course/Subject/CourseLevel/Classroom/TimetableSlot/Chapter.faculties M2M to User, `FacultyProfile.levels`, `SubjectHourlyRate`, `FacultyQRScanLog`, `SessionReport`, sales models `SalesDailyPlan`/`SalesDailyActivity`/`OdometerReading`, `BatchSequenceCounter`, timetable-aware QR logic, payslip recalc signals).

This guide now matches the comprehensive style of other modules. For timetable-specific flows (Exam v2, session matrix, proctoring), see `timetable_procedure_guide.md`. Updated for organization-scoped `CourseLevel` filtering (admin + API via `resolve_course_levels`), pure round-robin lead assignment, new Admission pipeline (Razorpay + bank RR), faculty QR/timetable-aware session reports, chapter faculties as direct User UUIDs, and full production docs across leads/sales/admissions/faculty/payroll.
