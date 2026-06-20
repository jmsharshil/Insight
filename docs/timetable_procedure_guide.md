# Timetable Scheduling & Exam Integration — Full API Reference Guide

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `application/json`  
> All responses are wrapped in `{ "success": true/false, "data": ... }`.

---

## Architecture & Workflow Diagram

```
                              ┌─────────────────────────────────┐
                              │   Client Submits TimetableSlot  │
                              └─────────────────────────────────┘
                                              │
                                              ▼
                                   ┌────────────────────┐
                                   │   Session Type?    │
                                   └────────────────────┘
                                              │
           ┌──────────────┬──────────────┬───┴──────────┬──────────────┐
           ▼              ▼              ▼               ▼              ▼
       [regular]    [class_test]      [prelim]       [practice]     [custom]
           │              │              │               │              │
           ▼              ▼              ▼               ▼              ▼
    ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐
    │Requires    │ │Requires    │ │Requires    │ │Requires    │ │Requires    │
    │slot_code,  │ │session_    │ │session_    │ │session_    │ │session_    │
    │day_of_week,│ │date,chaps, │ │date,chaps, │ │date,       │ │date,       │
    │faculty     │ │examiners,  │ │examiners,  │ │examiners,  │ │start_time, │
    │            │ │paper_      │ │paper_      │ │faculty     │ │end_time    │
    │            │ │checkers,   │ │checkers,   │ │            │ │            │
    │            │ │exam_data   │ │exam_data   │ │            │ │            │
    └────────────┘ └────────────┘ └────────────┘ └────────────┘ └────────────┘
           │              │              │               │              │
           ▼              ▼              ▼               ▼              ▼
    ┌────────────┐ ┌─────────────┐ ┌─────────────┐ ┌──────────────┐ ┌──────────────┐
    │Auto-fill   │ │Create Exam  │ │Create Exam  │ │Auto-calc     │ │exam_data     │
    │start/end   │ │record from  │ │record from  │ │end_time      │ │optional →    │
    │from        │ │exam_data    │ │exam_data    │ │              │ │create Exam   │
    │slot_code   │ │            │ │             │ │              │ │if provided   │
    └────────────┘ └─────────────┘ └─────────────┘ └──────────────┘ └──────────────┘
           │              │              │               │              │
           └──────────────┴──────────────┴───────────────┴──────────────┘
                                              │
                                              ▼
                            ┌─────────────────────────────────────┐
                            │    Clash Detection (Faculty +        │
                            │    Classroom overlap check)          │
                            └─────────────────────────────────────┘
                                              │
                                              ▼
                                ┌─────────────────────────┐
                                │  201 Created — Slot +   │
                                │  Exam UUID in response  │
                                └─────────────────────────┘
```

---

## Appendix A: System Choice Values & Display Mappings

### A.1 Session Types (`session_type`)
| Value | Display | Exam Auto-Created? | Notes |
| :--- | :--- | :--- | :--- |
| `regular` | Regular | ❌ No | Requires `slot_code` + `day_of_week` |
| `class_test` | Class Test | ✅ Yes (forced) | Chapters ≤ Order 2 only |
| `prelim` | Prelim | ✅ Yes (forced) | Manual `end_time` required |
| `practice` | Practice | ❌ No | No `paper_checkers` allowed |
| `custom` | Custom | ⚙️ Optional | Pass `exam_data` to create exam |

### A.2 Day of Week (`day_of_week`)
| Value | Display |
| :--- | :--- |
| `0` | Monday |
| `1` | Tuesday |
| `2` | Wednesday |
| `3` | Thursday |
| `4` | Friday |
| `5` | Saturday |
| `6` | Sunday |

### A.3 Slot Codes (`slot_code`) — Regular sessions only
| Value | Display | Auto start_time | Auto end_time |
| :--- | :--- | :--- | :--- |
| `P1` | P1 08:00–10:00 | 08:00:00 | 10:00:00 |
| `P2` | P2 10:15–12:15 | 10:15:00 | 12:15:00 |
| `P3` | P3 12:45–14:45 | 12:45:00 | 14:45:00 |
| `P4` | P4 15:00–17:00 | 15:00:00 | 17:00:00 |
| `P5` | P5 (Custom Time) | *(manual)* | *(manual)* |
| `P6` | P6 (Custom Time) | *(manual)* | *(manual)* |

