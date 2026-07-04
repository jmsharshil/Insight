# Results Module — Full API Reference & Walkthrough Guide

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>` (most endpoints; checker portal uses token param)  
> **Content-Type:** `application/json`  
> All responses wrapped in `{ "success": true/false, "message": "...", "data": {...} }`.  
> Role-based permissions enforced (super_admin, paper_checker, admin_senior_executive, branch_manager, student).

---

## Architecture & Workflow Diagram (Updated)

```
                              ┌─────────────────────────────┐
                              │      Exam Completed         │ (timetable/exams + ExamSession)
                              └──────────────┬──────────────┘
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       ▼                                           ▼
             Auto Mark Absent (no session)               Paper Allocation (CheckerToken)
                       │                                           │
                       ▼                                           ▼
             MarkSheet(is_absent=True)               Checker Portal (token) or Web (/marks/)
                       │                                           │
                       └───────────────────┬─────────────────────┘
                                           ▼
                            ┌─────────────────────────────┐
                            │   All Marks Submitted?      │ (no open queries)
                            └─────────────────────────────┘
                                           │
                                           ▼
                              ┌─────────────────────────────┐
                              │   POST /results/publish/    │ → calculate_ranks(), PublishedResult
                              └──────────────┬──────────────┘
                                             │
                                             ▼
                              ┌─────────────────────────────┐
                              │   Student Views Results     │ (GET /results/)
                              └──────────────┬──────────────┘
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       ▼                                           ▼
          Student Recheck Request (w/ answer_key + upload)   PaperCheckerQuery (on recheck)
                       │                                           │
                       ▼                                           ▼
              ASE Review (approve/reject)               Resolve Query → Resubmit Marks
                       │
                       ▼
              Re-assign Checker → New Token/Email → Update PublishedResult
```

**Key Additions:** `is_absent` auto-marking via ExamSession, `CheckerQuery` for payroll-safe clarifications, answer_key requirement on Exam before rechecks, bulk recheck support.
```

**Note:** The views follow consistent patterns seen in `attendance/views.py` (role helpers, organization filtering, comprehensive permission guards).

---

## Appendix A: System Choice Values & Statuses

### A.1 Recheck Statuses (`status`)
| Value | Display | Notes |
| :--- | :--- | :--- |
| `approval_pending` | Approval Pending | Initial student request |
| `approved` | Approved | ASE approved, new checker assigned |
| `rejected` | Rejected | ASE rejected request |
| `completed` | Completed | Recheck grading finished by checker |

### A.2 Query Statuses (`status`)
| Value | Display | Notes |
| :--- | :--- | :--- |
| `open` | Open | Blocks payroll for rechecked papers |
| `resolved` | Resolved | Allows payroll inclusion; checker can submit marks |
| `closed` | Closed | Final (rarely used) |

### A.3 MarkSheet Flags
- `is_submitted`: True after checker submits (blocks re-entry and publish until all done).
- `is_rechecked`: Set on recheck approval or query.
- `is_absent`: True if student did not attend (auto or manual).
- `is_pass`: Computed as `marks_obtained >= exam.pass_marks`.
- Open `CheckerQuery` prevents modification for non-admins.

### A.4 Role Permissions Summary (Updated)
| Role | View Papers | Enter Marks | Publish | Review Recheck/Query | Student Recheck | Raise Query |
|------|-------------|-------------|---------|----------------------|-----------------|-------------|
| super_admin | Yes | Yes | Yes | Yes | N/A | Yes |
| admin_senior_executive | Yes | Yes | Yes | Yes | N/A | No |
| paper_checker | Assigned only | Yes (own, if no open query) | No | No | N/A | Yes (on recheck) |
| branch_manager | Yes (status) | No | Yes | Yes | N/A | No |
| student | Own results | No | No | No | Yes | No |

**New:** `QUERY_ROLES = ['super_admin', 'paper_checker', 'admin_senior_executive']`

---

## Data Models Summary

