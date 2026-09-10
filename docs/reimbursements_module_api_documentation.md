# Reimbursements Module — Full Walkthrough & API Reference Guide

> **Base URL:** `https://api.example.com/api/v1/reimbursements/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `multipart/form-data` (for submission & proof uploads) / `application/json`  
> **Role-based Access:** All authenticated staff & employees can submit claims; `super_admin`, `admin_senior_executive`, `admin_executive`, `accountant`, and `branch_manager` can approve or reject claims.  
> **Standard Response Envelope:** `{ "success": true/false, "message": "...", "data": {...} }`  

---

## Overview

The `reimbursements` module provides an automated expense reimbursement workflow for all institute staff, faculty, and employee roles. Staff members can submit expense claims with supporting receipt/invoice proofs. Authorized managerial roles review and approve/reject claims. Approved claims automatically integrate into the monthly **Payroll** cycle: approved amounts are credited to the employee's payslip (`reimbursements_amount`), added to their `net_salary`, and marked as paid when the payroll run is disbursed.

---

## Data Models & Statuses

### Core Model: `Reimbursement`

| Field | Type | Description |
|---|---|---|
| `id` | `UUID` (PK) | Primary key (auto-generated UUIDv4) |
| `user` | `ForeignKey(User)` | Staff/Faculty member submitting the expense claim |
| `branch` | `ForeignKey(Branch)` | Branch associated with this claim (auto-assigned from user) |
| `title` | `CharField(255)` | Short title/subject of the expense (e.g., "Seminar Stationery") |
| `description` | `TextField` | Detailed explanation of what was purchased and business purpose |
| `amount` | `Decimal(12, 2)` | Expense amount claimed in INR (must be > 0.00) |
| `proof` | `FileField` | Uploaded receipt, bill, or invoice image/PDF |
| `expense_date` | `DateField` | Date when the expense occurred (defaults to today) |
| `status` | `CharField(20)` | `pending` \| `approved` \| `rejected` (default: `pending`) |
| `approved_by` | `ForeignKey(User)` | Manager/Admin who approved the claim |
| `approved_at` | `DateTimeField` | Timestamp when the claim was approved |
| `rejected_by` | `ForeignKey(User)` | Manager/Admin who rejected the claim |
| `rejected_at` | `DateTimeField` | Timestamp when the claim was rejected |
| `rejection_reason` | `TextField` | Mandatory reason provided when rejecting a claim |
| `payroll_run` | `ForeignKey(PayrollRun)` | Monthly payroll run in which this claim was included |
| `payslip` | `ForeignKey(PaySlip)` | Payslip in which this reimbursement was credited |
| `is_paid` | `BooleanField` | Marked `true` when the corresponding payroll run is disbursed |
| `created_at` | `DateTimeField` | Claim creation timestamp |
| `updated_at` | `DateTimeField` | Last update timestamp |

### Status State Machine

```text
       [ Staff Submits Claim ]
                 │
                 ▼
             ┌─────────┐
             │ pending │ ◄── [ Staff can edit/delete while pending ]
             └────┬────┘
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
  ┌──────────┐        ┌──────────┐
  │ approved │        │ rejected │
  └─────┬────┘        └──────────┘
        │
        ▼ (Included in Monthly Payroll Run)
  ┌──────────┐
  │ is_paid  │ (Marked upon Payroll Disbursal)
  └──────────┘