### A.4 Exam Type (`exam_type` inside `exam_data`)
| Value | Display |
| :--- | :--- |
| `offline` | Offline |
| `online` | Online |

### A.5 Result Release Mode (`result_release_mode` inside `exam_data`)
| Value | Display |
| :--- | :--- |
| `instant` | Instant |
| `manual` | Manual |

### A.6 Faculty Level (`level`)
| Value | Display |
| :--- | :--- |
| `executive` | Executive |
| `professional` | Professional |

### A.7 Faculty Employment Type (`employment_type`)
| Value | Display |
| :--- | :--- |
| `full_time` | Full Time |
| `part_time` | Part Time |
| `contract` | Contract |

---

## SECTION 1 — Timetable Exam Types (Reference Data)

Exam types are reference records that categorize what kind of exam a timetable slot holds (e.g., "Internal", "Board Exam"). Create these before creating timetable slots.

---

### 1.1 List All Exam Types

**`GET /api/v1/timetable/exam-types/`**

#### Query Params
| Param | Type | Description |
| :--- | :--- | :--- |
| *(none)* | | Returns all exam types for the organization |

#### Response (200 OK)
```json
{
  "success": true,
  "data": [
    {
      "id": "aaa00001-0000-0000-0000-000000000001",
      "organization": "org-uuid-here",
      "name": "Internal Assessment",
      "description": "Regular internal class assessments",
      "is_active": true,
      "created_at": "2026-06-01T10:00:00Z"
    },
    {
      "id": "aaa00002-0000-0000-0000-000000000002",
      "organization": "org-uuid-here",
      "name": "Board Exam",
      "description": "Official board-level examination",
      "is_active": true,
      "created_at": "2026-06-02T10:00:00Z"
    }
  ]
}
```

---

### 1.2 Create Exam Type

**`POST /api/v1/timetable/exam-types/`**

#### Request Body
```json
{
  "name": "Internal Assessment",
  "description": "Regular internal class assessments",
  "is_active": true
}
```

#### Response (201 Created)
```json
{
  "success": true,
  "message": "Exam type created.",
  "data": {
    "id": "aaa00001-0000-0000-0000-000000000001",
    "organization": "org-uuid-here",
    "name": "Internal Assessment",
    "description": "Regular internal class assessments",
    "is_active": true,
    "created_at": "2026-06-12T10:00:00Z"
  }
}
```

---

### 1.3 Get Exam Type Detail

**`GET /api/v1/timetable/exam-types/<exam_type_id>/`**

#### Response (200 OK)
```json
{
  "success": true,
  "data": {
    "id": "aaa00001-0000-0000-0000-000000000001",
    "organization": "org-uuid-here",
    "name": "Internal Assessment",
    "description": "Regular internal class assessments",
    "is_active": true,
    "created_at": "2026-06-12T10:00:00Z"
  }
}
```

#### Response (404 Not Found)
```json
{
  "success": false,
  "message": "Exam type not found."
}
```

---

### 1.4 Update Exam Type

**`PATCH /api/v1/timetable/exam-types/<exam_type_id>/`**

*(Send only the fields you want to update)*

#### Request Body
```json
{
  "description": "Updated description for internal assessments",
  "is_active": false
}
```

#### Response (200 OK)
```json
{
  "success": true,
  "message": "Exam type updated.",
  "data": {
    "id": "aaa00001-0000-0000-0000-000000000001",
    "name": "Internal Assessment",
    "description": "Updated description for internal assessments",
    "is_active": false,
    "created_at": "2026-06-12T10:00:00Z"
  }
}
```

---

### 1.5 Delete Exam Type

**`DELETE /api/v1/timetable/exam-types/<exam_type_id>/`**

#### Response (200 OK)
```json
{
  "success": true,
  "message": "Exam type deleted."
}
```

---

## SECTION 2 — Timetable Slots (Full CRUD)

---

### 2.1 List All Timetable Slots

**`GET /api/v1/timetable/`**

