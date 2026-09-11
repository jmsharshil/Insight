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

The sales suite covers five core operational capabilities:
1. **Sales Daily Field Activity & GPS/Odometer Tracking**: Daily activity logging for on-ground sales reps with geo-tagged and timestamped verification photos (start/end selfies, odometer readings, school visits, and exhibition evidence).
2. **Odometer Reading Approval & Travel Reimbursement**: Automated odometer calculation (`total_kms = end_kms - start_kms`) with managerial approval workflow (custom editable `expense_per_km`), monthly payslip credit (`reimbursements_amount`), and automatic settlement on payroll disbursement.
3. **Sales Inventory Allocation**: Material issue and tracking (brochures, promotional kits, standees, marketing collateral) assigned directly to sales personnel.
4. **Notification Types & Filter Integration**: Categorized push notifications and notification history filtering (`notification_type='sales'`, `notification_type='leads'`, and `notification_type='inventory'`) with auto-routing.
5. **Lead Transfer Requests**: Workflow for field reps to request transferring assigned leads to colleagues with senior managerial review.

---

## Data Models & Field Reference

### 1. `SalesDailyActivity` (`leads/models.py`)

Represents a single field-work container for a sales user on a specific calendar day.

| Field | Type | Description |
|---|---|---|
| `id` | `UUID` (PK) | Auto-generated UUIDv4 |
| `user` | `ForeignKey(User)` | Sales employee performing field activities |
| `activity_date` | `DateField` | Date of field activity (default: today). Unique per user per day |
| `notes` | `TextField` | Daily summary, school visit targets, or remarks |
| `photos` | `Reverse(SalesActivityPhoto)` | Related verification photos captured during the day |
| `odometer_reading` | `Reverse(OdometerReading)` | Linked travel kilometer calculation and approval record |
| `created_at` | `DateTimeField` | Record creation timestamp |
| `updated_at` | `DateTimeField` | Last update timestamp |

**Constraint:** Unique constraint on `['user', 'activity_date']` ensures only one activity record exists per sales representative per day. Submitting for the same day updates the existing record.

---

### 2. `SalesActivityPhoto` (`leads/models.py`)

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

### 3. `OdometerReading` (`leads/models.py`)

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

### 4. `ItemAllocation` for Sales Users (`inventory/models.py`)

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

### 5. `NotificationHistory` & Categories (`auth_user/models.py`)

System notifications stamped with `notification_type` choices:
`system`, `authentication`, `admission`, `attendance`, `timetable`, `chat`, `exam`, `fees`, `inventory`, `leads`, `leave`, `payroll`, `results`, `sales`, `support`.

- Odometer submissions, approvals, and rejections are categorized under `sales`.
- Sales/Leads CRM notifications are categorized under `leads`.
- Inventory notifications are categorized under `inventory`.

---

## Architecture & Workflows

### Daily Field Work Lifecycle

```tex[ SALES REP MORNING ROUTINE ]
  │
  ├── 1. POST /api/v1/sales/activities/ ────────────────────────► Creates/initializes daily activity
  │      {"activity_date": "2026-09-10", "notes": "Visiting 3 schools"}
  │
  ├── 2. POST /api/v1/sales/activities/<id>/photos/ ─────────────► Uploads 'start_selfie' (with GPS)
  │
  ├── 3. POST /api/v1/sales/activities/<id>/photos/ ─────────────► Uploads 'start_odometer' (with GPS + odometer_kms)
  │      └─► Automatically creates OdometerReading (start_kms=14250.50, status='pending')
  │
[ FIELD VISITS DURING THE DAY ]
  │
  ├── 4. POST /api/v1/sales/activities/<id>/photos/ ─────────────► School 1: 'school_exterior' + 'school_interior'
  │
  ├── 5. POST /api/v1/sales/activities/<id>/photos/ ─────────────► Exhibition: 'exhibition' photos (up to 6)
  │
[ EVENING CHECKOUT & REIMBURSEMENT APPROVAL ]
  │
  ├── 6. POST /api/v1/sales/activities/<id>/photos/ ─────────────► Uploads 'end_odometer' (with final kms)
  │      ├─► Automatically updates OdometerReading (end_kms=14298.20, total_kms=47.70)
  │      └─► Dispatches push notification (type='sales') to Branch Managers / Super Admins
  │
  ├── 7. POST /api/v1/sales/activities/<id>/photos/ ─────────────► Uploads 'end_selfie' (end of day)
  │
  └── 8. POST /api/v1/sales/odometer-readings/<id>/approve/ ──────► Manager approves reading + enters expense_per_km
         ├─► Computes total_expense = total_kms * expense_per_km
         ├─► Sends in-app notification (type='sales') to Sales Representative
         ├─► Automatically included under 'reimbursements_amount' in monthly PaySlip
         └─► Automatically marked 'is_paid=True' when PayrollRun is disbursed
```

---

## Complete API Reference

### 1. List Sales Daily Activities

**`GET /api/v1/sales/activities/`**

Retrieves daily activity logs including all attached photos, linked odometer reading, and user details.
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

#### 💡 New Day Empty Fields Behavior (Mobile / Frontend Guidance)
To prevent the mobile app from displaying yesterday's filled fields on a new day:
- On app launch, query:
  ```http
  GET /api/v1/sales/activities/?date=today
  ```
