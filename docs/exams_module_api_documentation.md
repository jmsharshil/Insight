# Exams Module API Documentation

This document provides a comprehensive list of all APIs available in the `exams` module, along with their request bodies and expected responses.

---

## 1. Exam Creation & Management

**NEW: Automatic `total_marks` Calculation & Enhanced List Fields**
`Exam.total_marks` is now **auto-derived** as `SUM(Question.marks)` across all linked questions (MCQ, subjective, true_false all support per-question `marks`).
- `ExamCreateSerializer` treats `total_marks` as effectively read-only on input (initial value accepted for validation but overridden by questions).
- `pass_marks <= total_marks` validation is retained.
- On any Question create/update/delete (via dedicated endpoints), `exam.recalculate_total_marks()` runs atomically to sync the value (removes manual drift).
- List responses now include computed fields: `questions_count`, `can_start_exam`, `is_upcoming`, `is_submitted`, `classroom`/`classroom_name` (pulled from linked `TimetableSlot`), `attendance_percentage` (non-absent MarkSheets / active batch students).
- `answer_key` visibility for students is strictly limited to 24h after `PublishedResult.published_at`.
- Existing exams are unaffected until next question mutation.

Exams are created automatically through the **Timetable** module (via `exam_data` + `session_type`) when scheduling class tests, prelims, or custom sessions. `paper_checkers`/`examiners` from slot are synced to `Exam.paper_checkers` / `supervisors`.

### 1.1 Create Exam via Timetable Slot
**Endpoint:** `POST /api/v1/timetable/`
When scheduling a session, you can pass `exam_data` to automatically create an `Exam` record linked to the timetable slot. This is mandatory for `class_test` and `prelim` session types.

**Note:** `total_marks` in `exam_data` is accepted for initial validation but will be recalculated once questions are added.

**Note:** `paper_checkers` specified in the timetable slot are **automatically synced** to the generated `Exam.paper_checkers` M2M field. No separate step is required.

**POST Request Body Example:**
```json
{
    "batch": "uuid-of-batch",
    "subject": "uuid-of-subject",
    "faculty": "uuid-of-faculty",
    "session_type": "class_test",
    "session_date": "2026-06-20",
    "start_time": "10:00:00",
    "chapters": ["uuid-of-chapter-1"],
    "examiners": ["uuid-of-examiner"],
    "paper_checkers": ["uuid-of-checker"],
    "exam_data": {
        "title": "Company Law — Class Test",
        "exam_type": "mcq",
        "exam_mode": "online",
        "total_marks": 50,
        "pass_marks": 18,
        "duration_minutes": 90,
        "instructions": "Attempt all questions. Time: 90 minutes.",
        "result_release_mode": "manual",
        "selected_papers": ["paper-uuid-1", "paper-uuid-2"],
        "geo_radius_meters": 100,
        "screen_lock_max_violations": 3,
        "screen_lock_action": "flag_only"
    }
}
```

### 1.2 List Exams
**Endpoint:** `GET /api/v1/exams/`

**Response includes:** All core fields + computed values from `ExamListSerializer`:
- `grace_marks`, `grace_marks_note`
- `answer_key` (URL or `null` for students — governed by `_student_can_see_answer_key()` using `PublishedResult.published_at + 24h`)
- `selected_papers` (full paper objects via nested `SubjectPaperSerializer`)
- `paper_checkers`, `supervisors` (lists of `{id, name, email}`)
- `questions_count`, `can_start_exam`, `is_upcoming`, `is_submitted`
- `classroom`, `classroom_name` (from linked timetable slot)
- `attendance_percentage` (post-exam only)

**Note:** `get_subject*` methods fallback to first `selected_papers` if no direct `subject`. `can_start_exam` includes detailed role/batch/time/submission checks with student profile caching.

### 1.3 Retrieve, Update & Delete Exam
**Endpoint:** `/api/v1/exams/{exam_id}/`
**Methods:** `GET`, `PATCH`, `DELETE`

**PATCH Request Body:** (Partial fields of Exam creation — also accepts `grace_marks`, `grace_marks_note`)

### 1.4 Add Grace Marks
**Endpoint:** `POST /api/v1/exams/{exam_id}/grace-marks/`
**Permission:** `super_admin`, `admin_senior_executive`, `branch_manager`

Applies grace marks to an exam and **automatically recalculates** `MarkSheet.marks_obtained`, `is_pass`, `PublishedResult.marks_obtained`, `percentage`, and re-ranks all students. Final marks are capped at `exam.total_marks`.