#### Query Params (all optional)
| Param | Type | Example | Description |
| :--- | :--- | :--- | :--- |
| `batch_id` | UUID (comma-separated) | `uuid1,uuid2` | Filter by one or more batch IDs |
| `day_of_week` | Integer (0–6) | `0` | Filter by day (0=Monday) |
| `faculty_id` | UUID | `uuid` | Filter slots for a specific faculty |
| `subject_id` | UUID | `uuid` | Filter slots for a specific subject |
| `course_id` | UUID | `uuid` | Filter slots by course |
| `session_type` | string | `regular` | Filter by session type |

#### Response (200 OK)
```json
{
  "success": true,
  "count": 2,
  "data": [
    {
      "id": "slot-uuid-0001",
      "batch": "batch-uuid-001",
      "batch_name": "cs_executive_june_2026_0101",
      "course": "course-uuid-001",
      "course_name": "CS Executive",
      "course_code": "CRS-0001",
      "subject": "subject-uuid-001",
      "subject_name": "Company Law",
      "faculty": "faculty-uuid-001",
      "faculty_name": "Prof. Ramesh Kumar",
      "faculty_employee_id": "FAC-0001",
      "classroom": "classroom-uuid-001",
      "classroom_name": "Room A",
      "day_of_week": 0,
      "day_label": "Monday",
      "day_of_week_display": "Monday",
      "start_time": "08:00:00",
      "end_time": "10:00:00",
      "is_recurring": true,
      "effective_from": "2026-06-01",
      "effective_to": "2026-12-31",
      "session_type": "regular",
      "session_type_display": "Regular",
      "session_name": "Monday Morning Lecture",
      "slot_code": "P1",
      "session_date": null,
      "chapters": [],
      "chapters_names": [],
      "examiners": [],
      "examiners_names": [],
      "paper_checkers": [],
      "paper_checkers_names": [],
      "timetable_exam_type": null,
      "exam_type_name": null,
      "exam": null
    }
  ]
}
```

---

### 2.2 Get Single Timetable Slot

**`GET /api/v1/timetable/<slot_id>/`**

#### Response (200 OK)
```json
{
  "success": true,
  "data": {
    "id": "slot-uuid-0001",
    "batch": "batch-uuid-001",
    "batch_name": "cs_executive_june_2026_0101",
    "course": "course-uuid-001",
    "course_name": "CS Executive",
    "subject": "subject-uuid-001",
    "subject_name": "Company Law",
    "faculty": "faculty-uuid-001",
    "faculty_name": "Prof. Ramesh Kumar",
    "faculty_employee_id": "FAC-0001",
    "classroom": "classroom-uuid-001",
    "classroom_name": "Room A",
    "day_of_week": 0,
    "day_label": "Monday",
    "day_of_week_display": "Monday",
    "start_time": "08:00:00",
    "end_time": "10:00:00",
    "is_recurring": true,
    "effective_from": "2026-06-01",
    "effective_to": "2026-12-31",
    "session_type": "regular",
    "session_type_display": "Regular",
    "session_name": "Monday Morning Lecture",
    "slot_code": "P1",
    "session_date": null,
    "chapters": [],
    "chapters_names": [],
    "examiners": [],
    "examiners_names": [],
    "paper_checkers": [],
    "paper_checkers_names": [],
    "timetable_exam_type": null,
    "exam_type_name": null,
    "exam": null
  }
}
```

#### Response (404 Not Found)
```json
{
  "success": false,
  "message": "Timetable slot not found."
}
```

---

### 2.3 Create Timetable Slot — Step-by-Step by Session Type

> **Common Fields for all session types:**
> | Field | Type | Required | Notes |
> | :--- | :--- | :--- | :--- |
> | `batch` | UUID | ✅ Yes | Batch to schedule for |
> | `subject` | UUID | Optional | Subject being taught |
> | `faculty` | UUID | See per-type | Faculty conducting the session |
> | `classroom` | UUID | Optional | Room for the session |
> | `session_type` | string | ✅ Yes | One of: `regular`, `class_test`, `prelim`, `practice`, `custom` |
> | `session_name` | string | Optional | Free-text label for the slot |
> | `organization` | UUID | Optional | Auto-filled from logged-in user |

---

#### 2.3.1 POST — Regular Session

**`POST /api/v1/timetable/`**

