# Leave Module — API Documentation

The `leave` module manages staff and faculty leave requests, leave policies, public holidays, and late entry records.

---

## Data Model

| Model | Purpose |
|---|---|
| `LeavePolicy` | Rules per leave type (e.g., Paid Leave, Sick Leave), quotas, and sandwich rules |
| `LeaveBalance` | Tracks a user's used and remaining days per leave type per year |
| `LeaveApplication` | An employee's request for leave (can be single, multi-day, or half-day) |
| `PublicHoliday` | Branch-level list of public holidays |
| `LateEntryRecord` | Tracks late arrivals. Can automatically trigger a half-day deduction based on policy |

---

## API Endpoints

### 1. Leave Policies
**`GET /api/v1/leave/policy/`**
**`GET / PATCH /api/v1/leave/policy/<uuid>/`**

### 2. Leave Balances
**`GET /api/v1/leave/balance/`**
**`GET /api/v1/leave/balance/<user_id>/`**
Check remaining leaves for the logged-in user or a specific user.

### 3. Leave Applications
**`GET /api/v1/leave/`**
**`POST /api/v1/leave/`**
Apply for a new leave.

**`GET /api/v1/leave/<uuid>/`**

**`POST /api/v1/leave/<uuid>/approve/`**
**`POST /api/v1/leave/<uuid>/reject/`**
Managerial endpoints to approve or reject leave requests.

### 4. Public Holidays
**`GET /api/v1/leave/public-holidays/`**
**`POST /api/v1/leave/public-holidays/`**
**`GET / PATCH / DELETE /api/v1/leave/public-holidays/<uuid>/`**

### 5. Late Entries
**`GET /api/v1/leave/late-entries/`**
**`POST /api/v1/leave/late-entries/`**
Record a late arrival.

**`GET /api/v1/leave/late-entries/<uuid>/`**
