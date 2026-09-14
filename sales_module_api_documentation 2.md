# Sales Module — Field Activity, Inventory & Notification APIs

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `multipart/form-data` (for activity photo uploads) / `application/json`  
> **Sales Roles:** `sales_senior_executive`, `sales_executive`, `tele_caller`  
> **Managerial Roles:** `branch_manager`, `super_admin`  
> **Standard Response Envelope:** `{ "success": true/false, "message": "...", "data": {...} }` or DRF object payloads  

---

## Overview

This guide documents the **Sales User APIs** introduced starting from the Notification Types architectural update (`b759ee1`) through the Additional Roles & Field Tracking release (`4d7e89a`).

The sales suite covers **eight** core operational capabilities (updated to match current `leads/views.py` + `inventory/views.py`):
1. **Sales Daily Plan & Scheduled Events** (`SalesDailyPlan`): Dual-purpose parent model for daily plans (`description`, itinerary) **and** scheduled events (`type`, `start_time`, `end_time`, `place`, reminder flags). Nests all child activities.
2. **Sales Daily Field Activity & GPS Tracking**: `SalesDailyActivity` container with auto-linked plan. Supports notes and verification photos.
3. **Sales Activity Photos** (`SalesActivityPhotoView`): Geo-tagged uploads (`start_selfie`/`end_selfie` auto-create `EmployeeAttendanceRecord` with GPS/shortfall/location_verified=False; odometer photos auto-sync `OdometerReading`; max 6 exhibition photos). Responses may include `"attendance"` key.
4. **Odometer Reading & Approval**: Vehicle-aware (`vehicle_type`: 2_wheeler=5/km default, 4_wheeler=12/km via `calculate_totals(override_expense_per_km=...)` in `save()`), daily per-reading approve/reject **plus new monthly bulk approve/reject** (`MonthlyOdometerApproveView`/`MonthlyOdometerRejectView` that batch-updates all pending readings for a user/month/year, emits one aggregated `notification_type='sales'`). Payroll integration (`_get_odometer_expenses_for_user`, `is_paid`, `payslip` linkage) preserved.
5. **Sales Inventory Allocation**: Full CRUD + `bulk_issue`/`my_allocations`/`return_item` (supports `sales_user`/`student`/`faculty`, atomic stock updates, `notification_type='inventory'`).
6. **Lead Management & CRM**: Public form POSTs, stage updates (auto-creates `Admission` + history + email/WhatsApp on `converted`), split `assign` (initial, front_desk+seniors) vs `reassign` (seniors only, creates `LeadAssignmentLog`).
7. **Lead Transfer Requests**: `LeadTransferRequestListCreateView` + `ReviewView` (pending→approved/rejected with audit + notifications).
8. **Notifications & Reminders**: `notification_type='sales'|'leads'|'inventory'`, `TriggerSalesRemindersView` (`POST /sales/plans/send-reminders/` wrapping Celery task).

---

## Data Models & Field Reference

### 1. `SalesDailyPlan` (Parent + Scheduled Event Model) (`leads/models.py`)

Dual-purpose record: daily sales plan **and** scheduled events (school visits, seminars, reminders). Now supports event metadata. All field activities are nested under it.

| Field | Type | Description |
|---|---|---|
| `id` | `UUID` (PK) | Auto-generated UUIDv4 |
| `user` | `ForeignKey(User)` | Sales employee / owner |
| `plan_date` | `DateField` | Date of the plan/event (default: today). Unique per user per day |
| `type` | `CharField` | Event type (e.g. `school_visit`, `seminar`, `follow_up`, `plan`) |
| `start_time` | `TimeField` | Scheduled start time (nullable) |
| `end_time` | `TimeField` | Scheduled end time (nullable) |
| `place` | `CharField` | Location / school name / venue |
| `description` | `TextField` | Narrative of planned activities or event notes |
| `reminder_sent` | `BooleanField` | Whether 1-day-before reminder was sent |
| `day_of_reminder_sent` | `BooleanField` | Whether same-day reminder was sent |
| `activities` | `Reverse(SalesDailyActivity)` | Related daily activity containers (`related_name='activities'`) |
| `created_at` | `DateTimeField` | Record creation timestamp |
| `updated_at` | `DateTimeField` | Last update timestamp |

**Constraint:** Unique constraint on `['user', 'plan_date']`. `SalesDailyPlanDetailView` provides full CRUD. `TriggerSalesRemindersView` evaluates and sends reminders via Celery.

---

### 2. `SalesDailyActivity` (Child Container) (`leads/models.py`)

Represents a **field-work activity container** for a sales user. **Multiple activities per `(user, activity_date)` are now supported** (the previous `UniqueConstraint` on `['user', 'activity_date']` has been removed). The optional `name` field differentiates multiple records on the same day (e.g. "Morning School Visit", "Seminar Follow-up", "Lead Follow-up").

| Field | Type | Description |
|---|---|---|
| `id` | `UUID` (PK) | Auto-generated UUIDv4 |
| `name` | `CharField(100)` | Optional name/title to distinguish multiple activities on same date (blank allowed) |
| `plan` | `ForeignKey(SalesDailyPlan)` | **Parent daily plan** this activity belongs to (nullable, `on_delete=SET_NULL`, `related_name='activities'`) |
| `user` | `ForeignKey(User)` | Sales employee performing field activities |
| `activity_date` | `DateField` | Date of field activity (default: today) |
| `notes` | `TextField` | Daily summary, school visit remarks, or execution notes |
| `photos` | `Reverse(SalesActivityPhoto)` | Related verification photos captured during the day |
| `odometer_reading` | `Reverse(OdometerReading)` | Linked travel kilometer calculation and approval record (1:1) |
| `created_at` | `DateTimeField` | Record creation timestamp |
| `updated_at` | `DateTimeField` | Last update timestamp |

**Cardinality Note:** No unique constraint on `(user, activity_date)`. `POST /sales/activities/` always creates a new record (no more `get_or_create`). Use the `name` field in POST body to label distinct activities on the same day. `SalesDailyPlan.post()` also creates a default named activity if none exists. Querysets and serializers updated to handle multiple activities per day.

---

### 3. `SalesActivityPhoto` (`leads/models.py`)

Stores timestamped, geo-tagged photo evidence attached to a daily activity.

| Field | Type | Description |
|---|---|---|
| `id` | `UUID` (PK) | Auto-generated UUIDv4 |
| `activity` | `ForeignKey(SalesDailyActivity)` | Parent activity container |
| `photo_type` | `CharField(30)` | Verification type (see choices below) |
| `photo` | `ImageField` | Uploaded image (stored under `media/sales/activity_photos/`) |
| `latitude` | `Decimal(9, 6)` | GPS latitude at time of capture (e.g., `19.113645`) |
| `longitude` | `Decimal(9, 6)` | GPS longitude at time of capture (e.g., `72.869734`) |
| `odometer_kms` | `Decimal(10, 2)` | Odometer kilometer reading (mandatory for odometer photo types) |
| `captured_at` | `DateTimeField` | Client-reported capture timestamp (default: now) |
| `created_at` | `DateTimeField` | Server upload timestamp |

#### Photo Type Choices (`photo_type`)

| Key | Display Label | Specific Validation Rules |
|---|---|---|
| `start_selfie` | Start of Day Selfie | `odometer_kms` must be `null` |
| `start_odometer` | Start of Day Odometer | **`odometer_kms` is mandatory**; auto-updates `OdometerReading.start_kms` |
| `school_interior` | School Interior | `odometer_kms` must be `null` |
| `school_exterior` | School Exterior | `odometer_kms` must be `null` |
| `exhibition` | Exhibition | Max **6 exhibition photos** allowed per activity day |
| `end_odometer` | End of Day Odometer | **`odometer_kms` is mandatory**; auto-updates `OdometerReading.end_kms` & computes `total_kms` |
| `end_selfie` | End of Day Selfie | `odometer_kms` must be `null` |