- `slot_code` (P1–P4), `day_of_week`, `faculty` are **required**
- `start_time` and `end_time` are **auto-computed** from `slot_code`
- `exam_data`, `chapters`, `examiners`, `paper_checkers`, `timetable_exam_type` are **forbidden**

##### Request Body
```json
{
  "batch": "batch-uuid-001",
  "subject": "subject-uuid-001",
  "faculty": "faculty-uuid-001",
  "classroom": "classroom-uuid-001",
  "session_type": "regular",
  "session_name": "Monday Morning Lecture",
  "slot_code": "P1",
  "day_of_week": 0,
  "is_recurring": true,
  "effective_from": "2026-06-01",
  "effective_to": "2026-12-31"
}
```

##### Response (201 Created)
```json
{
  "success": true,
  "message": "Timetable slot created.",
  "data": {
    "id": "slot-uuid-0001",
    "batch": "batch-uuid-001",
    "batch_name": "cs_executive_june_2026_0101",
    "subject": "subject-uuid-001",
    "subject_name": "Company Law",
    "faculty": "faculty-uuid-001",
    "faculty_name": "Prof. Ramesh Kumar",
    "classroom": "classroom-uuid-001",
    "classroom_name": "Room A",
    "session_type": "regular",
    "session_type_display": "Regular",
    "session_name": "Monday Morning Lecture",
    "slot_code": "P1",
    "day_of_week": 0,
    "day_label": "Monday",
    "start_time": "08:00:00",
    "end_time": "10:00:00",
    "is_recurring": true,
    "effective_from": "2026-06-01",
    "effective_to": "2026-12-31",
    "chapters": [],
    "examiners": [],
    "paper_checkers": [],
    "timetable_exam_type": null,
    "exam": null
  }
}
```

##### Error — Faculty Clash (400)
```json
{
  "success": false,
  "message": "Faculty has a scheduling conflict.",
  "clashing_slots": ["slot-uuid-existing-001"]
}
```

---

#### 2.3.2 POST — Class Test Session (Exam Auto-Created)

**`POST /api/v1/timetable/`**

- `session_date`, `start_time`, `chapters`, `faculty`, `examiners`, `paper_checkers`, `timetable_exam_type`, `exam_data` are **required**
- `end_time` is **auto-computed** (90-minute fixed duration)
- Chapters must belong to the selected subject and have `order ≤ 2`
- `slot_code` is **forbidden**

##### Request Body
```json
{
  "batch": "batch-uuid-001",
  "subject": "subject-uuid-001",
  "faculty": "faculty-uuid-001",
  "classroom": "classroom-uuid-001",
  "session_type": "class_test",
  "session_name": "Chapter 1 & 2 Test",
  "session_date": "2026-06-15",
  "start_time": "10:00:00",
  "chapters": [
    "chapter-uuid-001",
    "chapter-uuid-002"
  ],
  "examiners": ["user-uuid-examiner-001"],
  "paper_checkers": ["user-uuid-checker-001"],
  "timetable_exam_type": "aaa00001-0000-0000-0000-000000000001",
  "exam_data": {
    "title": "Company Law — Ch 1 & 2 Class Test",
    "exam_type": "offline",
    "total_marks": 50,
    "pass_marks": 18,
    "instructions": "Attempt all questions. Time: 90 minutes.",
    "result_release_mode": "manual"
  }
}
```

##### Response (201 Created)
```json
{
  "success": true,
  "message": "Timetable slot created.",
  "data": {
    "id": "slot-uuid-0002",
    "batch": "batch-uuid-001",
    "batch_name": "cs_executive_june_2026_0101",
    "subject": "subject-uuid-001",
    "subject_name": "Company Law",
    "faculty": "faculty-uuid-001",
    "faculty_name": "Prof. Ramesh Kumar",
    "session_type": "class_test",
    "session_type_display": "Class Test",
    "session_name": "Chapter 1 & 2 Test",
    "session_date": "2026-06-15",
    "start_time": "10:00:00",
    "end_time": "11:30:00",
    "chapters": ["chapter-uuid-001", "chapter-uuid-002"],
    "chapters_names": ["Introduction to Company Law", "Types of Companies"],
    "examiners": ["user-uuid-examiner-001"],
    "examiners_names": ["Dr. Anil Sharma"],
    "paper_checkers": ["user-uuid-checker-001"],
    "paper_checkers_names": ["Ms. Priya Gupta"],
    "timetable_exam_type": "aaa00001-0000-0000-0000-000000000001",
    "exam_type_name": "Internal Assessment",
    "exam": "exam-uuid-0001"
  }
}
```

