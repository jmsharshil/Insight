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

## Complete API Reference (Matches Current `results/views.py`)

### 1. Paper List, Marks Entry & Absent Marking

**`GET /api/v1/exams/<exam_id>/papers/`** (`PaperView`)

#### Query Params
- `is_submitted`, `is_pass`, `is_rechecked`, `is_absent`; search on `student__user__name`, `paper_checker__name`.

#### Response (200 OK)
```json
{
  "success": true,
  "count": 45,
  "data": [
    {
      "id": "ms-uuid-001",
      "exam": "exam-uuid",
      "student": "stu-uuid-001",
      "student_name": "Priya Shah",
      "paper_checker": "user-uuid",
      "paper_checker_name": "Prof. Anil Sharma",
      "marks_obtained": 42.5,
      "is_pass": true,
      "is_absent": false,
      "remarks": "Good attempt on theory",
      "checked_at": "2026-06-20T14:30:00Z",
      "is_submitted": true,
      "is_rechecked": false,
      "queries": []
    }
  ]
}
```

**`POST/PUT /api/v1/exams/<exam_id>/papers/<marksheet_id>/marks/`** (`PaperMarksView`)

- **POST**: Initial submission (blocks if already `is_submitted`).
- **PUT**: Update/recheck (handles `RecheckRequest` completion, updates `PublishedResult`, accepts `notes`).

#### Request Body
```json
{
  "marks_obtained": 78.0,
  "remarks": "Excellent performance on case studies",
  "notes": "Recheck notes here (for PUT)"
}
```

#### Success Response
```json
{
  "success": true,
  "message": "Marks submitted.",
  "data": {
    "marksheet_id": "ms-uuid-001",
    "marks_obtained": 78.0
  }
}
```

**Errors:**
- 403: Permission denied, not assigned, or **open query** (`has_open_query: true`).
- 400: Invalid marks range or already submitted (POST).
- Uses `_get_marksheet()` helper with organization/role guards.

**`POST /api/v1/exams/<exam_id>/papers/<marksheet_id>/mark-absent/`** (`MarkAbsentView`)
- Marks student absent (`is_absent=True`, `marks=0`, `submitted=True`).
- Allowed for admins, ASE, branch_manager, paper_checker.

**`POST /api/v1/exams/<exam_id>/mark-absent-all/`** (`MarkAllAbsentView`)
- Bulk: Uses `ExamSession` to mark all non-attendees as absent. Returns count.

**`DELETE /api/v1/exams/<exam_id>/papers/<marksheet_id>/`** (super_admin/ASE only) — removes marksheet.

---

### 2. Checker Status, Portal & Queries

**`GET /api/v1/exams/<exam_id>/checker-status/`** (`CheckerStatusView`)
- Returns totals, per-checker stats (assigned/submitted/pending counts, last_activity).
- Restricted to CHECKER_STATUS_ROLES.

**`POST /api/v1/checker-portal/submit/?token=...`** (`CheckerPortalSubmitView`, `AllowAny`)
- Token validation (exists, not used, not expired).
- Updates MarkSheet, marks token used.
- Simple success: `{"success": true, "message": "Marks submitted successfully."}`

**Paper Checker Query Endpoints** (`PaperCheckerQueryView`):

**`POST /api/v1/exams/<exam_id>/papers/<marksheet_id>/query/`**
```json
{
  "query_type": "answer_key_not_available",
  "description": "Answer key PDF missing for Q3."
}
```
- Only after recheck for paper_checkers. Creates open query, affects payroll.
- Response includes query details.

**`PATCH /api/v1/exams/<exam_id>/queries/<query_id>/resolve/`**
- Admin/ASE only. Can include `marks_obtained` to auto-submit.
- Sets `status=resolved`, updates payroll eligibility.

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

### 403 Permission Denied / Role or Assignment Issues
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

### 400 Validation / Business Rules
```json
{
  "success": false,
  "message": "Not all marksheets submitted.",
  "errors": { ... }
}
```
- "Invalid marks.", "Already submitted.", "Answer key has not been uploaded yet. Recheck not allowed."
- "This marksheet has an open query. Please resolve the query first."

### 409 Conflict (duplicate recheck)
```json
{
  "success": false,
  "message": "A recheck request is already pending or approved."
}
```

### Other Common
- 403 Token expired/used/invalid (portal).
- 404 for missing Exam, MarkSheet, RecheckRequest, Query.

---

## Related Modules & Migrations (Updated)

**Integrations (per current `views.py`, `models.py`):**
- **`exams`**: `Exam` (requires `answer_key` for rechecks), `CheckerToken`, `calculate_ranks()`, `generate_checker_token()`, emails (`send_checker_assignment_email`, `send_recheck_request_notification`).
- **`timetable`**: `ExamSession` used for auto-absent marking logic.
- **`students`**: Student profiles, linked_parents for visibility, batch for bulk operations.
- **`payroll`**: `CheckerQuery` integrates with `compute_payslip_for_user()` to exclude papers with open queries on rechecks.
- **Core**: Consistent `_user_role()`, organization filtering, `apply_filters()`, pagination patterns (mirrors `attendance/views.py` updates).

**After code/model updates, run:**
```bash
python manage.py makemigrations results
python manage.py migrate results
```

**Note on Code Style:** The `results/views.py` has been updated to match the robust, consistent patterns from `attendance/views.py` (role constants at top, helper functions, detailed permission/organization guards in every method, comprehensive error handling, support for new FRD features like queries and bulk operations). The documentation now fully reflects the **updated code**.

This guide matches the style and depth of other module docs (`timetable_procedure_guide.md`, `faculty_module_api_documentation.md`, `fees_module_api_documentation.md`).