```

- **`pending`**: Default state. Editable or cancellable by the applicant.
- **`approved`**: Approved by an authorized reviewer. Cannot be edited or deleted. Locked for payroll inclusion.
- **`rejected`**: Rejected with a required `rejection_reason`. Cannot be re-approved.
- **`is_paid = true`**: Set automatically upon `POST /api/v1/payroll/<run_id>/disburse/`.

---

## Role-Based Access Control (RBAC)

All roles are strictly validated against `User.ROLE_CHOICES`:

| Role | Submit Claims | View Own Claims | View Branch Claims | View All Claims | Edit / Delete | Approve / Reject |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Standard Staff / Faculty / Sales / Admin Exec / Coordinators** | ✅ | ✅ | ❌ | ❌ | ✅ (pending only) | ❌ |
| **`branch_manager`** | ✅ | ✅ | ✅ (assigned branch) | ❌ | ✅ (own pending) | ✅ (assigned branch) |
| **`admin_senior_executive` / `admin_executive`** | ✅ | ✅ | ✅ | ✅ | ✅ (own pending, delete any pending) | ✅ |
| **`accountant`** | ✅ | ✅ | ✅ | ✅ | ✅ (own pending, delete any pending) | ✅ |
| **`super_admin`** | ✅ | ✅ | ✅ | ✅ | ✅ (own pending, delete any pending) | ✅ |
| **`student` / `parents`** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

- Constants defined in `reimbursements/views.py`:
  - `GLOBAL_ADMIN_ROLES = {'super_admin', 'admin_senior_executive', 'admin_executive', 'accountant'}`
  - `BRANCH_APPROVER_ROLES = {'branch_manager'}`
  - `APPROVER_ROLES = GLOBAL_ADMIN_ROLES | BRANCH_APPROVER_ROLES`
  - `NON_STAFF_ROLES = {'student', 'parents', 'printers'}`
- Non-approvers can only view their own claims (even if omitting `?my=true`).
- `branch_manager` is automatically restricted to claims originating from staff in their assigned branch(es).
- Students, parents, and printers are blocked from submitting expense reimbursement claims.
- **RBAC Default Accessible Modules**: `reimbursements` is included in `ROLE_PERMISSIONS` under `default_modules` for all staff roles and in `URL_MODULE_MAP` (`^api/v1/reimbursements?/`).
- **Notification API Category**: All reimbursement notifications (submission, approval, rejection) are categorized under `notification_type = 'payroll'`, ensuring they show up in `GET /api/auth/notifications/?type=payroll` (and also in `?type=reimbursement`).

---

## Architecture & Lifecycle Walkthrough

```text
STAFF USER                                   APPROVER (Admin / Branch Manager)            PAYROLL ENGINE
    │                                                        │                                  │
    │── 1. POST /api/v1/reimbursements/ (multipart) ────────►│                                  │
    │      (status='pending', uploads proof)                 │                                  │
    │                                                        │                                  │
    │◄─── [In-app notification sent to super_admin/admins/accountants/branch_managers] ───│                                  │
    │                                                        │                                  │
    │                                                        │── 2. GET /reimbursements/<id>/   │
    │                                                        │      (inspect proof & notes)     │
    │                                                        │                                  │
    │                                                        │── 3. POST /<id>/approve/ ───────►│
    │                                                        │      (status='approved')         │
    │◄─── [Notification: 'Reimbursement Approved'] ──────────│                                  │
    │                                                                                           │
    │                                                        4. Monthly Payroll Generation ────►│
    │                                                           (draft or final run)            │
    │                                                           - Looks up approved unpaid      │
    │                                                           - Adds to payslip.reimbursements│
    │                                                           - Increases net_salary          │
    │                                                                                           │
    │                                                        5. POST /payroll/<id>/disburse/ ──►│
    │                                                           - Payslip disbursed             │
    │                                                           - Marks reimb.is_paid = true    │
    │◄─── [Notification: Payslip disbursed with reimbursements credited] ───────────────────────┘