##### Error — Missing `exam_data` (400)
```json
{
  "success": false,
  "errors": {
    "exam_data": "exam_data is required for class_test session."
  }
}
```

##### Error — Invalid chapter order (400)
```json
{
  "success": false,
  "errors": {
    "chapters": "class_test allows only chapters with order ≤ 2."
  }
}
```

---

#### 2.3.3 POST — Prelim Exam Session (Exam Auto-Created)

**`POST /api/v1/timetable/`**

- `session_date`, `start_time`, `end_time`, `chapters`, `faculty`, `examiners`, `paper_checkers`, `timetable_exam_type`, `exam_data` are **required**
- `end_time` must be **manually provided** and must be after `start_time`
- `slot_code` is **forbidden**

##### Request Body
```json
{
  "batch": "batch-uuid-001",
  "subject": "subject-uuid-001",
  "faculty": "faculty-uuid-001",
  "classroom": "classroom-uuid-001",
  "session_type": "prelim",
  "session_name": "June 2026 Prelim",
  "session_date": "2026-06-20",
  "start_time": "10:00:00",
  "end_time": "13:00:00",
  "chapters": [
    "chapter-uuid-001",
    "chapter-uuid-002",
    "chapter-uuid-003"
  ],
  "examiners": [
    "user-uuid-examiner-001",
    "user-uuid-examiner-002"
  ],
  "paper_checkers": ["user-uuid-checker-001"],
  "timetable_exam_type": "aaa00002-0000-0000-0000-000000000002",
  "exam_data": {
    "title": "Company Law — June 2026 Prelim",
    "exam_type": "offline",
    "total_marks": 100,
    "pass_marks": 35,
    "instructions": "All questions carry equal marks. Duration: 3 hours.",
    "result_release_mode": "manual"
  }
}
```

##### Response (201 Created)
```json
{
  "success": true,
  "message": "Timetable slot created.",
  "data": {
    "id": "slot-uuid-0003",
    "session_type": "prelim",
    "session_type_display": "Prelim",
    "session_name": "June 2026 Prelim",
    "session_date": "2026-06-20",
    "start_time": "10:00:00",
    "end_time": "13:00:00",
    "chapters": ["chapter-uuid-001", "chapter-uuid-002", "chapter-uuid-003"],
    "chapters_names": ["Introduction to Company Law", "Types of Companies", "Memorandum of Association"],
    "examiners": ["user-uuid-examiner-001", "user-uuid-examiner-002"],
    "examiners_names": ["Dr. Anil Sharma", "Prof. Meera Patel"],
    "paper_checkers": ["user-uuid-checker-001"],
    "paper_checkers_names": ["Ms. Priya Gupta"],
    "timetable_exam_type": "aaa00002-0000-0000-0000-000000000002",
    "exam_type_name": "Board Exam",
    "exam": "exam-uuid-0002"
  }
}
```

---

#### 2.3.4 POST — Practice Session

**`POST /api/v1/timetable/`**

- `session_date`, `start_time`, `faculty`, `examiners` are **required**
- `end_time` is **auto-computed**
- `paper_checkers`, `timetable_exam_type`, `exam_data`, `slot_code` are **forbidden**

##### Request Body
```json
{
  "batch": "batch-uuid-001",
  "subject": "subject-uuid-001",
  "faculty": "faculty-uuid-001",
  "classroom": "classroom-uuid-001",
  "session_type": "practice",
  "session_name": "Mock Practice Round 1",
  "session_date": "2026-06-18",
  "start_time": "14:00:00",
  "examiners": [
    "user-uuid-examiner-001",
    "user-uuid-examiner-002"
  ]
}
```