| Model | Purpose | Key Behaviors |
|-------|---------|---------------|
| `MarkSheet` | Per-student per-exam grading record | Linked to Exam + Student; tracks checker, marks, submission, recheck flags, `is_absent`; auto-computes `is_pass`; supports queries |
| `PublishedResult` | Final official result (immutable after publish) | Computed rank via `calculate_ranks()`; unique per (exam, student); updated on rechecks |
| `RecheckRequest` | Student-initiated re-evaluation (v2 — FRD §4.6.2) | Full lifecycle (`approval_pending` → `approved`/`rejected` → `completed`); supports `uploaded_marksheet` file, `checker_notes`; prevents duplicates; notifies ASE |
| `CheckerQuery` | Paper checker raises clarification requests | Links to MarkSheet; status (`open`/`resolved`); blocks payroll for rechecked papers until resolved; types include answer_key issues |
| `SubmissionReminderLog` | Audit for checker reminders | Tracks follow-ups for unsubmitted papers |

**Integration:** Closely tied to `exams` (Exam model with `answer_key` requirement for rechecks, CheckerToken, `calculate_ranks()`, emails), `timetable` (ExamSession for auto-absent), `students` (for visibility/filtering), payroll (via query filters in `compute_payslip_for_user()`).

---

## Key Workflows & Steps (Updated with Current Code)

### 1. Post-Exam Paper Checking & Absent Marking
1. Exam ends → `MarkAllAbsentView` can be called (uses `ExamSession` to identify no-shows).
2. Auto/manual `is_absent=True`, `marks_obtained=0`, `is_submitted=True`.
3. Papers allocated to `paper_checker` (via `CheckerToken`).
4. Checkers use web (`POST/PUT /papers/<id>/marks/`) or portal. **Open queries block non-admins**.

### 2. Publishing Results
1. Admin/ASE calls `POST /exams/<id>/results/publish/` — checks all `is_submitted=True` (no open queries), creates `PublishedResult`, calls `calculate_ranks()`, sets Exam status.
2. Students view via `GET /exams/<id>/results/` (role-filtered).
3. Top scorer returned in response.

### 3. Recheck Request (v2 — FRD §4.6.2)
1. **Requires** `Exam.answer_key` uploaded. Student POSTs to `/results/recheck-request/` with `reason` + optional `uploaded_marksheet` file.
2. ASE reviews via `GET /recheck-requests/` + `PATCH /recheck-requests/<id>/` (`action=approve` with `new_checker_id` or `reject`).
3. On approve: updates MarkSheet (`is_rechecked=True`, new checker, `is_submitted=False`), generates token, sends email.
4. Checker uses PUT `/marks/` (with optional `notes`) → sets RecheckRequest to `completed`, updates PublishedResult.
5. Prevents duplicate pending requests; supports **bulk** recheck for batch.

### 4. Paper Checker Queries (NEW)
1. After recheck starts, checker POSTs `/papers/<id>/query/` (`query_type`, `description`).
2. Creates `CheckerQuery(status='open')` — excludes paper from payroll.
3. ASE resolves via PATCH `/queries/<id>/resolve/` (optionally with marks) → `status='resolved'`, allows submission/payment.

### 5. Checker Portal Flow
- Token-based (`?token=...`), `AllowAny` permission.
- Validates token (not used, not expired), submits marks, marks token used.

**Safety Rules (from current views.py):**
- Strict role checks (`PAPER_MARK_ROLES`, `RECHECK_REQUEST_REVIEW_ROLES`, `QUERY_ROLES` etc.).
- Organization filtering on all querysets.
- Marks validation (`0 ≤ marks ≤ total_marks`).
- Query block in `_get_marksheet()` for open queries.
- Answer key enforcement in recheck request.
- No duplicate rechecks; comprehensive error messages.

---

## Complete API Reference (Matches Current `results/views.py` + Serializers)

All examples use the actual serializers (`MarkSheetSerializer`, `RecheckRequestSerializer`, `CheckerQuerySerializer`, etc.) and view logic.

### 1. Paper List, Marks Entry & Absent Marking

**`GET /api/v1/exams/<exam_id>/papers/`** (`PaperView`)

**Query Params:** `is_submitted`, `is_pass`, `is_rechecked`, `is_absent`, search (`student__user__name`, `paper_checker__name`).

