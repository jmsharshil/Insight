# Leave Module — API Documentation

The `leave` module manages staff/faculty leave requests, **conditional student leave approvals**, leave policies, public holidays, and late entry records.

**Key Recent Feature**: Student leaves enforce **parent-first conditional approval** (for student-submitted apps) using existing `StudentLeaveApplication` fields (`parent_consulted`, `parent_signature_date`, `status='pending'`, `received_by`, `reviewed_by`). No model changes or new migrations. Logic lives in `leave/views.py` + `dashboard/services.py`. Notifications and role-aware dashboard pending counts included. Parent-submitted leaves bypass to direct admin approval.

---

## Data Model

| Model | Purpose |
|---|---|
| `LeavePolicy` | Rules per leave type (e.g., Paid Leave, Sick Leave), quotas, and sandwich rules |
| `LeaveBalance` | Tracks a user's used and remaining days per leave type per year |
| `LeaveApplication` | Staff/faculty leave request (single/multi-day/half-day; multi-approver flow) |
| `StudentLeaveApplication` | Student leave request. **Reuses** `parent_consulted` (workflow toggle: False=needs parent step), `parent_signature_date`, `received_by`, `reviewed_by`, `status` for conditional parent→admin approval. Uses student-specific types + proof upload. |
| `PublicHoliday` | Branch-level list of public holidays (blocks overlapping applications) |
| `LateEntryRecord` | Tracks late arrivals. Auto half-day deduction per policy. |

**Note**: `StudentLeaveApplication.status_display` and dashboard `_get_leave_dashboard_data()` compute contextual labels like "Parent Approval Pending" based on `parent_consulted`.

---

## API Endpoints

### 1. Leave Policies
**`GET /api/v1/leave/policy/`**
**`GET / PATCH /api/v1/leave/policy/<uuid>/`**

### 2. Leave Balances
**`GET /api/v1/leave/balance/`**
**`GET /api/v1/leave/balance/<user_id>/`**
Check remaining leaves for the logged-in user or a specific user.

### 3. Staff / Faculty Leave Applications
**`GET /api/v1/leave/`**
**`POST /api/v1/leave/`**
Apply for a new leave.

**`GET /api/v1/leave/<uuid>/`**

**`POST /api/v1/leave/<uuid>/approve/`**
**`POST /api/v1/leave/<uuid>/reject/`**
Managerial endpoints (multi-approver: ASE → BM).

### 4. Public Holidays
**`GET /api/v1/leave/public-holidays/`**
**`POST /api/v1/leave/public-holidays/`**
**`GET / PATCH / DELETE /api/v1/leave/public-holidays/<uuid>/`**

### 5. Late Entries
**`GET /api/v1/leave/late-entries/`**
**`POST /api/v1/leave/late-entries/`**
Record a late arrival.

**`GET /api/v1/leave/late-entries/<uuid>/`**

### 6. Student Leave Applications (Conditional Approval)
See dedicated section below for parent-first workflow, role-based creation, shared `/approve/` endpoint (parents + admins), and computed status displays.

---

## Student Leave APIs

Student leave uses a **conditional two-step approval workflow** (no model changes; reuses `parent_consulted`, `parent_signature_date`, `status`, `received_by`, `reviewed_by` fields). 

- **Student-submitted** (`parent_consulted=False` at creation): Requires **parent approval first**, then admin.
- **Parent-submitted** (`parent_consulted=True`): Skips to admin approval only.
- Notifications drive the flow (`chat.notifications`): parents get "parent_approval" step; admins get "admin_approval".
- Dashboard and serializers compute role-aware `status_display` (`'Parent Approval Pending'` vs `'Admin Approval Pending'`).
- `STUDENT_LEAVE_ADMIN_ROLES = ['super_admin', 'branch_manager', 'admin_senior_executive']` for final approval.

### Leave Types (`leave_type` field)
Same as before (student-specific):

| Key | Label |
|---|---|
| `casual` | Casual Leave |
| `medical` | Medical Leave |
| `emergency` | Emergency Leave |
| `exam` | Exam Leave |
| `mobile_usage` | Mobile Usage Permission |
| `uniform` | Uniform Leave |

### Endpoints

#### List / Create
**`GET /api/v1/leave/student/`**
- **Admins/staff**: All applications in their branch/org (with filters).
- **Students/Parents**: Only their own / linked student's applications.
- Returns `parent_consulted`, computed `status_display`, `proof_document_url`, reviewer names.

**`POST /api/v1/leave/student/`**
- **Parents role**: Auto-sets `parent_consulted=True`, `parent_signature_date=today`, `received_by=parent`, notifies admins.
- **Students role**: Sets `parent_consulted=False`, notifies linked `ParentLink` parents.
- **Admins**: Can create directly for any student.
- `student_id` auto-resolved for non-admins.

---

#### Detail / Edit / Cancel
**`GET /api/v1/leave/student/<uuid>/`**
Full details (includes `parent_consulted`, `status_display`, `proof_document_url`, `reviewed_by_name` etc.). Supports `?expand=student,batch`.

**`PATCH /api/v1/leave/student/<uuid>/`**
- Only owner (student or linked parent via `_is_parent_of`).
- Only if `status=pending`.
- Supports updating parent fields, dates, reason, proof, etc.

