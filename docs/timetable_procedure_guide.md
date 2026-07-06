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
                                │  Exam (w/ proctoring   │
                                │  config, paper_checkers)│
                                └─────────────────────────┘
                                              │
                                              ▼
                            ┌─────────────────────────────────────┐
                            │ ensure_paper_checkers_for_exam()    │
                            │ (early M2M sync; delayed assignment │
                            │  post-exam via Celery task)         │
                            └─────────────────────────────────────┘


---

## Appendix A: System Choice Values & Display Mappings

### A.1 Session Types (`session_type`)
| Value | Display | Exam Auto-Created? | Required Fields | Forbidden Fields | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `regular` | Regular | ❌ No | `slot_code`, `day_of_week` (or `session_date` for P5/P6), `faculty` | `exam_data`, `examiners`, `paper_checkers` | Auto `start_time`/`end_time` from `FIXED_SLOTS`. Clash detection on faculty/classroom. Chapters optional (not typically used). |
| `class_test` | Class Test | ✅ Yes | `session_date`, `start_time`, `chapters`, `faculty`, `examiners`, `paper_checkers`, `exam_data` | `slot_code` | Auto `end_time` = start + 90min (`SESSION_DURATIONS`). Chapters limited to subject's early ones. Links to created `Exam`. |
| `prelim` | Prelim | ✅ Yes | `session_date`, `start_time`, `end_time`, `chapters`, `faculty`, `examiners`, `paper_checkers`, `exam_data` | `slot_code` | Manual `end_time` (typically 180min). Full Exam v2 with proctoring. |
| `practice` | Practice | ❌ No | `session_date`, `start_time`, `faculty`, `examiners` | `slot_code`, `paper_checkers`, `exam_data` | Auto `end_time` = start + 90min. No exam linkage. |
| `custom` | Custom | ⚙️ If `exam_data` provided | `session_date`, `start_time`, `end_time` | `slot_code` | Optional `exam_data` to auto-create linked Exam. Supports `selected_papers`. |

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

### A.4 Exam Data Fields (inside `exam_data` for exam-creating sessions)
The `exam_data` object is passed to `_handle_exam()` which creates or updates the linked `Exam` (OneToOne on TimetableSlot). Supports Exam v2 fields.

**Supported fields in `ExamDataSerializer`:**
- `title` (optional, auto-generated if omitted)
- `exam_type`: `'mcq'` or `'subjective'` (maps to Exam.exam_type; exam_mode defaults to `'offline'` in current flow)
- `total_marks`, `pass_marks` (required for pass_marks)
- `duration_minutes` (optional, auto-calculated from slot times)
- `instructions`
- `result_release_mode`: `'instant'` or `'manual'`
- `selected_papers`: list of SubjectPaper UUIDs (syncs to Exam.selected_papers M2M)

**Additional Exam v2 fields** (set on Exam model, some configurable via other endpoints or defaults):
- `exam_mode`: `'online'` or `'offline'`
- Geo: `geo_lat`, `geo_lon`, `geo_radius_meters`, `geo_check_interval_minutes`
- Screen: `screen_lock_max_violations`, `screen_lock_action`, `split_screen_max_warnings`, `split_screen_action`

See `exams_module_api_documentation.md` for full Exam CRUD and proctoring endpoints.

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

### A.8 Exam Proctoring Fields (in `exam_data`)
| Field | Type | Default/Notes |
| :--- | :--- | :--- |
| `geo_lat` / `geo_lon` | float | Center of allowed area (required if `geo_radius_meters > 0`) |
| `geo_radius_meters` | int | 0 = disabled. Periodic geo-checks during exam. |
| `screen_lock_threshold` | int | Violations before action (e.g. 3) |
| `split_screen_threshold` | int | Violations before action |
| `screen_action` | string | `flag_only` or `auto_submit` |
| `result_release_mode` | string | `instant` (auto-grade MCQ + publish) or `manual` |
| `allow_split_screen` | bool | Configures monitoring |

**Logic Notes:**
- `ensure_paper_checkers_for_exam()` populates `Exam.paper_checkers` M2M from timetable or branch fallback **early**.
- `assign_papers_to_checker()` is **delayed** (Celery task) until exam completion (`auto_mark_absent` runs, all `MarkSheet`s exist).
- Round-robin paper assignment (from `selected_papers`) happens at `/start/`.
- Signals on Question CRUD auto-run `recalculate_total_marks()`.

---