---

### 4. `OdometerReading` (`leads/models.py`)

Represents the daily odometer travel expense claim generated for a sales employee.

| Field | Type | Description |
|---|---|---|
| `id` | `UUID` (PK) | Auto-generated UUIDv4 |
| `activity` | `OneToOneField(SalesDailyActivity)` | Associated daily sales activity container |
| `user` | `ForeignKey(User)` | Sales employee who completed the travel |
| `start_kms` | `Decimal(10, 2)` | Start-of-day odometer reading from photo |
| `end_kms` | `Decimal(10, 2)` | End-of-day odometer reading from photo |
| `total_kms` | `Decimal(10, 2)` | `end_kms - start_kms` (auto-calculated) |
| `expense_per_km` | `Decimal(8, 2)` | Reimbursable rate per kilometer (editable by manager on approval) |
| `total_expense` | `Decimal(12, 2)` | `total_kms * expense_per_km` (auto-calculated) |
| `status` | `CharField(20)` | Status: `pending`, `approved`, `rejected` |
| `approved_by` | `ForeignKey(User)` | Approver (`super_admin`, `admin_senior_executive`, `accountant`, `branch_manager`) |
| `approved_at` | `DateTimeField` | Approval timestamp |
| `rejected_by` | `ForeignKey(User)` | Manager who rejected the claim |
| `rejected_at` | `DateTimeField` | Rejection timestamp |
| `rejection_reason` | `TextField` | Justification if rejected |
| `payroll_run` | `ForeignKey(PayrollRun)` | Linked payroll run in which the claim was credited |
| `payslip` | `ForeignKey(PaySlip)` | Linked employee payslip credited under `reimbursements_amount` |
| `is_paid` | `BooleanField` | Marked `True` automatically when payroll run is disbursed |
| `created_at` / `updated_at` | `DateTimeField` | Creation / update timestamps |

---

### 5. `ItemAllocation` for Sales Users (`inventory/models.py`)

Material issued to sales staff from branch inventory.

| Field | Type | Description |
|---|---|---|
| `sales_user` | `ForeignKey(User)` | Assigned sales employee (nullable) |
| `student` | `ForeignKey(StudentProfile)` | Student assignee (nullable) |
| `faculty` | `ForeignKey(FacultyProfile)` | Faculty assignee (nullable) |
| `item` | `ForeignKey(Item)` | Inventory stock item issued |
| `quantity` | `PositiveIntegerField` | Units allocated |
| `status` | `CharField(20)` | `issued` \| `returned` \| `lost` \| `damaged` |
| `issued_by` | `ForeignKey(User)` | Manager/Storekeeper who issued the item |
| `issued_at` | `DateTimeField` | Timestamp when issued |

**Target Recipient Validation Rule:**
- Exactly **one** of `student`, `faculty`, or `sales_user` must be provided.
- If `sales_user` is provided, user role **must** be in `{'sales_senior_executive', 'sales_executive', 'tele_caller'}`.

---

### 6. `NotificationHistory` & Categories (`auth_user/models.py`)

System notifications stamped with `notification_type` choices:
`system`, `authentication`, `admission`, `attendance`, `timetable`, `chat`, `exam`, `fees`, `inventory`, `leads`, `leave`, `payroll`, `results`, `sales`, `support`.

- Odometer submissions, approvals, and rejections are categorized under `sales`.
- Sales/Leads CRM notifications are categorized under `leads`.
- Inventory notifications are categorized under `inventory`.

---

## Architecture & Workflows

### Updated Daily Field Work + Lead + Inventory Lifecycle (Current Implementation)

```text
[ MORNING: PLAN + SCHEDULED EVENT CREATION ]
  │
  ├── 1. POST /api/v1/sales/plans/ ─────────────────────────────► Create/update SalesDailyPlan (now supports type/start_time/end_time/place)
  │      {"plan_date": "2025-10-15", "description": "...", "type": "school_visit", "start_time": "10:00", "place": "Ryan School"}
  │      └─► Auto-creates/links SalesDailyActivity + fires reminders via TriggerSalesRemindersView
  │
  ├── 2. GET/POST /api/v1/sales/activities/ ────────────────────► List or update notes (auto-links to plan)
  │
[ FIELD ACTIVITY & VERIFICATION ]
  │
  ├── 3. POST /sales/activities/<id>/photos/ (multipart) ───────► Upload photo (start_selfie / start_odometer / school_* / exhibition / end_*)
  │      • start_selfie/end_selfie → auto-creates EmployeeAttendanceRecord (GPS, shortfall_minutes, location_verified=False)
  │      • odometer photos → auto OdometerReading (vehicle_type support, calculate_totals: 5/km 2-wheeler / 12/km 4-wheeler)
  │      • Response includes optional "attendance" key
  │      • Max 6 exhibition photos enforced
  │
[ LEAD MANAGEMENT WORKFLOW ]
  │
  ├── 4. POST /leads/ (public) or PATCH /leads/<id>/ (stage update)
  │      • On stage=converted → auto-creates Admission (form_pending), AdmissionStatusHistory, sends email/WhatsApp
  │      • Split: PATCH /leads/<id>/assign/ (initial, front_desk+seniors) vs /reassign/ (seniors only + LeadAssignmentLog)
  │      • POST /leads/transfer-requests/ + PATCH /.../review/ (pending→approved/rejected with audit + notification)
  │
[ EVENING + APPROVAL + INVENTORY ]
  │
  ├── 5. POST /sales/odometer-readings/<id>/approve/ or /reject/ ──► Manager flow (guards on is_paid, both kms present)
  │      └─► Notification (type='sales'), payroll integration via _get_odometer_expenses_for_user()
  │
  ├── 6. Inventory: POST /inventory/allocations/ or /bulk_issue/
  │      • Supports sales_user/student/faculty, atomic stock tx, notification_type='inventory'
  │      • GET /inventory/allocations/my/ for self-service
  │
[ REMINDERS & NOTIFICATIONS ]
  └── 7. POST /sales/plans/send-reminders/ (TriggerSalesRemindersView) or GET /auth/notifications/?type=sales|leads|inventory
```
**New in this version:** Dual-purpose plans, auto-attendance on selfies, vehicle-aware odometer, admission auto-creation on lead conversion, split assign/reassign, full transfer request workflow, reminder trigger. All old inventory endpoints preserved below.
---

## Complete API Reference

### 1. List Sales Daily Plans (Parent Object)

**`GET /api/v1/sales/plans/`**

Retrieves daily plans created by sales personnel. As the **parent model**, each plan nests the day's high-level `description`, employee information, and all related child `activities` (including attached `photos` and `odometer_reading`).
- **Sales Staff** (`sales_executive`, `sales_senior_executive`, `tele_caller`): Sees only their own plans.
- **Branch Managers**: View plans across sales personnel in their authorized branches.
- **Super Admins & Accountants**: View plans across the entire organization.

#### Query Parameters
| Parameter | Type | Example | Description |
|---|---|---|---|
| `search` or `name` | `string` | `?search=Aakash` | Case-insensitive search on sales staff name, email, or phone. |
| `date` | `string` | `?date=today` or `?date=2026-09-10` | Filter by exact plan date. Pass `'today'` for current date. |
| `from_date` | `string` | `?from_date=2026-09-01` | Filter plans from this date onwards (`YYYY-MM-DD`). |
| `to_date` | `string` | `?to_date=2026-09-30` | Filter plans up to this date (`YYYY-MM-DD`). |
| `user_id` | `uuid` | `?user_id=550e8400...` | Filter by specific sales rep (managers and admins only). |

