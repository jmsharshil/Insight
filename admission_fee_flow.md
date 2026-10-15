# Admission and Fee Structure Workflow

This document outlines the complete lifecycle from the administrator creating a fee structure, to a student submitting their admission form, and finally receiving a Razorpay payment link via email.

```mermaid
sequenceDiagram
    actor Admin
    actor Student
    participant System as Insight Backend
    participant Razorpay
    
    Admin->>System: 1. Create Fee Structure (Course, Attempt, Year)
    Student->>System: 2. Submit Admission Form (Course, Attempt, Year)
    
    activate System
    System->>System: 3. Auto-link matching Fee Structure
    System->>System: 4. Calculate amount (Total - Token)
    System->>Razorpay: 5. Generate Payment Link
    Razorpay-->>System: Returns short_url
    System->>Student: 6. Email sent with Razorpay link
    deactivate System
```

---

## 1. Creating the Fee Structure
The process begins with an administrator creating a **Fee Structure** in the backend. 

When creating a fee structure, the admin specifies:
- **Target Audience:** `course` (e.g., CSEET, CS Executive), `attempt` (e.g., June, December), and `year` (e.g., 2024).
- **Fee Breakdown:** ICSI Registration fees, ICSI Exam fees, Institute fees (Module 1/2/Both), and a Token amount.
- **Total Amount:** Automatically calculated as the sum of all the components.

> [!NOTE]
> The `is_active` flag must be set to `True` for the fee structure to be successfully fetched by the admission form.

## 2. Filling out the Admission Form
When a student lands on the frontend and fills out the admission form, they provide their personal details, academic history, and crucially, they select:
1. **Course Level** (`course`)
2. **Attempt Month** (`batch_attempt`)
3. **Attempt Year** (`attempt_year`)

Once the student hits "Submit", a `POST` request is sent to the `/api/admissions/` endpoint.

## 3. Dynamic Fee Fetching
When the backend receives the form submission, the system automatically runs the `_assign_fee_structure` helper logic.

- It maps the student's chosen `course` (e.g., "cseet") to the correct `FeeStructure.level`.
- It queries the database for the active `FeeStructure` where `level`, `attempt`, and `year` strictly match the student's inputs.
- The matching fee structure is saved directly to the `Admission` record.

> [!IMPORTANT]
> If a student selects a combination of Course + Attempt + Year for which no active fee structure exists, the admission record will still be saved, but no fee structure will be attached, and the Razorpay link will fallback to the default base fees.

## 4. Razorpay Link Generation
After the fee structure is linked, the system computes the amount the student needs to pay.

Based on the student's selected `payment_type`:
- **Token Payment (`token`):** The Razorpay link amount is dynamically set to the `FeeStructure.token_amount`.
  - The remaining fee is calculated as: `Module Fee - Token Amount`.
  - The system automatically generates the 15-day policy notice:
    > *"In 15 days you have to pay remaining fees (₹XX,XXX) otherwise it will be considered as Finance."*
- **Full Payment (`full_payment`):** The Razorpay link amount is set to the fee of the student's selected module (e.g., `institute_fees_module_1` for Module 1, `institute_fees_module_2` for Module 2, or `institute_fees_all_modules` for both/all) **without deducting the token fee**.

> [!IMPORTANT]
> The Razorpay payment link will **only be generated and sent** if the student selected **"Full Payment"** (`full_payment`) or **"Token Payment"** (`token`) on the admission form. If they select **"Finance"** (`finance`), no payment link is created.

If the student is eligible for a link, the backend makes an API call to Razorpay via the `create_payment_link()` service.
- **Reference ID:** Uniquely generated as `ADM_{id}_{timestamp}`.
- **Customer Info:** Populated with the student's name, email, and phone number.

## 5. Email & WhatsApp Setup Notification
Once Razorpay returns a successful `short_url` payment link, the backend triggers an email notification to the student's registered email address (and WhatsApp message).

The setup message includes:
- A welcoming message confirming their form submission.
- **Remaining Fee Notice (for Token Payments):** An alert box highlighting that remaining fees must be paid within 15 days or it will be converted to Finance.
- The **Secure Online Payment Link** (the Razorpay `short_url`).
- Alternative offline bank transfer details (assigned round-robin to stay under daily limits).
- A portal link to upload their payment receipt if they choose offline bank transfer.

## 6. Post-Payment Confirmation & Receipt
When the student pays the token amount via Razorpay:
1. **Webhook Event (`payment_link.paid`):**
   - Marks the admission as `approval_pending`.
   - Records the transaction ID and stores the remaining fee notice in `admission.payment_note`, `admission.note`, and the status history.
2. **Payment Receipt Email & WhatsApp:**
   - Automatically sends an official PDF receipt.
   - Highlights the 15-day remaining fee notice:
     > *"⚠️ Important Notice Regarding Remaining Fees: In 15 days you have to pay remaining fees (₹XX,XXX) otherwise it will be considered as Finance."*
3. **API & Admin Visibility:**
   - Both `remaining_fees` and `token_payment_terms_note` are exposed in `AdmissionListSerializer` and `AdmissionDetailSerializer` for frontend display.
