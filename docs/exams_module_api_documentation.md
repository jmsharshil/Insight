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
