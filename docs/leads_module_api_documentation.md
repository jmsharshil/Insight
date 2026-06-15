# Leads Module — API Documentation

The `leads` module captures and manages prospective student inquiries (Contact / Inquiry forms). Counsellors manage the lead pipeline through stages, assign leads, and track conversion to admission.

---

## Data Model

| Model | Purpose |
|---|---|
| `Lead` | Core inquiry record (form submission) |
| `LeadStage` | Immutable log of every stage change |
| `LeadAssignmentLog` | Audit trail of every assignment change |

### Lead Stages
`new` → `contacted` → `interested` → `visit` → `follow_up` → `converted` → `lost`

### Course Types
`cseet`, `cs_executive`, `cs_professional`

---

## API Endpoints

### 1. List & Create Leads
**`GET /api/v1/leads/`**

Returns paginated list of leads. Filters are role-scoped:
- Admins / BMs see all leads in their branch
- Counsellors see only leads assigned to them

**Query Parameters:**
| Param | Type | Description |
|---|---|---|
| `form_type` | string | `contact` or `inquiry` |
| `current_stage` | string | Any stage value |
| `course` | string | `cseet`, `cs_executive`, `cs_professional` |
| `search` | string | Search by name, phone, email |

**Response:**
```json
{
  "count": 42,
  "results": [
    {
      "id": 1,
      "first_name": "Priya",
      "phone_student": "9876543210",
      "course": "cseet",
      "current_stage": "new",
      "assigned_to": null,
      "created_at": "2026-06-01T10:00:00Z"
    }
  ]
}
```

---

### 2. Get / Update Lead Detail
**`GET /api/v1/leads/<lead_id>/`**
**`PATCH /api/v1/leads/<lead_id>/`**

Returns full lead detail including stage history.

**PATCH Request Body:**
```json
{
  "note": "Called student, showed interest in CSEET."
}
```

---

### 3. Update Lead Stage
**`POST /api/v1/leads/<lead_id>/status/`**

Used by counsellors to move a lead through stages.

**Request Body:**
```json
{
  "stage": "contacted",
  "note": "Spoke on call for 10 minutes."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Stage updated to contacted.",
  "stage_history": [
    { "stage": "new", "changed_at": "2026-06-01T10:00:00Z" },
    { "stage": "contacted", "changed_at": "2026-06-02T09:30:00Z" }
  ]
}
```

---

### 4. Assign Lead
**`POST /api/v1/leads/<lead_id>/assign/`**

Assigns a lead to a counsellor (Admin / BM only).

**Request Body:**
```json
{
  "counsellor_id": "uuid-of-counsellor",
  "note": "Assigning to Riya for follow-up."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Lead assigned to Riya Patel."
}
```

---

### 5. Reassign Lead
**`POST /api/v1/leads/<lead_id>/reassign/`**

Reassigns an already-assigned lead to a different counsellor.

**Request Body:**
```json
{
  "counsellor_id": "uuid-of-new-counsellor",
  "note": "Transferred due to workload."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Lead reassigned successfully."
}
```

---

## Stage Transition Rules

| From Stage | Allowed Next Stages |
|---|---|
| `new` | `contacted`, `lost` |
| `contacted` | `interested`, `follow_up`, `lost` |
| `interested` | `visit`, `follow_up`, `converted`, `lost` |
| `visit` | `converted`, `follow_up`, `lost` |
| `follow_up` | `converted`, `lost` |
| `converted` | *(terminal — triggers admission creation)* |
| `lost` | *(terminal)* |

> [!NOTE]
> When a lead is marked `converted`, it is linked to an `Admission` record via `Lead.admission` (OneToOne). The admission form is then handled by the **Onboarding** module.

---

## Role-Based Access

| Role | Access |
|---|---|
| `admin` | Full access — all leads |
| `branch_manager` | All leads in their branch |
| `counsellor` | Only assigned leads |
| `student` / `parents` | No access |