#### 💡 Daily Plan Form Behavior (Mobile / Frontend Guidance)
- On app launch, query:
  ```http
  GET /api/v1/sales/plans/?date=today
  ```
- **If the sales representative has not submitted a plan for today yet**, the API returns an **empty array (`[]`)**.
- When the frontend receives `[]`, it should prompt the sales representative to enter their plan `description` for the day.
- Once submitted via `POST /api/v1/sales/plans/`, the record is saved, the day's `SalesDailyActivity` container is automatically initialized, and subsequent queries return the complete plan with nested activities.

#### Request Headers
```http
Authorization: Bearer <access_token>
```

#### Response Example (`200 OK`)
```json
[
  {
    "id": "4eb82a55-891a-4d43-855d-16a7f0518cf5",
    "user": "550e8400-e29b-41d4-a716-446655440000",
    "user_name": "Aakash Mehta",
    "plan_date": "2026-09-10",
    "description": "Visiting Ryan International School and Podar International in Malad. Meeting 45 parents at the afternoon career fair.",
    "activities": [
      {
        "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "user": "550e8400-e29b-41d4-a716-446655440000",
        "user_name": "Aakash Mehta",
        "plan": "4eb82a55-891a-4d43-855d-16a7f0518cf5",
        "activity_date": "2026-09-10",
        "notes": "Met counselor Mrs. Sharma at Ryan International; positive interest for CS Executive batch.",
        "photos": [
          {
            "id": "e4b2d1c0-789a-4bc1-9012-3456789abcde",
            "activity": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "photo_type": "start_selfie",
            "photo_type_display": "Start of Day Selfie",
            "photo": "http://api.example.com/media/sales/activity_photos/start_selfie_100926.jpg",
            "latitude": "19.113645",
            "longitude": "72.869734",
            "odometer_kms": null,
            "captured_at": "2026-09-10T09:05:00Z",
            "created_at": "2026-09-10T09:05:12Z"
          },
          {
            "id": "f5c3e2d1-890b-5cd2-0123-456789abcdef",
            "activity": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "photo_type": "start_odometer",
            "photo_type_display": "Start of Day Odometer",
            "photo": "http://api.example.com/media/sales/activity_photos/start_odo_100926.jpg",
            "latitude": "19.113650",
            "longitude": "72.869740",
            "odometer_kms": "14250.50",
            "captured_at": "2026-09-10T09:07:00Z",
            "created_at": "2026-09-10T09:07:15Z"
          },
          {
            "id": "b7e5a4f3-012d-7ef4-2345-6789abcdef01",
            "activity": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "photo_type": "end_odometer",
            "photo_type_display": "End of Day Odometer",
            "photo": "http://api.example.com/media/sales/activity_photos/end_odo_100926.jpg",
            "latitude": "19.113700",
            "longitude": "72.869800",
            "odometer_kms": "14298.20",
            "captured_at": "2026-09-10T18:15:00Z",
            "created_at": "2026-09-10T18:15:30Z"
          }
        ],
        "odometer_reading": {
          "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
          "activity": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
          "activity_date": "2026-09-10",
          "user": "550e8400-e29b-41d4-a716-446655440000",
          "user_name": "Aakash Mehta",
          "user_email": "aakash@example.com",
          "start_kms": "14250.50",
          "end_kms": "14298.20",
          "total_kms": "47.70",
          "expense_per_km": "6.00",
          "total_expense": "286.20",
          "status": "approved",
          "approved_by": "110e8400-e29b-41d4-a716-446655440001",
          "approved_by_name": "Kavita Desai",
          "approved_at": "2026-09-10T19:00:00Z",
          "rejected_by": null,
          "rejected_by_name": null,
          "rejected_at": null,
          "rejection_reason": "",
          "payroll_run": "220e8400-e29b-41d4-a716-446655440002",
          "payslip": "330e8400-e29b-41d4-a716-446655440003",
          "is_paid": false,
          "start_odometer_photo": "http://api.example.com/media/sales/activity_photos/start_odo_100926.jpg",
          "end_odometer_photo": "http://api.example.com/media/sales/activity_photos/end_odo_100926.jpg",
          "created_at": "2026-09-10T09:07:15Z",
          "updated_at": "2026-09-10T19:00:00Z"
        },
        "created_at": "2026-09-10T09:04:00Z",
        "updated_at": "2026-09-10T18:16:00Z"
      }
    ],
    "created_at": "2026-09-10T08:30:00Z",
    "updated_at": "2026-09-10T08:30:00Z"
  }
]
```

---

### 2. Sales Daily Plan Detail View (Full CRUD)

**`GET|PUT|PATCH|DELETE /api/v1/sales/plans/<uuid:pk>/`** (`SalesDailyPlanDetailView`)

Full control over a specific plan/scheduled event. Supports updating event metadata (`type`, `start_time`, `end_time`, `place`).

#### Query / Body Parameters (PATCH/PUT)
- Same fields as POST (plan_date, description, **type**, **start_time**, **end_time**, **place**).
- Seniors/managers can view/edit any; sales staff limited to own.

#### Response Example (`200 OK` for GET)
```json
{
  "id": "4eb82a55-891a-4d43-855d-16a7f0518cf5",
  "user": "550e8400-e29b-41d4-a716-446655440000",
  "user_name": "Aakash Mehta",
  "plan_date": "2025-10-15",
  "type": "school_visit",
  "start_time": "10:00:00",
  "end_time": "11:30:00",
  "place": "Ryan International School, Malad",
  "description": "Career counseling seminar for Class 12 commerce students.",
  "reminder_sent": false,
  "day_of_reminder_sent": false,
  "activities": [ ... ],
  "created_at": "...",
  "updated_at": "..."
}
```

**DELETE Response:**
```json
{"success": true, "message": "Sales plan deleted successfully."}
```

---

### 3. Create or Update Sales Daily Plan (List + POST)

**`GET /api/v1/sales/plans/`** and **`POST /api/v1/sales/plans/`**

(Details as in previous version — now also accepts `type`, `start_time`, `end_time`, `place` in POST body. Auto-links activity container. Idempotent on `plan_date`.)

**Updated Request Body Example:**
```json
{
  "plan_date": "2025-10-15",
  "type": "school_visit",
  "start_time": "10:00",
  "end_time": "12:00",
  "place": "Podar School",
  "description": "Conducting career fair and collecting leads."
}
```

---

### 4. List Sales Daily Activities

**`GET /api/v1/sales/activities/`**

Retrieves daily activity logs including attached photos, linked odometer reading, user details, and parent `plan` link.
- **Sales Staff** (`sales_executive`, `sales_senior_executive`, `tele_caller`): Sees only their own activities.
- **Branch Managers**: View activities across sales personnel in their authorized branches.
- **Super Admins & Accountants**: View activities across the entire organization.

#### Query Parameters
| Parameter | Type | Example | Description |
|---|---|---|---|
| `search` or `name` | `string` | `?search=Aakash` | Case-insensitive search on sales staff name, email, or phone. |
| `date` | `string` | `?date=today` or `?date=2026-09-10` | Filter by exact activity date. Pass `'today'` for current date. |
| `from_date` | `string` | `?from_date=2026-09-01` | Filter activities from this date onwards (`YYYY-MM-DD`). |
| `to_date` | `string` | `?to_date=2026-09-30` | Filter activities up to this date (`YYYY-MM-DD`). |
| `user_id` | `uuid` | `?user_id=550e8400...` | Filter by specific sales rep (managers and admins only). |

#### Request Headers
```http
Authorization: Bearer <access_token>
```

