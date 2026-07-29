# Exams Module API Documentation

This document provides a comprehensive list of all APIs available in the `exams` module, along with their request bodies and expected responses.

---

## 1. Exam Creation & Management

**NEW: Automatic `total_marks` Calculation**
`Exam.total_marks` is now **auto-derived** as `SUM(Question.marks)` across all linked questions (MCQ, subjective, true_false all support per-question `marks`).
- `ExamCreateSerializer` treats `total_marks` as effectively read-only on input (initial value accepted for validation but overridden by questions).
- `pass_marks <= total_marks` validation is retained.
- On any Question create/update/delete (via dedicated endpoints), `exam.recalculate_total_marks()` runs atomically to sync the value (removes manual drift).
- List/Detail/Start-Exam responses now always return up-to-date computed `total_marks`.
- `questions_count` is available in list views.
- Existing exams are unaffected until next question mutation.

Exams are created automatically through the **Timetable** module when scheduling class tests, prelims, or custom sessions.

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

**Response includes:** `grace_marks`, `grace_marks_note`, `answer_key` (URL or `null` for students after 24h window), `selected_papers`.

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

## 6. Subject Papers (Reusable Paper Library)

Papers are managed at the **Subject** level, making them reusable across multiple exams. An exam admin links one or more subject papers to an exam via `selected_papers`. When a student starts the exam, a paper is automatically assigned using a **round-robin** strategy.

### 6.1 Upload / List Subject Papers

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

### 6.2 Retrieve / Update / Delete a Subject Paper

**Endpoint:** `/api/v1/subjects/{subject_id}/papers/{paper_id}/`
**Methods:** `GET`, `PATCH`, `DELETE`

`PATCH` accepts any subset of `set_name`, `file`, `answer_key`.

### 6.3 Link Papers to an Exam (`selected_papers`)

When creating or updating an exam, pass `selected_papers` as a list of `SubjectPaper` UUIDs.

**PATCH `/api/v1/exams/{exam_id}/`:**
```json
{
    "selected_papers": ["uuid-of-paper-1", "uuid-of-paper-2"]
}
```

### 6.4 Round-Robin Paper Assignment at Exam Start

When a student hits `POST /api/v1/exams/{exam_id}/start/`, the system assigns the paper with the **lowest assignment count** to ensure even distribution.

### 6.5 Workflow Summary

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

## 7. Exam Model Fields Reference

The `Exam` model supports full proctoring, geo-fencing, screen monitoring, configurable result release, reusable subject papers, M2M paper_checkers, and grace marks.

### Key Model Fields (from `exams/models.py`)

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
| `selected_papers` | M2M | Links to `SubjectPaper` objects |
| `paper_checkers` | M2M | Users with `role='paper_checker'` |
| `answer_key` | FileField | Exam-level answer key upload |
| `grace_marks` | decimal | Grace marks added to all student results (**new**) |
| `grace_marks_note` | text | Reason for awarding grace marks (**new**) |

### Methods
- `recalculate_total_marks()`: Sum of `Question.marks` (auto via Django signals on Question CRUD).
- `ensure_paper_checkers()`: Populates `paper_checkers` M2M early on Exam create.

**Proctoring Flow:**
- `/start/` validates geo if configured, creates `ExamSession`.
- Periodic `/geo-check/` and `/screen-event/` log violations, trigger actions per thresholds.
- On submit, if `result_release_mode=instant` and MCQ-only, auto-grade and publish.

See `timetable_procedure_guide.md` for `exam_data` examples, `results_module_api_documentation.md` for marking/publishing/recheck integration.

**Migration Note:** After pulling latest code, run `python manage.py migrate exams` to pick up new fields (`grace_marks`, `grace_marks_note`).