**Note on Legacy Exam Types:** The dedicated `ExamType` / `timetable/exam-types/` endpoints and `timetable_exam_type` FK have been **completely removed** in the E4 refactor. All logic now uses `session_type` + nested `exam_data` (validated in `TimetableSlotCreateUpdateSerializer`). Exam linkage via OneToOne `TimetableSlot.exam`. See `exams_module_api_documentation.md` (Exam v2 with proctoring, `result_release_mode`, `selected_papers` round-robin at `/start/`, auto `total_marks` via signals) and Appendix A for full matrix.

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

- `session_date`, `start_time`, `chapters`, `faculty`, `examiners`, `paper_checkers`, `exam_data` are **required**
- `end_time` is **auto-computed** (90-minute fixed duration from `SESSION_DURATIONS`)
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
  "exam_data": {
    "title": "Company Law — Ch 1 & 2 Class Test",
    "exam_type": "mcq",
    "total_marks": 50,
    "pass_marks": 18,
    "instructions": "Attempt all questions. Time: 90 minutes.",
    "result_release_mode": "manual",
    "selected_papers": ["paper-uuid-001", "paper-uuid-002"]
  }
}


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
    "exam": "exam-uuid-0001"
  }
}


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

- `session_date`, `start_time`, `end_time`, `chapters`, `faculty`, `examiners`, `paper_checkers`, `exam_data` are **required**
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
  "exam_data": {
    "title": "Company Law — June 2026 Prelim",
    "exam_type": "subjective",
    "total_marks": 100,
    "pass_marks": 35,
    "instructions": "All questions carry equal marks. Duration: 3 hours.",
    "result_release_mode": "instant",
    "selected_papers": ["paper-uuid-003"]
  }
}


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
    "exam": "exam-uuid-0002"
  }
}


---

#### 2.3.4 POST — Practice Session

**`POST /api/v1/timetable/`**

- `session_date`, `start_time`, `faculty`, `examiners` are **required**
- `end_time` is **auto-computed** (from `SESSION_DURATIONS`)
- `paper_checkers`, `exam_data`, `slot_code` are **forbidden**

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
    "exam": null
  }
}


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
    "result_release_mode": "instant",
    "geo_radius_meters": 0,
    "screen_lock_threshold": 5,
    "screen_action": "flag_only"
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
    "exam": "exam-uuid-0003"
  }
}


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

### 2.6 Duplicate Timetable Slot (New Endpoint)

**`POST /api/v1/timetable/<slot_id>/duplicate/`**

Duplicates a `regular` session slot to a different `slot_code` / `day_of_week` (or `session_date`). Performs clash detection. Only works for regular sessions.

#### Request Body
```json
{
  "slot_code": "P2",
  "day_of_week": 2,
  "session_name": "Optional override"
}
```

- For P5/P6, also provide `start_time`/`end_time`.
- Returns the new slot with full details (201 Created).
- Errors: 400 for non-regular, invalid code, clashes, or missing params.

