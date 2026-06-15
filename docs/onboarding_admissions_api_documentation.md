# Onboarding & Admissions Module — API Documentation

The `onboarding` module manages the student admission lifecycle — from form submission through document collection, payment verification, and final enrollment. Enrollment automatically triggers student and fee record creation.

---

## Data Model

| Model | Purpose |
|---|---|
| `Admission` | Full admission application record |
| `AdmissionStatusHistory` | Immutable log of every status change |

### Admission Statuses
`form_pending` → `payment_pending` → `payment_submitted` → `approval_pending` → `approved` → `enrolled`  
*(Also: `rejected` at any stage)*

### Key Fields
| Field | Description |
|---|---|
| `fee_structure` | FK to `fees.FeeStructure` — pinned at time of approval, drives auto-fee creation |
| `assigned_bank_id` | ID from the built-in `BANK_ACCOUNTS` list assigned for payment |
| `payment_screenshot` | Uploaded by student as proof of payment |
| `transaction_id` | UPI / bank reference number |

---

## Enrollment Signal Chain

When `Admission.status` is set to `enrolled`, the following auto-triggers fire:

```
Admission → enrolled
    │
    ▼  onboarding/signals.py
    ├── Creates User (role=student)
    └── Creates Student profile
            │
            ▼  students/signals.py
            ├── auto_assign_batch()   (batches.services)
            └── create_student_fee() (fees.services)
```

---

## API Endpoints

### 1. List & Create Admissions
**`GET /api/v1/admissions/`**
**`POST /api/v1/admissions/`**

**GET Query Parameters:**
| Param | Description |
|---|---|
| `status` | Filter by admission status |
| `course` | Filter by course type |
| `branch` | Filter by branch UUID |

**POST Request Body:** (all fields from the admission form)
```json
{
  "first_name": "Priya",
  "surname": "Shah",
  "father_name": "Ramesh Shah",
  "mother_name": "Sneha Shah",
  "email": "priya@example.com",
  "email_parent": "ramesh@example.com",
  "phone_student": "9876543210",
  "phone_father": "9876543211",
  "dob": "2005-04-15",
  "category": "gen",
  "street": "123 MG Road",
  "city": "Ahmedabad",
  "state": "Gujarat",
  "pincode": "380001",
  "course": "cseet",
  "group_module": "full",
  "batch_attempt": "june",
  "location": "Ahmedabad",
  "qualification": "pass_12",
  "reference": "google",
  "tenth_medium": "cbse",
  "tenth_school": "DPS School",
  "tenth_percentage": "89.50",
  "tenth_percentile": "94.00",
  "twelfth_medium": "cbse",
  "twelfth_school": "DPS School",
  "twelfth_percentage": "82.00",
  "twelfth_percentile": "88.00"
}
```

**POST Success Response:**
```json
{
  "success": true,
  "message": "Admission submitted successfully.",
  "admission_id": 42
}
```

---

### 2. Get / Update Admission Detail
**`GET /api/v1/admissions/<admission_id>/`**
**`PATCH /api/v1/admissions/<admission_id>/`** *(Admin / Counsellor)*

Returns full admission details including status history.

---

### 3. Update Admission Status
**`POST /api/v1/admissions/<admission_id>/status/`**

**Request Body:**
```json
{
  "status": "approval_pending",
  "note": "Documents verified, pending manager approval."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Status updated to approval_pending.",
  "status_history": [...]
}
```

---

### 4. Approve Admission
**`POST /api/v1/admissions/<admission_id>/approve/`**

Moves admission to `approved`. Can optionally pin a `FeeStructure`.

**Request Body:**
```json
{
  "note": "Approved by manager.",
  "fee_structure_id": "uuid-of-fee-structure"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Admission approved.",
  "assigned_bank": {
    "bank_name": "SBI",
    "account_number": "38976542103",
    "ifsc_code": "SBIN0001234"
  }
}
```

---

### 5. Reject Admission
**`POST /api/v1/admissions/<admission_id>/reject/`**

**Request Body:**
```json
{
  "note": "Incomplete documents."
}
```

---

### 6. Upload Admission Documents
**`POST /api/v1/admissions/<admission_id>/documents/`**

Multipart form upload for required documents.

**Form Fields:**
| Field | Required |
|---|---|
| `doc_photo` | Yes |
| `doc_signature` | Yes |
| `doc_dob_certificate` | Yes |
| `doc_id_card` | Yes |
| `doc_twelfth_marksheet` | No |
| `doc_category_cert` | No |

**Response:**
```json
{
  "success": true,
  "message": "Documents uploaded successfully."
}
```

---

### 7. Submit Payment Proof
**`POST /api/v1/admissions/<admission_id>/payment/`**

Student uploads payment screenshot after paying to the assigned bank account.

**Form Fields:**
| Field | Type | Required |
|---|---|---|
| `payment_screenshot` | File | Yes |
| `transaction_id` | string | Yes |
| `payment_note` | string | No |

**Response:**
```json
{
  "success": true,
  "message": "Payment proof submitted. Status updated to payment_submitted."
}
```

---

## Status Flow

```
form_pending
    │
    ├── [student uploads documents]
    ▼
payment_pending
    │
    ├── [admin assigns bank + sends details]
    ├── [student submits payment proof]
    ▼
payment_submitted
    │
    ├── [admin verifies payment]
    ▼
approval_pending
    │
    ├── [BM / Admin approves]
    ▼
approved
    │
    ├── [Admin enrolls]
    ▼
enrolled ──► Auto-creates: User + Student + StudentFee
```
