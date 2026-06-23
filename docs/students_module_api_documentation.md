# Students Module — Full Walkthrough & API Reference Guide

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `application/json` (or multipart for uploads)  
> Responses wrapped as `{ "success": true/false, "message": "...", "data": {...} }`.

---

## Key Utility Functions (`students/utils.py`)

All business logic lives in `StudentService`:

### `StudentService.create_from_admission(admission, user, acting_user=None)`
- Atomic creation of `Student` profile from enrolled `Admission` (copies personal/academic/docs data).
- Links `ParentLink`s.
- Creates initial `StudentStatusHistory`.
- Generates `DigitalIDCard` (QR + visual card using PIL/qrcode if `has_photo`).
- Calls `fees.services.create_student_fee(student)` (which uses `get_installment_plan_status()` for approval rules).
- Logs errors non-fatally (student created even if fees fail).

**QR Payload:** `FRONTEND_BASE_URL/students/{student.id}` (scanned for attendance).

### `StudentService.update_status(student, new_status, reason='', acting_user=None)`
- Updates `Student.status`, creates `StudentStatusHistory`.
- Deactivates `DigitalIDCard` if status != `active`.
- Ties into fees status via signals or manual calls.

### `StudentService.allocate_batch(student, batch_name, reason='', acting_user=None)`
- Updates `current_batch_name`.
- Creates immutable `BatchHistory` entry.
- Used on enrollment and transfers.

### `StudentService.generate_id_card(student)`
- Requires `student.photo`.
- Generates QR code (payload = frontend student URL).
- Creates visual ID card PNG (header, photo, details, QR, footer) using PIL.
- Saves to `DigitalIDCard` (qr_image, card_image). Regenerates on demand.

### `StudentService.get_qr_identity_data(student, request=None)`
- Returns data for QR serializer (photo_url, qr_image_url, card_image_url, batch, branch, etc.).
- On-demand ID card generation if missing.
- Used by `/qr-id/` endpoint.

### `StudentService.upload_document(record, field_name, file)`
- Generic for Student/Admission. Updates field and triggers ID card regen if photo.

**Integration:** `has_overdue_installment()` from fees blocks attendance if unpaid items >15 days past due (on approved plans). `update_student_fee_status()` keeps StudentFee in sync.

---

## Data Models & Statuses

### Core Models
| Model | Purpose |
|-------|---------|
| `Student` | Master profile (linked to User, Admission, branch; has photo, current_batch_name, status) |
| `DigitalIDCard` | QR + visual card images (regeneratable) |
| `BatchHistory` | Immutable audit of batch changes |
| `StudentStatusHistory` | Immutable status change log |
| `ParentLink` | Links to parent Users |
| `InventoryIssue` | Issued items (books, uniform, ID card) with issued_by |

### Student Statuses
- `active` (default on enrollment)
- `inactive`
- `transferred`
- `alumni`
- `suspended`

**StudentFee status** (from fees module, linked 1:1): `approval_pending`, `partial`, `paid`, `overdue`.

---

## Architecture & Workflow Diagram

```text
ADMISSION enrolled
    │
    ▼
StudentService.create_from_admission()
    ├── Copy data from Admission
    ├── Create User links + ParentLink
    ├── StudentStatusHistory (active)
    ├── generate_id_card() if photo (QR + PIL visual card)
    └── create_student_fee() → StudentFee + InstallmentPlan (pending_approval per level rules)
          │
          ▼
Fees module (payments, update_student_fee_status(), mark_installment_paid())
          │
          ▼
Attendance QR scan → has_overdue_installment(student_id) ? BLOCK : allow
          │
Student actions: /profile/, /qr-id/, /documents/, /status/, /batch/, /inventory/
```

**Key Flows:**
- Enrollment from onboarding → students → fees (see onboarding docs).
- Status/batch changes always log history.
- Photo upload → auto-regenerate ID card.
- QR for attendance (geofence + time + device + fee check).

---

## FULL WALKTHROUGH: Student Profile & Operations

### Step 1: Enrollment (from Onboarding)
See onboarding docs. Auto-creates Student + ID card (if photo in admission) + fee record.

### Step 2: View Student Profile / Self-Profile
- Admin: GET `/students/<id>/` (full with relations).
- Student app: GET `/students/<id>/profile/` (optimized serializer, no sensitive fields).

### Step 3: Generate / Regenerate Digital ID Card & QR
- GET `/students/<id>/qr-id/` — Returns JSON with image URLs, QR payload. Errors if no photo.
- POST `/students/<id>/regenerate-id-card/` — Deletes old card, regenerates with current data (photo mandatory).

**QR scanned at attendance** → validates + checks `has_overdue_installment()` (blocks with specific 403 if overdue >15 days).

### Step 4: Update Student Status
POST `/students/<id>/status/` with `status` and optional `reason`. Logs to history, deactivates ID card if inactive.

### Step 5: Batch Allocation / Transfer
POST `/students/<id>/batch/` with `batch_name` + `reason`. Updates `current_batch_name`, creates `BatchHistory`.

### Step 6: Document & Photo Upload
POST `/students/<id>/documents/` (multipart: `field_name=photo` or `doc_id_proof`, `file=...`). If photo, auto-generates ID card.