#### Response Example (`200 OK`)
```json
[
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "user": "550e8400-e29b-41d4-a716-446655440000",
    "user_name": "Aakash Mehta",
    "plan": "4eb82a55-891a-4d43-855d-16a7f0518cf5",
    "activity_date": "2026-09-10",
    "notes": "Visited Ryan International School and Podar International. Met 45 parents at career fair.",
    "photos": [
      {
        "id": "e4b2d1c0-789a-4bc1-9012-3456789abcde",
        "activity": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "photo_type": "start_selfie",
        "photo_type_display": "Start of Day Selfie",
        "photo": "http://api.example.com/media/sales/activity_photos/start_selfie_100926.jpg",
        "latitude": "19.113645",
        "longitude": "72.869734",
        "odometer_kms": null,
        "captured_at": "2026-09-10T09:05:00Z",
        "created_at": "2026-09-10T09:05:12Z"
      },
      {
        "id": "f5c3e2d1-890b-5cd2-0123-456789abcdef",
        "activity": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "photo_type": "start_odometer",
        "photo_type_display": "Start of Day Odometer",
        "photo": "http://api.example.com/media/sales/activity_photos/start_odo_100926.jpg",
        "latitude": "19.113650",
        "longitude": "72.869740",
        "odometer_kms": "14250.50",
        "captured_at": "2026-09-10T09:07:00Z",
        "created_at": "2026-09-10T09:07:15Z"
      },
      {
        "id": "b7e5a4f3-012d-7ef4-2345-6789abcdef01",
        "activity": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "photo_type": "end_odometer",
        "photo_type_display": "End of Day Odometer",
        "photo": "http://api.example.com/media/sales/activity_photos/end_odo_100926.jpg",
        "latitude": "19.113700",
        "longitude": "72.869800",
        "odometer_kms": "14298.20",
        "captured_at": "2026-09-10T18:15:00Z",
        "created_at": "2026-09-10T18:15:30Z"
      }
    ],
    "odometer_reading": {
      "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "activity": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "activity_date": "2026-09-10",
      "user": "550e8400-e29b-41d4-a716-446655440000",
      "user_name": "Aakash Mehta",
      "user_email": "aakash@example.com",
      "start_kms": "14250.50",
      "end_kms": "14298.20",
      "total_kms": "47.70",
      "expense_per_km": "6.00",
      "total_expense": "286.20",
      "status": "approved",
      "approved_by": "110e8400-e29b-41d4-a716-446655440001",
      "approved_by_name": "Kavita Desai",
      "approved_at": "2026-09-10T19:00:00Z",
      "rejected_by": null,
      "rejected_by_name": null,
      "rejected_at": null,
      "rejection_reason": "",
      "payroll_run": "220e8400-e29b-41d4-a716-446655440002",
      "payslip": "330e8400-e29b-41d4-a716-446655440003",
      "is_paid": false,
      "start_odometer_photo": "http://api.example.com/media/sales/activity_photos/start_odo_100926.jpg",
      "end_odometer_photo": "http://api.example.com/media/sales/activity_photos/end_odo_100926.jpg",
      "created_at": "2026-09-10T09:07:15Z",
      "updated_at": "2026-09-10T19:00:00Z"
    },
    "created_at": "2026-09-10T09:04:00Z",
    "updated_at": "2026-09-10T18:16:00Z"
  }
]
```

---

### 4. Create or Initialize Daily Activity Container

**`POST /api/v1/sales/activities/`**

Initializes the day's field container or updates notes for the specified date. Automatically links to the user's `SalesDailyPlan` for that date if one exists.

#### Request Headers
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

#### Request Body
```json
{
  "activity_date": "2026-09-10",
  "notes": "Targeting Malad and Kandivali schools for CS Executive counseling."
}
```

*Note: `activity_date` defaults to current server local date if omitted.*

#### Response Example (`201 Created`)
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "user": "550e8400-e29b-41d4-a716-446655440000",
  "user_name": "Aakash Mehta",
  "plan": "4eb82a55-891a-4d43-855d-16a7f0518cf5",
  "activity_date": "2026-09-10",
  "notes": "Targeting Malad and Kandivali schools for CS Executive counseling.",
  "photos": [],
  "odometer_reading": null,
  "created_at": "2026-09-10T09:04:00Z",
  "updated_at": "2026-09-10T09:04:00Z"
}
```

#### Error Example: Non-Sales User Access (`403 Forbidden`)
```json
{
  "detail": "Only sales staff can upload sales activities."
}
```

---

### 5. Upload Sales Activity Photo Evidence

**`POST /api/v1/sales/activities/<uuid:activity_id>/photos/`**

Uploads a single photo with location and meter data attached to a specific daily activity.

#### Request Headers
```http
Authorization: Bearer <access_token>
Content-Type: multipart/form-data
```

#### Form-Data Parameters
| Field | Type | Required | Description |
|---|---|:---:|---|
| `photo` | `file` | Yes | Captured photo file (JPEG/PNG) |
| `photo_type` | `string` | Yes | One of: `start_selfie`, `start_odometer`, `school_interior`, `school_exterior`, `exhibition`, `end_odometer`, `end_selfie` |
| `latitude` | `decimal` | Yes | Latitude of capture location |
| `longitude` | `decimal` | Yes | Longitude of capture location |
| `odometer_kms` | `decimal` | Conditional | **Required** if `photo_type` is `start_odometer` or `end_odometer`. Must be absent otherwise. |
| `captured_at` | `iso-datetime` | No | Client capture timestamp (defaults to current time). |

#### Request Example (Start of Day Odometer)
```http
--boundary
Content-Disposition: form-data; name="photo_type"

start_odometer
--boundary
Content-Disposition: form-data; name="latitude"

19.113650
--boundary
Content-Disposition: form-data; name="longitude"

72.869740
--boundary
Content-Disposition: form-data; name="odometer_kms"

14250.50
--boundary
Content-Disposition: form-data; name="captured_at"

2026-09-10T09:07:00Z
--boundary
Content-Disposition: form-data; name="photo"; filename="odometer.jpg"
Content-Type: image/jpeg

