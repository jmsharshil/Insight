# Results Module — Full API Reference & Walkthrough Guide

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>` (most endpoints; checker portal uses token param)  
> **Content-Type:** `application/json`  
> All responses wrapped in `{ "success": true/false, "message": "...", "data": {...} }`.  
> Role-based permissions enforced (super_admin, paper_checker, admin_senior_executive, branch_manager, student).

---

## Architecture & Workflow Diagram

```
                              ┌─────────────────────────────┐
                              │      Exam Published         │ (from timetable/exams)
                              └──────────────┬──────────────┘
                                             │
                                             ▼
                              ┌─────────────────────────────┐
                              │   Paper Allocation (Checker) │
                              └──────────────┬──────────────┘
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       ▼                                           ▼
             Checker Portal (token)                       Web Portal (marks entry)
                       │                                           │
                       ▼                                           ▼
             POST /checker-portal/submit/             PATCH /papers/<id>/marks/
                       │                                           │
                       └───────────────────┬─────────────────────┘
                                           ▼
                            ┌─────────────────────────────┐
                            │   All Marks Submitted?      │
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
                                             ▼
                              ┌─────────────────────────────┐
                              │  Student Recheck Request    │ (v2 FRD §4.6.2)
                              └─────────────────────────────┘
                                             │
                                             ▼
                              ASE Review → Approve → Re-assign Checker → Re-grade
```

---

## Appendix A: System Choice Values & Statuses

### A.1 Recheck Statuses (`status`)
| Value | Display | Notes |
| :--- | :--- | :--- |
| `approval_pending` | Approval Pending | Initial student request |
| `approved` | Approved | ASE approved, new checker assigned |
| `rejected` | Rejected | ASE rejected request |
| `completed` | Completed | Recheck grading finished |

### A.2 MarkSheet Flags
- `is_submitted`: True after checker submits marks (blocks re-entry).
- `is_rechecked`: Set on recheck approval.
- `is_pass`: Computed as `marks_obtained >= exam.pass_marks`.

### A.3 Role Permissions Summary
| Role | Can View Papers | Enter Marks | Publish Results | Review Recheck | Student Recheck |
|------|-----------------|-------------|-----------------|----------------|-----------------|
| super_admin | Yes | Yes | Yes | Yes | N/A |
| admin_senior_executive | Yes | Yes | Yes | Yes | N/A |
| paper_checker | Assigned only | Yes (own) | No | No | N/A |
| branch_manager | Yes (status) | No | Yes | Yes | N/A |
| student | Own results | No | No | No | Yes |

---

## Data Models Summary

| Model | Purpose | Key Behaviors |
|-------|---------|---------------|
| `MarkSheet` | Per-student per-exam grading record | Linked to Exam + Student; tracks checker, marks, submission, recheck flags; auto `is_pass` |
| `PublishedResult` | Final official result (immutable after publish) | Computed rank via `calculate_ranks()`; unique per (exam, student) |
| `RecheckRequest` | Student-initiated re-evaluation (v2) | Status lifecycle; links to new_checker on approval; triggers token + email |
| `SubmissionReminderLog` | Audit for checker reminders | Tracks follow-ups for unsubmitted papers |

**Integration:** Closely tied to `exams` (Exam model, CheckerToken, emails), `timetable` (via SessionReport indirectly), `students` (for student details).

---

## Key Workflows & Steps

### 1. Post-Exam Paper Checking
1. Exam completed (from timetable `prelim`/`class_test` or custom).
2. Auto or manual allocation of papers to `paper_checker` users (via CheckerToken for portal).
3. Checkers use either web (`/papers/<id>/marks/`) or secure portal (`/checker-portal/submit/?token=...`).
4. All papers must be `is_submitted=True` before publish allowed.

### 2. Publishing Results
1. Admin/ASE calls `POST /results/publish/` — validates all submitted, creates `PublishedResult` records, calculates ranks, updates Exam status.
2. Students can view via `GET /results/`.
3. Top scorer highlighted in response.

### 3. Recheck Request (v2 — FRD §4.6.2)
1. Student (after results published) POSTs recheck request with reason.
2. ASE reviews (`GET /recheck-requests/`, PATCH action).
3. On approve: reassigns to new_checker, resets `is_submitted=False`, generates new token, sends email.
4. New marks update PublishedResult if exists.
5. Statuses audited; prevents duplicate pending requests.

### 4. Checker Portal Flow
- Token generated on allocation/recheck (expires, one-use).
- Portal submits marks → marksheet updated, token marked used.
- Exempt from auth but validated via token.

**Safety Rules:**
- Role guards everywhere.
- Cannot submit marks > total_marks or after submitted.
- Publish blocked if any pending papers.
- Recheck only after results published; no duplicate pending requests.

---

## Complete API Reference

### 1. Paper List & Marks Entry

**`GET /api/v1/exams/<exam_id>/papers/`**

#### Query Params
- `is_submitted`, `is_pass`, `is_rechecked`, search on student name/checker.

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
      "remarks": "Good attempt on theory",
      "checked_at": "2026-06-20T14:30:00Z",
      "is_submitted": true,
      "is_rechecked": false
    }
  ]
}
```

