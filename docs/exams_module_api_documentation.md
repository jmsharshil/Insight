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
    "timetable_exam_type": "uuid-of-exam-type",
    "exam_data": {
        "title": "Company Law — Class Test",
        "exam_type": "online",
        "total_marks": 50,  // initial value; auto-updated from questions
        "pass_marks": 18,
        "instructions": "Attempt all questions. Time: 90 minutes.",
        "result_release_mode": "manual"
    }
}
```

### 1.2 List Exams
**Endpoint:** `/api/v1/exams/`
**Methods:** `GET`

### 1.3 Retrieve, Update & Delete Exam
**Endpoint:** `/api/v1/exams/{exam_id}/`
**Methods:** `GET`, `PATCH`, `DELETE`

**PATCH Request Body:** (Partial fields of Exam creation)

---

## 2. Questions Management

**Note:** Adding, updating, or deleting questions automatically triggers `Exam.recalculate_total_marks()` (see section 1). This ensures `total_marks` always equals the sum of all `Question.marks`. Questions support independent `marks` values (no longer forced to uniform value).

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
            {
                "text": "Paris",
                "is_correct": true
            },
            {
                "text": "London",
                "is_correct": false
            }
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

**Note:** PATCH (including on `marks`) or DELETE will trigger recalculation of parent `Exam.total_marks` (via Django signals + explicit call). Responses now include the updated `total_marks`.

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
    "student_lat": 19.076090, // Required if exam has geo_radius_meters > 0
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
    "questions": [ ... ]
}
```

### Autosave Answers
**Endpoint:** `/api/v1/exams/{exam_id}/sessions/{session_id}/autosave/`
**Method:** `POST`

**Request Body:**
```json
{
    "question_id": "uuid-of-question",
    "selected_choice_id": "uuid-of-choice", // For MCQ
    "text_answer": "" // For subjective
}
```

**Success Response:**
```json
{
    "saved": true,
    "question_id": "uuid-of-question",
    "remaining_seconds": 3500
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

**Success Response:**
```json
{
    "geo_check": "passed",
    "distance_m": 15.5
}
```

### Screen Lock & Split Screen Events
**Endpoint:** `/api/v1/exams/{exam_id}/sessions/{session_id}/screen-event/`
**Method:** `POST`

**Request Body:**
```json
{
    "event": "lock_breach" // or "split_screen"
}
```

**Success Response:**
```json
{
    "event_logged": true,
    "warning": true,
    "violations": 1,
    "remaining_before_action": 2,
    "action": "warning_issued"
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

### Answer Key Distribution
**Endpoint:** `/api/v1/exams/{exam_id}/answer-key/distribute/`
**Method:** `POST`
*Sends an email link to assigned paper checkers with a secure token.*

### View Answer Key (Public with Token)
**Endpoint:** `/api/v1/answer-key/{exam_id}/?token=log_hash`
**Method:** `GET`
*Exempt from authentication if a valid token is provided.*

### Report Malpractice
**Endpoint:** `/api/v1/exams/{exam_id}/malpractice/`
**Methods:** `GET`, `POST`

**POST Request Body:**
```json
{
    "student_id": "uuid-of-student",
    "description": "Student was looking at a hidden phone.",
    "severity": "major" // choices: minor, major, disqualified
}
```

**POST Success Response:**
```json
{
    "success": true,
    "report_id": "uuid-of-report"
}
```

### Update & Delete Malpractice Report
**Endpoint:** `/api/v1/exams/{exam_id}/malpractice/{report_id}/`
**Methods:** `PATCH`, `DELETE`

---

## 6. Subject Papers (Reusable Paper Library)

Papers are now managed at the **Subject** level rather than per-exam, making them reusable across multiple exams. An exam admin links one or more subject papers to an exam via `selected_papers`. When a student starts the exam, a paper is automatically assigned using a **round-robin** strategy to ensure even distribution.

---

### 6.1 Upload / List Subject Papers

**Endpoint:** `POST /api/v1/subjects/{subject_id}/papers/`  
**Endpoint:** `GET  /api/v1/subjects/{subject_id}/papers/`  
**Permission:** Admin / Senior Executive roles

**POST Request (multipart/form-data):**

| Field        | Type     | Required | Description                         |
|--------------|----------|----------|-------------------------------------|
| `set_name`   | string   | Yes      | e.g., `"Set A"`, `"Morning Shift"` |
| `file`       | file     | Yes      | PDF / document to upload            |
| `answer_key` | file     | No       | Answer key PDF (optional)           |

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

---

### 6.2 Retrieve / Update / Delete a Subject Paper

**Endpoint:** `/api/v1/subjects/{subject_id}/papers/{paper_id}/`  
**Methods:** `GET`, `PATCH`, `DELETE`

`PATCH` accepts any subset of `set_name`, `file`, `answer_key`.

---

### 6.3 Link Papers to an Exam (`selected_papers`)

When creating or updating an exam, pass `selected_papers` as a list of `SubjectPaper` UUIDs to associate them with the exam. These must belong to any subject (no subject restriction enforced at this layer).

**PATCH `/api/v1/exams/{exam_id}/`:**
```json
{
    "selected_papers": ["uuid-of-paper-1", "uuid-of-paper-2"]
}
```

**GET `/api/v1/exams/{exam_id}/` response now includes:**
```json
{
    "selected_papers": [
        {
            "id": "uuid-of-paper-1",
            "subject": "uuid-of-subject",
            "subject_name": "Company Law",
            "set_name": "Set A",
            "file": "/media/subject_papers/set_a.pdf",
            "answer_key": null,
            "created_at": "2026-06-29T10:00:00Z"
        }
    ]
}
```

---

### 6.4 Round-Robin Paper Assignment at Exam Start

When a student hits `POST /api/v1/exams/{exam_id}/start/`, the system:

1. Retrieves all `selected_papers` for the exam (ordered by `set_name`).
2. Counts how many sessions already have each paper assigned.
3. Assigns the paper with the **lowest assignment count** to the new session.

This guarantees even distribution across all paper sets for the duration of the exam.

**Start Exam Response now includes `assigned_paper_id`:**
```json
{
    "session_id": "uuid-of-session",
    "remaining_seconds": 3600,
    "autosave_interval_seconds": 30,
    "geo_check_interval_minutes": 5,
    "exam_title": "Midterm",
    "total_marks": 100,
    "questions": [ "..." ]
}
```

> `ExamSession.assigned_paper` stores the paper assigned to the student. Use this to show/download the correct paper file during the exam session.

---

### 6.5 Workflow Summary

```
1. Upload papers to a subject:
   POST /api/v1/subjects/<subject_id>/papers/

2. Link papers to an exam:
   PATCH /api/v1/exams/<exam_id>/  { "selected_papers": ["uuid-1", "uuid-2"] }

3. Student starts exam → paper auto-assigned (round-robin):
   POST /api/v1/exams/<exam_id>/start/
```

