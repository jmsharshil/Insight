# Student Fees, Remaining Payment & 15-Day Finance Policy Documentation

This document covers the end-to-end workflow for student enrollment, credential dispatch, fee breakdown, remaining balance payment options, and the 15-day finance policy.

---

## 1. Admission Payment & Credential Dispatch Workflow

### 1.1 Credential Issuance Rule
Students **do not** receive login credentials immediately upon submitting the admission form. Login credentials are created and dispatched **only when the admission status transitions to `'enrolled'`**:

* **Token Payment via Razorpay (Online):**  
  As soon as the student pays the token amount through the Razorpay link, the webhook auto-verifies the payment and transitions the admission status to `'enrolled'`. Login credentials (Username + Temporary Password) are dispatched immediately via **Email** and **WhatsApp**.
* **Token Payment via Cash / Cheque (Offline):**  
  The student uploads payment proof and transaction reference. Once the **Accountant** (Level 1) and **Super Admin** (Level 2) approve the payment, the admission status transitions to `'enrolled'`. Login credentials are dispatched immediately upon Super Admin approval.
* **Full Payment on Admission:**  
  If the student pays the full fee upfront at admission time, `total_due` becomes `0`, and no remaining balance is left.

---

## 2. The 15-Day Finance Rule

When a student pays only a token fee at admission:
1. **Starting Date:** The countdown starts from `student.enrolled_at` (the exact timestamp when the student was enrolled and login credentials were sent).
2. **Deadline Date:** $\text{Deadline Date} = \text{Enrolled Date} + 15\text{ calendar days}$.
3. **If within 15 days (`days_left >= 0`):**
   * The student sees an active countdown notice with their exact deadline date and days remaining.
   * Status is marked as `pending_payment`.
4. **If 15 days expire without full payment (`days_left < 0`):**
   * The status switches to `moved_to_finance`.
   * The student's admission `payment_type` is automatically set to `'finance'`.
   * A clear alert informs the student that their balance has been moved to the finance process and that the finance team will assist them with the loan/EMI process.
5. **Installment Flow:**
   * Installments are disabled in the `my-fees` response (`"installments": []`, `"installments_enabled": false`) so students focus directly on clearing the balance or proceeding with finance. All database models and tables for installment plans remain intact in the system.

---

## 3. API Reference: Student My Fees (`/api/v1/fees/my-fees/`)

* **Base URL:** `/api/v1/fees/my-fees/`
* **Authorization:** `Bearer <JWT Token>` (Role must be `student` or `parents`)
* **Content-Type:** `application/json` (GET & JSON POST) or `multipart/form-data` (POST with file upload)

---

### 3.1 `GET /api/v1/fees/my-fees/` — Retrieve Fee Overview & Payment History

Retrieves the authenticated student's fee summary, remaining balance, 15-day finance countdown, and complete payment history.

#### Response Attributes:
| Field | Type | Description |
|---|---|---|
| `student_id` | UUID string | ID of the student profile |
| `admission_id` | Integer | ID of the original admission form |
| `admission_number` | String | Unique admission number (e.g., `ADM-2025-000042`) |
| `is_fully_paid` | Boolean | `true` if remaining fee is zero; `false` otherwise |
| `summary.total_billed` | Decimal | Total course/institute fee |
| `summary.total_discount` | Decimal | Total discount applied |
| `summary.total_paid` | Decimal | Amount paid to date |
| `summary.total_due` | Decimal | Remaining fee amount due |
| `finance_notice` | Object / null | Detailed 15-day rule status (null if fully paid) |
| `finance_notice.enrolled_date` | Date string | Date credentials were issued |
| `finance_notice.deadline_date` | Date string | 15-day cutoff date (`YYYY-MM-DD`) |
| `finance_notice.days_left` | Integer | Days remaining before finance cutoff |
| `finance_notice.days_overdue` | Integer | Days passed since deadline (if overdue) |
| `finance_notice.is_moved_to_finance` | Boolean | `true` if 15 days expired; `false` otherwise |
| `finance_notice.status` | String | `pending_payment` or `moved_to_finance` |
| `finance_notice.note` | String | User-facing explanatory message |
| `remaining_fee_options` | Object / null | Allowed payment modes (null if fully paid) |
| `payments` | Array | Full history of token and balance payments |
| `payments[].payment_label` | String | `"Token Payment"`, `"Full Payment"`, etc. |
| `payments[].payment_type` | String | `"token"`, `"full_payment"`, or `"finance"` |
| `payments[].payment_mode` | String | `"online"`, `"cash"`, `"cheque"` |
| `payments[].payment_date` | Date string | Date payment was made |
| `payments[].payment_proof_url` | String / null | Full absolute URL to uploaded screenshot/proof |
| `payments[].transaction_ref` | String | Transaction ID or cheque number |
| `payments[].status` | String | `verified`, `approval_pending`, `level_1_approved` |
| `payments[].receipt_number` | String | Unique payment receipt code |
| `payment_history` | Array | **Same audit trail array as Admission Form**. Lists link generation, offline submissions, approvals, proofs, amounts, and dates |