### Step 7: Inventory Management
- GET `/students/<id>/inventory/` — List issued items.
- POST `/students/<id>/inventory/` — Issue new item (e.g. uniform, books). Links to `issued_by` user.

### Step 8: Fee & Attendance Integration
- View fee summary: GET `/fees/student/<id>/` (from fees module).
- Overdue → blocks QR check-in (see attendance_procedure_guide.md for blocked response example with `reason: "overdue_installment"`).

### Step 9: Reports
Combined in reports module or via student list filters (`status`, `current_batch_name`).

---

## Complete API Reference

### Student List & Detail
- **GET** `/api/v1/students/` — Paginated. Filters: `status`, `course`, `branch`, `current_batch_name`; search on name/admission_number/email/phone. `StudentListSerializer`.
- **GET** `/api/v1/students/<id>/` — Full detail (prefetches history, inventory, parents, id_card). `StudentDetailSerializer`. Supports fallback to user_id.
- **PATCH** `/api/v1/students/<id>/` — Update profile fields. `StudentUpdateSerializer`.
- **DELETE** `/api/v1/students/<id>/` — Soft or hard delete.

**Example Detail Response (abridged):**
```json
{
  "success": true,
  "data": {
    "id": "stu-uuid-001",
    "admission_number": "ADM-2026-001",
    "full_name": "Priya Shah",
    "status": "active",
    "course": "cseet",
    "current_batch_name": "CSEET_JUNE_2026_01",
    "photo_url": "https://.../photo.jpg",
    "qr_image_url": "https://.../qr.png",
    "card_image_url": "https://.../card.png",
    "branch_name": "Mumbai Main",
    "parent_links": [...],
    "status_history": [...],
    "batch_history": [...],
    "inventory_issues": [...]
  }
}
```

### Self Profile & QR
- **GET** `/api/v1/students/<id>/profile/` — Student-facing (lighter serializer).

- **GET** `/api/v1/students/<id>/qr-id/` — QR identity data.

**Success:**
```json
{
  "success": true,
  "data": {
    "student_id": "stu-uuid-001",
    "admission_number": "ADM-2026-001",
    "full_name": "Priya Shah",
    "course": "cseet",
    "batch_name": "CSEET_JUNE_2026_01",
    "branch_name": "Mumbai",
    "photo_url": "...",
    "qr_payload": "http://localhost:5173/students/stu-uuid-001",
    "qr_image_url": "...",
    "card_image_url": "...",
    "is_active": true
  }
}
```

**Error (no photo):**
```json
{
  "success": false,
  "message": "QR identity pass cannot be generated: profile photo is required. Please upload a photo via PATCH /api/students/<id>/documents/."
}
```

- **POST** `/api/v1/students/<id>/regenerate-id-card/` — Forces regen.

**Success:**
```json
{
  "success": true,
  "message": "ID card regenerated successfully.",
  "data": {
    "qr_image": "https://.../_qr.png",
    "card_image": "https://.../_card.png"
  }
}
```

### Status & Batch
- **POST** `/api/v1/students/<id>/status/`

**Request:**
```json
{
  "status": "suspended",
  "reason": "Non-payment of fees after warning."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Student status updated to 'suspended'.",
  "data": {
    "student_id": "stu-uuid-001",
    "admission_number": "ADM-2026-001",
    "status": "suspended"
  }
}
```

- **POST** `/api/v1/students/<id>/batch/`

**Request:**
```json
{
  "batch_name": "CS_EXEC_JUNE_2026_02",
  "reason": "Student requested batch transfer."
}
```

**Response:** Similar success with new batch_name.

### Documents & Inventory
- **POST** `/api/v1/students/<id>/documents/` — Multipart (`field_name`, `file`). Auto ID card regen on photo.

**Success:**
```json
{
  "success": true,
  "message": "Document 'photo' uploaded successfully.",
  "data": {"field_name": "photo"}
}
```

- **GET** `/api/v1/students/<id>/inventory/` — List.

**Response:**
```json
{
  "success": true,
  "count": 2,
  "data": [ { "item_name": "Uniform Set", "issued_at": "...", "issued_by": "..." }, ... ]
}
```

- **POST** `/api/v1/students/<id>/inventory/` — Issue item.

**Request:**
```json
{
  "item_name": "Textbook - Company Law",
  "quantity": 1,
  "notes": "Issued during orientation"
}
```

**Response:** Created inventory record.

---

## Common Errors & Notes
- 400: No photo for QR/ID card, invalid status, validation errors.
- 404: Student not found (tries student ID or linked user ID).
- 500: QR/PIL generation errors (logged, graceful fallback).
- ID card uses frontend URL for QR (configurable via settings.FRONTEND_BASE_URL).
- All history immutable for audit.
- Ties directly to fees (overdue blocks attendance) and onboarding (auto-creation).

**Related Docs:**
- `onboarding_admissions_api_documentation.md` (enrollment trigger)
- `fees_module_api_documentation.md` (fee status, installments, overdue check)
- `attendance_procedure_guide.md` (QR scan with fee validation)
- `timetable_procedure_guide.md` (student timetable view)

This guide reflects current implementation including PIL-based visual cards, QR payload to frontend, service-based enrollment chain, and tight integration with updated fees utils.