#### Example Response (201)
```json
{
  "success": true,
  "message": "Timetable slot duplicated.",
  "data": { ...full TimetableSlotListSerializer output... }
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

## SECTION 5 — Complete API Endpoint Summary Table (E4 Updated)

**Note:** Legacy `timetable/exam-types/` endpoints and `timetable_exam_type` field have been removed. All exam creation is now driven by `session_type` + inline `exam_data` (see Appendix A.1 and `_handle_exam()`).

| # | Method | Endpoint | Description |
| :--- | :--- | :--- | :--- |
| 1 | `GET` | `/api/v1/batches/dropdowns/` | Academic dropdowns with nested E2 data: courses → levels, subjects (with chapters + papers), batches, branches, classrooms. Supports `?branch_id=` |
| 2 | `GET` | `/api/v1/timetable/` | List timetable slots with filters (`batch_id`, `faculty_id`, `session_type`, `day_of_week`, etc.) + computed `_names` fields |
| 3 | `POST` | `/api/v1/timetable/` | Create slot — strict per-`session_type` validation, clash detection (faculty+classroom), auto Exam for `class_test`/`prelim`/`custom` (if `exam_data` given) |
| 4 | `GET` | `/api/v1/timetable/<slot_id>/` | Single slot detail (includes `exam`, `chapters_names`, `examiners_names`, `paper_checkers_names`) |
| 5 | `PATCH` | `/api/v1/timetable/<slot_id>/` | Partial update (re-runs validation + clash checks; supports updating `exam_data`) |
| 6 | `DELETE` | `/api/v1/timetable/<slot_id>/` | Delete slot (linked `Exam` record is **preserved**) |
| 7 | `POST` | `/api/v1/timetable/<slot_id>/duplicate/` | Duplicate regular slot to new `slot_code`/`day_of_week` (or `session_date`); performs clash detection. Only for `regular` sessions |
| 8 | `GET` | `/api/v1/timetable/faculty/<faculty_id>/` | Faculty's weekly timetable grouped by day label |
| 9 | `GET` | `/api/v1/timetable/student/<student_id>/` | Student's aggregated timetable (from all enrolled batches), grouped by day |
| 10 | `GET` | `/api/v1/courses/` | Course CRUD (includes nested levels & subjects via serializers) |
| 11 | `GET` | `/api/v1/faculty/` | List faculty profiles (annotated with `subjects`, `subject_name`, batch counts) |
| 12 | `GET` | `/api/v1/faculty/<faculty_id>/` | Faculty detail with subjects taught across batches |

See `batches_module_api_documentation.md` for full CRUD on Courses, Subjects, Chapters, Levels, Batches (assign/remove students/faculty), Classrooms.

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

## SECTION 8 — Proctoring, Geo-Fencing, Screen Monitoring & Delayed Checker Assignment

Timetable-created Exams now support full **Exam v2** proctoring:

### Key Behaviors (Synced from `exam_data`)
- **Geo-fencing**: If `geo_radius_meters > 0`, `check_geo_boundary()` validates student location on `/start/` and periodic `/geo-check/`. Violations logged; configurable action on threshold.
- **Screen Monitoring**: `ScreenEventView` tracks `lock_breach` / `split_screen`. Uses thresholds + `screen_action` (`flag_only` vs `auto_submit_session()`).
- **Result Release**: `instant` → auto-grades MCQs via `auto_grade_mcq()`, creates `PublishedResult`. `manual` defers to checker.
- **Paper Checkers**:
  - `ensure_paper_checkers_for_exam()` runs on slot/exam create: copies from `TimetableSlot.paper_checkers` M2M or falls back to branch-level checkers.
  - **Delayed Assignment**: `assign_papers_to_checker()` (via Celery task) runs **only after exam ends** (`auto_mark_absent()`, all `MarkSheet` records created, `selected_papers` distributed). Uses round-robin on `Exam.selected_papers`.
- **ExamSession**: Stores `assigned_paper`, geo violations, screen violations, `status`.
- **Signals**: Question CRUD → `recalculate_total_marks()` on parent Exam.

**Related Endpoints** (see `exams_module_api_documentation.md`):
- `/exams/{id}/start/` (with lat/lon)
- `/sessions/{session_id}/geo-check/`
- `/sessions/{session_id}/screen-event/`
- `/exams/{id}/submit/`
- Malpractice, Answer Key (token-based), Subject Papers (`selected_papers`).

**can_start_exam** logic (in serializer): time window, no duplicate session, batch match, geo pre-check.

---

## SECTION 9 — Additional Endpoints & Current State

### 9.1 Academic Dropdowns (for UI forms)

**`GET /api/v1/batches/dropdowns/`** (or with `?branch_id=xxx`)

Returns nested data for courses, levels, batches, subjects (with chapters + papers), branches, classrooms. Used by frontend for creating timetable slots, batches, etc. Includes E2 nested structures.

Response includes `subjects` with `chapters` and `papers` arrays.

### 9.2 Other Batches Module Endpoints

See `batches_module_api_documentation.md` for full coverage of Courses, Subjects, Chapters (E2), Batches (with auto-naming/QR, assign students/faculty), Classrooms, Levels.

**Current Migration Status:** All E4 changes (session_type matrix, Exam integration, M2M sync in `_handle_exam()`, `AcademicDropdownsView`, duplicate endpoint, updated serializers with per-type validation using `FIXED_SLOTS`/`SESSION_DURATIONS`, `_names` computed fields, CourseLevel/Chapter nesting) have been applied. Run `python manage.py migrate` if any pending. Tests in `batches/tests.py` and `tests_edge_cases.py` cover clash detection, validation rules, and exam creation flows.

**Sync Note:** This guide is now aligned with `TimetableSlotCreateUpdateSerializer.validate()`, `TimetableDuplicateSlotView`, `AcademicDropdownsView`, and `TimetableSlotListSerializer` (as of latest code).