**Request Body:**
```json
{
    "grace_marks": 5,
    "grace_marks_note": "Out of syllabus question in section B"
}
```

**Success Response:**
```json
{
    "success": true,
    "message": "Grace marks of 5 added to Exam and applied to 45 student results."
}
```

**Error Responses:**
- `400`: `"Invalid grace_marks. Must be a positive number."`
- `403`: `"Permission denied."`
- `404`: `"Exam not found."`

---

## 2. Questions Management

**Note:** Adding, updating, or deleting questions automatically triggers `Exam.recalculate_total_marks()`. Questions support independent `marks` values.

### List & Add Questions
**Endpoint:** `/api/v1/exams/{exam_id}/questions/`
**Methods:** `GET`, `POST`

**POST Request Body:**
```json
[
    {
        "question_text": "What is the capital of France?",
        "question_type": "mcq",
        "marks": 5,
        "order": 1,
        "choices": [
            {"text": "Paris", "is_correct": true},
            {"text": "London", "is_correct": false}
        ]
    },
    {
        "question_text": "True or False: ...",
        "question_type": "true_false",
        "marks": 2,
        "order": 2
    }
]
```

**POST Success Response:**
```json
{
    "success": true,
    "message": "Questions added. total_marks auto-updated.",
    "total_marks": 50,
    "questions_count": 2
}
```

### Update & Delete Question
**Endpoint:** `/api/v1/exams/{exam_id}/questions/{question_id}/`
**Methods:** `PATCH`, `DELETE`

**Note:** PATCH or DELETE triggers recalculation of parent `Exam.total_marks`. Responses include the updated `total_marks`.

---

## 3. Seating Arrangement

### View & Assign Seats
**Endpoint:** `/api/v1/exams/{exam_id}/seating/`
**Methods:** `GET`, `POST`

**POST Request Body (Manual Assignment):**
```json
[
    {
        "student_id": "uuid-of-student",
        "room_name": "Room 101",
        "seat_number": "A1",
        "row_number": 1
    }
]
```

**POST Request Body (Auto Assignment):**
```json
{
    "auto": true
}
```

**POST Success Response:**
```json
{
    "success": true,
    "message": "Assigned 1 seats."
}
```

### Update & Remove Seat
**Endpoint:** `/api/v1/exams/{exam_id}/seating/{seat_id}/`
**Methods:** `PATCH`, `DELETE`

---

## 4. Student Online Exam Flow

### Start Exam
**Endpoint:** `/api/v1/exams/{exam_id}/start/`
**Method:** `POST`

**Request Body:**
```json
{
    "student_lat": 19.076090,
    "student_lon": 72.877426
}
```

**Success Response:**
```json
{
    "session_id": "uuid-of-session",
    "remaining_seconds": 3600,
    "autosave_interval_seconds": 30,
    "geo_check_interval_minutes": 5,
    "exam_title": "Midterm",
    "total_marks": 100,
    "questions": []
}
```

### Autosave Answers
**Endpoint:** `/api/v1/exams/{exam_id}/sessions/{session_id}/autosave/`
**Method:** `POST`

**Request Body:**
```json
{
    "question_id": "uuid-of-question",
    "selected_choice_id": "uuid-of-choice",
    "text_answer": ""
}
```

### Periodic Geo-Check
**Endpoint:** `/api/v1/exams/{exam_id}/sessions/{session_id}/geo-check/`
**Method:** `POST`

**Request Body:**
```json
{
    "student_lat": 19.076090,
    "student_lon": 72.877426
}
```

### Screen Lock & Split Screen Events
**Endpoint:** `/api/v1/exams/{exam_id}/sessions/{session_id}/screen-event/`
**Method:** `POST`

**Request Body:**
```json
{
    "event": "lock_breach"
}
```

### Submit Exam
**Endpoint:** `/api/v1/exams/{exam_id}/submit/`
**Method:** `POST`

**Request Body:**
```json
{
    "session_id": "uuid-of-session",
    "answers": [
        {
            "question_id": "uuid-of-question",
            "selected_choice_id": "uuid-of-choice",
            "text_answer": ""
        }
    ]
}
```

**Success Response:**
```json
{
    "submitted": true,
    "marks_obtained": 85,
    "percentage": 85.0,
    "is_pass": true
}
```

---

## 5. Malpractice & Answer Keys

### Answer Key Distribution (to Paper Checkers)
**Endpoint:** `POST /api/v1/exams/{exam_id}/answer-key/distribute/`
*Sends a secure token email link to assigned paper checkers.*

