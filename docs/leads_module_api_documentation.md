# Leads Module — Full Walkthrough & API Reference Guide

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `application/json`  
> Role-scoped visibility: Counsellors see only assigned leads; BM/Admin see branch/org leads.

---

## Key Utility Functions (in `leads/services.py` or views)

- **Stage updates** create immutable `LeadStage` entries.
- **Assignment** creates `LeadAssignmentLog`.
- **Assignment**: Pure round-robin via `leads.signals.auto_assign_lead` (pre_save signal). Uses `form_type` (`contact` → `tele_caller` role, `inquiry` → `counsellor` role) with `get_role_filter_q`. Does **not** override existing `assigned_to`. Calls `notify_new_lead_assignment`.
- **Conversion** (`converted` stage): **Auto-conversion signal to `onboarding.Admission` is now commented out** (manual CRM → Admission onboarding flow preferred via new `Admission` model in `admissions/models.py`).
- New sales models integrated: `SalesDailyPlan`, `SalesDailyActivity`, `SalesActivityPhoto`, `OdometerReading` (payroll linkage, approval workflow, vehicle rates).

**Integration:** `converted` lead → `onboarding_admissions_api_documentation.md` (form submission → fees/student creation). Ties to updated fees installment rules on enrollment.

---

## Data Models & Statuses

### Core Models
| Model | Purpose |
|-------|---------|
| `Lead` | Inquiry (contact/inquiry form data, stage, assigned_counsellor, linked admission on conversion) |
| `LeadStage` | Immutable stage history log |
| `LeadAssignmentLog` | Immutable assignment/reassignment audit |

### Lead Stages (with transitions)
- `new` (default on creation)
- `contacted`
- `interested`
- `visit`
- `follow_up`
- `converted` (terminal → creates Admission)
- `lost` (terminal)

**Course Types:** `cseet`, `cs_executive`, `cs_professional` (maps to fees level rules).

---

## Architecture & Workflow Diagram

```text
WEB FORM (Contact/Inquiry) ──► Lead (new) 
          │
          ▼
**auto_assign_lead** (pre_save signal, pure round-robin by `form_type` via `get_role_filter_q` → tele_caller/counsellor)
          │
          ▼
Counsellor/Telecaller assignment + `notify_new_lead_assignment` (system notif)
          │
          ▼
Stage progression (POST /status/) → immutable `LeadStage` history + `LeadAssignmentLog`
          │
          ▼
`converted` stage (manual) ──► **Admission pipeline** (new `admissions.Admission` model, status workflow, bank round-robin, Razorpay)
          │
          ▼
Onboarding flow (form submission → fees bank select via `fees.utils`, payment, approval → Student + StudentFee)
          │
          └─► `get_installment_plan_status()` based on `CourseLevel.course_type`
```

**Key Points:**
- Round-robin is automatic on Lead creation/update (no override of existing assignee).
- Conversion signal to Admission **disabled** (use manual Admission creation or dedicated CRM flow).
- New sales activity models (`SalesDailyPlan`, `SalesDailyActivity` etc.) link to payroll for field team (odometer claims, daily plans, photo proofs, manager approval).
- All stage/assignment changes immutable for audit.
- Role-based filtering in list view (counsellor sees only assigned).
- Feeds into updated `admissions`, `fees`, `students`, `payroll` modules.

---

## FULL WALKTHROUGH: Lead to Admission Conversion

### Step 1: Lead Capture
Public or admin POST to create Lead (`new` stage, form_type=contact/inquiry).

### Step 2: Assignment
Automatic round-robin via signal on Lead save (`auto_assign_lead`). Uses `form_type` to select role (`tele_caller` for contact forms, `counsellor` for inquiries). `notify_new_lead_assignment` fires. Manual re-assignment via `/assign/` still supported (logs to `LeadAssignmentLog`).

### Step 3: Pipeline Management
Counsellor/Telecaller updates stage progressively with notes. Immutable `LeadStage` + assignment logs for full audit trail.

### Step 4: Conversion
`converted` stage no longer auto-creates Admission (signal commented). Use dedicated **Admission onboarding pipeline** (see `onboarding_admissions_api_documentation.md` and new `admissions/models.py` with `AdmissionStatusHistory`, bank round-robin, Razorpay integration, full student data fields).

### Step 5: Onward Flow
Manual creation of `Admission` (status workflow: `form_pending` → `payment_pending` → `approved` etc.). Links to `fees.utils.select_bank_accounts_for_payment()`, installment rules via `CourseLevel.course_type`, enrollment to Student/StudentFee.

**Example:** Converted CSEET lead with fee_structure creates StudentFee with default 1-installment (approved) or multi (pending_approval if >2).

### Step 6: Analytics
Leads list with filters for conversion rate tracking. Lost leads with reasons.

---

## Complete API Reference

### List Leads
**`GET /api/v1/leads/`** — Paginated. Role-scoped (counsellor sees assigned only).

**Query Params:** `form_type` (`contact`/`inquiry`), `current_stage`, `course`, `assigned_to`, `search` (name/phone/email), `date_from`, `date_to`.

