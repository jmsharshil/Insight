# Results Module — API Documentation

The `results` module manages post-exam operations, including paper allocation to checkers, marks entry, publishing final results, and handling student recheck requests.

---

## Data Model

| Model | Purpose |
|---|---|
| `CheckerAllocation` | Assigns an exam to specific faculty members to grade papers |
| `StudentMarksheet` | Represents one student's attempt at an exam |
| `ExamResult` | The final published result for a student on a given exam |
| `RecheckRequest` | A student's formal request to have their paper re-evaluated |

---

## API Endpoints

### 1. Papers and Marks
**`GET /api/v1/exams/<exam_id>/papers/`**
List all submitted papers / marksheets for a specific exam.

**`PATCH /api/v1/exams/<exam_id>/papers/<marksheet_id>/marks/`**
Enter or update marks for a specific student's paper.

### 2. Checking Status & Submission
**`GET /api/v1/exams/<exam_id>/checker-status/`**
Check the progress of paper checking for a given exam.

**`POST /api/v1/checker-portal/submit/`**
Submit the finalized paper grades via the external checker portal. (Note: Exempt from JWT authentication but uses a secure token).

### 3. Results Management
**`POST /api/v1/exams/<exam_id>/results/publish/`**
Finalize marks and officially publish results. Generates `ExamResult` records.

**`GET /api/v1/exams/<exam_id>/results/`**
List all published results for an exam.

**`DELETE /api/v1/exams/<exam_id>/results/<result_id>/`**
Delete a specific published result.

### 4. Recheck Workflow
**`POST /api/v1/exams/<exam_id>/papers/<marksheet_id>/recheck/`**
(Legacy endpoint for triggering a paper recheck)

**`POST /api/v1/exams/<exam_id>/results/recheck-request/`**
Allows a student to formally submit a recheck request for their published result.

**`GET /api/v1/exams/<exam_id>/recheck-requests/`**
List all recheck requests for an exam (for admin/faculty).

**`POST /api/v1/exams/<exam_id>/recheck-requests/<request_id>/`**
Approve, reject, or mark a recheck request as resolved.