### View Answer Key (Public Token-Based)
**Endpoint:** `GET /api/v1/answer-key/{exam_id}/?token=log_hash`
*Exempt from authentication. Valid for 48 hours after distribution.*

### Answer Key Visibility for Students
- The `answer_key` field is returned in the Exam detail/list response.
- **For students:** The URL is `null` unless:
  1. The exam status is `results_published`, AND
  2. The student's `PublishedResult.published_at` is **within the last 24 hours**.
- After 24 hours from result publication, the field returns `null` automatically (no separate API call needed).
- **For admins/faculty:** Always visible.

### Upload Exam Materials (Answer Key / Question Paper)
**Endpoint:** `POST /api/v1/exams/{exam_id}/upload-materials/`
**Permission:** Assigned faculty, `super_admin`, `admin_senior_executive`, `branch_manager`
**Content-Type:** `multipart/form-data`

| Field | Type | Description |
|---|---|---|
| `answer_key` | file | Uploads directly to `Exam.answer_key`. Visible to students for 24h after result publishing. |
| `question_paper` | file | Auto-creates a `SubjectPaper` and links it to `Exam.selected_papers`. Exam must have a `subject` assigned. |

**Success Response:**
```json
{
    "success": true,
    "message": "Answer Key and Question Paper uploaded successfully."
}
```

### Faculty Material Upload Notifications
When an exam is created/scheduled and either `answer_key` or `question_paper` is missing, the **assigned faculty** automatically receives a notification to upload the missing material. A **daily Celery task** (`send_exam_material_upload_reminders`) also sends reminders for all draft/scheduled exams with missing materials until they are uploaded.

### Report Malpractice
**Endpoint:** `/api/v1/exams/{exam_id}/malpractice/`
**Methods:** `GET`, `POST`

**POST Request Body:**
```json
{
    "student_id": "uuid-of-student",
    "description": "Student was looking at a hidden phone.",
    "severity": "major"
}
```

### Update & Delete Malpractice Report
**Endpoint:** `/api/v1/exams/{exam_id}/malpractice/{report_id}/`
**Methods:** `PATCH`, `DELETE`

---

## 6. OMR (Optical Mark Recognition) APIs

**For offline MCQ exams only.** Powered by `exams/omr.py`:
- Bubble detection via OpenCV (`_detect_bubbles_from_image`).
- OCR fallback via pytesseract (`_parse_text_answer_key`, `_extract_text_from_image`).
- Student metadata extraction (`parse_student_identity_from_sheet` — name, roll_number, admission_number from header text).
- Grading with negative marking support (`grade_omr`).

Results are stored in `results.models.MarkSheet` (`marks_obtained`, `question_marks` JSON breakdown, `is_pass`, `remarks`). Also updates linked `ExamSession.uploaded_answer_sheet` and `is_submitted`.

**Prerequisites:**
- Exam must have `exam_mode='offline'`, `exam_type='mcq'`.
- `answer_key` FileField must be populated (via `/upload-materials/`).
- Dependencies (server-side): `opencv-python-headless`, `pytesseract` + Tesseract binary, `pdf2image` (+ Poppler), numpy, Pillow.
- High-quality scans recommended for reliable bubble detection.

### 6.1 Single Student OMR Upload
**Endpoint:** `POST /api/v1/exams/{exam_id}/students/{student_id}/omr-upload/`

**Permissions:** `super_admin`, `branch_manager`, `admin_senior_executive`, assigned `faculty`, or the student themselves.

**Content-Type:** `multipart/form-data`

**Request Fields:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `answer_sheet` | file | Yes | - | Scanned OMR sheet (JPG/PNG/PDF) |
| `n_questions` | int | No | `exam.total_marks` or 100 | Number of questions on sheet |
| `marks_per_question` | float | No | 1.0 | Marks per correct answer |
| `negative_marks` | float | No | 0.0 | Penalty per incorrect answer |

The endpoint:
1. Validates permissions, exam type/mode, and answer key.
2. Extracts correct answers from `Exam.answer_key` (bubble detection or OCR).
3. Parses student identity from the uploaded sheet (to prevent mismatches).
4. Detects student's bubbled answers.
5. Grades and creates/updates `MarkSheet` + `ExamSession`.

**Success Response:**
```json
{
    "success": true,
    "score": 42.0,
    "total": 50.0,
    "is_pass": true,
    "correct": 42,
    "wrong": 5,
    "unanswered": 3,
    "breakdown": [
        {
            "question": 1,
            "correct_answer": "A",
            "student_answer": "A",
            "result": "correct",
            "marks": 1.0
        }
        // ... full per-question array
    ],
    "marksheet_id": "uuid-of-marksheet"
}
```

