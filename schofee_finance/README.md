# SchoFee B2B Education Loan Integration (`schofee_finance`)

This Django application implements the backend integration for the **SchoFee B2B Education Loan API (v3.0)** within Insight Institute ERP.

Backend only: Neither client secrets nor access tokens are ever exposed to frontend or mobile clients. The mobile and web applications communicate solely with Insight Institute backend endpoints under `/api/v1/finance/`.

---

## 1. Environment Variables & Settings

Configure the following variables in your `.env` file (see `.env.example` for placeholders):

| Variable | Required | Description | Example |
| :--- | :--- | :--- | :--- |
| `SCHOFEE_BASE_URL` | Yes | Base URL of SchoFee API (no trailing slash, no `/v1`) | `https://api-staging.schofee.com` |
| `SCHOFEE_CLIENT_ID` | Yes | Issued B2B Client ID (HTTP Basic username) | `inst_insight_b2b` |
| `SCHOFEE_CLIENT_SECRET` | Yes | Issued B2B Client Secret (HTTP Basic password) | `s3cr3t_t0k3n_...` |
| `SCHOFEE_SCOPES` | Yes | Space-separated OAuth scopes granted to institute | `courses:read banks:read students:write loan-applications:write loan-applications:read verification:request verification:write` |
| `SCHOFEE_TIMEOUT_SECONDS` | No | HTTP request timeout in seconds (default: 30) | `30` |

---

## 2. Architecture & Flow Diagram

```
                                [ Insight Frontend / Mobile ]
                                             │
                        1. Submit Admission with payment_type="finance"
                                             ▼
                                [ onboarding.Admission ]
                                             │
                        2. Initializes FinanceApplication (INITIATED)
                                             ▼
                               [ POST /api/v1/finance/applications/ ]
                                             │
            ┌────────────────────────────────┴────────────────────────────────┐
            │                                                                 │
      Step 1: Upload Documents                                          Step 2: Create Student
      POST /v1/students/documents                                       POST /v1/students
      (returns data.path)                                               (Idempotency-Key: "stu-{adm_id}")
            │                                                                 │
            └────────────────────────────────┬────────────────────────────────┘
                                             │
                                Step 3: Create Loan Application
                                POST /v1/loan-applications
                                (Idempotency-Key: "loan-{adm_id}")
                                (returns loanAppID & customerID)
                                             │
                                Step 4: Required Actions
                                GET /v1/loan-applications/{id}/required-actions
                                (Status: OTP_PENDING)
                                             │
                              Participant OTP Verification
                              POST .../participants/{id}/otp-requests
                              POST .../participants/{id}/otp-verifications
                                             │
                       All required actions completed (items: [])
                                             ▼
                           FinanceApplication -> VERIFIED
                                             │
                              Automatic Student Enrollment:
                              - admission.status = "enrolled"
                              - StudentService.create_from_admission()
                              - Payment record created in fees module
```

---

## 3. Endpoints Reference

All endpoints are hosted under `/api/v1/finance/`:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/applications/` | Submits student/applicant personal data, loan terms, and documents. Runs the resumable pipeline. |
| `GET` | `/applications/<id>/` | Retrieves application status, estimated EMI structure, and pending participant verification actions. |
| `POST` | `/applications/<id>/participants/<participantId>/otp/send/` | Requests an OTP for an applicant or co-applicant. |
| `POST` | `/applications/<id>/participants/<participantId>/otp/verify/` | Verifies the OTP. When all participants are verified, auto-enrolls the student. |
| `GET` | `/courses/` | Returns cached SchoFee course catalog for the admission form UI. |

---

## 4. Security Rules Followed

1. **Credentials**: `client_id` and `client_secret` are kept strictly in backend environment variables and never logged or exposed.
2. **Log Sanitization**: Request bodies, response bodies, Aadhaar, PAN, OTPs, access tokens, and SchoFee document paths are NEVER logged. Only `traceId`, `endpoint`, HTTP `status`, and `errorCode` are logged.
3. **Document Paths**: SchoFee internal `path` values returned by `/students/documents` are used only internally to pass to `/students` and are excluded from all user API responses.
4. **No Plaintext Storage**: In accordance with the security requirement and absence of an encryption helper at rest, plaintext Aadhaar and PAN are validated in memory and passed directly over TLS to SchoFee; they are not saved at rest.
5. **IDOR Protection**: Every detail, OTP send, and OTP verify endpoint validates ownership against the authenticated user and admission organization boundary.

---

## 5. Management Commands

### Smoke Test
Verify staging API connectivity without executing loan applications:
```bash
python manage.py schofee_smoke_test
```
*Output: Tests token generation, courses retrieval, and banks retrieval. Prints HTTP status codes and counts only.*

### Course Synchronization
Synchronize SchoFee courses into the ERP `CourseMapping` table:
```bash
python manage.py sync_schofee_courses --page-size 100
```

---

## 6. How to Run the Tests

Execute the automated test suite:
```bash
python manage.py test schofee_finance.tests
```

---

## 7. Future Extension Points

When SchoFee releases future specifications beyond v3.0:
- **Consent Sessions**: Extend `pipeline.py` between Step 3 and Step 4 when webhooks or consent sessions are introduced.
- **Bank Statements & AA**: Add banking report ingestion in `schofee_finance/services/banking.py`.
- **Lender Webhooks**: Add webhook listener under `POST /api/v1/finance/webhook/` with signature verification.
