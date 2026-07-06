# Auth & User Management — Full API Reference & Walkthrough Guide

> **Base URL:** `https://api.example.com/api/v1/auth/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `application/json`  
> All responses are wrapped in `{ "success": true/false, "message": "...", "data": ... }` or error formats. Most endpoints return JWT tokens on successful auth.

---

## Architecture & Workflow Diagram

```
                              ┌─────────────────────────────┐
                              │     Organization Setup      │
                              │   (Super Admin Onboarding)  │
                              └──────────────┬──────────────┘
                                             │
                                             ▼
                              ┌─────────────────────────────┐
                              │   Create SuperAdmin User    │
                              │   (via /organizations/create/)│
                              └──────────────┬──────────────┘
                                             │
                                             ▼
                              ┌─────────────────────────────┐
                              │   Password Set Email Sent   │
                              │   (via PasswordSetToken)    │
                              └──────────────┬──────────────┘
                                             │
           ┌─────────────────┬───────────────┴───────────────┐
           │                 │                               │
           ▼                 ▼                               ▼
   [Register Flow]    [Add User Flow]                 [Login Flow]
   (Public/Invited)   (SuperAdmin only)               (All Roles)
           │                 │                               │
           ▼                 ▼                               ▼
    OTP via Email     Password Set Email             JWT Access + Refresh
   (EmailOTP model)   (PasswordSetToken)            + User Profile in resp
           │                 │                               │
           └──────────────┬──┴───────────────────────────────┘
                          ▼
               ┌─────────────────────────────┐
               │   Role-Based Access Control  │
               │   (permissions.py + views)   │
               └─────────────────────────────┘
                          │
                          ▼
             ┌──────────────────────────────┐
             │  User Management (CRUD) +    │
             │  Profile, Notifications, FCM │
             └──────────────────────────────┘
