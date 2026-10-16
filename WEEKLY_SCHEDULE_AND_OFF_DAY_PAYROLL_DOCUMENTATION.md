# Weekly Schedule, Working Hours & Off-Day Payroll Documentation

## 1. Overview

This document details the day-wise **Weekly Schedule** system, auto-calculation of **Daily Working Hours**, the **`is_off` Flag**, and the corresponding **Payroll Zero-Deduction** logic implemented across `auth_user`, `attendance`, and `payroll`.

### Key Objectives
1. **Per-Day Shift Timings**: Define individual `start_time` and `end_time` for each day of the week (**Sunday through Saturday**).
2. **Auto-Calculated Working Hours per Day**: Automatically calculate each day's `working_hours` between `start_time` and `end_time` inside `weekly_schedule`.
3. **Single User-Level `working_hours`**: Preserve a single `working_hours` field on the `User` model representing the overall daily average across active (non-off) working days for backward compatibility.
4. **`is_off` Flag for All Days**: Every day (including Sunday and weekdays like Wednesday) can be marked as `is_off: true` or `false`.
5. **Sunday Shift Timings Support**: Sunday supports `start_time`, `end_time`, auto-calculated `working_hours`, and `is_off`.
6. **Payroll Zero-Deduction**: Days marked with `is_off: true` are treated as designated off days / paid leaves in payroll calculations:
   - **Zero absence deduction** (salary is **NOT deducted**).
   - Excluded from required working days (`working_days` and `working_days_passed`).
   - Excluded from `absent_dates` and `absent_days`.
   - Excluded from late / shortfall delay penalties.

---

## 2. Architecture & Data Model

### 2.1 User Model (`auth_user/models.py`)

Added a JSON field to the `User` model:

```python
weekly_schedule = models.JSONField(
    null=True, blank=True, default=dict,
    help_text="Day-wise schedule dict with start_time, end_time, working_hours, and is_off flag per day."
)
```

#### Helper Methods on `User`

| Method | Description |
|---|---|
| `user.get_shift_timings_for_date(target_date=None)` | Returns `(start_time, end_time)` as `datetime.time` objects for the date's day of the week from `weekly_schedule`. Falls back to `(user.work_start_time, user.work_end_time)`. Shift times on off days (e.g. Sunday) are preserved. |
| `user.get_working_hours_for_date(target_date=None)` | Returns `Decimal` required working hours for the date. Returns `Decimal('0.00')` if `user.is_day_off(target_date)` is `True`. Otherwise returns that day's scheduled hours or `user.working_hours`. |
| `user.is_day_off(target_date=None)` | Returns `True` if `is_off: true` is configured for that day in `weekly_schedule`. If `weekly_schedule` is not configured, defaults to Sunday being off (`weekday() == 6`). |
| `user.update_today_working_hours(save=True)` | Dynamically evaluates today's required working hours and updates `user.working_hours`. |

---

## 3. Weekly Schedule Structure & Calculation Logic

### 3.1 JSON Schedule Format

Each day's entry in `user.weekly_schedule` contains 4 standard attributes:

```json
{
  "sunday": {
    "start_time": "10:00:00",
    "end_time": "14:00:00",
    "working_hours": 4.0,
    "is_off": true
  },
  "monday": {
    "start_time": "10:00:00",
    "end_time": "19:00:00",
    "working_hours": 9.0,
    "is_off": false
  },
  "tuesday": {
    "start_time": "13:00:00",
    "end_time": "19:00:00",
    "working_hours": 6.0,
    "is_off": false
  },
  "wednesday": {
    "start_time": "10:00:00",
    "end_time": "19:00:00",
    "working_hours": 9.0,
    "is_off": true
  },
  "thursday": {
    "start_time": "10:00:00",
    "end_time": "19:00:00",
    "working_hours": 9.0,
    "is_off": false
  },
  "friday": {
    "start_time": "10:00:00",
    "end_time": "19:00:00",
    "working_hours": 9.0,
    "is_off": false
  },
  "saturday": {
    "start_time": "10:00:00",
    "end_time": "19:00:00",
    "working_hours": 9.0,
    "is_off": false
  }
}
```

### 3.2 Processing Routine (`auth_user/utils.py:process_weekly_schedule`)