- **If the sales representative has not created an activity for today yet**, the API returns an **empty array (`[]`)**.
- When the frontend receives `[]`, it must render **blank, fresh upload inputs** (Start Selfie, Start Odometer, etc.).
- When the sales representative uploads photos or saves notes, the today record is created and will be returned on subsequent queries.

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

### 2. Create or Initialize Daily Activity Container

**`POST /api/v1/sales/activities/`**

Initializes the day's field container or updates notes for the specified date.

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
  "activity_date": "2026-09-10",
  "notes": "Targeting Malad and Kandivali schools for CS Executive counseling.",
  "photos": [],
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

### 3. Upload Sales Activity Photo Evidence

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

#### Response Example (`201 Created`)
```json
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
}
```

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

### 4. List Odometer Readings

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

### 5. Retrieve Single Odometer Reading

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

### 6. Approve Odometer Reading

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

### 7. Reject Odometer Reading

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

### 8. Monthly Payslip Integration & Settlement Workflow

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

### 9. Allocate Inventory to Sales Users

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

### 10. Bulk Issue Inventory to Sales User

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

### 11. Filtered Notifications for Sales Users

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

### 12. Mark All Notifications as Read

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

### 13. Lead Transfer Request & Review

#### Request Transfer (Sales Rep)
**`POST /api/v1/leads/transfer-requests/`**

Allows a sales representative or counsellor to formally request transferring a lead they own to another counselor/rep.

```json
{
  "lead_id": 105,
  "reason": "Student relocating to Dadar branch; requesting handover to Dadar sales executive."
}
```

#### Response Example (`201 Created`)
```json
{
  "id": 14,
  "lead": 105,
  "lead_name": "Neha Joshi",
  "requested_by": "Aakash Mehta",
  "reason": "Student relocating to Dadar branch; requesting handover to Dadar sales executive.",
  "status": "pending",
  "created_at": "2026-09-10T11:15:00Z"
}
```

#### Review Transfer Request (Senior Roles / BM / Admin)
**`PATCH /api/v1/leads/transfer-requests/<id>/review/`**

Approves or rejects the transfer. Upon approval, updates `lead.assigned_to`, creates an immutable `LeadAssignmentLog`, and sends a push notification to the new assignee.

```json
{
  "status": "approved",
  "assigned_to": "660e8400-e29b-41d4-a716-446655440005"
}
```

#### Response Example (`200 OK`)
```json
{
  "id": 14,
  "lead": 105,
  "lead_name": "Neha Joshi",
  "status": "approved",
  "reviewed_by": "Kavita Desai",
  "assigned_to": "Riya Patel"
}
```

---

## Role Permissions Matrix

| Endpoint | Sales Executive / Tele Caller | Sales Senior Exec | Branch Manager | Super Admin / Accountant |
|---|:---:|:---:|:---:|:---:|
| `GET /sales/activities/` | Own activities | Own activities | Branch sales team | All sales team |
| `POST /sales/activities/` | ✅ | ✅ | ✅ | ✅ |
| `POST /sales/activities/<id>/photos/` | ✅ (own activity) | ✅ (own activity) | ✅ | ✅ |
| `GET /sales/odometer-readings/` | Own readings | Own readings | Branch sales team | All sales team |
| `GET /sales/odometer-readings/<pk>/` | Own reading | Own reading | Branch sales team | All sales team |
| `POST /sales/odometer-readings/<pk>/approve/` | ❌ | ❌ | ✅ (own branch) | ✅ (all) |
| `POST /sales/odometer-readings/<pk>/reject/` | ❌ | ❌ | ✅ (own branch) | ✅ (all) |
| `POST /inventory/allocations/` (receive) | ✅ (recipient) | ✅ (recipient) | ✅ (assigner) | ✅ (assigner) |
| `GET /notifications/?type=sales` | ✅ (own) | ✅ (own) | ✅ (own) | ✅ (own) |
| `POST /leads/transfer-requests/` | ✅ (assigned leads) | ✅ (assigned leads) | ❌ | ❌ |
| `PATCH /leads/transfer-requests/<id>/review/` | ❌ | ✅ | ✅ | ✅ |

---

## Integration Summary

- **Leads & Sales Activities (`leads/`):** Links sales activity logs directly into CRM field presence, tracks daily GPS/odometer readings, provides manager approve/reject endpoints with editable per-km rates, and enables peer lead transfer workflows.
- **Monthly Payroll (`payroll/`):** Approved, unpaid odometer readings are automatically queried via `_get_odometer_expenses_for_user()`, credited on the employee's monthly `PaySlip` under `reimbursements_amount`, linked to `PayrollRun`, and marked `is_paid=True` upon disbursement.
- **Inventory Module (`inventory/`):** Dedicated tracking of marketing assets, brochures, and seminar standees assigned to sales reps with `ItemAllocation.sales_user`.
- **Chat & Notifications (`chat.notifications`, `auth_user`):** Real-time alerts stamped with `notification_type='sales'` for odometer reading approvals and submissions, allowing granular client-side filtering via `GET /api/auth/notifications/?type=sales`.