[binary image data]
--boundary--
```

#### Response Example (`201 Created`) — with new auto-features
```json
{
  "id": "f5c3e2d1-890b-5cd2-0123-456789abcdef",
  "activity": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "photo_type": "start_selfie",
  "photo_type_display": "Start of Day Selfie",
  "photo": "http://api.example.com/media/sales/activity_photos/start_selfie_100926.jpg",
  "latitude": "19.113645",
  "longitude": "72.869734",
  "odometer_kms": null,
  "captured_at": "2026-09-10T09:05:00Z",
  "created_at": "2026-09-10T09:05:12Z",
  "attendance": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "user": "550e8400-e29b-41d4-a716-446655440000",
    "check_in_time": "2026-09-10T09:05:00Z",
    "gps_latitude": "19.113645",
    "gps_longitude": "72.869734",
    "location_verified": false,
    "shortfall_minutes": 15,
    "status": "present"
  }
}
```

**New Behavior (SalesActivityPhotoView):**
- `start_selfie` / `end_selfie`: Automatically creates/updates `EmployeeAttendanceRecord` (with GPS, `shortfall_minutes` calculation, `location_verified=False` initially).
- Odometer photos (`start_odometer`/`end_odometer`): Auto-creates or updates `OdometerReading`; supports `vehicle_type` (2_wheeler/4_wheeler) via `calculate_totals()` (defaults: 5/km for 2-wheeler, 12/km for 4-wheeler). PATCH `/odometer-readings/<id>/` allowed on pending records to set `vehicle_type`.
- `exhibition`: Enforces max 6 photos per activity.
- Response may include optional `"attendance"` key when selfie photo triggers attendance record.

#### Error Example: Missing Odometer on Meter Photo (`400 Bad Request`)
```json
{
  "odometer_kms": [
    "Required for odometer photos."
  ]
}
```

#### Error Example: Providing Odometer on Non-Meter Photo (`400 Bad Request`)
```json
{
  "odometer_kms": [
    "Only valid for odometer photos."
  ]
}
```

#### Error Example: Exceeding 6 Exhibition Photos Limit (`400 Bad Request`)
```json
{
  "detail": "A maximum of 6 exhibition photos is allowed."
}
```

---

### 6. List Odometer Readings

**`GET /api/v1/sales/odometer-readings/`**

Retrieves the list of odometer readings, their calculated kilometers, per-km reimbursement rates, approval statuses, and photo links.
- **Sales Staff** (`sales_executive`, `sales_senior_executive`, `tele_caller`): Returns only their own odometer records.
- **Branch Managers**: Returns records for sales staff in their managed branches.
- **Super Admins & Accountants**: Returns records across the entire organization.

#### Query Parameters
| Parameter | Type | Example | Description |
|---|---|---|---|
| `status` | `string` | `?status=pending` | Filter by status: `pending`, `approved`, or `rejected`. |
| `user_id` | `uuid` | `?user_id=550e...` | Filter by a specific sales user (managers and admins only). |
| `search` or `name` | `string` | `?search=Aakash` | Case-insensitive search on user name, email, or phone. |
| `date` | `string` | `?date=2026-09-10` | Filter by activity date (`YYYY-MM-DD` or `'today'`). |
| `from_date` | `string` | `?from_date=2026-09-01` | Filter by activity date from (`YYYY-MM-DD`). |
| `to_date` | `string` | `?to_date=2026-09-30` | Filter by activity date to (`YYYY-MM-DD`). |
| `is_paid` | `boolean` | `?is_paid=false` | Filter by whether the claim has been disbursed in payroll (`true` or `false`). |

#### Response Example (`200 OK`)
```json
[
  {
    "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "activity": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "activity_date": "2026-09-10",
    "user": "550e8400-e29b-41d4-a716-446655440000",
    "user_name": "Aakash Mehta",
    "user_email": "aakash@example.com",
    "start_kms": "14250.50",
    "end_kms": "14298.20",
    "total_kms": "47.70",
    "expense_per_km": "6.00",
    "total_expense": "286.20",
    "status": "approved",
    "approved_by": "110e8400-e29b-41d4-a716-446655440001",
    "approved_by_name": "Kavita Desai",
    "approved_at": "2026-09-10T19:00:00Z",
    "rejected_by": null,
    "rejected_by_name": null,
    "rejected_at": null,
    "rejection_reason": "",
    "payroll_run": "220e8400-e29b-41d4-a716-446655440002",
    "payslip": "330e8400-e29b-41d4-a716-446655440003",
    "is_paid": false,
    "start_odometer_photo": "http://api.example.com/media/sales/activity_photos/start_odo_100926.jpg",
    "end_odometer_photo": "http://api.example.com/media/sales/activity_photos/end_odo_100926.jpg",
    "created_at": "2026-09-10T09:07:15Z",
    "updated_at": "2026-09-10T19:00:00Z"
  }
]
```

---

### 7. Retrieve Single Odometer Reading

**`GET /api/v1/sales/odometer-readings/<uuid:pk>/`**

Retrieves detailed information for a single odometer reading.

#### Response Example (`200 OK`)
```json
{
  "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "activity": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "activity_date": "2026-09-10",
  "user": "550e8400-e29b-41d4-a716-446655440000",
  "user_name": "Aakash Mehta",
  "user_email": "aakash@example.com",
  "start_kms": "14250.50",
  "end_kms": "14298.20",
  "total_kms": "47.70",
  "expense_per_km": "6.00",
  "total_expense": "286.20",
  "status": "approved",
  "approved_by": "110e8400-e29b-41d4-a716-446655440001",
  "approved_by_name": "Kavita Desai",
  "approved_at": "2026-09-10T19:00:00Z",
  "rejected_by": null,
  "rejected_by_name": null,
  "rejected_at": null,
  "rejection_reason": "",
  "payroll_run": null,
  "payslip": null,
  "is_paid": false,
  "start_odometer_photo": "http://api.example.com/media/sales/activity_photos/start_odo_100926.jpg",
  "end_odometer_photo": "http://api.example.com/media/sales/activity_photos/end_odo_100926.jpg",
  "created_at": "2026-09-10T09:07:15Z",
  "updated_at": "2026-09-10T19:00:00Z"
}
```

---

### 8. Approve Odometer Reading

**`POST /api/v1/sales/odometer-readings/<uuid:pk>/approve/`**

Approves a pending odometer reading and applies an editable per-kilometer reimbursement rate.
- **Allowed Roles:** `super_admin`, `admin_senior_executive`, `accountant`, `branch_manager`.
- **Automatic Calculations:** `total_expense = total_kms * expense_per_km`.
- **Automatic Push Notification:** Dispatches an in-app notification of type `'sales'` to the employee with approval details.
- **Payslip Crediting:** Automatically picked up during payroll calculation for inclusion in the upcoming monthly `PaySlip` under `reimbursements_amount`.

#### Request Headers
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

#### Request Body
```json
{
  "expense_per_km": 6.50
}
```

#### Response Example (`200 OK`)
```json
{
  "success": true,
  "message": "Odometer reading approved (47.70 km @ ₹6.50/km = ₹310.05). Added to upcoming payslip.",
  "data": {
    "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "activity": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "activity_date": "2026-09-10",
    "user": "550e8400-e29b-41d4-a716-446655440000",
    "user_name": "Aakash Mehta",
    "start_kms": "14250.50",
    "end_kms": "14298.20",
    "total_kms": "47.70",
    "expense_per_km": "6.50",
    "total_expense": "310.05",
    "status": "approved",
    "approved_by": "110e8400-e29b-41d4-a716-446655440001",
    "approved_by_name": "Kavita Desai",
    "approved_at": "2026-09-10T19:00:00Z",
    "rejected_by": null,
    "is_paid": false
  }
}
```

#### Error Example: Missing End Odometer Reading (`400 Bad Request`)
```json
{
  "detail": "Cannot approve odometer reading: both start and end odometer readings are required."
}
```

#### Error Example: Modifying Disbursed Claim (`400 Bad Request`)
```json
{
  "detail": "Cannot modify an odometer reading that has already been paid in payroll."
}
```

---

### 9. Reject Odometer Reading

**`POST /api/v1/sales/odometer-readings/<uuid:pk>/reject/`**

Rejects an odometer reading claim with an optional/mandatory reason.
- **Allowed Roles:** `super_admin`, `admin_senior_executive`, `accountant`, `branch_manager`.
- **Automatic Push Notification:** Dispatches an in-app notification of type `'sales'` to the employee with rejection details and reason.

#### Request Body
```json
{
  "rejection_reason": "End odometer photo was blurred and kilometer display was not legible."
}
```

#### Response Example (`200 OK`)
```json
{
  "success": true,
  "message": "Odometer reading rejected.",
  "data": {
    "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "status": "rejected",
    "rejected_by": "110e8400-e29b-41d4-a716-446655440001",
    "rejected_by_name": "Kavita Desai",
    "rejected_at": "2026-09-10T19:15:00Z",
    "rejection_reason": "End odometer photo was blurred and kilometer display was not legible."
  }
}
```

---

### 9b. **NEW** Monthly Bulk Odometer Approve / Reject (Preferred for Payroll Settlement)

**`POST /api/v1/sales/odometer/monthly/approve/`** (`MonthlyOdometerApproveView`)

**`POST /api/v1/sales/odometer/monthly/reject/`** (`MonthlyOdometerRejectView`)

Bulk processes **all pending** `OdometerReading` records for a given `user_id` in a specific `month`/`year`. This is the recommended manager workflow for monthly settlement (avoids approving dozens of daily records individually). 

- Filters: `status='pending'`, `activity__activity_date__year=year`, `__month=month`, respects branch scoping and `ODOMETER_APPROVER_ROLES`.
- For approve: calls `calculate_totals(override_expense_per_km=...)` (or uses vehicle rate), sets `approved_by`, `approved_at`, `status='approved'` on **all** matching records.
- For reject: sets `rejected_by`, `rejected_at`, `status='rejected'`, `rejection_reason`.
- Sends **one** aggregated `notification_type='sales'` (with total kms/expense summary) instead of per-reading notifications.
- Serializers: `MonthlyOdometerApproveSerializer` (`user_id`, `month`, `year`, optional `expense_per_km`), `MonthlyOdometerRejectSerializer` (`user_id`, `month`, `year`, optional `rejection_reason`).
- Response aggregates count of updated records, total expense, etc.

#### Monthly Approve Request Body Example
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "month": 9,
  "year": 2025,
  "expense_per_km": 7.50
}
```