**`POST /api/v1/exams/<exam_id>/papers/<marksheet_id>/marks/`** (or PUT for update/recheck)

#### Request Body
```json
{
  "marks_obtained": 78.0,
  "remarks": "Excellent performance on case studies"
}
```

#### Success Response (201/200)
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

#### Error Examples
- 400 Invalid marks: `{"success": false, "message": "Invalid marks."}`
- 403 Not assigned: `{"success": false, "message": "Not assigned to you."}`
- 400 Already submitted: `{"success": false, "message": "Already submitted."}`

**DELETE** `/api/v1/exams/<exam_id>/papers/<marksheet_id>/` (super_admin only) — removes marksheet.

---

### 2. Checker Status & Portal

**`GET /api/v1/exams/<exam_id>/checker-status/`**

#### Response (200 OK)
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

**`POST /api/v1/checker-portal/submit/?token=secure-token-here`** (AllowAny, token-based)

#### Request Body
```json
{
  "marks_obtained": 85.5,
  "remarks": "Strong conceptual clarity"
}
```

#### Success Response
```json
{
  "success": true,
  "message": "Marks submitted successfully."
}
```

**Errors:** Invalid/expired token → 403 with specific message.

---

### 3. Publish & View Results

**`POST /api/v1/exams/<exam_id>/results/publish/`** (Admin/ASE/BranchManager)

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
- 400 Not all submitted: `{"success": false, "message": "Not all marksheets submitted."}`
- 400 Already published.

**`GET /api/v1/exams/<exam_id>/results/`**

Supports filters (`is_pass`), search on student name. Student/parent roles see only own.

#### Response Example
```json
{
  "success": true,
  "count": 1,
  "data": [
    {
      "id": "pr-uuid-001",
      "exam": "exam-uuid",
      "student_name": "Priya Shah",
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

**`DELETE /api/v1/exams/<exam_id>/results/<result_id>/`** — Unpublishes (admin only). Returns success message.

---

### 4. Recheck Requests (v2)

**`POST /api/v1/exams/<exam_id>/results/recheck-request/`** (Student only, after results published)

#### Request Body
```json
{
  "reason": "Discrepancy in practical marks. Requesting re-evaluation."
}
```

#### Success Response (201)
```json
{
  "recheck_requested": true,
  "status": "approval_pending",
  "message": "Your recheck request has been submitted for review."
}
```

**Errors:**
- 403 Only students.
- 400 No published result or already has pending recheck (409 Conflict).

**`GET /api/v1/exams/<exam_id>/recheck-requests/`** (ASE/Manager)

Supports filter by `status`, search on student name.

**`PATCH /api/v1/exams/<exam_id>/recheck-requests/<request_id>/`**

#### Request Body (approve example)
```json
{
  "action": "approve",
  "new_checker_id": "user-uuid-for-new-checker"
}
```

#### Request Body (reject)
```json
{
  "action": "reject"
}
```

#### Success Responses
- Approve: `{"success": true, "message": "Recheck approved and reassigned to new checker."}`
- Reject: `{"success": true, "message": "Recheck request rejected."}`

**Legacy recheck endpoint** (`POST /papers/<marksheet_id>/recheck/`) still supported for direct admin reassignment.

---

## Common Error Responses

### 403 Permission Denied
```json
{
  "success": false,
  "message": "Permission denied."
}
```

### 400 Validation / Business Rule
```json
{
  "success": false,
  "message": "Not all marksheets submitted.",
  "errors": { ... }
}
```

### 409 Conflict (duplicate recheck)
```json
{
  "success": false,
  "message": "A recheck request is already pending or approved."
}
```

### 404 Not Found
Standard for missing exam/marksheet/request.

---

## SECTION — Related Modules & Migrations

**Integrations:**
- `exams`: Uses `Exam`, `CheckerToken`, `calculate_ranks()`, emails for assignment/notification.
- `timetable`: Source of exams via session_type=class_test/prelim.
- `students`: Links to Student for names, results visibility (student/parent roles filter).
- `faculty`: Paper checkers are users with paper_checker role.

**After code updates, run:**
```bash
python manage.py migrate results
```

This guide fully documents the current implementation including v2 recheck flow (FRD §4.6.2), role guards, token-based portal, rank calculation, and cross-module ties. Matches style of `timetable_procedure_guide.md`, `faculty_module_api_documentation.md`, and `fees_module_api_documentation.md`.