```

### Step 1: Staff Member Submits a Claim
- An employee incurs an official out-of-pocket expense (e.g., student refreshments, books, travel, stationery).
- Staff calls `POST /api/v1/reimbursements/` with `title`, `description`, `amount`, `expense_date`, and the receipt/invoice file (`proof`).
- Branch is automatically populated from the user profile. Status is set to `pending`.

### Step 2: System Dispatches Real-Time Alert
- Global approver alert: `notify_users_by_role(['super_admin', 'admin_senior_executive', 'accountant'])` and branch alert to `branch_manager` trigger notifications with `metadata={'reimbursement_id': str(id)}`.

### Step 3: Review & Scoping
- Approvers view pending claims via `GET /api/v1/reimbursements/?status=pending`.
- `branch_manager` only sees claims from their branch.
- Admins inspect the claim details and proof URL via `GET /api/v1/reimbursements/<id>/`.

### Step 4: Modifications & Cancellations
- While status is `pending`, the applicant can update claim details via `PATCH /api/v1/reimbursements/<id>/` or delete/cancel the claim via `DELETE /api/v1/reimbursements/<id>/`.
- Once approved or rejected, edits and deletions are strictly blocked (`400 Bad Request`).

### Step 5: Approval or Rejection
- **Approve**: Reviewer calls `POST /api/v1/reimbursements/<id>/approve/`. Status becomes `approved`, `approved_by` and `approved_at` are stamped. An in-app push notification is sent to the claimant.
- **Reject**: Reviewer calls `POST /api/v1/reimbursements/<id>/reject/` with `{ "rejection_reason": "Receipt unreadable" }`. Status becomes `rejected`, `rejected_by` and `rejected_at` are stamped. Claimant is notified with the rejection reason.

### Step 6: Summary Metrics for Dashboards
- Reviewers and accountants call `GET /api/v1/reimbursements/summary/` to get real-time aggregates: total claimed, pending count/amount, approved count/amount, rejected count/amount, and paid count/amount.

### Step 7: Automatic Monthly Payroll Integration
- When the monthly payroll is computed (`compute_payslip_for_faculty` or `compute_payslip_for_user` in `payroll/utils.py`), the system invokes `_get_reimbursements_for_user(user, payroll_run)`:
  - Finds all `Reimbursement` records for that user where `status='approved'` and `is_paid=False`.
  - Calculates `reimbursements_total = sum(r.amount)`.
  - Stamps `reimbursements_amount = reimbursements_total` onto the `PaySlip`.
  - Adds `reimbursements_total` into `net_salary`: `net = max(Decimal(0), net + reimbursements_total)`.
  - Links the reimbursement records to the `payslip` and `payroll_run`.
- In `payroll/pdf_services.py`, `reimbursements_amount` is added to earnings/gross breakdown and rendered in the official PDF payslip.
- In `PayslipAdjustView`, manual accountant adjustments recalculate `net_salary` by preserving `reimbursements_amount`.

### Step 8: Disbursal & Final Settlement
- When the accountant or admin disburses the payroll run via `POST /api/v1/payroll/<run_id>/disburse/`, all linked reimbursements are atomically updated:
  ```python
  Reimbursement.objects.filter(payroll_run=pr).update(is_paid=True)
  ```
- Claims are now fully closed and marked `is_paid=True`.

---

## API Reference

### 1. List / Filter Reimbursements

**`GET /api/v1/reimbursements/`**

Fetches a list of reimbursement claims. Filterable by status, date ranges, user, and branch.

#### Query Parameters
| Parameter | Type | Required | Description |
|---|---|:---:|---|
| `my` | `boolean` | No | If `true` or `1`, forces returning only the logged-in user's claims regardless of reviewer role. |
| `status` | `string` | No | Filter by claim status: `pending`, `approved`, or `rejected`. |
| `user_id` | `uuid` | No | Filter by claimant user UUID (approvers only). |
| `branch_id` | `uuid` | No | Filter by branch UUID (`super_admin` / `admin` only). |
| `from_date` | `date (YYYY-MM-DD)` | No | Filter expenses on or after this date. |
| `to_date` | `date (YYYY-MM-DD)` | No | Filter expenses on or before this date. |
| `month` | `integer (1-12)` | No | Filter expenses occurring in a specific calendar month. |
| `year` | `integer (YYYY)` | No | Filter expenses occurring in a specific calendar year. |

#### Request Headers
```http
Authorization: Bearer <access_token>
```

#### Response Example (`200 OK`)
```json
{
  "success": true,
  "count": 2,
  "data": [
    {
      "id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
      "user": "550e8400-e29b-41d4-a716-446655440000",
      "user_name": "Rohan Sharma",
      "user_email": "rohan.sharma@example.com",
      "user_role": "sales_executive",
      "branch": "880e8400-e29b-41d4-a716-446655440001",
      "branch_name": "Andheri West Center",
      "title": "School Seminar Brochures Printing",
      "description": "Printed 500 promotional brochures for the DPS School seminar.",
      "amount": "2500.00",
      "proof": "http://api.example.com/media/reimbursements/proofs/receipt_500.pdf",
      "expense_date": "2026-09-02",
      "status": "approved",
      "approved_by": "770e8400-e29b-41d4-a716-446655440002",
      "approved_by_name": "Kavita Desai",
      "approved_at": "2026-09-03T11:20:00Z",
      "rejected_by": null,
      "rejected_by_name": null,
      "rejected_at": null,
      "rejection_reason": "",
      "payroll_run": "990e8400-e29b-41d4-a716-446655440003",
      "payroll_month": 9,
      "payroll_year": 2026,
      "payslip": "110e8400-e29b-41d4-a716-446655440004",
      "is_paid": false,
      "created_at": "2026-09-02T14:30:00Z",
      "updated_at": "2026-09-03T11:20:00Z"
    },
    {
      "id": "b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e",
      "user": "550e8400-e29b-41d4-a716-446655440000",
      "user_name": "Rohan Sharma",
      "user_email": "rohan.sharma@example.com",
      "user_role": "sales_executive",
      "branch": "880e8400-e29b-41d4-a716-446655440001",
      "branch_name": "Andheri West Center",
      "title": "Fuel Expense for Client Visit",
      "description": "Travel from center to Borivali for school principal meeting.",
      "amount": "450.00",
      "proof": "http://api.example.com/media/reimbursements/proofs/fuel_receipt.jpg",
      "expense_date": "2026-09-05",
      "status": "pending",
      "approved_by": null,
      "approved_by_name": null,
      "approved_at": null,
      "rejected_by": null,
      "rejected_by_name": null,
      "rejected_at": null,
      "rejection_reason": "",
      "payroll_run": null,
      "payroll_month": null,
      "payroll_year": null,
      "payslip": null,
      "is_paid": false,
      "created_at": "2026-09-05T16:45:00Z",
      "updated_at": "2026-09-05T16:45:00Z"
    }
  ]
}
```

---

### 2. Submit Reimbursement Claim

**`POST /api/v1/reimbursements/`**

Submits a new reimbursement claim. Requires multipart form data since receipt/bill file upload is mandatory.

#### Request Headers
```http
Authorization: Bearer <access_token>
Content-Type: multipart/form-data
```

#### Form-Data Parameters
| Field | Type | Required | Description |
|---|---|:---:|---|
| `title` | `string` | Yes | Short title (max 255 chars). |
| `description` | `string` | No | Detailed description. |
| `amount` | `decimal` | Yes | Expense amount claimed (must be > 0). |
| `proof` | `file` | Yes | Supporting bill, invoice, or receipt (PDF, JPG, PNG). |
| `expense_date` | `date (YYYY-MM-DD)` | No | Date expense was incurred (defaults to current date). |

#### Request Body Example (Multipart Form)
```http
--boundary
Content-Disposition: form-data; name="title"

