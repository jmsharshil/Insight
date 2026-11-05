# Combo Offer API Guide

This guide covers the CSEET + CS Executive combo offer.

## Important Rules

- `combo_offer` identifies an admission as a combo admission.
- `fee_structure` is the only fee structure field on `Admission`.
- Create and assign one separate Fee Structure for the combo and set `is_combo: true`.
- The combo Fee Structure amount is used directly; it is not calculated by adding regular fee structures.
- The future CS Executive batch is stored separately in `combo_future_batch`.
- Do not send future-batch messages until the CS Executive enrollment year has been reached.

## Base URL and Authentication

```text
/api/v1/
```

Most administrative APIs require authentication:

```http
Authorization: Bearer <access_token>
```

The admission and payment setup APIs are public where noted.

---

## 1. Create the Combo Fee Structure

```http
POST /api/v1/fee-structures/
Content-Type: application/json
```

`is_combo` must be `true`. If `name` is omitted, the generated name includes `COMBO`.

### Request Body

```json
{
  "name": "",
  "course": "CSEET_COURSE_UUID",
  "level": "CSEET_LEVEL_UUID",
  "attempt": "june",
  "year": 2026,
  "is_combo": true,
  "is_active": true,
  "total_amount": 40000,
  "token_amount": 5000,
  "icsi_registration_fees": 15000,
  "icsi_exam_fees": 5000,
  "icsi_registration_fees_via_cseet": 0,
  "icsi_registration_fees_direct": 0,
  "institute_fees_all_modules": 20000,
  "description": "CSEET and CS Executive combo offer"
}
```

### Successful Response

```json
{
  "success": true,
  "message": "Fee structure created.",
  "data": {
    "id": "fee-structure-uuid",
    "name": "BRANCH_CSEET_JUNE_26_COMBO",
    "attempt": "june",
    "year": 2026,
    "total_amount": "40000.00",
    "token_amount": "5000.00",
    "is_combo": true,
    "is_active": true
  }
}
```

Status: `201 Created`

### Error Response

```json
{
  "success": false,
  "message": "Please fix the errors below.",
  "errors": {
    "attempt": ["This field is required."],
    "token_amount": ["Token amount cannot exceed total amount."]
  }
}
```

Status: `400 Bad Request`

---

## 2. Find Combo Fee Structures

```http
GET /api/v1/fee-structures/?is_active=true
GET /api/v1/fee-structures/?search=COMBO&is_active=true
```

Both the `is_combo` and `name` fields are useful to identify the combo structure in the response.