##### Response (201 Created)
```json
{
  "success": true,
  "message": "Timetable slot created.",
  "data": {
    "id": "slot-uuid-0004",
    "session_type": "practice",
    "session_type_display": "Practice",
    "session_name": "Mock Practice Round 1",
    "session_date": "2026-06-18",
    "start_time": "14:00:00",
    "end_time": "16:00:00",
    "faculty": "faculty-uuid-001",
    "faculty_name": "Prof. Ramesh Kumar",
    "examiners": ["user-uuid-examiner-001", "user-uuid-examiner-002"],
    "examiners_names": ["Dr. Anil Sharma", "Prof. Meera Patel"],
    "paper_checkers": [],
    "timetable_exam_type": null,
    "exam": null
  }
}
```

---

#### 2.3.5 POST — Custom Session (Optional Exam)

**`POST /api/v1/timetable/`**

- `session_date`, `start_time`, `end_time` are **required**
- All other fields are **optional** (including `exam_data`)
- If `exam_data` is passed, an Exam record is created and linked
- `slot_code` is **forbidden**

##### Request Body (with optional exam)
```json
{
  "batch": "batch-uuid-001",
  "subject": "subject-uuid-001",
  "faculty": "faculty-uuid-001",
  "classroom": "classroom-uuid-001",
  "session_type": "custom",
  "session_name": "Special Orientation & Diagnostic Quiz",
  "session_date": "2026-06-25",
  "start_time": "09:00:00",
  "end_time": "11:00:00",
  "exam_data": {
    "title": "Diagnostic Quiz — Company Law",
    "exam_type": "online",
    "total_marks": 20,
    "pass_marks": 10,
    "result_release_mode": "instant"
  }
}
```

##### Request Body (without exam)
```json
{
  "batch": "batch-uuid-001",
  "session_type": "custom",
  "session_name": "Guest Lecture — Corporate Governance",
  "session_date": "2026-06-28",
  "start_time": "11:00:00",
  "end_time": "13:00:00"
}
```

##### Response (201 Created — with exam)
```json
{
  "success": true,
  "message": "Timetable slot created.",
  "data": {
    "id": "slot-uuid-0005",
    "session_type": "custom",
    "session_type_display": "Custom",
    "session_name": "Special Orientation & Diagnostic Quiz",
    "session_date": "2026-06-25",
    "start_time": "09:00:00",
    "end_time": "11:00:00",
    "faculty": "faculty-uuid-001",
    "faculty_name": "Prof. Ramesh Kumar",
    "chapters": [],
    "examiners": [],
    "paper_checkers": [],
    "timetable_exam_type": null,
    "exam": "exam-uuid-0003"
  }
}
```

---

### 2.4 Update Timetable Slot

**`PATCH /api/v1/timetable/<slot_id>/`**

Send **only the fields** you want to update. Clash detection runs again on update.

#### Request Body (example — update faculty and session_name)
```json
{
  "faculty": "faculty-uuid-002",
  "session_name": "Updated Monday Morning Lecture"
}
```

#### Request Body (example — update exam details on class_test)
```json
{
  "exam_data": {
    "total_marks": 75,
    "pass_marks": 27,
    "instructions": "Updated instructions."
  }
}
```

#### Response (200 OK)
```json
{
  "success": true,
  "message": "Timetable slot updated.",
  "data": {
    "id": "slot-uuid-0001",
    "session_type": "regular",
    "session_name": "Updated Monday Morning Lecture",
    "faculty": "faculty-uuid-002",
    "faculty_name": "Prof. Sunita Verma",
    "slot_code": "P1",
    "day_of_week": 0,
    "start_time": "08:00:00",
    "end_time": "10:00:00",
    "exam": null
  }
}
```

#### Error — Faculty Clash on Update (400)
```json
{
  "success": false,
  "message": "Faculty has a scheduling conflict.",
  "clashing_slots": ["slot-uuid-existing-999"]
}
```

#### Error — Slot Not Found (404)
```json
{
  "success": false,
  "message": "Timetable slot not found."
}
```

---

### 2.5 Delete Timetable Slot

**`DELETE /api/v1/timetable/<slot_id>/`**

> ⚠️ **Warning:** Deleting a slot does **not** delete the linked Exam record. The Exam stays in the system. Only the timetable slot link is removed.

#### Response (200 OK)
```json
{
  "success": true,
  "message": "Timetable slot deleted."
}
```

#### Response (404 Not Found)
```json
{
  "success": false,
  "message": "Timetable slot not found."
}
```

---

## SECTION 3 — Personal Timetable Views (Read-Only)