**`DELETE /api/v1/leave/student/<uuid>/`**
- Owner only, sets `status='cancelled'` if pending.

---

#### Approve / Reject
**`POST /api/v1/leave/student/<uuid>/approve/`** (shared endpoint)
- **If `parent_consulted=False` and requester is linked parent**: Sets `parent_consulted=True`, `parent_signature_date=now.date()`, `received_by=parent`, notifies admins ("now pending final admin approval").
- **If admin role**: Sets `status='approved'`, `reviewed_by=requester`, notifies student + parents.
- Returns contextual success message.

**`POST /api/v1/leave/student/<uuid>/reject/`**
- **Admin-only**. Body: `{"rejection_reason": "..."}`.
- Sets `status='rejected'`, stores reason, notifies applicant.

**Note**: `_is_parent_of()` uses `ParentLink` (prefers `is_primary=True`). Rejects invalid role/state transitions with clear messages.

---

### Student Leave Status Flow & Displays

```
Student submits (pending, parent_consulted=False)
    ↓ (parent /approve/)
Parent approves → (pending, parent_consulted=True, notifies admins)
    ↓ (admin /approve/)
Admin approves → approved
          or
      (at any pending stage) → rejected (admin) or cancelled (owner)
```

**Computed `status_display`** (in serializers + dashboard):
- `pending` + `!parent_consulted` → "Parent Approval Pending"
- `pending` + `parent_consulted` → "Admin Approval Pending"
- `approved`, `rejected`, `cancelled` → standard display

---

### Student Leave Response Example

```json
{
  "id": "uuid",
  "student": "student-uuid",
  "student_name": "Rahul Sharma",
  "batch_name": "JEE 2026",
  "leave_type": "medical",
  "leave_type_display": "Medical Leave",
  "from_date": "2026-06-24",
  "to_date": "2026-06-25",
  "from_time": null,
  "to_time": null,
  "reason": "Doctor visit",
  "is_capable_of_proof": true,
  "proof_document_url": "https://.../leave/student_proof/cert.pdf",
  "parent_consulted": false,
  "parent_signature_date": null,
  "status": "pending",
  "status_display": "Parent Approval Pending",
  "received_by": null,
  "reviewed_by": null,
  "reviewed_by_name": null,
  "reviewed_at": null,
  "rejection_reason": "",
  "created_at": "2026-06-23T07:45:00Z"
}
```

---

## Cross-Module Integration

```text
┌──────────────────────┐     ┌──────────────────────┐
│ Leave Module         │────►│ Payroll Module        │
│ Approved leaves      │     │ Unpaid leaves trigger │
│ (staff + student)    │     │ deductions. Leave     │
│ LateEntryRecords     │     │ encashment applied.   │
└──────────────────────┘     └──────────────────────┘

┌──────────────────────┐     ┌──────────────────────┐
│ Leave Module         │────►│ Attendance Module     │
│ Approved leaves      │     │ Attendance records    │
│ (staff + student)    │     │ auto-flagged as       │
│                      │     │ "on_leave" status.    │
└──────────────────────┘     └──────────────────────┘

┌──────────────────────┐     ┌──────────────────────┐
│ Leave Module         │────►│ Chat/Notifications    │
│ StudentLeave         │     │ Parent-first workflow │
│ (parent_consulted)   │     │ + admin alerts via    │
│                      │     │ send_system_notification │
└──────────────────────┘     └──────────────────────┘

┌──────────────────────┐     ┌──────────────────────┐
│ Leave Module         │────►│ Dashboard Module      │
│ Student leaves       │     │ Role-aware pending_   │
│ + parent_consulted   │     │ count + recent_leaves │
│                      │     │ with status_display   │
└──────────────────────┘     └──────────────────────┘
```

**Key Integrations:**
- **Payroll/Attendance**: Approved `LeaveApplication` + `StudentLeaveApplication` (when status=approved) affect payslips, deductions, and attendance flagging (`on_leave`).
- **Notifications** (`chat.notifications.send_system_notification`): Used in student leave flow for parent alerts (`step=parent_approval`, metadata with `student_leave_id`), admin notifications, and post-approval/rejection to student+parents.
- **Dashboard** (`dashboard/services.py:_get_leave_dashboard_data`): 
  - Staff: uses `LeaveBalance` + `LeaveApplication` aggregates.
  - Students/Parents: queries `StudentLeaveApplication` (scoped by student/ParentLink), role-aware `pending_count` (parents see only `parent_consulted=False` ones needing their action), `recent_leaves` with computed `status_display` and `parent_consulted` fields for UI consistency with serializers.
- **Students Module**: `ParentLink` for `_is_parent_of()` and parent notifications/lookup (prefers `is_primary=True`).

**Implementation Note**: All student leave conditional logic is view-layer only (`StudentLeaveListCreateView`, `StudentLeaveApproveView`, helpers like `_notify_admins`, `_is_parent_of`, `_user_role`, `_user_branch_id`, `_is_parent_of`). Preserves existing staff multi-approver patterns. No changes to `leave/models.py`.

---

**Last Updated**: With conditional parent-first approval workflow, role-aware dashboard integration, and notification-driven steps (Oct 2024). See `leave/views.py` and `dashboard/services.py` for implementation details matching this documentation.