```

**Key Concepts:**
- **Multi-Tenant**: All users tied to an `Organization`.
- **OTP-based Verification**: Email OTP for registration, forgot password.
- **Password Set Flow**: New users (esp. from AddUser) receive a secure token link to set initial password.
- **Role Hierarchy**: `super_admin` > branch_manager/admins > operational roles (faculty, counsellor, student, parents, etc.).
- **JWT**: SimpleJWT for access/refresh tokens. `me/` and profile endpoints return rich user context including role-specific fields.

---

## Appendix A: System Choice Values & Role Mappings

### A.1 User Roles (`role`)
| Value | Display Name | Typical Permissions | Notes |
|------|--------------|---------------------|-------|
| `super_admin` | Super Admin | Full system access, org creation, add any user | One per organization |
| `branch_manager` | Branch Manager | Manage branch users, reports | Can oversee multiple branches |
| `admin_senior_executive` | Admin Senior Executive | High-level admin ops | - |
| `admin_executive` | Admin Executive | Standard admin tasks | - |
| `front_desk` | Front Desk | Student inquiries, basic ops | - |
| `counsellor` | Counsellor | Lead conversion, student guidance | - |
| `sales_senior_executive` | Sales Senior Executive | Sales oversight | - |
| `sales_executive` | Sales Executive | Lead management | - |
| `tele_caller` | Tele Caller | Outbound calls | - |
| `exam_supervisor` | Exam Supervisor | Exam proctoring, geo/screen monitoring, malpractice reports | Integrates with Exam v2 (`/start/`, `/geo-check/`, `/screen-event/`, answer-key distribution) |
| `paper_checker` | Paper Checker | Exam evaluation, rechecks (answer-key gated), queries | Uses `per_paper_rate`; integrates with `CheckerQuery`, `MarkSheet`, delayed round-robin assignment from `selected_papers` |
| `accountant` | Accountant | Fees, payroll | - |
| `student` | Student | View own timetable, attendance, results, exams | Linked to `students.Student` profile |
| `parents` | Parents | View linked student's data | Uses `linked_student` FK |
| `faculty` | Faculty | Timetable, attendance marking, subjects | Auto-creates `FacultyProfile`, `employee_id` |
| `house_keeping` | House Keeping | Facility management | - |
| `security` | Security | Access control | - |

### A.2 Level Choices (Employee fields)
| Value | Display |
|------|---------|
| `executive` | Executive |
| `professional` | Professional |

### A.3 Employment Type
| Value | Display |
|------|---------|
| `full_time` | Full Time |
| `part_time` | Part Time |
| `contract` | Contract |
| `visiting` | Visiting |

**Note:** Faculty/employees get extra fields populated (`employee_id`, `qualification`, `salary`, `per_paper_rate`, etc.). `is_active=False` by default until password is set.

---

## SECTION 1 — Organization & Super Admin Onboarding

### 1.1 Create Organization + Super Admin

**`POST /organizations/create/`** (Public endpoint)

#### Request Body
```json
{
  "organization_name": "ABC Institute of Commerce",
  "username": "superadmin_abc",
  "email": "admin@abcinstitute.com",
  "phone": "9876543210",
  "name": "Dr. Rajesh Sharma"
}
```

#### Response (201 Created)
```json
{
  "message": "Organization and super admin user created successfully. Password setup email sent.",
  "organization_id": "org-uuid-1234",
  "user_id": "user-uuid-5678",
  "success": true
}
```

**Flow:** Creates `Organization`, `User` (role=`super_admin`, `is_active=False`), generates `PasswordSetToken`, sends email with setup link.

### 1.2 Organization Detail

**`GET /organization/`** (Authenticated)

#### Response (200 OK)
```json
{
  "success": true,
  "data": {
    "id": "org-uuid-1234",
    "name": "ABC Institute of Commerce",
    "logo_url": "",
    "footer_text": "",
    "primary_color": "#2563EB",
    "website_url": "",
    "created_at": "2026-06-01T10:00:00Z"
  }
}
```

**PATCH** supported for super_admin to update branding.

---

## SECTION 2 — User Registration & Verification (All Roles)

### 2.1 Register New User

**`POST /register/`** (AllowAny)

#### Request Body (example for student)
```json
{
  "username": "student_rohan",
  "email": "rohan@example.com",
  "phone": "9123456789",
  "name": "Rohan Sharma",
  "role": "student",
  "password": "SecurePass123!"
}
```

#### Response (200 OK)
```json
{
  "message": "OTP sent to email"
}
```

**Notes:** 
- `organization` auto-filled from request context if authenticated.
- Creates user with `is_active=False`.
- Generates `EmailOTP` (5 min expiry).

**Role-specific:** For `faculty`, `branch` is recommended in AddUser flow (see Section 5).

### 2.2 Verify OTP

**`POST /verify-otp/`**

#### Request Body
```json
{
  "email": "rohan@example.com",
  "otp": "123456"
}
```

#### Response (200 OK)
```json
{
  "message": "Account verified successfully",
  "success": true
}
```

**Errors:**
- 400: Invalid/expired OTP
- 404: User not found

**Flow:** Marks OTP verified, sets `user.is_active = True`.

---

## SECTION 3 — Authentication & Token Management

### 3.1 Login (All Roles)

**`POST /login/`**

#### Request Body
```json
{
  "email": "rohan@example.com",
  "password": "SecurePass123!",
  "organization": "org-uuid-1234"   // optional
}
```

#### Response (200 OK)
```json
{
  "message": "Login successful",
  "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "user": {
    "id": "user-uuid-5678",
    "username": "student_rohan",
    "email": "rohan@example.com",
    "phone": "9123456789",
    "name": "Rohan Sharma",
    "role": "student",
    "role_display": "Student",
    "profile_pic": "https://api.example.com/media/profile_pics/rohan.jpg",
    "organization": "org-uuid-1234",
    "organization_name": "ABC Institute of Commerce",
    "linked_student": null
  }
}
```

**Special for Parents/Students:**
- `linked_student` returns the associated `Student` profile UUID.
- Faculty response includes `employee_id`, subjects, etc. via profile serializers.

**Errors:**
- 400: "Incorrect email or password" or "Account is not verified"

### 3.2 Refresh Token

**`POST /token/refresh/`** (SimpleJWT)

#### Request Body
```json
{
  "refresh": "<refresh_token>"
}
```

#### Response
```json
{
  "access": "<new_access_token>"
}
```

### 3.3 User Profile (`me/`)

**`GET /me/`** (Authenticated, supports GET/PUT)

#### Response (GET)
```json
{
  "id": "user-uuid",
  "username": "...",
  "email": "...",
  "name": "...",
  "role": "faculty",
  "role_display": "Faculty",
  "branch_name": "Mumbai Main",
  "profile_pic": "...",
  "organization_name": "...",
  "salary_retention_percentage": 0,
  ...
}
```

**PUT** allows updating `name`, `email`, `profile_pic` (multipart).

---

## SECTION 4 — Password Management

### 4.1 Forgot Password

**`POST /forgot-password/`**

#### Request Body
```json
{
  "email": "user@example.com"
}
```

Response: `{"message": "OTP sent successfully"}`

Then use `/reset-password/` with OTP (similar to verify-otp but includes new password).

### 4.2 Set Initial Password (from Email Link)

**`POST /set-password/`**

#### Request Body (or token in query params)
```json
{
  "token": "secure-token-from-email",
  "password": "NewPass123!",
  "confirm_password": "NewPass123!"
}
```

**Response:** `{"message": "Password set successfully. You may now log in."}`

Used after AddUser or Org creation.

### 4.3 Change Password (Authenticated)

**`POST /change-password/`**

#### Request Body
```json
{
  "current_password": "OldPass123!",
  "new_password": "NewSecurePass456!",
  "confirm_new_password": "NewSecurePass456!"
}
```

Response: `{"message": "Password changed successfully"}`

---

## SECTION 5 — User Management (CRUD) — Admin Only

**Permissions:** `super_admin` or appropriate admin roles. Most filter by user's `organization`.

### 5.1 List Users

**`GET /users/`**

#### Query Params
- `role=student,faculty` (comma or multiple)
- `is_active=true`
- `branch=uuid`
- Search on name/email/phone

#### Response (200 OK)
```json
{
  "success": true,
  "data": [
    {
      "id": "uuid",
      "name": "Prof. Ramesh Kumar",
      "email": "...",
      "role": "faculty",
      "role_display": "Faculty",
      "is_active": true,
      "branch_name": "Main Branch",
      "profile_pic": "...",
      "created_at": "..."
    }
  ]
}
```

### 5.2 Add User (Super Admin Only)

**`POST /users/add/`**

#### Request Body (example for faculty)
```json
{
  "username": "faculty_ramesh",
  "email": "ramesh@abcinstitute.com",
  "phone": "9988776655",
  "name": "Prof. Ramesh Kumar",
  "role": "faculty",
  "branch": "branch-uuid-001"
}
```

**Response (201):** User created, password-set email sent. Auto-creates `FacultyProfile` for faculty role.

**Note:** `linked_student` for parents role.

### 5.3 Get/Update User

**`GET/PATCH /users/<user_id>/`**

Supports multipart for `profile_pic`.

**PATCH Example (update faculty details):**
```json
{
  "name": "Prof. Ramesh Kumar Updated",
  "qualification": "M.Com, FCS",
  "salary": "85000.00",
  "per_paper_rate": "25.00"
}
```

### 5.4 Toggle User Status

**`POST /users/<user_id>/toggle-status/`**

#### Request Body
```json
{
  "is_active": true
}
```

### 5.5 Delete User

**`DELETE /users/<user_id>/delete/`**

Soft-delete behavior (sets inactive or hard deletes per implementation).

---

## SECTION 6 — Notifications & Push (FCM)

### 6.1 Register FCM Token

**`POST /fcm-token/`** (also supports GET/DELETE)

#### Request Body
```json
{
  "fcm_token": "firebase-device-token-here"
}
```

Response: `{"detail": "FCM token registered successfully."}`

### 6.2 Test Notification

**`POST /test-notification/`** (for debugging)

#### Request Body
```json
{
  "title": "Test Push",
  "body": "Hello from backend!",
  "user_id": "optional-target-uuid"
}
```

### 6.3 Notification History

**`GET /notifications/`**

Supports pagination. Auto-cleans records >60 days old.

**PATCH** to mark all as read.

#### Response Example
```json
{
  "success": true,
  "count": 5,
  "results": [
    {
      "id": "notif-uuid",
      "title": "Exam Reminder",
      "body": "Your prelim starts tomorrow",
      "is_read": false,
      "created_at": "...",
      "notification_type": "exam"
    }
  ]
}
```

---

## SECTION 7 — Role-Specific Workflows & Integrations

### 7.1 Parents Role
- Use `ParentStudentProfileAPIView` (commented in urls but available).
- `linked_student` FK connects to a `student` user.
- Can view child's attendance, results, timetable via other modules.

### 7.2 Faculty Role
- Auto `FacultyProfile` creation on AddUser.
- Extra fields: `employee_id`, `per_paper_rate`, `qr_code`, `subjects`.
- Integrates with timetable, attendance marking, exams (as examiner/paper_checker).

### 7.3 Student Role
- Linked to `students.Student` model.
- Restricted views in attendance, results, exams.

### 7.4 Exam Supervisor / Paper Checker
- Special rates and permissions for exam workflows (proctoring, marking, rechecks).
- `exam_supervisor`: Handles geo/screen events, malpractice.
- `paper_checker`: Uses `per_paper_rate`; handles `MarkSheet`, `CheckerQuery` (blocks payroll if open), rechecks (requires `answer_key` on Exam).

**Cross-Module Notes:**
- **Timetable:** M2M links for `examiners`/`paper_checkers` (synced to Exam via `ensure_paper_checkers()`).
- **Exams v2:** Full integration with proctoring endpoints, `selected_papers` round-robin, `result_release_mode`.
- **Results/Payroll:** Query resolution affects payslips; delayed assignment post-exam.
- **Leads/Onboarding:** Sales roles create leads that convert to students.

---

## SECTION 8 — Complete API Endpoint Summary Table

| # | Method | Endpoint | Description | Auth Required |
|---|--------|----------|-------------|---------------|
| 1 | `POST` | `/register/` | Register user + send OTP | No |
| 2 | `POST` | `/verify-otp/` | Verify email OTP | No |
| 3 | `POST` | `/login/` | Login + return JWT + profile | No |
| 4 | `POST` | `/token/refresh/` | Refresh access token | No |
| 5 | `POST` | `/forgot-password/` | Send reset OTP | No |
| 6 | `POST` | `/reset-password/` | Reset with OTP | No |
| 7 | `POST` | `/change-password/` | Change own password | Yes |
| 8 | `POST` | `/set-password/` | Set initial password from token | No |
| 9 | `GET/PUT` | `/me/` | Current user profile (update name/pic) | Yes |
| 10 | `GET` | `/users/` | List users (with filters) | Yes |
| 11 | `POST` | `/users/add/` | Add new user (super_admin) | Yes |
| 12 | `GET/PATCH` | `/users/<uuid:user_id>/` | Get or update specific user | Yes |
| 13 | `DELETE` | `/users/<uuid:user_id>/delete/` | Delete user | Yes |
| 14 | `POST` | `/users/<uuid:user_id>/toggle-status/` | Activate/deactivate user | Yes |
| 15 | `POST` | `/organizations/create/` | Create org + super admin | No |
| 16 | `GET/PATCH` | `/organization/` | Org details | Yes |
| 17 | `POST/GET/DELETE` | `/fcm-token/` | Manage push notification token | Yes |
| 18 | `POST` | `/test-notification/` | Send test push | Yes |
| 19 | `GET/PATCH` | `/notifications/` | Notification history | Yes |

---

## SECTION 9 — Common Error Responses

### 400 — Validation / Business Error
```json
{
  "success": false,
  "message": "Please fix the errors below.",
  "errors": {
    "email": ["This field is required."],
    "password": ["Passwords do not match"]
  }
}
```

### 400 — Invalid Credentials / OTP
```json
{
  "error": "Incorrect email or password",
  "success": false
}
```

### 403 — Permission Denied
```json
{
  "error": "You do not have permission to add users.",
  "success": false
}
```

### 404 — Not Found
```json
{
  "success": false,
  "message": "User not found."
}
```

**JWT Errors (401):**
```json
{
  "detail": "Authentication credentials were not provided."
}
```

---

## SECTION 10 — Setup & Migrations

> **After pulling latest code:**
> 
> ```bash
> python manage.py makemigrations auth_user
> python manage.py migrate auth_user
> ```
>
> **Key Models:** `User` (extends AbstractBaseUser), `Organization`, `EmailOTP`, `PasswordSetToken`, `NotificationHistory`.
>
> **Signals:** Auto employee_id generation, FacultyProfile creation for faculty role.
>
> **Permissions:** See `auth_user/permissions.py` for custom role-based rules.

**Best Practices:**
1. Always use the password-set flow for new internal users.
2. Call `/fcm-token/` immediately after login on mobile apps.
3. Use `?role=student,faculty` filters heavily on user list.
4. Super admins should create branches first via the `branch` app before adding faculty.
5. Monitor `NotificationHistory` for 60-day retention compliance.

This guide covers **all roles** and **all steps** from initial org setup through daily user operations. For module-specific integrations (timetable, exams, payroll), refer to their respective guides.