Seminar Standee Flex Banner
--boundary
Content-Disposition: form-data; name="description"

Emergency banner print for career guidance seminar at St. Xavier's.
--boundary
Content-Disposition: form-data; name="amount"

1850.00
--boundary
Content-Disposition: form-data; name="expense_date"

2026-09-08
--boundary
Content-Disposition: form-data; name="proof"; filename="banner_receipt.pdf"
Content-Type: application/pdf

[binary file data]
--boundary--
```

#### Response Example (`201 Created`)
```json
{
  "success": true,
  "message": "Reimbursement claim submitted successfully.",
  "data": {
    "id": "c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f",
    "user": "550e8400-e29b-41d4-a716-446655440000",
    "user_name": "Rohan Sharma",
    "user_email": "rohan.sharma@example.com",
    "user_role": "sales_executive",
    "branch": "880e8400-e29b-41d4-a716-446655440001",
    "branch_name": "Andheri West Center",
    "title": "Seminar Standee Flex Banner",
    "description": "Emergency banner print for career guidance seminar at St. Xavier's.",
    "amount": "1850.00",
    "proof": "http://api.example.com/media/reimbursements/proofs/banner_receipt.pdf",
    "expense_date": "2026-09-08",
    "status": "pending",
    "approved_by": null,
    "approved_by_name": null,
    "approved_at": null,
    "rejected_by": null,
    "rejected_by_name": null,
    "rejected_at": null,
    "rejection_reason": "",
    "payroll_run": null,
    "payroll_month": null,
    "payroll_year": null,
    "payslip": null,
    "is_paid": false,
    "created_at": "2026-09-08T09:15:00Z",
    "updated_at": "2026-09-08T09:15:00Z"
  }
}
```

#### Validation Error Example (`400 Bad Request`)
```json
{
  "success": false,
  "message": "Validation failed",
  "errors": {
    "amount": [
      "Amount must be greater than zero."
    ],
    "proof": [
      "No file was submitted."
    ]
  }
}
```

---

### 3. Summary Analytics Breakdown

**`GET /api/v1/reimbursements/summary/`**

Provides aggregate counts and monetary totals for claims, broken down by status and payment disbursement state.

#### Query Parameters
| Parameter | Type | Required | Description |
|---|---|:---:|---|
| `my` | `boolean` | No | Scope metrics to logged-in user only. |
| `branch_id` | `uuid` | No | Scope metrics to branch (`super_admin` / `admin` only). |

#### Response Example (`200 OK`)
```json
{
  "success": true,
  "summary": {
    "total_claims": 24,
    "total_amount": "58400.00",
    "pending_count": 6,
    "pending_amount": "12350.00",
    "approved_count": 14,
    "approved_amount": "38250.00",
    "rejected_count": 4,
    "rejected_amount": "7800.00",
    "paid_count": 10,
    "paid_amount": "27400.00"
  }
}
```

---

### 4. Claim Details

**`GET /api/v1/reimbursements/<uuid:pk>/`**

Retrieves full details of a specific claim. Standard users can only view their own claims.

#### Response Example (`200 OK`)
```json
{
  "success": true,
  "data": {
    "id": "c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f",
    "user": "550e8400-e29b-41d4-a716-446655440000",
    "user_name": "Rohan Sharma",
    "user_email": "rohan.sharma@example.com",
    "user_role": "sales_executive",
    "branch": "880e8400-e29b-41d4-a716-446655440001",
    "branch_name": "Andheri West Center",
    "title": "Seminar Standee Flex Banner",
    "description": "Emergency banner print for career guidance seminar at St. Xavier's.",
    "amount": "1850.00",
    "proof": "http://api.example.com/media/reimbursements/proofs/banner_receipt.pdf",
    "expense_date": "2026-09-08",
    "status": "pending",
    "approved_by": null,
    "approved_by_name": null,
    "approved_at": null,
    "rejected_by": null,
    "rejected_by_name": null,
    "rejected_at": null,
    "rejection_reason": "",
    "payroll_run": null,
    "payroll_month": null,
    "payroll_year": null,
    "payslip": null,
    "is_paid": false,
    "created_at": "2026-09-08T09:15:00Z",
    "updated_at": "2026-09-08T09:15:00Z"
  }
}
```

#### Error Example (`404 Not Found`)
```json
{
  "success": false,
  "message": "Reimbursement not found or access denied."
}
```

---

### 5. Update Reimbursement Claim (Partial)

**`PATCH /api/v1/reimbursements/<uuid:pk>/`**

Allows the claimant or an authorized manager to edit fields while the claim is in `pending` status.

#### Request Body Example (JSON or Multipart)
```json
{
  "amount": "1950.00",
  "description": "Updated cost after including delivery fees for flex banner."
}
```

#### Response Example (`200 OK`)
```json
{
  "success": true,
  "message": "Reimbursement updated.",
  "data": {
    "id": "c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f",
    "title": "Seminar Standee Flex Banner",
    "amount": "1950.00",
    "status": "pending"
  }
}
```

#### Error Example: Editing Non-Pending Claim (`400 Bad Request`)
```json
{
  "success": false,
  "message": "Cannot edit claim with status approved."
}
```

---

### 6. Delete / Cancel Claim

**`DELETE /api/v1/reimbursements/<uuid:pk>/`**

Allows the owner or `super_admin`/`admin` to cancel and delete a pending reimbursement claim.

#### Response Example (`200 OK`)
```json
{
  "success": true,
  "message": "Reimbursement deleted."
}
```

#### Error Example: Deleting Approved Claim (`400 Bad Request`)
```json
{
  "success": false,
  "message": "Cannot delete claim with status approved."
}
```

---

### 7. Approve Reimbursement Claim

**`POST /api/v1/reimbursements/<uuid:pk>/approve/`**

Approves the expense claim. Restricted to `super_admin`, `admin_senior_executive`, `admin_executive`, `accountant`, and `branch_manager` (for claims in their assigned branch). Once approved, the claim is queued for inclusion in the user's next monthly payroll run.

#### Request Headers
```http
Authorization: Bearer <access_token>
```
*No request body required.*

#### Response Example (`200 OK`)
```json
{
  "success": true,
  "message": "Reimbursement 'Seminar Standee Flex Banner' approved successfully. Amount will be added to monthly pay.",
  "data": {
    "id": "c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f",
    "title": "Seminar Standee Flex Banner",
    "amount": "1950.00",
    "status": "approved",
    "approved_by": "770e8400-e29b-41d4-a716-446655440002",
    "approved_by_name": "Kavita Desai",
    "approved_at": "2026-09-09T10:15:30Z",
    "is_paid": false
  }
}
```

#### Error Example: Permission Denied (`403 Forbidden`)
```json
{
  "success": false,
  "message": "Permission denied. Only admins or branch managers can approve."
}
```

#### Error Example: Already Approved (`400 Bad Request`)
```json
{
  "success": false,
  "message": "Claim is already approved."
}
```

---

### 8. Reject Reimbursement Claim

**`POST /api/v1/reimbursements/<uuid:pk>/reject/`**

Rejects the expense claim. Restricted to `super_admin`, `admin_senior_executive`, `admin_executive`, `accountant`, and `branch_manager` (for claims in their assigned branch). Requires an explicit explanation in `rejection_reason`.

#### Request Headers
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

#### Request Body
```json
{
  "rejection_reason": "Receipt does not show GST registration details and exceeds the petty-cash threshold without prior PO."
}
```

#### Response Example (`200 OK`)
```json
{
  "success": true,
  "message": "Reimbursement 'Seminar Standee Flex Banner' rejected.",
  "data": {
    "id": "c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f",
    "title": "Seminar Standee Flex Banner",
    "amount": "1950.00",
    "status": "rejected",
    "rejected_by": "770e8400-e29b-41d4-a716-446655440002",
    "rejected_by_name": "Kavita Desai",
    "rejected_at": "2026-09-09T10:20:00Z",
    "rejection_reason": "Receipt does not show GST registration details and exceeds the petty-cash threshold without prior PO."
  }
}
```

#### Error Example: Missing Rejection Reason (`400 Bad Request`)
```json
{
  "success": false,
  "errors": {
    "rejection_reason": [
      "This field is required."
    ]
  }
}
```

---

## Cross-Module Integration Architecture

### 1. Payroll Integration (`payroll/utils.py` & `payroll/views.py`)

```text
┌───────────────────────────────────────┐
│        reimbursements.models          │
│ status = 'approved', is_paid = False  │
└──────────────────┬────────────────────┘
                   │
                   ▼