### List Response

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "fee-structure-uuid",
      "name": "BRANCH_CSEET_JUNE_26_COMBO",
      "attempt": "june",
      "year": 2026,
      "total_amount": "40000.00",
      "token_amount": "5000.00",
      "is_combo": true,
      "is_active": true
    }
  ]
}
```

### Get One Fee Structure

```http
GET /api/v1/fee-structures/{fee_structure_id}/
```

Not found response:

```json
{
  "success": false,
  "message": "Fee structure not found."
}
```

Status: `404 Not Found`

---

## 3. Create or Submit the Combo Admission

```http
POST /api/v1/admissions/
Content-Type: application/json
```

This endpoint can accept the complete form or update an existing admission when `id` is included.

### Request Body

Submit the combo Fee Structure UUID in the normal `fee_structure` field:

```json
{
  "first_name": "Test",
  "surname": "Student",
  "phone_student": "9876543210",
  "email": "student@example.com",
  "course": "cseet",
  "batch_attempt": "june",
  "attempt_year": 2026,
  "combo_offer": true,
  "fee_structure": "fee-structure-uuid",
  "payment_type": "full_payment",
  "payment_choice": "online",
  "branch": 1,
  "consent": true
}
```

### Explicit Fee Structure

Use this when the client already selected a structure:

```json
{
  "fee_structure": "fee-structure-uuid",
  "combo_offer": true
}
```

### Automatic Fee Structure Selection

The server also supports omitting `fee_structure`:

```json
{
  "course": "cseet",
  "batch_attempt": "june",
  "attempt_year": 2026,
  "combo_offer": true
}
```

The server selects an active Fee Structure matching:

1. `attempt`
2. `year`
3. `is_combo: true`
4. If no exact-year match exists, legacy name/description matching may be used

When a Fee Structure with no explicit selection is found, it is saved into the admission's normal `fee_structure` field.

### Successful Response

```json
{
  "success": true,
  "message": "Your admission form has been submitted successfully. We have sent you an email with bank details for fee payment. Please check your inbox to complete the process.",
  "data": {
    "admission_id": "IIPS-000123",
    "status": "payment_pending",
    "status_display": "Payment Pending",
    "payment_type": "full_payment",
    "payment_choice": "online",
    "total_fees": "40000.00",
    "remaining_fees": "40000.00",
    "is_paid": false,
    "is_razorpay_paid": false,
    "razorpay_payment_status": "pending"
  }
}
```

Status: `200 OK` or `201 Created`, depending on the admission creation path.

### Admission Validation Errors

```json
{
  "success": false,
  "message": "Please fix the errors below.",
  "errors": {
    "phone_student": ["This field is required."],
    "fee_structure": ["Invalid pk \"...\" - object does not exist."]
  }
}
```

Status: `400 Bad Request`

### Duplicate Phone Error

```json
{
  "success": false,
  "message": "Please fix the phone number errors.",
  "errors": {
    "phone_student": ["This phone number is already linked to another admission."]
  }
}
```

Status: `400 Bad Request`

### Admission Not Found

```json
{
  "success": false,
  "message": "Admission not found for this ID."
}
```

Status: `404 Not Found`

---

## 4. Update Combo Details

```http
PATCH /api/v1/admissions/{admission_id}/
Content-Type: application/json
```

### Request Body

```json
{
  "combo_offer": true,
  "course": "cseet",
  "batch_attempt": "dec",
  "attempt_year": 2026,
  "fee_structure": "fee-structure-uuid"
}
```

Changing `batch_attempt`, `attempt_year`, or `combo_offer` recalculates the future CS Executive batch.

### Success Response

```json
{
  "success": true,
  "message": "Admission updated successfully.",
  "data": {
    "id": "IIPS-000123",
    "combo_offer": true,
    "fee_structure": "fee-structure-uuid",
    "combo_future_batch_attempt": "dec",
    "combo_future_attempt_year": 2026
  }
}
```

Status: `200 OK`

---

## 5. Get Admission and Verify the Combo

```http
GET /api/v1/admissions/{admission_id}/
```

The response includes:

- `combo_offer`
- `fee_structure`
- `combo_future_batch`
- `combo_future_batch_attempt`
- `combo_future_attempt_year`

### Response Example

```json
{
  "success": true,
  "data": {
    "id": "IIPS-000123",
    "course": "cseet",
    "batch_attempt": "june",
    "attempt_year": 2026,
    "combo_offer": true,
    "fee_structure": "fee-structure-uuid",
    "combo_future_batch": 123,
    "combo_future_batch_attempt": "june",
    "combo_future_attempt_year": 2027
  }
}
```

### Not Found

```json
{
  "success": false,
  "message": "Admission not found."
}
```

Status: `404 Not Found`

---

## 6. Set Up or Regenerate Payment

```http
POST /api/v1/admissions/{admission_id}/setup/
Content-Type: application/json
```

This endpoint is public and should be called immediately after the admission is submitted if the client did not already generate payment setup.

### Request Body

```json
{
  "payment_type": "token",
  "payment_choice": "online",
  "payment_amount": 5000,
  "force_new_link": false
}
```

Supported payment types:

- `full_payment`
- `token`
- `finance`

Supported payment choices:

- `online`
- `cash`
- `cheque`
- `check` (normalized to `cheque`)

### Success Response

```json
{
  "success": true,
  "message": "Payment setup completed.",
  "data": {
    "admission_id": "IIPS-000123",
    "status": "payment_pending",
    "payment_type": "token",
    "payment_choice": "online",
    "total_fees": "40000.00",
    "remaining_fees": "35000.00",
    "is_paid": false,
    "is_razorpay_paid": false,
    "razorpay_payment_status": "pending",
    "razorpay_payment_link": "https://razorpay.com/payment-link",
    "payment_history": []
  }
}
```

Status: `200 OK`

### Admission Not Found

```json
{
  "success": false,
  "message": "Admission not found."
}
```

Status: `404 Not Found`

---

## 7. Submit Payment Proof

```http
POST /api/v1/admissions/{admission_id}/payment/
Content-Type: multipart/form-data
```

### Form Fields

```text
payment_amount=5000
transaction_id=TXN123456
payment_choice=online
payment_screenshot=<image-or-pdf-file>
```

Cash and cheque payments can be submitted according to the frontend flow without a screenshot.

### Success Response

```json
{
  "success": true,
  "message": "Payment submitted successfully.",
  "data": {
    "admission_id": "IIPS-000123",
    "status": "payment_submitted",
    "payment_amount": "5000.00"
  }
}
```

Status: `200 OK`

---

## 8. Status Workflow and Approval

Expected status flow:

```text
form_pending
  -> payment_pending
  -> payment_submitted
  -> approved
  -> enrolled