**Response (200 OK)**
```json
{
  "success": true,
  "count": 45,
  "data": [
    {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "exam": "exam-uuid",
      "student": "stu-uuid-001",
      "student_name": "Priya Shah",
      "roll_number": "101",
      "paper_checker": "user-uuid",
      "checker_name": "Prof. Anil Sharma",
      "marks_obtained": 42.5,
      "is_pass": true,
      "is_absent": false,
      "remarks": "Good attempt on theory",
      "checked_at": "2026-06-20T14:30:00Z",
      "is_submitted": true,
      "is_rechecked": false,
      "has_open_query": false
    }
  ]
}
```

**`POST/PUT /api/v1/exams/<exam_id>/papers/<marksheet_id>/marks/`** (`PaperMarksView`)

**Request Body**
```json
{
  "marks_obtained": 78.0,
  "remarks": "Excellent performance on case studies",
  "notes": "Recheck verification complete - improved score justified"
}
```

**Success Response (200)**
```json
{
  "success": true,
  "message": "Marks updated. Recheck completed if applicable.",
  "data": {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "student_name": "Priya Shah",
    "marks_obtained": 78.0,
    "is_pass": true,
    "is_rechecked": true,
    "remarks": "Excellent performance on case studies",
    "checked_at": "2026-06-22T10:15:00Z"
  }
}
```

**Common Errors:**
```json
{
  "success": false,
  "message": "This marksheet has an open query. Please resolve the query first.",
  "has_open_query": true
}
```
(or "Not assigned to you.", "Invalid marks.", "Already submitted.")

**`POST /api/v1/exams/<exam_id>/papers/<marksheet_id>/mark-absent/`** (`MarkAbsentView`)

**Request Body:** (empty or `{ "remarks": "Medical emergency" }`)

**Success Response**
```json
{
  "success": true,
  "message": "Student marked as absent.",
  "data": {
    "marksheet_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "is_absent": true,
    "marks_obtained": 0,
    "status": "absent"
  }
}
```

**`POST /api/v1/exams/<exam_id>/mark-absent-all/`** (`MarkAllAbsentView`)

**Success Response**
```json
{
  "success": true,
  "message": "12 students marked as absent.",
  "absent_count": 12
}
```

**`DELETE /api/v1/exams/<exam_id>/papers/<marksheet_id>/`** — Super admin only. Returns `{"success": true, "message": "Marksheet deleted."}`.

---

### 2. Checker Status, Portal & Queries

**`GET /api/v1/exams/<exam_id>/checker-status/`** (`CheckerStatusView`)

**Response**
```json
{
  "success": true,
  "data": {
    "total_papers": 50,
    "submitted": 42,
    "approval_pending": 8,
    "overdue": 0,
    "checkers": [
      {
        "checker_id": "user-uuid",
        "checker_name": "Prof. Anil Sharma",
        "assigned_count": 15,
        "submitted_count": 12,
        "pending_count": 3,
        "last_activity": "2026-06-21T09:15:00Z"
      }
    ]
  }
}
```

**`POST /api/v1/checker-portal/submit/?token=secure-token-here`** (`AllowAny`)

**Request Body**
```json
{
  "marks_obtained": 85.5,
  "remarks": "Strong conceptual clarity. Minor deduction for Q2."
}
```

**Success Response**
```json
{
  "success": true,
  "message": "Marks submitted successfully."
}
```

**Paper Checker Query Endpoints (`PaperCheckerQueryView`)**

**`POST /api/v1/exams/<exam_id>/papers/<marksheet_id>/query/`**

**Request Body**
```json
{
  "query_type": "answer_key_not_available",
  "description": "Answer key is missing for the practical section (questions 5-8). Cannot grade accurately."
}
```

**Success Response (201)**
```json
{
  "success": true,
  "message": "Query raised. This paper will not count toward payment until resolved.",
  "data": {
    "id": "query-uuid-001",
    "query_type": "answer_key_not_available",
    "query_type_display": "Answer Key Not Available",
    "description": "...",
    "status": "open",
    "status_display": "Open",
    "created_at": "2026-06-22T11:00:00Z"
  }
}
```

**`PATCH /api/v1/exams/<exam_id>/queries/<query_id>/resolve/`**

**Request Body (optional marks update)**
```json
{
  "marks_obtained": 82.0,
  "remarks": "Answer key provided. Adjusted marks."
}
```

