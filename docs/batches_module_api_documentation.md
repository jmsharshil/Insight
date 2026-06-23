# Batches Module — Full Walkthrough & API Reference Guide

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `application/json`  
> All responses wrapped in `{ "success": true/false, "data": ... , "message": "..." }`.

**See Also:** `timetable_procedure_guide.md` for full TimetableSlot CRUD, session types, exam auto-creation, clash detection, faculty/student personal timetables, and exam-types reference.

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
| `TimetableSlot` | Scheduled sessions | See dedicated timetable guide for session_type logic, exam auto-create, clash detection |

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
8. Schedule **TimetableSlots** (see timetable guide for per-session-type payloads, auto exam creation for tests/prelims, clash detection on faculty/classroom).

### Dropdowns for Forms
Use `/batches/dropdowns/` for frontend selects (courses, levels, attempt types, days, session_types, slot_codes, etc.).

**Integration Notes:**
- Fees: CourseLevel `course_type` + `get_installment_plan_status()`.
- Students: Batch assignment creates `BatchHistory`.
- Timetable/Results: Chapters used in session reports and exam papers.
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
- Timetable creation detailed in dedicated guide (includes 5 session types, exam_data, clash detection).

**Migrations:** Run `python manage.py migrate batches` after updates (includes sequence counter, QR fields, session enhancements).

This guide now matches the comprehensive style of other modules. For timetable-specific flows (including exam integration), refer to `timetable_procedure_guide.md`. Updated to reflect auto-naming, QR generation, total_hours signals, and cross-module ties to fees/students/faculty.
