# Timetable Management Procedure Guide

## 1. Overview
The Timetable Management System handles the scheduling of all academic sessions, seamlessly integrating with faculty assignments, classroom capacity, curriculum tracking (chapters), and the examination module. This guide outlines the standard operating procedures, validation rules, and integration points for scheduling personnel.

---

## 2. Session Types

The system categorizes timetable slots into five distinct types, each with its own specific rules and automation behaviors:

1. **Regular** (`regular`): Standard, recurring lectures based on predefined slot timings.
2. **Class Test** (`class_test`): Periodic, chapter-specific assessments.
3. **Prelim** (`prelim`): Major preparatory examinations.
4. **Practice** (`practice`): Mock tests or practical sessions involving multiple examiners.
5. **Custom** (`custom`): Flexible, ad-hoc scheduling for special events or make-up classes.

---

## 3. Data Requirements & Validation Rules

### 3.1 Regular Sessions
**Purpose:** Daily or weekly recurring lectures.
*   **Required Fields:** `slot_code` (e.g., P1, P2), `day_of_week`, `faculty`.
*   **Forbidden Fields:** `chapters`, `examiners`, `paper_checkers`, `timetable_exam_type`, `exam_data`.
*   **Automation:** The `start_time` and `end_time` are automatically populated based on the organization's standard `slot_code` definitions.

### 3.2 Class Test Sessions
**Purpose:** Routine assessments limited to specific chapters.
*   **Required Fields:** `session_date`, `start_time`, `chapters` (list), `faculty`, `examiners` (list), `paper_checkers` (list), `timetable_exam_type`, `exam_data` (object).
*   **Forbidden Fields:** `slot_code`.
*   **Automation & Validation:** 
    *   System validates that all selected `chapters` belong to the scheduled `subject`.
    *   System enforces that only introductory chapters (Order ≤ 2) can be tested in this format.
    *   The `end_time` is auto-calculated based on global duration constants.
    *   An `Exam` record is automatically generated using the `exam_data` payload.

### 3.3 Prelim Sessions
**Purpose:** High-stakes, comprehensive preparatory exams.
*   **Required Fields:** `session_date`, `start_time`, `end_time`, `chapters` (list), `faculty`, `examiners` (list), `paper_checkers` (list), `timetable_exam_type`, `exam_data` (object).
*   **Forbidden Fields:** `slot_code`.
*   **Automation:** An `Exam` record is automatically generated using the `exam_data` payload.

### 3.4 Practice Sessions
**Purpose:** Practical evaluations, mock interviews, or informal assessments.
*   **Required Fields:** `session_date`, `start_time`, `faculty`, `examiners` (list).
*   **Forbidden Fields:** `slot_code`, `paper_checkers`, `timetable_exam_type`, `exam_data`.
*   **Automation:** The `end_time` is auto-calculated based on global practice duration constants. Multiple examiners can be assigned simultaneously.

### 3.5 Custom Sessions
**Purpose:** Fully flexible scheduling.
*   **Required Fields:** `session_date`, `start_time`, `end_time`.
*   **Forbidden Fields:** `slot_code`.
*   **Optional Fields:** `faculty`, `chapters`, `examiners`, `paper_checkers`, `timetable_exam_type`, `exam_data`.
*   **Automation:** If the `exam_data` object is provided, the system will dynamically generate an integrated `Exam` record for this custom session.

---

## 4. Examination Module Integration (`exam_data`)

When creating a `class_test`, `prelim`, or an exam-enabled `custom` session, the API expects an `exam_data` object. This object seamlessly links the scheduling system to the testing ecosystem.

### `exam_data` Schema
| Field | Type | Requirement | Description / Default |
| :--- | :--- | :--- | :--- |
| `total_marks` | Integer | **Required** | Maximum score achievable. |
| `pass_marks` | Integer | **Required** | Minimum score required to pass. |
| `title` | String | Optional | If omitted, auto-generates as `"{Subject} - {Session Type} ({Date})"`. |
| `exam_type` | String | Optional | `"online"` or `"offline"`. Defaults to `"offline"`. |
| `duration_minutes` | Integer | Optional | If omitted, calculated automatically from `start_time` and `end_time`. |
| `instructions` | String | Optional | Standard test instructions for students. |
| `result_release_mode` | String | Optional | `"instant"` or `"manual"`. Defaults to `"instant"`. |

---

## 5. API Payload Examples

### Example: Creating a Class Test (with Exam Integration)
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
    "instructions": "No calculators allowed."
  }
}
```

### Example: Creating a Regular Lecture
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