```

Offline or verification delays may place the admission in `approval_pending`.

### Change Status

```http
PATCH /api/v1/admissions/{admission_id}/status/
Authorization: Bearer <authorized-user-token>
Content-Type: application/json
```

```json
{
  "status": "enrolled",
  "note": "Combo admission approved and enrolled."
}
```

Only Super Admin users can set `enrolled`. Accountant or Super Admin can set `approved`.

### Permission Response

```json
{
  "success": false,
  "message": "Permission denied. Only Super Admin can complete enrollment (Level 2)."
}
```

Status: `403 Forbidden`

### Validation Response

```json
{
  "success": false,
  "errors": {
    "status": ["This field is required."]
  }
}
```

Status: `400 Bad Request`

---

## Future Batch Mapping

The future CS Executive batch is calculated from the CSEET attempt:

| CSEET attempt | Future CS Executive attempt | Future year |
|---|---|---|
| June | June | CSEET year + 1 |
| October | December | Same year |
| February | December | Same year |
| December | December | CSEET year + 1 |

Examples:

- June 2026 -> Executive June 2027
- October 2026 -> Executive December 2026
- December 2026 -> Executive December 2027

If no matching active Executive batch exists, `combo_future_batch` remains `null`. No payment or enrollment error should be caused by the future batch not existing.

### Important Message Rule

Do not send any future CS Executive batch messages during the current CSEET admission year merely because a future batch record has been resolved.

Send or display messages only when:

1. The current date reaches the resolved Executive attempt year.
2. The student is eligible for the Executive phase.
3. The Executive batch is active.

---

## Complete Frontend Steps

1. Create a regular CSEET Fee Structure for normal admissions.
2. Create a separate combo Fee Structure and set `is_combo=true`.
3. Make sure the combo structure has the intended combo price, attempt, and year.
4. Display the combo structure in the frontend using `is_combo=true`.
5. Submit the admission with `combo_offer=true`, CSEET course details, and the combo `fee_structure` UUID.
6. If the frontend does not send `fee_structure`, let the backend auto-select the matching active combo structure.
7. Call `POST /admissions/{admission_id}/setup/` to calculate payment and create the payment link.
8. Charge the amount from the combo Fee Structure.
9. Submit online proof, cash/cheque payment, or confirm the Razorpay payment.
10. Complete the two-level approval workflow.
11. Resolve and store the future batch.
12. Do not send next-batch notifications until the resolved Executive year.

---

## Common Error Summary

| Status | Meaning |
|---|---|
| `400 Bad Request` | Missing required fields or invalid Fee Structure/payment data |
| `403 Forbidden` | User is not allowed to perform approval/enrollment |
| `404 Not Found` | Admission or Fee Structure does not exist |
| `500 Internal Server Error` | Unexpected server-side creation or payment setup failure |