These endpoints return timetable data **grouped by day of week** for easy calendar rendering.

---

### 3.1 Faculty Weekly Timetable

**`GET /api/v1/timetable/faculty/<faculty_id>/`**

Returns all slots assigned to a faculty member, grouped by day.

#### Response (200 OK)
```json
{
  "success": true,
  "data": {
    "Monday": [
      {
        "id": "slot-uuid-0001",
        "batch": "batch-uuid-001",
        "batch_name": "cs_executive_june_2026_0101",
        "batch_code": "BAT-2026-0001",
        "subject": "subject-uuid-001",
        "subject_name": "Company Law",
        "classroom": "classroom-uuid-001",
        "classroom_name": "Room A",
        "day_of_week": 0,
        "day_label": "Monday",
        "day_of_week_display": "Monday",
        "start_time": "08:00:00",
        "end_time": "10:00:00",
        "session_type": "regular",
        "session_date": null,
        "slot_code": "P1"
      }
    ],
    "Wednesday": [
      {
        "id": "slot-uuid-0002",
        "batch": "batch-uuid-001",
        "batch_name": "cs_executive_june_2026_0101",
        "batch_code": "BAT-2026-0001",
        "subject": "subject-uuid-001",
        "subject_name": "Company Law",
        "classroom": "classroom-uuid-001",
        "classroom_name": "Room A",
        "day_of_week": 2,
        "day_label": "Wednesday",
        "day_of_week_display": "Wednesday",
        "start_time": "10:15:00",
        "end_time": "12:15:00",
        "session_type": "regular",
        "session_date": null,
        "slot_code": "P2"
      }
    ]
  }
}
```

---

### 3.2 Student Weekly Timetable

**`GET /api/v1/timetable/student/<student_id>/`**

Returns all slots for every batch the student is enrolled in, grouped by day.

#### Response (200 OK)
```json
{
  "success": true,
  "data": {
    "Monday": [
      {
        "id": "slot-uuid-0001",
        "subject": "subject-uuid-001",
        "subject_name": "Company Law",
        "faculty": "faculty-uuid-001",
        "faculty_name": "Prof. Ramesh Kumar",
        "faculty_employee_id": "FAC-0001",
        "classroom": "classroom-uuid-001",
        "classroom_name": "Room A",
        "day_of_week": 0,
        "day_label": "Monday",
        "day_of_week_display": "Monday",
        "start_time": "08:00:00",
        "end_time": "10:00:00",
        "session_type": "regular",
        "session_date": null,
        "slot_code": "P1"
      }
    ],
    "Sunday": []
  }
}
```

---

## SECTION 4 — Faculty Profile Subjects API

Use this to retrieve which subjects a faculty member currently teaches across all batches.

---

### 4.1 List All Faculty

**`GET /api/v1/faculty/`**

#### Response (200 OK)
```json
{
  "success": true,
  "data": [
    {
      "id": "faculty-uuid-001",
      "employee_id": "FAC-0001",
      "full_name": "Prof. Ramesh Kumar",
      "email": "ramesh@institute.com",
      "phone": "9876543210",
      "photo_url": "https://api.example.com/media/faculty/photos/ramesh.jpg",
      "branch": "branch-uuid-001",
      "branch_name": "Mumbai Main Branch",
      "level": "professional",
      "level_display": "Professional",
      "employment_type": "full_time",
      "employment_type_display": "Full Time",
      "specialization": "Company Law, Securities Law",
      "subject_expertise": "Corporate Governance",
      "joining_date": "2024-01-15",
      "is_active": true,
      "batch_count": 2,
      "created_at": "2024-01-15T10:00:00Z",
      "batch_name": "cs_executive_june_2026_0101, cs_professional_dec_2026_0055",
      "subjects": [
        "subject-uuid-001",
        "subject-uuid-002"
      ],
      "subject_name": "Company Law, Securities Law"
    }
  ]
}
```

---

### 4.2 Faculty Profile Detail (with Subjects)

**`GET /api/v1/faculty/<faculty_id>/`**

