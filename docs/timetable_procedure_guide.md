# Timetable Scheduling & Exam Integration API Procedure Guide

This guide provides the exact API endpoints, request bodies, and expected responses for scheduling each type of timetable session in the system.

---

## Step 1: Schedule a Regular Session
**Purpose:** Daily or weekly recurring lectures.
**Endpoint:** `POST /api/v1/timetable/`
**Headers:** `Authorization: Bearer <token>`, `Content-Type: application/json`

### Request Body
```json
{
  "batch": "123e4567-e89b-12d3-a456-426614174000",
  "subject": "123e4567-e89b-12d3-a456-426614174001",
  "faculty": "123e4567-e89b-12d3-a456-426614174002",
  "classroom": "123e4567-e89b-12d3-a456-426614174003",
  "session_type": "regular",
  "slot_code": "P1",
  "day_of_week": 0,
  "is_recurring": true,
  "effective_from": "2026-06-01",
  "effective_to": "2026-12-31"
}
```

### Response (201 Created)
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174099",
  "organization": "123e4567-e89b-12d3-a456-426614174000",
  "batch": "123e4567-e89b-12d3-a456-426614174000",
  "subject": "123e4567-e89b-12d3-a456-426614174001",
  "faculty": "123e4567-e89b-12d3-a456-426614174002",
  "classroom": "123e4567-e89b-12d3-a456-426614174003",
  "session_type": "regular",
  "slot_code": "P1",
  "day_of_week": 0,
  "start_time": "08:00:00",
  "end_time": "09:30:00",
  "is_recurring": true,
  "effective_from": "2026-06-01",
  "effective_to": "2026-12-31",
  "exam": null
}
```

---

## Step 2: Schedule a Class Test (Automated Exam Creation)
**Purpose:** Routine chapter-specific assessments. Automatically generates an `Exam` record.
**Endpoint:** `POST /api/v1/timetable/`
**Headers:** `Authorization: Bearer <token>`, `Content-Type: application/json`

### Request Body
```json
{
  "batch": "123e4567-e89b-12d3-a456-426614174000",
  "subject": "123e4567-e89b-12d3-a456-426614174001",
  "faculty": "123e4567-e89b-12d3-a456-426614174002",
  "classroom": "123e4567-e89b-12d3-a456-426614174003",
  "session_type": "class_test",
  "session_date": "2026-06-15",
  "start_time": "10:00:00",
  "chapters": ["123e4567-e89b-12d3-a456-426614174004"],
  "examiners": ["123e4567-e89b-12d3-a456-426614174005"],
  "paper_checkers": ["123e4567-e89b-12d3-a456-426614174006"],
  "timetable_exam_type": "123e4567-e89b-12d3-a456-426614174007",
  "exam_data": {
    "title": "React JS Mid-Term",
    "exam_type": "offline",
    "total_marks": 50,
    "pass_marks": 18,
    "duration_minutes": 90
  }
}
```

### Response (201 Created)
*(Notice the `exam` UUID at the bottom, confirming the exam was successfully generated in the background).*
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174099",
  "organization": "123e4567-e89b-12d3-a456-426614174000",
  "batch": "123e4567-e89b-12d3-a456-426614174000",
  "session_type": "class_test",
  "session_date": "2026-06-15",
  "start_time": "10:00:00",
  "end_time": "11:30:00",
  "chapters": ["123e4567-e89b-12d3-a456-426614174004"],
  "examiners": ["123e4567-e89b-12d3-a456-426614174005"],
  "paper_checkers": ["123e4567-e89b-12d3-a456-426614174006"],
  "timetable_exam_type": "123e4567-e89b-12d3-a456-426614174007",
  "exam": "987e6543-e21b-12d3-a456-426614174888",
  "exam_title": "React JS Mid-Term"
}
```

---

## Step 3: Schedule a Prelim Exam
**Purpose:** High-stakes preparatory exams. Automatically generates an `Exam` record.
**Endpoint:** `POST /api/v1/timetable/`
**Headers:** `Authorization: Bearer <token>`, `Content-Type: application/json`