**Success Response**
```json
{
  "success": true,
  "message": "Query resolved. Paper now eligible for payment on next payroll run (if submitted).",
  "data": { ...query details with status: "resolved"... }
}
```

---

### 3. Publish & View Results

**`POST /api/v1/exams/<exam_id>/results/publish/`**

**Success Response**
```json
{
  "success": true,
  "message": "Results published.",
  "data": {
    "student_count": 45,
    "top_scorer": "Rahul Sharma"
  }
}
```

**`GET /api/v1/exams/<exam_id>/results/`** (`ResultView`)

**Response Example**
```json
{
  "success": true,
  "count": 45,
  "data": [
    {
      "id": "pr-uuid-001",
      "exam": "exam-uuid",
      "student_name": "Priya Shah",
      "roll_number": "101",
      "marks_obtained": 85.5,
      "total_marks": 100,
      "percentage": 85.5,
      "is_pass": true,
      "rank": 1,
      "published_at": "2026-06-22T10:00:00Z"
    }
  ]
}
```

**`DELETE /api/v1/exams/<exam_id>/results/<result_id>/`** → `{"success": true, "message": "Result deleted."}`

---

### 4. Recheck Requests (v2 — Enhanced) (`RecheckRequestSerializer`, `RecheckRequestCreateSerializer`, `RecheckRequestActionSerializer`)

**`POST /api/v1/exams/<exam_id>/results/recheck-request/`** (`StudentRecheckRequestView` — supports `multipart/form-data` for file upload)

**Request Body**
```json
{
  "reason": "Discrepancy between my calculated marks and published score in practical section.",
  "uploaded_marksheet": "(optional PDF/image of answer sheet)"
}
```

**Success Response (201 Created)**
```json
{
  "recheck_requested": true,
  "status": "approval_pending",
  "message": "Your recheck request has been submitted for review.",
  "upload_provided": true
}
```

**Error Examples**
```json
{
  "success": false,
  "message": "Answer key has not been uploaded yet. Recheck not allowed."
}
```
(or 409 for duplicate pending request, 403 for non-student).

**`GET /api/v1/exams/<exam_id>/recheck-requests/`** (`RecheckRequestListView`)

**Response Example**
```json
{
  "success": true,
  "count": 3,
  "data": [
    {
      "id": "recheck-uuid-001",
      "student_name": "Priya Shah",
      "roll_number": "101",
      "reason": "Discrepancy in practical marks...",
      "uploaded_marksheet_url": "/media/recheck_uploads/scan.pdf",
      "checker_notes": "Verified calculation error. Score adjusted +5.",
      "status": "completed",
      "status_display": "Completed",
      "reviewed_by_name": "Admin Senior Executive",
      "new_checker_name": "Dr. Meera Patel",
      "created_at": "2026-06-22T10:30:00Z"
    }
  ]
}
```

**`PATCH /api/v1/exams/<exam_id>/recheck-requests/<request_id>/`** (`RecheckRequestActionView`)

**Request Body — Approve**
```json
{
  "action": "approve",
  "new_checker_id": "user-uuid-for-new-checker"
}
```

**Request Body — Reject**
```json
{
  "action": "reject",
  "reason": "Insufficient evidence of marking error."
}
```

**Success Responses**
```json
{
  "success": true,
  "message": "Recheck approved and reassigned to new checker."
}
```
(or reject message).

**Bulk Recheck (`BulkRecheckRequestView` — view ready, URL mapping pending):**
- **Body:** `{"reason": "Batch-wide re-evaluation after answer key review"}`
- Creates multiple `RecheckRequest` records for the exam's batch (if `PublishedResult` exists and no pending recheck).
- Returns count of created requests.

**Legacy direct re-assignment:** `POST /api/v1/exams/<exam_id>/papers/<marksheet_id>/recheck/` still supported for admins.

---

### 2. Checker Status, Portal & Queries

**`GET /api/v1/exams/<exam_id>/checker-status/`** (`CheckerStatusView`)