#### Example Response (Within 15-Day Window):
```json
{
  "success": true,
  "role": "student",
  "student_id": "8a72b6c1-4c3e-4fa0-86c0-798cb3d41f12",
  "admission_id": 142,
  "admission_number": "ADM-2025-000142",
  "payment_history": [
    {
      "event": "payment_link_created",
      "payment_choice": "online",
      "payment_type": "token",
      "payment_type_display": "Token",
      "amount": 5000.0,
      "razorpay_payment_link": "https://rzp.io/i/abcdef123",
      "razorpay_payment_link_id": "plink_P897Gf412",
      "status": "paid",
      "date": "2026-10-21",
      "created_at": "2026-10-21T09:30:00Z",
      "total_fees": 50000.0,
      "token_amount": 5000.0,
      "remaining_fees": 45000.0,
      "terms_note": "In 15 days you have to pay remaining fees otherwise it will be considered as Finance."
    },
    {
      "event": "payment_approved",
      "payment_choice": "online",
      "payment_choice_display": "Online",
      "payment_type": "token",
      "amount": 5000.0,
      "transaction_id": "pay_Plkn875412Aa",
      "receipt_number": "RCT-202610-0012",
      "status": "verified",
      "date": "2026-10-21",
      "payment_proof": null,
      "payment_screenshot": null,
      "total_fees": 50000.0,
      "remaining_fees": 45000.0
    }
  ],
  "data": {
    "admission_id": 142,
    "admission_number": "ADM-2025-000142",
    "is_fully_paid": false,
    "summary": {
      "total_billed": 50000.0,
      "total_discount": 0.0,
      "total_paid": 5000.0,
      "total_due": 45000.0
    },
    "finance_notice": {
      "enrolled_date": "2026-10-21",
      "deadline_date": "2026-11-05",
      "deadline_date_display": "05 Nov 2026",
      "days_left": 15,
      "days_overdue": 0,
      "is_moved_to_finance": false,
      "status": "pending_payment",
      "note": "Please pay your remaining fee of ₹45,000 within 15 days of receiving your login credentials (deadline: 05 Nov 2026, 15 day(s) remaining). If not paid within 15 days, your fee balance will automatically be moved to the finance process."
    },
    "remaining_fee_options": {
      "amount_due": 45000.0,
      "payment_types": [
        { "key": "full_payment", "label": "Full Payment" },
        { "key": "finance", "label": "Finance (No Immediate Payment)" }
      ],
      "payment_choices": [
        { "key": "online", "label": "Online Transfer (Razorpay)" },
        { "key": "cash", "label": "Cash" },
        { "key": "cheque", "label": "Cheque" }
      ],
      "instruction": "To pay remaining fees, submit POST /api/v1/fees/my-fees/ with payment_type and payment_choice. If full_payment and online: Razorpay link is generated. If full_payment and cash/cheque: upload payment_proof and transaction_ref. If finance: finance option is registered."
    },
    "fees": [
      {
        "id": "fe983421-3a01-49b2-8491-125d0c89e41b",
        "fee_name": "CS Executive Both Modules",
        "total_amount": "50000.00",
        "discount": "0.00",
        "amount_paid": "5000.00",
        "amount_due": "45000.00",
        "status": "partial",
        "status_display": "Partial",
        "due_date": "2026-11-05"
      }
    ],
    "installments": [],
    "installments_enabled": false,
    "payments": [
      {
        "id": "761d8a43-6d0b-410a-8d76-b94f0bcf5f71",
        "payment_label": "Token Payment",
        "payment_type": "token",
        "payment_type_display": "Token Payment",
        "amount": "5000.00",
        "payment_mode": "online",
        "payment_mode_display": "Online Transfer",
        "transaction_ref": "pay_Plkn875412Aa",
        "payment_proof_url": "https://api.example.com/media/payments/proofs/token_rec.png",
        "status": "verified",
        "status_display": "Verified",
        "receipt_number": "RCT-202610-0012",
        "payment_date": "2026-10-21",
        "note": "Auto-verified via Razorpay: plink_P897Gf412"
      }
    ],
    "refunds": [],
    "payment_history": [
      {
        "event": "payment_link_created",
        "payment_choice": "online",
        "payment_type": "token",
        "amount": 5000.0,
        "razorpay_payment_link": "https://rzp.io/i/abcdef123",
        "status": "paid",
        "date": "2026-10-21"
      },
      {
        "event": "payment_approved",
        "payment_choice": "online",
        "payment_type": "token",
        "amount": 5000.0,
        "transaction_id": "pay_Plkn875412Aa",
        "receipt_number": "RCT-202610-0012",
        "status": "verified",
        "date": "2026-10-21"
      }
    ]
  }
}
```

