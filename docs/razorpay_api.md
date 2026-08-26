# Razorpay API Reference — Insight ERP

> **Base path:** `/api/v1/fees/`  
> **Service layer:** `fees/razorpay_service.py`  
> **Configuration:** `.env` → `insight/settings.py`

---

## Table of Contents

1. [Configuration](#configuration)
2. [Payment Links](#payment-links)
   - [Generate Payment Link](#1-generate-payment-link)
   - [Fetch Payment Link](#2-fetch-payment-link)
   - [Cancel Payment Link](#3-cancel-payment-link)
3. [Payments](#payments)
   - [Fetch Payment Details](#4-fetch-payment-details)
4. [Refunds](#refunds)
   - [Initiate Refund](#5-initiate-refund)
5. [Webhooks](#webhooks)
   - [Webhook Receiver](#6-webhook-receiver)
   - [Webhook Test Simulation](#7-webhook-test-simulation)
6. [Onboarding / Admission Flow](#onboarding--admission-flow)
7. [Internal Service Functions](#internal-service-functions)
8. [Webhook Event Reference](#webhook-event-reference)
9. [Reference ID Conventions](#reference-id-conventions)

---

## Configuration

Add to `.env`:

```env
RAZORPAY_KEY_ID=rzp_live_xxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxx
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret
```

| Setting | Description |
|---|---|
| `RAZORPAY_KEY_ID` | Razorpay API Key ID (live or test) |
| `RAZORPAY_KEY_SECRET` | Razorpay API Key Secret |
| `RAZORPAY_WEBHOOK_SECRET` | HMAC-SHA256 secret for validating webhook signatures |

> If `RAZORPAY_KEY_ID` is empty, all service functions return `{ "success": false, "error": "Razorpay is not configured on this server." }`.

---

## Payment Links

### 1. Generate Payment Link

Creates a Razorpay Payment Link for a student fee record and returns the short URL.

```
POST /api/v1/fees/razorpay/generate-link/
```

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `student_fee_id` | `UUID` | Yes | UUID of the `StudentFee` record |
| `payment_type` | `string` | No | `"token_full"` (default) or `"token_finance"` |
| `amount` | `number` | No | Override amount in INR. If omitted, resolved from `payment_type` |

**Payment Type Logic**

| `payment_type` | Amount Charged |
|---|---|
| `token_full` (default) | Full outstanding amount (`StudentFee.amount_due`) |
| `token_finance` | `FeeStructure.token_amount`, falls back to `amount_due` |

**Example Request**

```json
{
  "student_fee_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "payment_type": "token_full"
}
```

**Success Response** `201`

```json
{
  "success": true,
  "message": "Razorpay payment link created.",
  "data": {
    "payment_link_id": "plink_xxxxxxxxxx",
    "short_url": "https://rzp.io/l/xxxxxxxxxx",
    "amount": 5000.0,
    "payment_type": "token_full",
    "status": "created",
    "expire_by": null
  }
}
```

**Error Responses**

| Status | Condition |
|---|---|
| `400` | `student_fee_id` missing or `amount <= 0` |
| `404` | `StudentFee` not found |
| `502` | Razorpay API rejected the request |

**Side Effects**
- If the student has an associated `Admission` record, `razorpay_payment_link` and `razorpay_payment_link_id` are saved to it.
- The `reference_id` sent to Razorpay follows the format `SF_<uuid>_<payment_type>`.

---

### 2. Fetch Payment Link

Fetches live status of an existing Razorpay payment link.

```
GET /api/v1/fees/razorpay/payment-link/<link_id>/
```

**Path Parameter**

| Parameter | Description |
|---|---|
| `link_id` | Razorpay payment link ID, e.g. `plink_xxxxxxxxxx` |

**Success Response** `200`

```json
{
  "success": true,
  "data": {
    "id": "plink_xxxxxxxxxx",
    "reference_id": "SF_3fa85f64_token_full",
    "short_url": "https://rzp.io/l/xxxxxxxxxx",
    "amount": 5000.0,
    "amount_paid": 0.0,
    "status": "created",
    "payments": []
  }
}
```

**Error Response** `404` — Link not found on Razorpay.

---

### 3. Cancel Payment Link

Cancels/expires a Razorpay payment link so it can no longer be paid.

```
POST /api/v1/fees/razorpay/cancel-link/<link_id>/
```

**Path Parameter**

| Parameter | Description |
|---|---|
| `link_id` | Razorpay payment link ID |

**Success Response** `200`

```json
{
  "success": true,
  "message": "Payment link cancelled.",
  "data": { }
}
```

**Error Response** `400` — Razorpay cancellation failed.

**Side Effects**
- Clears `razorpay_payment_link` and `razorpay_payment_link_id` from any `Admission` record that held this link.

---

## Payments

### 4. Fetch Payment Details

Fetches full details of a specific Razorpay payment.

```
GET /api/v1/fees/razorpay/payment/<razorpay_payment_id>/
```

**Path Parameter**

| Parameter | Description |
|---|---|
| `razorpay_payment_id` | Razorpay payment ID, e.g. `pay_xxxxxxxxxx` |

**Success Response** `200`

```json
{
  "success": true,
  "data": {
    "id": "pay_xxxxxxxxxx",
    "amount": 500000,
    "currency": "INR",
    "status": "captured",
    "method": "upi",
    "email": "student@example.com",
    "contact": "9876543210"
  }
}
```

**Error Response** `404` — Payment not found.

---

## Refunds

### 5. Initiate Refund

Triggers a refund for a Razorpay payment and optionally creates a local `Refund` record.

```
POST /api/v1/fees/razorpay/refund/
```

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `payment_id` | `string` | Yes | Razorpay payment ID (`pay_xxx`) |
| `amount` | `number` | Yes | Amount to refund in INR |
| `reason` | `string` | No | Human-readable refund reason |
| `local_payment_id` | `UUID` | No | Local `Payment` record ID — creates a `Refund` entry and updates `StudentFee` status |

**Example Request**

```json
{
  "payment_id": "pay_xxxxxxxxxx",
  "amount": 2500,
  "reason": "Course cancellation",
  "local_payment_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

**Success Response** `201`

```json
{
  "success": true,
  "message": "Refund initiated on Razorpay.",
  "data": {
    "razorpay_refund_id": "rfnd_xxxxxxxxxx",
    "razorpay_payment_id": "pay_xxxxxxxxxx",
    "amount": 2500.0,
    "status": "processed",
    "local_refund_id": "a1b2c3d4-..."
  }
}
```

**Error Responses**

| Status | Condition |
|---|---|
| `400` | `payment_id` or `amount` missing |
| `502` | Razorpay refund API failed |

---

## Webhooks

### 6. Webhook Receiver

Receives and processes Razorpay webhook events. Register this URL in **Razorpay Dashboard → Webhooks**.

```
POST /api/v1/fees/razorpay/webhook/
```

> **Auth:** No authentication. Validates the `X-Razorpay-Signature` header via HMAC-SHA256 using `RAZORPAY_WEBHOOK_SECRET`.

**Headers**

| Header | Description |
|---|---|
| `X-Razorpay-Signature` | HMAC-SHA256 signature of the raw request body |
| `Content-Type` | `application/json` |

**Supported Events**

| Event | Handler | Effect |
|---|---|---|
| `payment_link.paid` | `process_payment_link_paid_event` | Creates `Payment` record (SF flow) or updates `Admission` status (ADM flow). Sends receipt via email + WhatsApp |
| `payment_link.partially_paid` | `process_payment_link_paid_event` | Same as above |
| `refund.processed` | `process_refund_processed_event` | Creates/updates local `Refund` record. Updates `StudentFee` status |
| `payment_link.cancelled` | `process_payment_link_cancelled_event` | Clears payment link from `Admission` |
| `payment_link.expired` | `process_payment_link_cancelled_event` | Same as above |

**Response** Always returns `200` to prevent Razorpay retries.

```json
{ "success": true }
```

**Invalid Signature Response** `400`

```json
{ "success": false, "message": "Invalid signature." }
```

---

### 7. Webhook Test Simulation

Simulates a `payment_link.paid` event locally — no live Razorpay callback needed. Runs the full pipeline: payment creation, PDF receipt generation, email dispatch, WhatsApp notification.

```
POST /api/v1/fees/razorpay/webhook/test/
```

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `reference_id` | `string` | Yes | E.g. `"SF_<uuid>_token_full"` or `"ADM_<admission_id>"` |
| `amount` | `number` | No | Amount in INR (default: `100`) |
| `rp_payment_id` | `string` | No | Mock payment ID (auto-generated if omitted) |

**Example — StudentFee flow**

```json
{
  "reference_id": "SF_3fa85f64-5717-4562-b3fc-2c963f66afa6_token_full",
  "amount": 5000
}
```

**Example — Admission flow**

```json
{
  "reference_id": "ADM_42",
  "amount": 1000,
  "rp_payment_id": "pay_TEST_MANUAL"
}
```

**Success Response** `200`

```json
{
  "success": true,
  "message": "Webhook simulation complete. Check server logs and the recipient inbox / WhatsApp.",
  "simulated_payload": { },
  "result": { "success": true, "processed": "SF", "payment_id": "..." }
}
```

---

## Onboarding / Admission Flow

When a student submits their admission form, the system **automatically** creates a Razorpay payment link and sends it via email and WhatsApp. This happens internally via `_setup_payment_bank_and_notify()`.

**Trigger endpoints:**
- `POST /api/v1/admissions/` — student submits their form
- `PATCH /api/v1/admissions/<id>/` — form update that transitions status from `form_pending`

**Reference ID format:** `ADM_<admission_id>_<unix_timestamp>`

**Automated steps:**

1. A bank account is selected based on payment threshold rules
2. A Razorpay payment link is created via `create_payment_link()`
3. The `short_url` is saved to `Admission.razorpay_payment_link`
4. Email sent with the Razorpay link + bank transfer fallback details
5. WhatsApp message sent to the student's phone

**After payment — webhook `payment_link.paid` fires:**

1. `Admission.status` → `approval_pending`
2. `Admission.razorpay_payment_id` is saved
3. PDF payment receipt generated (via ReportLab)
4. PDF uploaded to Azure Blob Storage
5. Receipt sent via email (with PDF attachment) + WhatsApp (PDF document)

---

## Internal Service Functions

Located in `fees/razorpay_service.py`. All functions return `{ "success": bool, "data": ..., "error": "..." }`.

| Function | Signature | Description |
|---|---|---|
| `create_payment_link` | `(amount, reference_id, customer_name, customer_email, customer_contact, description, bank_account_data)` | Creates a Razorpay Payment Link. Optionally routes to a bank via `bank_account_data` |
| `fetch_payment_link` | `(link_id)` | Fetches live status of a payment link |
| `cancel_payment_link` | `(link_id)` | Cancels/expires a payment link |
| `fetch_payment` | `(razorpay_payment_id)` | Fetches a payment object by ID |
| `create_refund` | `(payment_id, amount, reason)` | Initiates a refund on Razorpay |
| `build_upi_link` | `(upi_id, amount, payee_name, note)` | Builds a `upi://pay?...` deep-link URI for mobile |
| `verify_webhook_signature` | `(body, signature)` | Verifies `X-Razorpay-Signature` via HMAC-SHA256 |
| `process_payment_link_paid_event` | `(payload)` | Handles `payment_link.paid` / `partially_paid` (SF + ADM flows) |
| `process_refund_processed_event` | `(payload)` | Handles `refund.processed` events |
| `process_payment_link_cancelled_event` | `(payload)` | Handles `payment_link.cancelled` / `expired` events |
| `send_admission_payment_notification` | `(admission, amount_paid, rp_payment_id)` | Sends PDF receipt email + WhatsApp for ADM flow |
| `is_razorpay_enabled` | `()` | Returns `True` if `RAZORPAY_KEY_ID` is configured |

---

## Webhook Event Reference

| Event | Trigger |
|---|---|
| `payment_link.paid` | Customer completes full payment |
| `payment_link.partially_paid` | Customer pays partial amount |
| `payment_link.cancelled` | Link manually cancelled via API or dashboard |
| `payment_link.expired` | Link expires without payment |
| `refund.processed` | Razorpay refund is completed |

---

## Reference ID Conventions

Reference IDs passed to Razorpay must be globally unique per payment link.

| Flow | Format | Example |
|---|---|---|
| Student Fee — full | `SF_<uuid>_token_full` | `SF_3fa85f64-..._token_full` |
| Student Fee — token | `SF_<uuid>_token_finance` | `SF_3fa85f64-..._token_finance` |
| Admission | `ADM_<admission_id>_<unix_ts>` | `ADM_42_1724567890` |

Webhook processor routing by prefix:

- `SF_` → Creates `Payment` record + updates `StudentFee` status
- `ADM_` → Updates `Admission.status` to `approval_pending`

---

## Error Response Format

```json
{
  "success": false,
  "message": "Human-readable error.",
  "detail": { }
}
```

| HTTP Status | Meaning |
|---|---|
| `400` | Bad request or validation error |
| `404` | Resource not found |
| `502` | Razorpay API rejected the request |