**Response (200 OK)**
```json
{
  "success": true,
  "data": {
    "total_papers": 50,
    "submitted": 42,
    "approval_pending": 8,
    "overdue": 0,
    "checkers": [
      {
        "checker_id": "user-uuid-123",
        "checker_name": "Prof. Anil Sharma",
        "assigned_count": 15,
        "submitted_count": 12,
        "pending_count": 3,
        "last_activity": "2026-06-21T09:15:00Z"
      }
    ]
  }
}
```

**`POST /api/v1/checker-portal/submit/?token=secure-token-here`** (`CheckerPortalSubmitView` — `AllowAny`)

**Request Body**
```json
{
  "marks_obtained": 85.5,
  "remarks": "Strong conceptual clarity. Minor deduction for Q2."
}
```

**Success Response**
```json
{
  "success": true,
  "message": "Marks submitted successfully."
}
```

**Error Example (Invalid Token)**
```json
{
  "success": false,
  "message": "Token expired or used."
}
```

**Paper Checker Query Endpoints** (`PaperCheckerQueryView` — uses `CheckerQueryCreateSerializer` / `CheckerQuerySerializer`):

**`POST /api/v1/exams/<exam_id>/papers/<marksheet_id>/query/`**

**Request Body**
```json
{
  "query_type": "answer_key_not_available",
  "description": "Answer key is missing for the practical section (questions 5-8). Cannot grade accurately."
}
```

**Success Response (201 Created)**
```json
{
  "success": true,
  "message": "Query raised. This paper will not count toward payment until resolved.",
  "data": {
    "id": "query-uuid-001",
    "query_type": "answer_key_not_available",
    "query_type_display": "Answer Key Not Available",
    "description": "Answer key is missing...",
    "status": "open",
    "status_display": "Open",
    "raised_by_name": "Prof. Anil Sharma",
    "created_at": "2026-06-22T11:00:00Z"
  }
}
```

**`PATCH /api/v1/exams/<exam_id>/queries/<query_id>/resolve/`**

**Request Body (can include marks to auto-resolve & submit)**
```json
{
  "marks_obtained": 82.0,
  "remarks": "Answer key now provided by ASE. Adjusted final score."
}
```

**Success Response**
```json
{
  "success": true,
  "message": "Query resolved. Paper now eligible for payment on next payroll run (if submitted).",
  "data": {
    "id": "query-uuid-001",
    "status": "resolved",
    "status_display": "Resolved",
    "resolved_by_name": "Admin Senior Executive",
    "resolved_at": "2026-06-22T11:30:00Z"
  }
}
```

---

### 3. Publish & View Results

**`POST /api/v1/exams/<exam_id>/results/publish/`** (`PublishResultView`, PUBLISH_ROLES)

#### Response (200 OK)
```json
{
  "success": true,
  "message": "Results published.",
  "data": {
    "student_count": 45,
    "top_scorer": "Rahul Sharma"
  }
}
```

**Errors:**
- 400: Not all submitted, already published, or open queries.
- Uses bulk_create for efficiency.

**`GET /api/v1/exams/<exam_id>/results/`** (`ResultView`)
- Filters: `is_pass`; search on student name.
- Role-based: students see only own; parents via linked_parents.
- Returns rank, percentage, etc.

**`DELETE /api/v1/exams/<exam_id>/results/<result_id>/`** (`ResultDeleteView`) — unpublishes specific result (admin only).

---

### 4. Recheck Requests (v2 — Enhanced)

**`POST /api/v1/exams/<exam_id>/results/recheck-request/`** (`StudentRecheckRequestView`)
- **Student only**. Requires published result + `exam.answer_key`.
- Supports multipart for `uploaded_marksheet` file.
- Checks for existing pending/approved requests (409).

#### Request Body
```json
{
  "reason": "Discrepancy in practical marks. Requesting re-evaluation."
}
```

#### Success (201)
```json
{
  "recheck_requested": true,
  "status": "approval_pending",
  "message": "Your recheck request has been submitted for review.",
  "upload_provided": true
}
```

**`GET /api/v1/exams/<exam_id>/recheck-requests/`** (`RecheckRequestListView`)
- ASE/Manager. Filter by `status`, search by student name. Returns full serializer data (incl. uploaded file URL, notes).