**Error Responses:**
- `400`: Wrong exam mode/type, missing `answer_sheet` or `answer_key`.
- `403`: Permission denied, branch mismatch, or OCR-parsed identity does not match target `student_id`.
- `409`: Sheet already submitted for this student.
- `422`: OMR parsing failed (bad image quality, no bubbles detected, etc.).

### 6.2 Bulk OMR Upload
**Endpoint:** `POST /api/v1/exams/{exam_id}/omr-upload/bulk/`

**Permissions:** Admin roles or assigned faculty only.

**Content-Type:** `multipart/form-data`

**Request Fields:** 
- `answer_sheets` (or `answer_sheet`): Multiple files (list).
- Same optional params as single upload (`n_questions`, `marks_per_question`, `negative_marks`).

**Auto-matching:** Each sheet is independently OCR'd for student identity (`parse_student_identity_from_sheet` + `_find_student_from_sheet_metadata` which prefers admission_number → roll_number → name patterns). Grading is isolated per file.

**Success Response:**
```json
{
    "success": true,
    "processed": 25,
    "succeeded": 23,
    "failed": 2,
    "results": [
        {
            "file_name": "omr_student42.pdf",
            "status": "success",
            "student_id": "uuid",
            "student_name": "Alice Smith",
            "score": 47.0,
            "total": 50.0,
            "is_pass": true,
            "marksheet_id": "uuid"
        },
        {
            "file_name": "bad_scan.pdf",
            "status": "error",
            "message": "Could not resolve student from sheet metadata."
        }
    ]
}
```

**Notes:**
- Failures do not block successful sheets (per-file resilience).
- All successful entries update corresponding `MarkSheet.question_marks` (for detailed review in results module).
- See `views.py:OMRBulkUploadView` and `omr.py` for full implementation details (temp files, contour detection thresholds, regex patterns, etc.).

---

## 7. Subject Papers (Reusable Paper Library)

Papers are managed at the **Subject** level, making them reusable across multiple exams. An exam admin links one or more subject papers to an exam via `selected_papers`. When a student starts the exam, a paper is automatically assigned using a **round-robin** strategy.

### 7.1 Upload / List Subject Papers

**Endpoint:** `POST /api/v1/subjects/{subject_id}/papers/`
**Endpoint:** `GET  /api/v1/subjects/{subject_id}/papers/`
**Permission:** Admin / Senior Executive roles

**POST Request (multipart/form-data):**

| Field | Type | Required | Description |
|---|---|---|---|
| `set_name` | string | Yes | e.g., `"Set A"`, `"Morning Shift"` |
| `file` | file | Yes | PDF / document to upload |
| `answer_key` | file | No | Answer key PDF (optional) |
| `no_of_questions` | integer | Yes | Total number of questions |

> `subject` is inferred from the URL — do not pass it in the body.

**POST Success Response:**
```json
{
    "success": true,
    "data": {
        "id": "uuid-of-paper",
        "subject": "uuid-of-subject",
        "subject_name": "Company Law",
        "set_name": "Set A",
        "file": "/media/subject_papers/set_a.pdf",
        "answer_key": "/media/subject_papers/answer_keys/set_a_key.pdf",
        "created_at": "2026-06-29T10:00:00Z"
    }
}
```

### 7.2 Retrieve / Update / Delete a Subject Paper

**Endpoint:** `/api/v1/subjects/{subject_id}/papers/{paper_id}/`
**Methods:** `GET`, `PATCH`, `DELETE`

`PATCH` accepts any subset of `set_name`, `file`, `answer_key`.

### 7.3 Link Papers to an Exam (`selected_papers`)

When creating or updating an exam, pass `selected_papers` as a list of `SubjectPaper` UUIDs.

**PATCH `/api/v1/exams/{exam_id}/`:**
```json
{
    "selected_papers": ["uuid-of-paper-1", "uuid-of-paper-2"]
}
```

### 7.4 Round-Robin Paper Assignment at Exam Start

When a student hits `POST /api/v1/exams/{exam_id}/start/`, the system assigns the paper with the **lowest assignment count** to ensure even distribution.

### 7.5 Workflow Summary

```
1. Upload papers to a subject:
   POST /api/v1/subjects/<subject_id>/papers/

2. Link papers to an exam:
   PATCH /api/v1/exams/<exam_id>/  { "selected_papers": ["uuid-1", "uuid-2"] }

3. [Optional] Upload question paper directly to exam:
   POST /api/v1/exams/<exam_id>/upload-materials/  { question_paper: <file> }

4. Student starts exam → paper auto-assigned (round-robin):
   POST /api/v1/exams/<exam_id>/start/
```