---

### 3.2 `POST /api/v1/fees/my-fees/` — Pay Remaining Balance

Allows the authenticated student or parent to clear remaining fees or choose the finance route.

#### Case 1: Online + Full Payment (Generates Razorpay Link)
* **Headers:** `Content-Type: application/json`
* **Request Body:**
  ```json
  {
    "payment_type": "full_payment",
    "payment_choice": "online"
  }
  ```
* **Success Response (`200 OK`):**
  ```json
  {
    "success": true,
    "payment_type": "full_payment",
    "payment_choice": "online",
    "message": "Razorpay payment link generated successfully for remaining fees.",
    "data": {
      "student_id": "8a72b6c1-4c3e-4fa0-86c0-798cb3d41f12",
      "admission_id": 142,
      "student_fee_id": "fe983421-3a01-49b2-8491-125d0c89e41b",
      "amount": 45000.0,
      "payment_link_url": "https://rzp.io/i/78aGbcd",
      "payment_link_id": "plink_Q912Kl0123",
      "payment_mode": "online",
      "status": "link_generated"
    }
  }
  ```
* **Automated Webhook Action:**  
  When the student pays this link, Razorpay sends the `payment_link.paid` webhook (`fees/razorpay_service.py`). The system:
  1. Creates a verified `Payment` record.
  2. Updates `StudentFee` amount paid and moves status to `paid`.
  3. Sends the official payment receipt automatically.

---

#### Case 2: Cheque / Cash + Full Payment (Upload Payment Proof)
* **Headers:** `Content-Type: multipart/form-data`
* **Form Fields:**
  * `payment_type`: `"full_payment"`
  * `payment_choice`: `"cheque"` *(or `"cash"`)*
  * `transaction_ref`: `"CHQ-897512"` *(Cheque Number or Cash Receipt Ref)*
  * `payment_proof`: `[Image or PDF file of cheque/receipt]` *(Required for cheque)*
  * `payment_note`: `"Cheque deposited at branch desk"` *(Optional)*
* **Success Response (`201 Created`):**
  ```json
  {
    "success": true,
    "payment_type": "full_payment",
    "payment_choice": "cheque",
    "message": "Remaining fee payment proof for Cheque submitted successfully! It is pending verification by the accountant and super admin.",
    "data": {
      "payment_id": "31b9d4f2-512c-48be-9b1f-7f61c320d9a8",
      "student_id": "8a72b6c1-4c3e-4fa0-86c0-798cb3d41f12",
      "admission_id": 142,
      "student_fee_id": "fe983421-3a01-49b2-8491-125d0c89e41b",
      "amount": 45000.0,
      "payment_mode": "cheque",
      "transaction_ref": "CHQ-897512",
      "status": "approval_pending",
      "status_display": "Approval Pending",
      "payment_date": "2026-10-21",
      "payment_proof_url": "https://api.example.com/media/payments/proofs/cheque_photo.jpg"
    }
  }
  ```
* **Internal Action:**  
  * Creates `Payment` with status `approval_pending`.
  * Logs entry in admission status history.
  * Dispatches notification to accountants and super admins for 2-level verification.

---

#### Case 3: Finance Selection (No Immediate Payment)
* **Headers:** `Content-Type: application/json`
* **Request Body:**
  ```json
  {
    "payment_type": "finance"
  }
  ```
* **Success Response (`200 OK`):**
  ```json
  {
    "success": true,
    "payment_type": "finance",
    "message": "Finance option selected. No immediate payment is required. Our finance team will assist you with the process.",
    "data": {
      "student_id": "8a72b6c1-4c3e-4fa0-86c0-798cb3d41f12",
      "admission_id": 142,
      "student_fee_id": "fe983421-3a01-49b2-8491-125d0c89e41b",
      "payment_type": "finance",
      "amount_due": 45000.0,
      "status": "finance_selected"
    }
  }
  ```
* **Internal Action:**  
  Sets `payment_type = 'finance'` on the admission record so counsellors and the finance desk can follow up.

---

## 4. Key Summary Table

| Scenario | Admission Action | Credentials Dispatched? | Remaining Balance | 15-Day Countdown? |
|---|---|---|---|---|
| **Full Payment Upfront** | Pays 100% online/offline | Yes (Immediately upon verification) | ₹0 (`is_fully_paid: true`) | No |
| **Token Payment (Online/Offline)** | Pays token fee (e.g. ₹5,000) | Yes (Immediately upon verification) | ₹Total - ₹Token | **Yes (Active for 15 days)** |
| **Balance Paid within 15 Days** | Pays via online (Razorpay) or cheque/cash | Already has credentials | Updates to ₹0 (`is_fully_paid: true`) | Completed |
| **Balance Not Paid in 15 Days** | No action taken | Already has credentials | Remaining balance stays due | **Switches to `moved_to_finance`** |
