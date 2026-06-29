# Audit Log Module API Documentation

## Overview

The Audit Log module **automatically records every API request** made to the system through Django middleware — no manual calls are required from views. Each entry captures who did what, when, and from where. Logs are stored in the database and optionally flushed to Azure Blob Storage for long-term archival.

---

## AuditLog Record Structure

Every log entry contains the following fields:

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Unique identifier |
| `user` | UUID | FK to the user who made the request (null if anonymous) |
| `user_email` | string | Email of the user |
| `user_name` | string | Display name of the user |
| `user_role` | string | Role of the user (e.g., `admin`, `faculty`, `student`) |
| `organization` | UUID | FK to the user's organization |
| `organization_name` | string | Name of the organization |
| `action` | string | High-level action: `CREATE`, `READ`, `UPDATE`, `DELETE`, `LOGIN`, `LOGOUT`, `OTHER` |
| `event` | string | **Human-readable event** based on the API called (e.g., `"Student started exam"`) |
| `method` | string | HTTP method: `GET`, `POST`, `PATCH`, `PUT`, `DELETE` |
| `path` | string | Full request path (e.g., `/api/v1/exams/{id}/start/`) |
| `endpoint_name` | string | DRF view name (e.g., `exam-start`) |
| `status_code` | integer | HTTP response status code |
| `query_params` | string | Query string from the URL |
| `request_body` | string | Sanitized request body (passwords/tokens redacted) |
| `response_summary` | string | Top-level keys + types from the response |
| `ip_address` | string | Client IP address |
| `user_agent` | string | Browser/client user agent |
| `target_model` | string | The affected model (e.g., `exams.Exam`) |
| `target_id` | string | PK of the affected object |
| `timestamp` | datetime | When the request occurred |
| `flushed_to_blob` | boolean | Whether the entry has been synced to blob storage |

### Event Field Examples

The `event` field is automatically resolved from the API path and HTTP method:

| API Endpoint | Method | `event` |
|---|---|---|
| `/api/v1/accounts/login/` | POST | `User logged in` |
| `/api/v1/accounts/logout/` | POST | `User logged out` |
| `/api/v1/exams/` | POST | `Exam created` |
| `/api/v1/exams/{id}/start/` | POST | `Student started exam` |
| `/api/v1/exams/{id}/submit/` | POST | `Student submitted exam` |
| `/api/v1/exams/{id}/papers/` | POST | `Exam paper uploaded` |
| `/api/v1/exams/{id}/papers/` | GET | `Exam papers fetched` |
| `/api/v1/exams/{id}/malpractice/` | POST | `Malpractice report created` |
| `/api/v1/exams/{id}/answer-key/distribute/` | POST | `Answer key distributed to checkers` |
| `/api/v1/exams/{id}/seating/` | POST | `Seating arrangement set` |
| `/api/v1/attendance/` | POST | `Attendance marked` |
| `/api/v1/students/` | POST | `Student created` |
| `/api/v1/faculty/` | GET | `Faculty list fetched` |
| `/api/v1/fees/` | POST | `Fee record created` |
| `/api/v1/leave/` | POST | `Leave request submitted` |
| `/api/v1/inventory/` | DELETE | `Inventory item deleted` |
| `/api/v1/reports/` | GET | `Report generated` |

---

## API Endpoints

### 1. List Audit Logs
- **Endpoint**: `/api/audit-logs/`
- **Method**: `GET`
- **Description**: List audit log entries with optional filters.
- **Query Parameters**:
  - `user_id`: Filter by user UUID.
  - `organization_id`: Filter by organization UUID.
  - `action`: Filter by action — `CREATE`, `READ`, `UPDATE`, `DELETE`, `LOGIN`, `LOGOUT`, `OTHER`.
  - `event`: Partial/case-insensitive match on the human-readable event string.
  - `method`: Filter by HTTP method (e.g., `GET`, `POST`).
  - `path`: Substring match on request path.
  - `status_code`: Filter by HTTP status code.
  - `date_from`: Start timestamp for filtering (`YYYY-MM-DDTHH:MM:SSZ`).
  - `date_to`: End timestamp for filtering.
  - `flushed_to_blob`: `true` / `false`.
- **Response**:
  ```json
  [
      {
          "id": "uuid",
          "user": "uuid",
          "user_email": "user@example.com",
          "user_name": "Harshil Shah",
          "user_role": "admin",
          "organization": "uuid",
          "organization_name": "JMS Institute",
          "action": "CREATE",
          "event": "Student started exam",
          "method": "POST",
          "path": "/api/v1/exams/abc123/start/",
          "endpoint_name": "exam-start",
          "status_code": 200,
          "query_params": "",
          "request_body": "{\"student_lat\": 19.076090, \"student_lon\": 72.877426}",
          "response_summary": "{\"session_id\": \"str\", \"remaining_seconds\": \"int\"}",
          "ip_address": "122.170.55.74",
          "user_agent": "Mozilla/5.0 ...",
          "target_model": "",
          "target_id": "",
          "timestamp": "2026-06-28T10:00:00Z",
          "flushed_to_blob": true
      }
  ]
  ```

---

### 2. Retrieve Audit Log Entry
- **Endpoint**: `/api/audit-logs/{uuid}/`
- **Method**: `GET`
- **Description**: Retrieve a single audit log entry by its ID.
- **Response**: Same structure as an item in the List response above.

---

### 3. Manually Trigger Blob Flush
- **Endpoint**: `/api/audit-logs/flush/`
- **Method**: `POST`
- **Description**: Admin-only. Manually triggers a background flush of all un-synced logs to Azure Blob Storage.
- **Request Body**: None
- **Response**:
  - **202 Accepted**:
    ```json
    { "detail": "Flush scheduled successfully in background." }
    ```
  - **403 Forbidden**:
    ```json
    { "detail": "Admin access required to trigger flush." }
    ```

---

### 4. Get Audit Logs by User (Blob)
- **Endpoint**: `/api/audit-logs/by-user/`
- **Method**: `GET`
- **Description**: Download the raw daily log file for a specific user from Azure Blob Storage.
- **Query Parameters**:
  - `user_name` *(required)*: Display name of the user.
  - `date` *(required)*: Date in `YYYY-MM-DD` format.
  - `organization_name` *(optional)*: Defaults to the requester's organization.
- **Response**:
  - **200 OK**: Returns the log file as a downloadable text file.
  - **400 Bad Request**:
    ```json
    { "detail": "user_name and date query parameters are required." }
    ```
  - **404 Not Found**:
    ```json
    { "detail": "No log file found for the given parameters." }
    ```

---

## How It Works

All logging is handled automatically by `AuditLogMiddleware` in `auditlog/middleware.py`. You do not need to add any logging code to views.

- **What is logged**: All requests to `/api/*` paths, except excluded paths (`/admin/`, `/static/`, etc.).
- **Sensitive data**: `password`, `pin`, `token`, `refresh`, `access`, `authorization`, `secret` fields in request bodies are automatically **redacted** before saving.
- **Event resolution**: The `event` field is derived from `_EVENT_RULES` in `middleware.py` — a priority-ordered list of `(url_fragment, http_method, description)` tuples. To add new event mappings, extend `_EVENT_RULES`.
- **Blob sync**: Each log entry is immediately uploaded to Azure Blob Storage (organized by `organization/user/date`). If the upload fails, the entry stays in the DB with `flushed_to_blob=False` for a later retry.