---

## 8. Exam Model Fields Reference

The `Exam` model supports full proctoring, geo-fencing, screen monitoring, configurable result release, reusable subject papers, M2M `paper_checkers`/`supervisors`, **OMR grading for offline MCQ**, and grace marks.

**OMR-specific usage:** `answer_key` FileField is the source of truth for correct answers in offline mode (parsed via `extract_answer_key_from_file()`). `MarkSheet` (in `results` app) receives the auto-graded `marks_obtained` + `question_marks` breakdown.

### Key Model Fields & Computed Serializer Fields (from `exams/models.py` + `serializers.py`)

| Field | Type | Description |
|---|---|---|
| `exam_mode` | choice | `'online'` (proctored) or `'offline'` (paper-based) |
| `geo_lat`, `geo_lon`, `geo_radius_meters` | decimal | Geo-fence coordinates; `0` disables geo check |
| `geo_check_interval_minutes` | int | Periodic geo validation interval during exam |
| `screen_lock_max_violations` | int | Max screen-lock violations before action |
| `screen_lock_action` | choice | `'flag_only'` or `'auto_submit'` |
| `split_screen_max_warnings` | int | Max split-screen warnings before action |
| `split_screen_action` | choice | `'flag_only'` or `'auto_submit'` |
| `result_release_mode` | choice | `'instant'` (auto-grade MCQ on submit) or `'manual'` (admin publishes) |
| `selected_papers` | M2M | Links to `SubjectPaper` objects (round-robin assignment on `/start/`) |
| `paper_checkers` | M2M | Users with `role='paper_checker'` (synced from timetable slot) |
| `supervisors` | M2M | Users with `role='exam_supervisor'` (synced from `examiners` in timetable) |
| `answer_key` | FileField | Exam-level answer key upload. **Critical for OMR**: used by `extract_answer_key_from_file()` for offline MCQ grading (bubble detection or OCR). |
| `grace_marks` | decimal | Grace marks added to all student results |
| `grace_marks_note` | text | Reason for awarding grace marks |
| `classroom` / `classroom_name` | (computed) | Pulled from linked `TimetableSlot.classroom` (via `hasattr` check in serializer) |
| `attendance_percentage` | float | `(non-absent MarkSheet.count() / active batch students) * 100`; `null` for draft/scheduled exams (uses `results.models.MarkSheet`) |
| `can_start_exam`, `is_upcoming`, `is_submitted` | bool | Student-specific logic with caching (`_cached_student`), time-window checks, and submission status from `ExamSession` |

### Methods & Serializer Helpers
- `recalculate_total_marks()`: Sum of `Question.marks` (auto via Django signals on Question CRUD).
- `ensure_paper_checkers_for_exam()`: Early population of `paper_checkers` M2M from timetable slot (called in views).
- `_student_can_see_answer_key(request, exam)`: Controls `answer_key` visibility (admins always see; students only within 24h of `PublishedResult.published_at`).

**Proctoring & OMR Flow:**
- Online: `/start/` validates geo, creates `ExamSession`, assigns paper round-robin.
- Periodic `/geo-check/` and `/screen-event/` log violations (ScreenEventSerializer), trigger actions per thresholds.
- Offline MCQ: Use the dedicated **OMR endpoints** (section 6) with scanned sheets. `OMRUploadView` / `OMRBulkUploadView` call `exams.omr.*` functions and auto-populate `MarkSheet`.
- `ExamListSerializer.get_can_start_exam()` includes student caching, batch match, time window (or `ongoing` status), and no prior submission check.
- On submit (online) or OMR upload, if `result_release_mode=instant` and MCQ-only, auto-grade and publish.

See `timetable_procedure_guide.md` (updated for `session_type` + nested `exam_data`, clash 409 responses, confirm/export/publish endpoints) for full integration examples. Also see `results_module_api_documentation.md` for `MarkSheet` review, recheck, and rank calculation.

**Migration Note:** After pulling latest code, run `python manage.py migrate exams` (new fields: `grace_marks`, `grace_marks_note`, timetable OneToOne link, proctoring config). OMR support uses existing `answer_key` + `MarkSheet.question_marks` (no additional migration). All changes synced with `ExamListSerializer`, `ExamCreateSerializer`, `SubjectPaperSerializer`, and the new OMR views. See `exams/omr.py` + `views.py:OMR*View` for implementation.