The `process_weekly_schedule(schedule_data)` utility:
1. **Normalizes Day Keys**: Accepts day names or integer weekday indices (e.g. `'monday'`, `'Monday'`, `'MON'`, `0`).
2. **Safe Boolean Parsing**: Parses `is_off` values from JSON booleans or form strings (`"true"`, `"false"`, `"1"`, `"0"`, `"yes"`, `"t"`).
3. **Auto-Calculates Daily Working Hours**:
   - If `start_time` and `end_time` are provided, computes:
     $$\text{Daily Working Hours} = \frac{\text{end\_time} - \text{start\_time}}{3600}$$
     (handles midnight-crossing shifts automatically).
   - If explicit `working_hours` is sent, that value is preserved.
   - If marked `is_off: true`, the day's scheduled shift duration is still stored in `weekly_schedule[day]['working_hours']` for reference.
4. **Averages Non-Off Days for User.working_hours**:
   - Averages all active working days (`is_off: false` and `working_hours > 0`):
     $$\text{User.working\_hours} = \frac{\sum \text{Active Daily Hours}}{\text{Total Active Days}}$$
   - Off days (`is_off: true`) do **not** dilute the active daily average.

---

## 4. Payroll Zero-Deduction Logic (`payroll/utils.py`)

When calculating monthly payroll for an employee with `weekly_schedule`:

### 4.1 Required Working Days Count
Instead of hardcoding Monday–Friday (`weekday < 5`), the system evaluates:
```python
working_days = sum(
    1 for d in range(1, calendar.monthrange(year, month)[1] + 1)
    if not user.is_day_off(date(year, month, d))
)
```

### 4.2 Passed Working Days (`working_days_passed`)
Days marked with `is_off: true` are excluded from `working_days_passed`:
```python
working_days_passed = sum(
    1 for d in range(1, last_day + 1)
    if not user.is_day_off(date(year, month, d))
)
```

### 4.3 Absence Loop & Deductions
In both faculty (`compute_payslip_for_faculty`, `preview_payslip_for_faculty`) and non-faculty (`compute_payslip_for_user`):
```python
is_off_day = user.is_day_off(curr_date)
if is_off_day:
    continue  # Scheduled off day: NOT counted as absent, NO salary deduction!
```
- Because off days are excluded from both `working_days_passed` and `absent_dates`, `absent_days` evaluates to `0`.
- **`absence_deductions = Decimal('0.00')`**.
- Full basic salary is retained with **zero deduction** for off days.

### 4.4 Shortfall & Delay Penalties
```python
for d_date, d_delay in daily_delays.items():
    if has_custom_sched and user.is_day_off(d_date):
        continue  # Scheduled off day: no shortfall deduction or penalty
```

---

## 5. API Usage & Request Payloads

### 5.1 Endpoints
- **Create User**: `POST /api/user/add/`
- **Update User**: `PUT /api/user/update/<uuid:user_id>/`
- **Partial Update**: `PATCH /api/user/update/<uuid:user_id>/`
- **Get User Profile**: `GET /api/user/profile/` or `GET /api/user/<uuid:user_id>/`
- **List Users**: `GET /api/user/list/`

---

### 5.2 Payload Formats

#### Option A: Nested JSON Object (`weekly_schedule`)
Recommended for JSON requests:

```json
{
  "email": "employee@example.com",
  "name": "Jane Doe",
  "phone": "9876543210",
  "role": "admin_executive",
  "branch": "4b6efb40-7e3e-4b7f-8561-2f31b816bbde",
  "employment_type": "full_time",
  "salary": 35000.00,
  "weekly_schedule": {
    "sunday": {
      "start_time": "10:00:00",
      "end_time": "14:00:00",
      "is_off": true
    },
    "monday": {
      "start_time": "10:00:00",
      "end_time": "19:00:00",
      "is_off": false
    },
    "tuesday": {
      "start_time": "10:00:00",
      "end_time": "19:00:00",
      "is_off": false
    },
    "wednesday": {
      "start_time": "10:00:00",
      "end_time": "19:00:00",
      "is_off": true
    },
    "thursday": {
      "start_time": "10:00:00",
      "end_time": "19:00:00",
      "is_off": false
    },
    "friday": {
      "start_time": "10:00:00",
      "end_time": "19:00:00",
      "is_off": false
    },
    "saturday": {
      "start_time": "10:00:00",
      "end_time": "16:00:00",
      "is_off": false
    }
  }
}
```

#### Option B: Flat Form-Data / Multipart Fields
Supported in `multipart/form-data` and standard form posts:

```
email: employee@example.com
name: Jane Doe
phone: 9876543210
role: admin_executive
branch: 4b6efb40-7e3e-4b7f-8561-2f31b816bbde
sunday_start_time: 10:00:00
sunday_end_time: 14:00:00
sunday_is_off: true
monday_start_time: 10:00:00
monday_end_time: 19:00:00
monday_is_off: false
wednesday_start_time: 10:00:00
wednesday_end_time: 19:00:00
wednesday_is_off: true
```

