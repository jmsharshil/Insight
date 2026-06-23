# Faculty Module — API Documentation

The `faculty` module manages faculty profiles, hourly rates by subject, and the recording of conducted sessions.

---

## Data Model

| Model | Purpose |
|---|---|
| `FacultyProfile` | Core profile for teachers. Includes `work_start_time` and `work_end_time` for shift scheduling |
| `SubjectHourlyRate` | Defines how much a faculty is paid per hour for a specific subject |
| `SessionReport` | Logs each class/session conducted by the faculty for payroll |

### FacultyProfile — Key Fields

| Field | Type | Description |
|---|---|---|
| `work_start_time` | `TimeField` (nullable) | Shift start time, e.g. `09:00`. Used for late-entry detection and attendance checks |
| `work_end_time` | `TimeField` (nullable) | Shift end time, e.g. `17:00`. Used to detect early checkout |

These fields are returned in both the **list** (`GET /api/v1/faculty/`) and **detail** (`GET /api/v1/faculty/<uuid>/`) responses, and can be set via `PATCH /api/v1/faculty/<uuid>/`.

---

## API Endpoints

### 1. List & Create Faculty
**`GET /api/v1/faculty/`**
**`POST /api/v1/faculty/`**

### 2. Faculty Detail
**`GET /api/v1/faculty/<uuid>/`**
**`PATCH /api/v1/faculty/<uuid>/`**
**`DELETE /api/v1/faculty/<uuid>/`**

### 3. Faculty QR / Identity
**`GET /api/v1/faculty/<uuid>/qr-id/`**
**`POST /api/v1/faculty/qr-checkin/`**
Allows faculty to scan a QR code to check in and check out. 
- During `check_in`, it logs the faculty entry and automatically calculates late penalties if applicable.
- During `check_out`, it accepts an optional array of `session_reports` in the payload (containing chapters covered, completion status, topics) to automatically generate Session Report records for payroll computation. It also calculates early checkout penalties if the faculty leaves before their scheduled classes end.

### 4. Subject Hourly Rates
**`GET /api/v1/faculty/<uuid>/subject-rates/`**
**`POST /api/v1/faculty/<uuid>/subject-rates/`**
**`GET / PATCH / DELETE /api/v1/faculty/<uuid>/subject-rates/<rate_id>/`**
Configure pay rates for different subjects taught by the faculty.

### 5. Faculty Sessions
**`GET /api/v1/faculty/sessions/`**
**`POST /api/v1/faculty/sessions/`**
Log a completed teaching session. Required for hour-based payroll processing.

**`GET /api/v1/faculty/sessions/summary/`**
Provides an aggregate summary of sessions conducted, filtered by month.

**`GET /api/v1/faculty/sessions/<session_id>/`**
**`GET /api/v1/faculty/<uuid>/sessions/`** (all sessions for a specific faculty)