**Response Example:**
```json
{
  "success": true,
  "count": 42,
  "data": [
    {
      "id": "lead-uuid-001",
      "first_name": "Priya",
      "surname": "Shah",
      "phone_student": "9876543210",
      "email": "priya@example.com",
      "course": "cseet",
      "current_stage": "interested",
      "assigned_to": {"id": "coun-uuid", "name": "Riya Patel"},
      "created_at": "2026-06-01T10:00:00Z",
      "stage_history_count": 3
    }
  ]
}
```

### Lead Detail & Update
- **GET** `/api/v1/leads/<lead_id>/` — Full + full stage/assignment history.
- **PATCH** `/api/v1/leads/<lead_id>/` — Update notes, details, or basic fields.

**PATCH Example:**
```json
{
  "note": "Student visited campus, very interested in CS Executive program.",
  "course": "cs_executive"
}
```

### Stage Update
**`POST /api/v1/leads/<lead_id>/status/`**

**Request:**
```json
{
  "stage": "visit",
  "note": "Campus visit scheduled for June 15. Discussed fees and batch options."
}
```

**Success:**
```json
{
  "success": true,
  "message": "Stage updated to visit.",
  "data": {
    "current_stage": "visit",
    "stage_history": [
      {"stage": "new", "note": "Initial inquiry", "changed_at": "..."},
      ...
    ]
  }
}
```

**Transition Validation:** Enforced per rules (e.g. cannot jump new → converted directly). `converted` triggers Admission creation.

### Assignment
- **POST** `/api/v1/leads/<lead_id>/assign/` (Admin/BM)

**Request:**
```json
{
  "counsellor_id": "coun-uuid-001",
  "note": "Assigned based on CSEET expertise."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Lead assigned to Riya Patel.",
  "data": {"assigned_to": "Riya Patel", "assignment_history": [...]}
}
```

- **POST** `/api/v1/leads/<lead_id>/reassign/` — Similar for changes.

### Conversion Specifics
When stage=`converted`:
- Creates `Admission` (pre-fills data from Lead).
- Sets `Lead.admission = new_admission`.
- Can pass additional data in status update for fee_structure, etc.
- Flows directly into onboarding (payment_pending with bank selection).

**Error Example (invalid transition):**
```json
{
  "success": false,
  "message": "Invalid stage transition from 'new' to 'converted'.",
  "allowed": ["contacted", "lost"]
}
```

---

## Stage Transition Rules (Enforced in Service/View)

| Current | Allowed Next |
|---------|--------------|
| new | contacted, lost |
| contacted | interested, follow_up, lost |
| interested | visit, follow_up, converted, lost |
| visit | converted, follow_up, lost |
| follow_up | converted, lost |
| converted / lost | (terminal) |

**Conversion Note:** Triggers `onboarding.Admission` + email if configured. Links to fees on enrollment (installment plans per level.name).

---

## Role-Based Access & Permissions

| Role | Can View | Can Assign | Can Update Stage | Can Convert |
|------|----------|------------|------------------|-------------|
| super_admin / admin | All | Yes | Yes | Yes |
| branch_manager | Branch | Yes | Yes | Yes |
| counsellor | Assigned only | No | Yes (own leads) | Yes |
| faculty / student | None | No | No | No |

**Filters auto-applied** in ListView based on user role/branch/organization.

---

## Sales Daily Activities & Lead Transfer Requests

Starting with the sales field-activity release, the `leads` application also powers:
1. **Sales Daily Activity & GPS Verification**: Field tracking for sales executives with odometer, visit, and exhibition photo uploads.
   - `GET /api/v1/sales/activities/`
   - `POST /api/v1/sales/activities/`
   - `POST /api/v1/sales/activities/<activity_id>/photos/`
2. **Lead Transfer Requests**: Workflow for sales representatives and counsellors to request lead handovers to colleagues.
   - `POST /api/v1/leads/transfer-requests/`
   - `GET /api/v1/leads/transfer-requests/`
   - `PATCH /api/v1/leads/transfer-requests/<id>/review/`
3. **Odometer Approval & Travel Reimbursement**: Tracking daily kilometers, managerial approval with editable `expense_per_km`, and automated settlement via monthly payslips (`PaySlip.reimbursements_amount`).
   - `GET /api/v1/sales/odometer-readings/`
   - `GET /api/v1/sales/odometer-readings/<id>/`
   - `POST /api/v1/sales/odometer-readings/<id>/approve/`
   - `POST /api/v1/sales/odometer-readings/<id>/reject/`

👉 **Full Guide**: For detailed request/response examples, date/name filters, and constraints, see [sales_module_api_documentation.md](file:///c:/Users/Admin/OneDrive%20-%20JMS%20Advisory%20Services%20Private%20Limited/Desktop/Insight/docs/sales_module_api_documentation.md).

---

**Related Modules & Docs:**
- `sales_module_api_documentation.md` (Sales field activities, GPS/meter verification, lead transfers)
- `onboarding_admissions_api_documentation.md` (conversion target)
- `students_module_api_documentation.md` (post-enrollment profile)
- `fees_module_api_documentation.md` (bank selection on form submit, installment creation on enrollment)
- `attendance_procedure_guide.md`, `payroll_module_api_documentation.md`

This updated documentation aligns with the enhanced fees/onboarding/students flows (level-based status, utils integration, signals/services). All endpoints, request/response examples, rules, and cross-module links included.