The serializer automatically merges flat day fields into `weekly_schedule`.

---

### 5.3 Response Format

```json
{
  "message": "User created successfully. Password setup email sent.",
  "user_id": "1c7d23d8-e7bb-4b68-9842-c51d655fbe90",
  "working_hours": "8.50",
  "weekly_schedule": {
    "sunday": {
      "start_time": "10:00:00",
      "end_time": "14:00:00",
      "working_hours": 4.0,
      "is_off": true
    },
    "monday": {
      "start_time": "10:00:00",
      "end_time": "19:00:00",
      "working_hours": 9.0,
      "is_off": false
    },
    "tuesday": {
      "start_time": "10:00:00",
      "end_time": "19:00:00",
      "working_hours": 9.0,
      "is_off": false
    },
    "wednesday": {
      "start_time": "10:00:00",
      "end_time": "19:00:00",
      "working_hours": 9.0,
      "is_off": true
    },
    "thursday": {
      "start_time": "10:00:00",
      "end_time": "19:00:00",
      "working_hours": 9.0,
      "is_off": false
    },
    "friday": {
      "start_time": "10:00:00",
      "end_time": "19:00:00",
      "working_hours": 9.0,
      "is_off": false
    },
    "saturday": {
      "start_time": "10:00:00",
      "end_time": "16:00:00",
      "working_hours": 6.0,
      "is_off": false
    }
  },
  "branch": "4b6efb40-7e3e-4b7f-8561-2f31b816bbde",
  "branches": ["4b6efb40-7e3e-4b7f-8561-2f31b816bbde"]
}
```

---

## 6. Attendance & QR Scan Log Integration

### 6.1 Dynamic Timings for QR Check-ins
In [attendance/views.py](file:///d:/Insight/attendance/views.py):
- Check-in and check-out logs inspect the faculty/user's day-specific shift timings using `user.get_shift_timings_for_date(today)`.
- If an employee checks in on a Sunday that has `10:00` to `14:00`, early/late calculations compare against that Sunday shift.

### 6.2 Shortfall Threshold Evaluation
In [attendance/utils.py](file:///d:/Insight/attendance/utils.py):
- `check_half_day_shortfall` checks actual worked minutes against `user.get_working_hours_for_date(record.date)`.
- If the day was an off day (`is_off: true`), required working hours is `0.00` and no shortfall penalty is triggered.

---

## 7. Automated Test Suite

Targeted unit tests in [auth_user/tests.py](file:///d:/Insight/auth_user/tests.py):

| Test Method | Coverage |
|---|---|
| `test_sunday_start_and_end_time_with_is_off_and_working_hours` | Verifies Sunday timings, auto-calculation of Sunday's `working_hours`, `is_off: True`, and preservation of shift timings. |
| `test_payroll_zero_deduction_for_custom_off_days` | Verifies that days with `is_off: True` (Wednesday and Sunday) result in `0` absence deductions and preserve full basic salary. |
| `test_process_weekly_schedule_auto_calculates_each_day` | Verifies normalization and daily `working_hours` calculation across multiple days. |
| `test_user_get_working_hours_for_date` | Verifies date resolution for Monday, Tuesday, Wednesday, and Sunday. |
| `test_add_user_with_weekly_schedule_calculates_daily_and_average_working_hours` | Verifies user creation with nested JSON schedule and overall `working_hours` average. |
| `test_add_user_with_flat_day_fields` | Verifies flat form field parsing (`monday_start_time`, `tuesday_end_time`, etc.). |
| `test_add_user_api_endpoint_with_weekly_schedule` | Verifies REST API `POST /api/user/add/` response containing `weekly_schedule` and `working_hours`. |

### Running the Tests
```powershell
$env:PYTHONIOENCODING="utf-8"
python manage.py test auth_user.tests.AuthUserAPITestCase.test_sunday_start_and_end_time_with_is_off_and_working_hours auth_user.tests.AuthUserAPITestCase.test_payroll_zero_deduction_for_custom_off_days auth_user.tests.AuthUserAPITestCase.test_process_weekly_schedule_auto_calculates_each_day auth_user.tests.AuthUserAPITestCase.test_user_get_working_hours_for_date auth_user.tests.AuthUserAPITestCase.test_add_user_with_weekly_schedule_calculates_daily_and_average_working_hours auth_user.tests.AuthUserAPITestCase.test_add_user_with_flat_day_fields auth_user.tests.AuthUserAPITestCase.test_add_user_api_endpoint_with_weekly_schedule
```
Result: **`Ran 7 tests in 4.332s — OK`**.
