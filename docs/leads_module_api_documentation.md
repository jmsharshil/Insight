# Leads Module — Full Walkthrough & API Reference Guide

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `application/json`  
> Role-scoped visibility: Counsellors see only assigned leads; BM/Admin see branch/org leads.

---

## Key Utility Functions (in `leads/services.py` or views)

- **Stage updates** create immutable `LeadStage` entries.
- **Assignment** creates `LeadAssignmentLog`.
- **Conversion** (`converted` stage): Auto-creates linked `onboarding.Admission` record (with `fee_structure` if provided), triggers onboarding flow (bank assignment via `fees.utils.select_bank_accounts_for_payment()`, email, etc.).
- Round-robin counsellor assignment in related onboarding.

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
Counsellor assignment (POST /assign/) + logs
          │
          ▼
Stage progression (POST /status/) → LeadStage history
          │
          ▼
converted stage ──► Auto create Admission (onboarding)
          │
          ▼
onboarding flow (form, payment_pending via fees bank select, enrollment → Student + StudentFee)
          │
          └─► fees.utils.get_installment_plan_status() + update_student_fee_status()
```

**Key Points:**
- All stage/assignment changes immutable for audit.
- Conversion links `Lead.admission` (OneToOne).
- Role-based filtering in list view.
- Feeds into updated onboarding/students/fees chain (pending_approval installments, QR fee checks).

---

## FULL WALKTHROUGH: Lead to Admission Conversion

### Step 1: Lead Capture
Public or admin POST to create Lead (`new` stage, form_type=contact/inquiry).

### Step 2: Assignment
Admin/BM assigns to counsellor (round-robin possible via services). Logs change.

### Step 3: Pipeline Management
Counsellor updates stage progressively with notes. Each change logged in `LeadStage`.

### Step 4: Conversion
Set stage=`converted` + optional `admission_data`. Auto-creates `Admission` record (status=`form_pending`), links back to Lead.

### Step 5: Onward Flow
See `onboarding_admissions_api_documentation.md`: student fills form → bank assigned (fees.utils) → payment → approval → enrollment → Student + fees (with level-based installment status from `get_installment_plan_status()`).

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

**Related Modules & Docs:**
- `onboarding_admissions_api_documentation.md` (conversion target)
- `students_module_api_documentation.md` (post-enrollment profile)
- `fees_module_api_documentation.md` (bank selection on form submit, installment creation on enrollment)
- `attendance_procedure_guide.md`, `payroll_module_api_documentation.md`

This updated documentation aligns with the enhanced fees/onboarding/students flows (level-based status, utils integration, signals/services). All endpoints, request/response examples, rules, and cross-module links included.