#### Monthly Reject Request Body Example
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "month": 9,
  "year": 2025,
  "rejection_reason": "Missing end_odometer photos for several days."
}
```

#### Response Example (`200 OK`)
```json
{
  "success": true,
  "message": "Successfully processed 8 pending odometer readings for Sep 2025 (total 412.5 km, ₹2,062.50).",
  "updated_count": 8,
  "total_kms": 412.5,
  "total_expense": 2062.5,
  "notification_sent": true
}
```

**Note:** Daily per-reading approve/reject endpoints remain fully functional and non-breaking. Monthly bulk is optimized for payroll month-end processing.

---

### 10. Monthly Payslip Integration & Settlement Workflow

Approved odometer readings follow an automated lifecycle aligned with standard expense reimbursements:

```text
[ Daily Field Work ]
  Sales rep uploads start and end odometer photos
          │
          ▼
[ Manager Review ]
  Manager visits GET /api/v1/sales/odometer-readings/
  Approves via POST /api/v1/sales/odometer-readings/<id>/approve/ {"expense_per_km": 6.50}
  (Status -> 'approved', total_expense calculated)
          │
          ▼
[ Monthly Payroll Generation ]
  During draft/final payroll calculation (compute_payslip_for_user):
  • System calls _get_odometer_expenses_for_user(user, payroll_run)
  • Aggregates all approved, unpaid (is_paid=False) odometer readings
  • Adds the sum to PaySlip.reimbursements_amount
  • Links readings to PaySlip and PayrollRun
          │
          ▼
[ Payroll Disbursal ]
  Accountant/Admin marks PayrollRun as disbursed:
  • All linked OdometerReading records are automatically marked is_paid=True