┌───────────────────────────────────────────────────────────┐
│ payroll.utils._get_reimbursements_for_user(user, run)     │
│ 1. Fetches approved unpaid claims                         │
│ 2. Calculates total reimbursement amount                  │
│ 3. Sets payslip.reimbursements_amount = total             │
│ 4. Adds to net_salary: net = max(0, net + total)          │
│ 5. Links: reimb.update(payslip=slip, payroll_run=run)     │
└──────────────────┬────────────────────────────────────────┘
                   │
                   ▼
┌───────────────────────────────────────────────────────────┐
│ payroll.views.PayrollDisburseView                         │
│ On POST /payroll/<id>/disburse/:                          │
│ Reimbursement.objects.filter(payroll_run=pr).update(      │
│     is_paid=True                                          │
│ )                                                         │
└───────────────────────────────────────────────────────────┘
```

- **Faculty Payslips (`compute_payslip_for_faculty`)**: Reconciles session hours, rates, penalties, and credits `reimbursements_total` directly into `net_salary`.
- **Staff Payslips (`compute_payslip_for_user`)**: Credits `reimbursements_total` for all employee roles (`sales_executive`, `counsellor`, `paper_checker`, `front_desk`, etc.).
- **Payslip Adjustments (`PayslipAdjustView`)**: When accountants edit slips, net calculation preserves:
  $$\text{net\_salary} = \text{basic} + \text{hours\_amount} + \text{bonus} + \mathbf{reimbursements\_amount} - \text{deductions}$$
- **PDF Payslip Generation (`generate_payslip_pdf`)**: Displays `reimbursements_amount` under earnings and calculates `gross_salary` including reimbursements.

### 2. Notifications Integration (`chat.notifications`)
- When a claim is created: `notify_users_by_role(['super_admin', 'admin_senior_executive', 'accountant'])` and branch notification to `branch_manager` trigger system and push alerts.
- When approved: `send_system_notification` sends instant alert to claimant:
  > *"Your reimbursement claim '...' for ₹... has been approved and will be added to your monthly pay."*
- When rejected: Alert sent to claimant with rejection reason:
  > *"Your reimbursement claim '...' for ₹... was rejected. Reason: ..."*

### 3. Role Matrix & Branch Scoping
- Staff members inherit branch assignment automatically.
- Approver resolution verifies `get_user_role(user) in APPROVER_ROLES` (strictly defined from `User.ROLE_CHOICES`).

---

## Testing & Verification Checklist

- [x] **Claim Creation**: Submit valid claim with file upload ➔ Returns `201 Created` with `status='pending'`.
- [x] **Zero / Negative Amount**: Submit claim with amount `0.00` or `-50.00` ➔ Returns `400 Bad Request`.
- [x] **Role Visibility**: Non-approvers receive only their own claims from `GET /api/v1/reimbursements/`.
- [x] **Branch Isolation**: `branch_manager` only sees claims belonging to staff in their assigned branch.
- [x] **Approval Flow**: Approver calls `approve/` ➔ Returns `200 OK`, sets `approved_by` and `approved_at`.
- [x] **Rejection Flow**: Approver calls `reject/` with reason ➔ Returns `200 OK`, sets `rejection_reason`.
- [x] **Editing Guard**: Attempting to edit or delete approved claim ➔ Returns `400 Bad Request`.
- [x] **Payroll Engine Credit**: Generate payroll run ➔ Payslip reflects `reimbursements_amount` in `data` and adds to `net_salary`.
- [x] **Payroll Disbursal Hook**: Disburse payroll run ➔ Reimbursement record transitions to `is_paid=True`.