#### Response (200 OK)
```json
{
  "success": true,
  "data": {
    "id": "faculty-uuid-001",
    "employee_id": "FAC-0001",
    "full_name": "Prof. Ramesh Kumar",
    "email": "ramesh@institute.com",
    "phone": "9876543210",
    "photo_url": "https://api.example.com/media/faculty/photos/ramesh.jpg",
    "branch": "branch-uuid-001",
    "qualification": "M.Com, FCS",
    "specialization": "Company Law, Securities Law",
    "subject_expertise": "Corporate Governance, SEBI Regulations",
    "level": "professional",
    "level_display": "Professional",
    "employment_type": "full_time",
    "employment_type_display": "Full Time",
    "joining_date": "2024-01-15",
    "salary": "85000.00",
    "hourly_rate": "500.00",
    "bank_account": "1234567890",
    "ifsc_code": "HDFC0001234",
    "pan_number": "ABCDE1234F",
    "qr_code_url": "https://api.example.com/media/faculty/qr/ramesh_qr.png",
    "is_active": true,
    "created_at": "2024-01-15T10:00:00Z",
    "batch_name": "cs_executive_june_2026_0101, cs_professional_dec_2026_0055",
    "subjects": [
      "subject-uuid-001",
      "subject-uuid-002"
    ],
    "subject_name": "Company Law, Securities Law"
  }
}
```

> **Field Reference:**
> | Field | Type | Description |
> | :--- | :--- | :--- |
> | `subjects` | `array[UUID]` | Unique Subject UUIDs assigned to this faculty across all batches |
> | `subject_name` | `string` | Comma-separated display names matching `subjects` |
> | `batch_name` | `string` | Comma-separated names of all batches this faculty teaches |

---

## SECTION 5 — Complete API Endpoint Summary Table

| # | Method | Endpoint | Description |
| :--- | :--- | :--- | :--- |
| 1 | `GET` | `/api/v1/timetable/` | List all timetable slots (with filters) |
| 2 | `POST` | `/api/v1/timetable/` | Create a new timetable slot |
| 3 | `GET` | `/api/v1/timetable/<slot_id>/` | Get a single slot detail |
| 4 | `PATCH` | `/api/v1/timetable/<slot_id>/` | Update a timetable slot |
| 5 | `DELETE` | `/api/v1/timetable/<slot_id>/` | Delete a timetable slot |
| 6 | `GET` | `/api/v1/timetable/faculty/<faculty_id>/` | Faculty's weekly timetable (grouped by day) |
| 7 | `GET` | `/api/v1/timetable/student/<student_id>/` | Student's weekly timetable (grouped by day) |
| 8 | `GET` | `/api/v1/timetable/exam-types/` | List all timetable exam types |
| 9 | `POST` | `/api/v1/timetable/exam-types/` | Create a timetable exam type |
| 10 | `GET` | `/api/v1/timetable/exam-types/<id>/` | Get exam type detail |
| 11 | `PATCH` | `/api/v1/timetable/exam-types/<id>/` | Update an exam type |
| 12 | `DELETE` | `/api/v1/timetable/exam-types/<id>/` | Delete an exam type |
| 13 | `GET` | `/api/v1/faculty/` | List all faculty (includes `subjects`, `subject_name`) |
| 14 | `GET` | `/api/v1/faculty/<faculty_id>/` | Faculty profile detail (includes `subjects`, `subject_name`) |

---

## SECTION 6 — Common Error Responses

### 400 — Validation Error (missing required field)
```json
{
  "success": false,
  "message": "Please fix the errors below.",
  "errors": {
    "exam_data": "exam_data is required for class_test session.",
    "chapters": "This field is required for class_test session."
  }
}
```

### 400 — Scheduling Conflict
```json
{
  "success": false,
  "message": "Faculty has a scheduling conflict.",
  "clashing_slots": ["slot-uuid-conflicting-001"]
}
```

### 401 — Unauthorized
```json
{
  "detail": "Authentication credentials were not provided."
}
```

### 404 — Not Found
```json
{
  "success": false,
  "message": "Timetable slot not found."
}
```

---

## SECTION 7 — Migrations Required

> **⚠️ Action Required**
>
> After pulling the latest code, run these commands to apply all pending database migrations:
>
> ```bash
> python manage.py migrate batches
> ```
>
> This applies:
> - `0016` — `exam` (OneToOneField → `exams.Exam`) on `TimetableSlot`
> - `0017` — `session_name` (CharField max 200) on `TimetableSlot`