```

---

### 11. Allocate Inventory to Sales Users

**`POST /api/v1/inventory/allocations/`**

Allocates marketing materials or equipment from branch inventory to a designated sales representative. Auto-deducts the item's stock and sends a real-time system notification to `super_admin`.

#### Request Headers
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

#### Request Body
```json
{
  "item": "501e8400-e29b-41d4-a716-446655440010",
  "sales_user": "550e8400-e29b-41d4-a716-446655440000",
  "quantity": 250,
  "notes": "CS Executive Course Prospectus brochures for school distribution."
}
```

#### Response Example (`201 Created`)
```json
{
  "id": "701e8400-e29b-41d4-a716-446655440020",
  "item": "501e8400-e29b-41d4-a716-446655440010",
  "item_name": "CS Executive Information Brochure 2026-27",
  "student": null,
  "student_name": null,
  "faculty": null,
  "faculty_name": null,
  "sales_user": "550e8400-e29b-41d4-a716-446655440000",
  "sales_user_name": "Aakash Mehta",
  "quantity": 250,
  "status": "issued",
  "status_display": "Issued",
  "issued_at": "2026-09-10T10:00:00Z",
  "issued_by": "770e8400-e29b-41d4-a716-446655440002",
  "issued_by_name": "Kavita Desai",
  "returned_at": null,
  "return_notes": "",
  "notes": "CS Executive Course Prospectus brochures for school distribution."
}
```

---

### 12. Bulk Issue Inventory to Sales User

**`POST /api/v1/inventory/allocations/bulk_issue/`**

Allocates multiple stock items in a single atomic transaction to a sales user.

#### Request Body
```json
{
  "sales_user": "550e8400-e29b-41d4-a716-446655440000",
  "allocations": [
    {
      "item": "501e8400-e29b-41d4-a716-446655440010",
      "quantity": 100,
      "notes": "CSEET Flyers"
    },
    {
      "item": "602e8400-e29b-41d4-a716-446655440011",
      "quantity": 2,
      "notes": "Roll-up Standees"
    }
  ]
}
```

#### Response Example (`201 Created`)
```json
[
  {
    "id": "801e8400-e29b-41d4-a716-446655440030",
    "item_name": "CSEET Promotional Flyers",
    "sales_user_name": "Aakash Mehta",
    "quantity": 100,
    "status": "issued"
  },
  {
    "id": "802e8400-e29b-41d4-a716-446655440031",
    "item_name": "Insight Roll-up Standee 6x3",
    "sales_user_name": "Aakash Mehta",
    "quantity": 2,
    "status": "issued"
  }
]
```

---

### 13. View Allocated Inventory Items (Sales User Self-Service)

**`GET /api/v1/inventory/allocations/`** or **`GET /api/v1/inventory/allocations/my/`**

Allows sales representatives to view all marketing collateral, brochures, exhibition kits, and roll-up standees allocated to them.

#### Automatic Scoping & Security
- When called by a sales representative (`sales_executive`, `sales_senior_executive`, `tele_caller`, `senior_tele_caller`, `associate_bdm`), `GET /api/v1/inventory/allocations/` automatically restricts the queryset to **only items allocated to the calling user** (`sales_user=request.user`).
- **Dedicated Self-Service Endpoint**: `GET /api/v1/inventory/allocations/my/` is also available as an explicit route.

#### Query Parameters
| Parameter | Type | Required | Description |
|---|---|:---:|---|
| `status` | `string` | No | Filter by allocation status: `issued` (currently holding) or `returned` (returned to branch). |
| `page` | `integer` | No | Pagination page number. |
| `page_size` | `integer` | No | Number of records per page. |

#### Request Example
```http
GET /api/v1/inventory/allocations/?status=issued
Authorization: Bearer <sales_access_token>
```

#### Response Example (`200 OK`)
```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "801e8400-e29b-41d4-a716-446655440030",
      "item": "501e8400-e29b-41d4-a716-446655440010",
      "item_name": "CS Executive Information Brochure 2026-27",
      "sales_user": "550e8400-e29b-41d4-a716-446655440000",
      "sales_user_name": "Aakash Mehta",
      "quantity": 100,
      "status": "issued",
      "status_display": "Issued",
      "issued_at": "2026-09-10T10:00:00Z",
      "issued_by": "770e8400-e29b-41d4-a716-446655440002",
      "issued_by_name": "Kavita Desai",
      "returned_at": null,
      "return_notes": "",
      "notes": "Prospectus brochures for school seminars"
    },
    {
      "id": "802e8400-e29b-41d4-a716-446655440031",
      "item": "602e8400-e29b-41d4-a716-446655440011",
      "item_name": "Insight Roll-up Standee 6x3",
      "sales_user": "550e8400-e29b-41d4-a716-446655440000",
      "sales_user_name": "Aakash Mehta",
      "quantity": 2,
      "status": "issued",
      "status_display": "Issued",
      "issued_at": "2026-09-10T10:00:00Z",
      "issued_by": "770e8400-e29b-41d4-a716-446655440002",
      "issued_by_name": "Kavita Desai",
      "returned_at": null,
      "return_notes": "",
      "notes": "School exhibition standees"
    }
  ]
}
```

---

### 14. Filtered Notifications for Sales Users

**`GET /api/auth/notifications/`**

Fetches notifications for the logged-in user, filtered by `notification_type`.

#### Query Parameters
| Parameter | Type | Required | Description |
|---|---|:---:|---|
| `type` or `notification_type` | `string` | No | Category filter: `sales` (odometer submissions & approvals), `leads`, `inventory`, `payroll`, `attendance`, `system`, etc. |
| `page` | `integer` | No | Pagination page number. |
| `page_size` | `integer` | No | Number of records per page. |

#### Request Example (Sales / Odometer Notifications)
```http
GET /api/auth/notifications/?type=sales
Authorization: Bearer <access_token>
```

#### Response Example (`200 OK`)
```json
{
  "success": true,
  "count": 1,
  "next": null,
  "previous": null,
  "page_size": 50,
  "data": [
    {
      "id": "d1e2f3a4-b5c6-7d8e-9f0a-1b2c3d4e5f6a",
      "title": "Odometer Reading Approved",
      "body": "Your odometer reading for 2026-09-10 (47.70 km @ ₹6.00/km = ₹286.20) has been approved.",
      "data": {
        "odometer_reading_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
        "sales_activity_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "type": "odometer_approved",
        "route": "/sales/odometer-readings/7c9e6679-7425-40de-944b-e07fc1f90ae7"
      },
      "notification_type": "sales",
      "is_read": false,
      "created_at": "2026-09-10T19:00:00Z"
    }
  ]
}
```

---

### 15. Mark All Notifications as Read

**`PATCH /api/auth/notifications/`**

Marks all unread notifications as read for the authenticated user.

#### Response Example (`200 OK`)
```json
{
  "success": true,
  "message": "Marked 4 notifications as read."
}
```

---

### 16. Trigger Sales Reminders (Celery Integration)

**`POST /api/v1/sales/plans/send-reminders/`** (`TriggerSalesRemindersView`)

Manually triggers the reminder Celery task for all upcoming `SalesDailyPlan` events (1-day-before and same-day reminders based on `reminder_sent` / `day_of_reminder_sent` flags). Typically called by a cron/scheduler or admin.

#### Request Headers
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

#### Request Body (Optional)
```json
{
  "date": "2025-10-15"
}
```

#### Response Example (`200 OK`)
```json
{
  "success": true,
  "message": "Reminder task triggered successfully for 12 plans.",
  "reminders_sent": 8,
  "day_of_reminders_sent": 4
}
```

This endpoint wraps the Celery task that evaluates `SalesDailyPlan` records with `type`, `start_time`, `place` and sends push notifications via the notification system (`notification_type='sales'`).

---

### 17. Full Lead Management & CRM APIs (from `leads/views.py`)

**Key Implementation Details (synchronized with current codebase):**
- `get_lead_queryset()`: Applies role-based filtering. `RESTRICTED_ROLES = {'counsellor', 'tele_caller', 'sales_executive'}` — these see only assigned leads; seniors/front_desk see all.
- **Split Assignment Logic**: `LeadAssignView` (initial assignment — allowed for front_desk + seniors) vs `LeadReassignView` (reassignment only by seniors, creates immutable `LeadAssignmentLog` entry for audit).
- **LeadStatusUpdateView**: On `PATCH /leads/<id>/` with `stage=converted`:
  - Auto-creates `Admission` record (`status='form_pending'`, maps fields like name/phone/course from lead).
  - Creates `AdmissionStatusHistory`.
  - Sends email + WhatsApp via `send_email()` / `send_whatsapp_with_fallback()`.
- Public lead capture: `POST /leads/` (no auth required for inquiry form).
- Transfer workflow uses `LeadTransferRequestListCreateView` + `LeadTransferRequestReviewView` (pending → approved/rejected with audit log + notification of type='leads').

#### 17.1 Public Lead Capture (No Auth)
**`POST /api/v1/leads/`**
```json
{
  "name": "Priya Sharma",
  "phone": "9876543210",
  "email": "priya@example.com",
  "course_interest": "CS Executive",
  "source": "school_seminar"
}
```

#### 17.2 List & Detail Leads
**`GET /api/v1/leads/`** (filtered by role via `get_lead_queryset()`)  
**`GET /api/v1/leads/<id>/`**

#### 17.3 Update Lead Stage (with Auto-Admission on Conversion)
**`PATCH /api/v1/leads/<uuid:pk>/`** (`LeadStatusUpdateView`)

```json
{
  "stage": "converted",
  "notes": "Student joined CS Executive batch"
}
```
**On `converted`**: Triggers Admission creation, history log, email/WhatsApp notifications.

#### 17.4 Initial Lead Assignment
**`PATCH /api/v1/leads/<id>/assign/`** (`LeadAssignView` — front_desk + seniors only)

```json
{
  "assigned_to": "550e8400-e29b-41d4-a716-446655440000"
}
```

#### 17.5 Reassign Lead (with Audit Log)
**`PATCH /api/v1/leads/<id>/reassign/`** (`LeadReassignView` — seniors only)

Creates `LeadAssignmentLog` entry automatically.

#### 17.6 Lead Transfer Requests (as before)
**`POST /api/v1/leads/transfer-requests/`** (`LeadTransferRequestListCreateView`)
**`PATCH /api/v1/leads/transfer-requests/<id>/review/`** (`LeadTransferRequestReviewView`)

(Details unchanged from previous version — creates audit + 'leads' notification on review.)

---

### 18. Legacy Inventory APIs (Preserved — Do Not Remove)

All legacy endpoints from previous documentation are retained below for backward compatibility. These map to `ItemCategoryViewSet`, `ItemViewSet`, `StockTransactionViewSet`, `ItemAllocationViewSet` in `inventory/views.py`.

#### Legacy Inventory ViewSets (Full CRUD)

| ViewSet | Endpoint | Methods | Description |
|---------|----------|---------|-------------|
| `ItemCategoryViewSet` | `/inventory/categories/` | GET, POST, PUT, PATCH, DELETE | Manage inventory categories (e.g. "Brochures", "Standees", "Marketing Kits") |
| `ItemViewSet` | `/inventory/items/` | GET, POST, PUT, PATCH, DELETE | CRUD for stock items with current_quantity, branch, low_stock_threshold |
| `StockTransactionViewSet` | `/inventory/transactions/` | GET, POST | Record stock in/out transactions (atomic updates to Item.current_quantity) |
| `ItemAllocationViewSet` | `/inventory/allocations/` | GET, POST, PUT, PATCH, DELETE | Full allocation management (supports sales_user, student, faculty) |

#### Additional Legacy Action Endpoints (preserved)

- **`POST /inventory/allocations/bulk_issue/`** — Atomic multi-item issue (as documented above)
- **`GET /inventory/allocations/my/`** — Self-service view for sales users (as documented)
- **`POST /inventory/allocations/<id>/return_item/`** — Return allocated item (updates status to 'returned', increments stock)
- **My Allocations Query**: `GET /inventory/allocations/?sales_user=me` or role-based scoping

**Photo Type Matrix (Legacy — Preserved)**

| photo_type | Requires GPS | Requires Odometer | Max Per Day | Auto Trigger |
|------------|---------------|-------------------|-------------|--------------|
| start_selfie | Yes | No | 1 | AttendanceRecord |
| start_odometer | Yes | Yes | 1 | OdometerReading.start_kms |
| school_exterior | Yes | No | Unlimited | None |
| school_interior | Yes | No | Unlimited | None |
| exhibition | Yes | No | **6** | None |
| end_odometer | Yes | Yes | 1 | OdometerReading.end_kms + totals |
| end_selfie | Yes | No | 1 | AttendanceRecord (checkout) |

**Legacy Daily Field Work Lifecycle (9-step ASCII — Preserved for reference)**

```text
[ SALES REP MORNING ROUTINE: PLAN & FIELD INITIALIZATION ]
  │
  ├── 1. POST /api/v1/sales/plans/ ─────────────────────────────► Creates daily plan with targets & itinerary
  │      {"plan_date": "2026-09-10", "description": "Visiting Malad & Kandivali schools"}
  │      └─► Automatically creates & links SalesDailyActivity container
  │
  ├── 2. POST /api/v1/sales/activities/ ────────────────────────► (Optional) Updates daily execution notes
  │      {"activity_date": "2026-09-10", "notes": "Meeting school principals and career counselors"}
  │      └─► Automatically links to today's SalesDailyPlan if one exists
  │
  ├── 3. POST /api/v1/sales/activities/<id>/photos/ ─────────────► Uploads 'start_selfie' (with GPS)
  │
  ├── 4. POST /api/v1/sales/activities/<id>/photos/ ─────────────► Uploads 'start_odometer' (with GPS + odometer_kms)
  │      └─► Automatically creates OdometerReading (start_kms=14250.50, status='pending')
  │
