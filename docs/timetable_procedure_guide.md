# Timetable Scheduling & Exam Integration API Procedure Guide

This guide provides the exact API endpoints, request bodies, and expected responses for scheduling each type of timetable session in the system.

---

## Architecture & Workflow Diagram

The following diagram illustrates the API validation logic, automated calculations, and how the `Exam` generation module is triggered depending on the selected `session_type`.

```text
                                  +--------------------------------------+
                                  |    Client Submits TimetableSlot      |
                                  +--------------------------------------+
                                                    |
                                                    v
                                         +--------------------+
                                         |    Session Type?   |
                                         +--------------------+
                                                    |
         +--------------------+---------------------+---------------------+--------------------+
         |                    |                     |                     |                    |
         v                    v                     v                     v                    v
    [regular]            [class_test]           [prelim]             [practice]            [custom]
         |                    |                     |                     |                    |
         v                    v                     v                     v                    v
+------------------+ +------------------+ +------------------+ +------------------+ +------------------+
|Validate slot_code| |Validate chapters,| |Validate chapters,| |Validate multiple | | Validate custom  |
|& day_of_week     | |examiners, paper_ | |examiners, paper_ | |examiners         | | start_time and   |
|                  | |checkers          | |checkers          | |                  | | end_time         |
+------------------+ +------------------+ +------------------+ +------------------+ +------------------+
         |                    |                     |                     |                    |
         v                    v                     v                     v                    v
+------------------+ +------------------+ +------------------+ +------------------+ +------------------+
|Auto-compute      | | exam_data        | | exam_data        | |Auto-compute      | | exam_data        |
|start/end times   | | provided?        | | provided?        | |end_time          | | provided?        |
+------------------+ +------------------+ +------------------+ +------------------+ +------------------+
         |               |          |          |         |            |               |          |
         |              Yes         No        Yes        No           |              Yes         No
         |               |          |          |         |            |               |          |
         |               v          v          v         v            |               v          |
         |      +------------+ +--------+ +---------+ +--------+      |      +------------+      |
         |      |Calc length & | |Return 400| |Calc length| |Return 400|      |      |Calc length & |      |
         |      |Create Exam | |Bad Req | |Create Exam| |Bad Req |      |      |Create Exam |      |
         |      +------------+ +--------+ +---------+ +--------+      |      +------------+      |
         |               |                     |                      |               |          |
         v               v                     v                      v               v          v
+----------------------------------------------------------------------------------------------------+
|                                    Create TimetableSlot Record                                     |
+----------------------------------------------------------------------------------------------------+
                                                    |
                                                    v
                                  +--------------------------------------+
                                  | Return 201 Created & slot/exam UUIDs |
                                  +--------------------------------------+
```

---

## Appendix A: System Choice Mappings & Reference Data

Before scheduling, refer to the following system-defined choices and their display values.

### A.1 Session Types (`session_type`)
| Value | Display Name |
| :--- | :--- |
| `regular` | Regular |
| `class_test` | Class Test |
| `prelim` | Prelim |
| `practice` | Practice |
| `custom` | Custom |

### A.2 Day of Week (`day_of_week`)
| Value (Integer) | Display Name |
| :--- | :--- |
| `0` | Monday |
| `1` | Tuesday |
| `2` | Wednesday |
| `3` | Thursday |
| `4` | Friday |
| `5` | Saturday |
| `6` | Sunday |

### A.3 Slot Codes (`slot_code`)
*(Used only for `regular` sessions to determine automated timing)*
| Value | Display Name |
| :--- | :--- |
| `P1` | P1 08:00–10:00 |
| `P2` | P2 10:15–12:15 |
| `P3` | P3 12:45–14:45 |
| `P4` | P4 15:00–17:00 |

### A.4 Exam Mode (`exam_type`)
| Value | Display Name |
| :--- | :--- |
| `offline` | Offline |
| `online` | Online |

### A.5 Result Release Mode (`result_release_mode`)
| Value | Display Name |
| :--- | :--- |
| `instant` | Instant |
| `manual` | Manual |

---

## Step 1: Schedule a Regular Session
**Purpose:** Daily or weekly recurring lectures.
*   **Required Fields:** `slot_code` (must be P1-P4), `day_of_week` (0-6), `faculty`.
*   **Forbidden Fields:** `exam_data`, `chapters`, `examiners`, `paper_checkers`, `timetable_exam_type`.
*   **Note:** Start and end times are strictly derived from the selected `slot_code`.
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
*   **Required Fields:** `session_date`, `start_time`, `chapters` (list of UUIDs), `faculty`, `examiners` (list of UUIDs), `paper_checkers` (list of UUIDs), `timetable_exam_type`, `exam_data`.
*   **Forbidden Fields:** `slot_code`.
*   **Note:** The system strictly validates that chapters are mapped to the correct subject and belong to introductory levels (Order ≤ 2).
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
*   **Required Fields:** `session_date`, `start_time`, `end_time`, `chapters`, `faculty`, `examiners`, `paper_checkers`, `timetable_exam_type`, `exam_data`.
*   **Forbidden Fields:** `slot_code`.
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
*   **Required Fields:** `session_date`, `start_time`, `faculty`, `examiners` (array).
*   **Forbidden Fields:** `slot_code`, `paper_checkers`, `timetable_exam_type`, `exam_data`.
*   **Note:** The system automatically calculates `end_time` based on practice configurations.
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
*   **Required Fields:** `session_date`, `start_time`, `end_time`.
*   **Forbidden Fields:** `slot_code`.
*   **Optional Fields:** `faculty`, `chapters`, `examiners`, `paper_checkers`, `timetable_exam_type`, `exam_data`.
*   **Note:** Full flexibility. Passing `exam_data` dynamically links an exam to the slot.
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