**`PATCH /api/v1/exams/<exam_id>/recheck-requests/<request_id>/`** (`RecheckRequestActionView`)
- Only ASE/super_admin.
- `{"action": "approve", "new_checker_id": "..."}` or `{"action": "reject"}`.
- On approve: reassigns, generates token, sends email.
- Legacy `PaperRecheckView` (`POST /papers/<id>/recheck/`) still available for direct reassignment.

**Bulk Recheck** (`BulkRecheckRequestView` — view implemented but URL mapping pending in `urls.py`):
- POST to dedicated bulk endpoint (planned `/exams/<exam_id>/results/recheck-request/bulk/`).
- ASE/super_admin only. Creates multiple `RecheckRequest`s for batch students (requires `answer_key` on Exam).

---

## Common Error Responses (from Current Implementation)

### 403 Permission / Role / Assignment Issues
```json
{
  "success": false,
  "message": "Permission denied."
}
```
or
```json
{
  "success": false,
  "message": "Not assigned to you.",
  "has_open_query": true
}
```
or
```json
{
  "success": false,
  "message": "Only students can request recheck."
}
```

### 400 Validation / Business Rule Violations
```json
{
  "success": false,
  "message": "Not all marksheets submitted.",
  "errors": { ... }
}
```
Common messages:
- `"Invalid marks."`
- `"Already submitted."`
- `"Answer key has not been uploaded yet. Recheck not allowed."`
- `"This marksheet has an open query. Please resolve the query first."`
- `"A recheck request is already pending or approved."` (also returns 409)

### 409 Conflict
```json
{
  "success": false,
  "message": "A recheck request is already pending or approved."
}
```

### Portal Token Errors
```json
{
  "success": false,
  "message": "Token expired or used."
}
```

### 404 Not Found
Standard for missing `Exam`, `MarkSheet`, `RecheckRequest`, or `CheckerQuery`.

**All endpoints** include organization-based filtering and strict role checks matching the constants at the top of `results/views.py`.

---

## SECTION 5 — Result Analytics & Aggregation APIs (On-the-Fly)

These **read-only** endpoints compute all aggregates, pass percentages, ranks, and top-performer lists **directly from `PublishedResult`** (with `select_related` joins to `Exam.subject`, `Exam.faculty`, `Exam.batch`). 

**No new models, no signals, no materialized views** — uses `annotate()`, `values()`, `Count`/`Avg`/`Max`/`Min`, `ExpressionWrapper(F('passed_students')*100.0/Coalesce(...))`, `F()` for grouping, and `Q()` filters. Matches the "no new models" directive from the core update.

All endpoints:
- Require roles: `super_admin`, `admin_senior_executive`, or `branch_manager`.
- Apply organization scoping via `exam__branch__organization`.
- Support query params: `?batch_id=...&subject_id=...&faculty_id=...&exam_id=...` (UUIDs).
- Return consistent fields: `total_students`, `passed_students`, `pass_percentage` (float), `average_marks`, `highest_marks`, `lowest_marks`, etc.
- Order by `-pass_percentage`, `-average_marks` by default.

**Base paths:** `/api/v1/results/subject-wise/`, `/faculty-wise/`, `/batch-wise/`, `/summary/`, `/analytics/` (see `results/urls.py`).

### 5.1 Subject-Wise Results

**`GET /api/v1/results/subject-wise/`**

**Query Params (optional):** `subject_id`, `batch_id`, `exam_id`

**Response Example (200 OK)**
```json
{
  "success": true,
  "count": 12,
  "data": [
    {
      "subject_id": "sub-uuid-001",
      "subject_name": "Company Law",
      "batch_id": "batch-uuid-001",
      "batch_name": "CS_Executive_June_2026",
      "exam_id": "exam-uuid-001",
      "exam_title": "June Prelim 2026",
      "total_students": 45,
      "appeared_students": 45,
      "passed_students": 38,
      "pass_percentage": 84.44,
      "average_marks": 72.5,
      "highest_marks": 98.0,
      "lowest_marks": 42.0
    },
    ...
  ]
}
```

### 5.2 Faculty-Wise Results

**`GET /api/v1/results/faculty-wise/`**

Groups by `faculty` + `subject`. Returns `faculty_id`, `faculty_name`, `subject_name`, etc. (same aggregate fields).