[ FIELD VISITS DURING THE DAY ]
  │
  ├── 5. POST /api/v1/sales/activities/<id>/photos/ ─────────────► School 1: 'school_exterior' + 'school_interior'
  │
  ├── 6. POST /api/v1/sales/activities/<id>/photos/ ─────────────► Exhibition: 'exhibition' photos (up to 6)
  │
[ EVENING CHECKOUT & REIMBURSEMENT APPROVAL ]
  │
  ├── 7. POST /api/v1/sales/activities/<id>/photos/ ─────────────► Uploads 'end_odometer' (with final kms)
  │      ├─► Automatically updates OdometerReading (end_kms=14298.20, total_kms=47.70)
  │      └─► Dispatches push notification (type='sales') to Branch Managers / Super Admins
  │
  ├── 8. POST /api/v1/sales/activities/<id>/photos/ ─────────────► Uploads 'end_selfie' (end of day)
  │
  └── 9. POST /api/v1/sales/odometer-readings/<id>/approve/ ──────► Manager approves reading + enters expense_per_km
         ├─► Computes total_expense = total_kms * expense_per_km
         ├─► Sends in-app notification (type='sales') to Sales Representative
         ├─► Automatically included under 'reimbursements_amount' in monthly PaySlip
         └─► Automatically marked 'is_paid=True' when PayrollRun is disbursed
```

**Note:** The updated 7-step lifecycle (with scheduled events, auto-admission, transfer requests, reminders) is the current primary workflow. Legacy diagrams and ViewSet tables are kept for reference and backward compatibility. No old APIs have been removed.

---

### 19. Updated Role Permissions Matrix (includes new views)
---

## Role Permissions Matrix (Updated with New Views)

| Endpoint / View | Sales Exec/Tele | Sales Senior | Branch Manager | Super Admin/Accountant |
|-----------------|-----------------|--------------|----------------|------------------------|
| `GET/POST/PATCH/DELETE /sales/plans/<pk>/` (`SalesDailyPlanDetailView`) | Own only | Own only | Branch team | All |
| `GET/POST /sales/plans/` | Own | Own | Branch | All |
| `GET/POST /sales/activities/` | Own | Own | Branch | All |
| `POST /sales/activities/<id>/photos/` (`SalesActivityPhotoView`) | Own activity (auto-attendance/odometer) | Own | Branch | All |
| `GET /sales/odometer-readings/` + Detail + PATCH (pending) | Own | Own | Branch + approve/reject | All |
| `POST /sales/odometer-readings/<pk>/(approve|reject)/` (daily) | ❌ | ❌ | ✅ (branch) | ✅ |
| `POST /sales/odometer/monthly/(approve|reject)/` (bulk by user/month/year) | ❌ | ❌ | ✅ (ODOMETER_APPROVER_ROLES + branch scoping) | ✅ |
| `POST /sales/plans/send-reminders/` (`TriggerSalesRemindersView`) | ❌ | ❌ | ✅ | ✅ |
| `GET/POST/PATCH /leads/` + `/assign/` + `/reassign/` + `/status/` (`Lead*View`s) | Own leads (restricted) | Full (assign/reassign/status) | Full + review transfers | Full |
| `POST/PATCH /leads/transfer-requests/...` | Request own | Request + review | Review | Review |
| Inventory ViewSets (`ItemCategoryViewSet`, `ItemViewSet`, `ItemAllocationViewSet`, `bulk_issue`, `my_allocations`, `return_item`) | View own (`my/`) | View own | Full CRUD | Full CRUD |
| `GET /auth/notifications/?type=sales|leads|inventory` | ✅ | ✅ | ✅ | ✅ |
| `PATCH /auth/notifications/` | ✅ | ✅ | ✅ | ✅ |

**Notes:** 
- `RESTRICTED_ROLES` limit visibility for junior roles.
- Odometer PATCH allowed only on `status=pending` and `is_paid=False`.
- Lead conversion (`stage=converted`) auto-triggers Admission creation only for authorized users.

---

## Integration Summary (Fully Synchronized with Current Implementation)

- **Sales Plans & Activities (`leads/views.py`):** `SalesDailyPlan` now dual-purpose (plan + scheduled event with `type`/`start_time`/`place`/`reminder_*` flags). `SalesDailyPlanDetailView` provides full CRUD. `SalesActivityPhotoView` auto-creates `EmployeeAttendanceRecord` (GPS + shortfall) on selfies and `OdometerReading` (with `calculate_totals()`, vehicle_type support) on meter photos. `TriggerSalesRemindersView` fires Celery reminders.
- **Odometer & Payroll (`leads/models.py` + `payroll/`):** Vehicle-aware expense calc (2_wheeler=5/km, 4_wheeler=12/km default). `OdometerReadingApproveView`/`RejectView` with guards (`is_paid=False`, both kms required). Integrated via `_get_odometer_expenses_for_user()` into `PaySlip.reimbursements_amount`.
- **Lead CRM (`leads/views.py`):** Role-based `get_lead_queryset()`, split `LeadAssignView` vs `LeadReassignView` (with `LeadAssignmentLog`), `LeadTransferRequest*View`s (audit + 'leads' notifications), `LeadStatusUpdateView` auto-creates `Admission` (with `form_pending`, `AdmissionStatusHistory`, email/WhatsApp) on `stage=converted`.
- **Inventory (`inventory/views.py` + `models.py`):** All legacy ViewSets (`ItemCategoryViewSet`, `ItemViewSet`, `StockTransactionViewSet`, `ItemAllocationViewSet`), `bulk_issue`, `my_allocations`, `return_item` fully preserved. Supports `sales_user`/`student`/`faculty`, atomic tx, `notification_type='inventory'`.
- **Notifications (`auth_user/models.py`):** Unified filtering by `notification_type='sales'|'leads'|'inventory'`. Cross-references to `attendance`, `onboarding`, `chat.notifications` maintained.
- **Legacy Content:** All previous Markdown tables, 9-step ASCII lifecycle, exhaustive photo-type matrix, and old inventory endpoints retained verbatim per documentation policy.

This document serves as the single source of truth for the entire sales module.