### Request Body
```json
{
  "batch": "123e4567-e89b-12d3-a456-426614174000",
  "subject": "123e4567-e89b-12d3-a456-426614174001",
  "faculty": "123e4567-e89b-12d3-a456-426614174002",
  "classroom": "123e4567-e89b-12d3-a456-426614174003",
  "session_type": "prelim",
  "session_date": "2026-06-16",
  "start_time": "10:00:00",
  "end_time": "13:00:00",
  "chapters": ["123e4567-e89b-12d3-a456-426614174004", "123e4567-e89b-12d3-a456-426614174008"],
  "examiners": ["123e4567-e89b-12d3-a456-426614174005"],
  "paper_checkers": ["123e4567-e89b-12d3-a456-426614174006"],
  "timetable_exam_type": "123e4567-e89b-12d3-a456-426614174007",
  "exam_data": {
    "title": "Final Prelim Examination",
    "exam_type": "offline",
    "total_marks": 100,
    "pass_marks": 35,
    "result_release_mode": "manual"
  }
}
```

### Response (201 Created)
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174099",
  "session_type": "prelim",
  "session_date": "2026-06-16",
  "start_time": "10:00:00",
  "end_time": "13:00:00",
  "chapters": ["123e4567-e89b-12d3-a456-426614174004", "123e4567-e89b-12d3-a456-426614174008"],
  "examiners": ["123e4567-e89b-12d3-a456-426614174005"],
  "paper_checkers": ["123e4567-e89b-12d3-a456-426614174006"],
  "timetable_exam_type": "123e4567-e89b-12d3-a456-426614174007",
  "exam": "987e6543-e21b-12d3-a456-426614174889",
  "exam_title": "Final Prelim Examination"
}
```

---

## Step 4: Schedule a Practice Session
**Purpose:** Mock tests or practicals. Permits multiple examiners.
**Endpoint:** `POST /api/v1/timetable/`
**Headers:** `Authorization: Bearer <token>`, `Content-Type: application/json`

### Request Body
```json
{
  "batch": "123e4567-e89b-12d3-a456-426614174000",
  "subject": "123e4567-e89b-12d3-a456-426614174001",
  "faculty": "123e4567-e89b-12d3-a456-426614174002",
  "classroom": "123e4567-e89b-12d3-a456-426614174003",
  "session_type": "practice",
  "session_date": "2026-06-18",
  "start_time": "14:00:00",
  "examiners": [
    "123e4567-e89b-12d3-a456-426614174005",
    "123e4567-e89b-12d3-a456-426614174009"
  ]
}
```

### Response (201 Created)
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174099",
  "session_type": "practice",
  "session_date": "2026-06-18",
  "start_time": "14:00:00",
  "end_time": "16:00:00",
  "examiners": [
    "123e4567-e89b-12d3-a456-426614174005",
    "123e4567-e89b-12d3-a456-426614174009"
  ],
  "exam": null
}
```

---

## Step 5: Schedule a Custom Session
**Purpose:** Flexible, ad-hoc scheduling. Can optionally include an exam.
**Endpoint:** `POST /api/v1/timetable/`
**Headers:** `Authorization: Bearer <token>`, `Content-Type: application/json`

### Request Body (With Optional Exam)
```json
{
  "batch": "123e4567-e89b-12d3-a456-426614174000",
  "subject": "123e4567-e89b-12d3-a456-426614174001",
  "classroom": "123e4567-e89b-12d3-a456-426614174003",
  "session_type": "custom",
  "session_date": "2026-06-20",
  "start_time": "09:00:00",
  "end_time": "11:00:00",
  "faculty": "123e4567-e89b-12d3-a456-426614174002",
  "exam_data": {
    "title": "Surprise Diagnostic Quiz",
    "exam_type": "online",
    "total_marks": 20,
    "pass_marks": 10
  }
}
```

### Response (201 Created)
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174099",
  "session_type": "custom",
  "session_date": "2026-06-20",
  "start_time": "09:00:00",
  "end_time": "11:00:00",
  "faculty": "123e4567-e89b-12d3-a456-426614174002",
  "exam": "987e6543-e21b-12d3-a456-426614174890",
  "exam_title": "Surprise Diagnostic Quiz"
}
```