**Example use:** `?faculty_id=...&subject_id=...`

### 5.3 Batch-Wise Results

**`GET /api/v1/results/batch-wise/`**

Groups by `batch` (optionally + subject). Ideal for batch performance reports.

### 5.4 Overall Summary & Top-5 Lists

**`GET /api/v1/results/summary/`** or **`GET /api/v1/results/analytics/`** (`ResultAnalyticsView`)

Combines overall stats with top-5 lists (subjects, faculty, batches) using separate annotated querysets limited to `[:5]`.

**Response Example**
```json
{
  "success": true,
  "data": {
    "overall": {
      "total_students": 1250,
      "passed_students": 1025,
      "pass_percentage": 82.0,
      "average_percentage": 71.25,
      "average_marks": 71.25
    },
    "top_subjects": [
      {
        "exam__subject__id": "sub-001",
        "exam__subject__name": "Company Law",
        "total": 120,
        "passed": 105,
        "pass_pct": 87.5,
        "avg_marks": 78.4
      },
      ...
    ],
    "top_faculty": [ ... ],
    "top_batches": [ ... ],
    "total_published_results": 1250
  }
}
```

**Technical Note:** Uses `base_qs.values('exam__subject__id', ...).annotate(...)` for top lists; `Coalesce` prevents division-by-zero on pass_percentage. Fully compatible with existing publish/recheck/query flows (ranks computed in `calculate_ranks()` on publish/recheck).

### 5.5 Results Export API (NEW)

**`GET /api/v1/results/export/?type=<type>&exam_id=...`**

**Supported `type` values:** `exam` (per-exam student list), `subject-wise`, `faculty-wise`, `analytics`/`summary`.

**Query Params:** Same as aggregate views + `format=csv` (default; only CSV supported for now).

**Response:** CSV file download with `Content-Disposition: attachment; filename="results_....csv"`.

**Example (exam results):**
```
Student Name,Roll Number,Marks Obtained,Total Marks,Percentage,Rank,Is Pass,Published At,Exam Title
Priya Shah,101,85.5,100,85.5,1,True,2026-06-22,...
...
```

**Example (analytics summary):**
```
Overall Summary
Total Students,Passed Students,Pass Percentage,Avg Percentage,Avg Marks
1250,1025,82.0,71.25,71.25

Top Subjects
Subject Name,Total,Passed,Pass %,Avg Marks
Company Law,120,105,87.5,78.4
...
```

**Use cases:** Download for reports, Excel import, or admin dashboards. Ties into the on-the-fly aggregates (no extra DB load beyond the annotated queries). Extendable to PDF/Excel via libraries like openpyxl (add to requirements if needed).

Update frontend to add export buttons calling this endpoint (e.g., with `type=analytics` for summary reports).

---

## Related Modules & Migrations (Updated)

**Integrations (per current `views.py`, `models.py`):**
- **`exams`**: `Exam` (requires `answer_key` for rechecks, now also used for subject/faculty/batch FKs in aggregates), `CheckerToken`, `calculate_ranks()`, `generate_checker_token()`, emails.
- **`timetable`**: `ExamSession` for auto-absent; timetable slots now drive many Exams used in analytics.
- **`students`**: Visibility, batch links for bulk recheck/analytics.
- **`payroll`**: `CheckerQuery` (open status excludes from `compute_payslip_for_user()`); new analytics do not affect payroll.
- **Core**: `_user_role()`, `apply_filters()`, `F()`/`ExpressionWrapper` patterns now used in analytics views.
- **No new models**: All subject/faculty/batch/summary aggregates computed live from `PublishedResult` (see `SubjectWiseResultView`, `ResultAnalyticsView` etc.).

**After pulling latest code, run:**
```bash
python manage.py makemigrations results
python manage.py migrate results
python manage.py migrate exams  # for any Exam FK updates
```

**Note on Code Style:** `results/views.py` now uses consistent role constants, organization guards, and annotation-based aggregation (no legacy model views). This documentation has been updated to reflect **all current endpoints**, removal of dedicated aggregate models, and the new on-the-fly analytics (matching style of `timetable_procedure_guide.md`).

This completes the results module reference.
