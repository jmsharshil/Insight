# API Documentation: Faculty Multi-Level & Chapter Multi-Faculty Features

This document provides complete, production-ready documentation for all modified and new API behaviors supporting:
1. **Multiple Academic Levels (`CourseLevel`)** for Faculty members (Create, Update, List, Detail).
2. **Multiple Assigned Faculties (`User` with `role='faculty'`)** for Course Chapters — chapters now store faculty as **User IDs directly** (no FacultyProfile indirection).
3. **User Management Sync** for Faculty roles (Create User, Update User, Profile).

---

## Table of Contents
- [1. Architecture & Key Concepts](#1-architecture--key-concepts)
- [2. Faculty APIs](#2-faculty-apis)
  - [2.1 Create Faculty](#21-create-faculty)
  - [2.2 Update Faculty](#22-update-faculty)
  - [2.3 Get Faculty Detail](#23-get-faculty-detail)
  - [2.4 List Faculty Profiles (with Level Filtering)](#24-list-faculty-profiles-with-level-filtering)
  - [2.5 Deactivate / Delete Faculty](#25-deactivate--delete-faculty)
- [3. Chapter APIs](#3-chapter-apis)
  - [3.1 Create Chapter](#31-create-chapter)
  - [3.2 Update Chapter](#32-update-chapter)
  - [3.3 Get Chapter Detail](#33-get-chapter-detail)
  - [3.4 List Chapters (with Faculty Filtering)](#34-list-chapters-with-faculty-filtering)
  - [3.5 Delete Chapter](#35-delete-chapter)
  - [3.6 Academic Dropdowns](#36-academic-dropdowns)
- [4. Auth & User Management APIs](#4-auth--user-management-apis)
  - [4.1 Add User (Faculty Role)](#41-add-user-faculty-role)
  - [4.2 Update User (Faculty Role)](#42-update-user-faculty-role)
  - [4.3 User List & Profile Representation](#43-user-list--profile-representation)
- [5. Common Errors & Status Codes](#5-common-errors--status-codes)

---

## 1. Architecture & Key Concepts

### A. Academic Levels for Faculty
- **Models**: Both `FacultyProfile.levels` and `User.levels` are `ManyToManyField('batches.CourseLevel')`.
- **Organization Constraint (Multi-Tenant Rule)**: Levels must belong to the **same `Organization`** as the faculty's `branch.organization`. 
  - **API Enforcement**: `resolve_course_levels(..., organization=...)` filters the queryset using the branch's org (see `FacultyListCreateView`, `FacultyUpdateSerializer.update`). Non-matching inputs are silently excluded.
  - **Admin Enforcement**: `formfield_for_manytomany` in `FacultyProfileAdmin` (object_id lookup for edits; superuser sees all).
  - Matches scoping in `Subject` and `BatchFacultyAdmin`.
- **Backward Compatibility**: The legacy `level` CharField (`'executive'`, `'professional'`, `'cseet'`) is preserved and auto-populated based on the primary level chosen (derived from first resolved `CourseLevel`).
- **Input Flexibility**: The APIs accept `levels` as:
  - An array of `CourseLevel` UUIDs: `["333c44a8-24ba-41e1-89a9-92c565cf4fda", ...]`
  - An array of level names or legacy slugs: `["executive", "professional"]` or `["CS Executive", "CS Professional"]`
  - A JSON-encoded string or comma-separated string (useful for `multipart/form-data` uploads with photos): `'["uuid1", "uuid2"]'` or `'executive,professional'`

### B. Assigned Faculties for Chapters
- **Model**: `Chapter.faculties` is `ManyToManyField(settings.AUTH_USER_MODEL, limit_choices_to={'role': 'faculty'}, related_name='faculty_chapters')`.
  - ✅ **Strictly linked to `User`** — no FacultyProfile involvement.
  - The reverse relation on User is `user.faculty_chapters` (the chapters assigned to that user).
- **Input**: `faculties` must be an array of **`User` UUIDs** where `user.role == 'faculty'`.
  - Passing a FacultyProfile ID will return a validation error (use User ID instead).
  - Empty array `[]` unassigns all faculties.
- **Output**: `faculties` → array of User UUIDs. `faculties_details` → array of objects with `id` (User ID), `user_id`, `name`, `email`, `phone`, `level`, `levels`.
- **Filtering**: `GET /chapters/?faculty_id=<user_uuid>` filters chapters where that User is an assigned faculty.

---

## 2. Faculty APIs

### 2.1 Create Faculty

Creates a new `User` with `role='faculty'`, creates a linked `FacultyProfile`, auto-generates employee ID and QR code, and associates the faculty with multiple `CourseLevel`s.

- **URL**: `/api/v1/faculty/`
- **Method**: `POST`
- **Content-Type**: `application/json` or `multipart/form-data` (when uploading `photo`)
- **Authentication**: Bearer Token (`Authorization: Bearer <access_token>`)
- **Allowed Roles**: `super_admin`, `branch_manager`, `admin_senior_executive`

#### Step-by-Step Logic
1. Validates that `branch_id` is provided (or extracted from the user's branch).
2. Verifies the email does not already exist.
3. Auto-generates a unique username and sets default temporary credentials.
4. Generates a branch-prefixed `employee_id` (e.g. `EMP-MUM-0001`) and generates the faculty QR code.
5. Resolves `levels` array (UUIDs, names, or slugs) and links them to both `FacultyProfile.levels` and `User.levels`.
6. Sets the primary `level` string for legacy systems (`executive` / `professional` / `cseet`).

#### Request Headers
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

#### Request Body
| Field | Type | Required | Description | Example |
|---|---|---|---|---|
| `email` | String | **Yes** | Unique email address | `"faculty.sharma@example.com"` |
| `full_name` | String | **Yes** | Full name of the faculty | `"Prof. Rohit Sharma"` |
| `phone` | String | **Yes** | Contact phone number | `"9876543210"` |
| `qualification` | String | **Yes** | Academic degrees / qualifications | `"CA, CS, LL.B"` |
| `specialization` | String | **Yes** | Area of specialization | `"Corporate Restructuring & Tax"` |
| `subject_expertise` | String | No | Subject descriptions | `"Direct Tax, IBC"` |
| `levels` | Array[UUID / String] | No | Academic levels taught | `["4a221d6b-0f58-4b0b-8680-f28b36f8102d", "333c44a8-24ba-41e1-89a9-92c565cf4fda"]` or `["executive", "professional"]` |
| `level` | String | No | Legacy fallback (`executive`, `professional`, `cseet`) | `"executive"` |
| `employment_type` | String | No | `full_time` or `visiting` (default `full_time`) | `"visiting"` |
| `joining_date` | Date | **Yes** | Date format `YYYY-MM-DD` | `"2026-02-01"` |
| `salary` | Number | No | Monthly salary (for full-time) | `75000` |
| `hourly_rate` | Number | No | Per-hour rate (for visiting) | `2500` |
| `branch` or `branch_id` | UUID | No* | Branch UUID (*required if super_admin) | `"b97a2cb4-8a4d-44a0-9701-d0074f07a7d4"` |
| `bank_account` | String | No | Bank account number | `"123456789012"` |
| `ifsc_code` | String | No | Bank IFSC code | `"HDFC0000123"` |
| `pan_number` | String | No | PAN card number | `"ABCDE1234F"` |
| `photo` | File | No | Profile photo (use `multipart/form-data`) | Binary |

#### Example Request Body (JSON)
```json
{
  "email": "rohit.sharma@example.com",
  "full_name": "Prof. Rohit Sharma",
  "phone": "9876543210",
  "qualification": "FCS, LL.M",
  "specialization": "Corporate Law & Securities",
  "levels": [
    "4a221d6b-0f58-4b0b-8680-f28b36f8102d",
    "333c44a8-24ba-41e1-89a9-92c565cf4fda"
  ],
  "employment_type": "visiting",
  "hourly_rate": 2500,
  "joining_date": "2026-02-01",
  "branch": "b97a2cb4-8a4d-44a0-9701-d0074f07a7d4"
}
```

#### Success Response (`201 Created`)
```json
{
  "success": true,
  "message": "Faculty created.",
  "data": {
    "faculty_id": "5ddcc745-b419-40c3-a60b-4d8fb4138fda",
    "employee_id": "EMP-MUM-0001",
    "user_id": "b0a9d4bb-5d40-4751-8cfe-7344a4e148e8",
    "photo_url": null,
    "qr_code_url": "https://hrmsknowcraftstorage.blob.core.windows.net/media/qr/faculty/EMP-MUM-0001.png"
  }
}
```

---

### 2.2 Update Faculty

Updates an existing faculty profile, including modifying their academic level assignments.

- **URL**: `/api/v1/faculty/<faculty_id>/`
- **Method**: `PATCH`
- **Content-Type**: `application/json` or `multipart/form-data`
- **Authentication**: Bearer Token
- **Allowed Roles**: `super_admin`, `branch_manager`, `admin_senior_executive`

#### Step-by-Step Logic
1. Resolves `FacultyProfile` within the user's organization and branch scope.
2. Accepts partial updates for any profile fields.
3. If `levels` is supplied:
   - Resolves the provided CourseLevel IDs / names / slugs.
   - Updates `FacultyProfile.levels`.
   - Automatically synchronizes `User.levels`.
   - Updates legacy string `level` on both `FacultyProfile` and `User`.

#### Example Request Body
```json
{
  "specialization": "Corporate Restructuring, IBC & Securities",
  "levels": [
    "333c44a8-24ba-41e1-89a9-92c565cf4fda"
  ],
  "hourly_rate": 2800
}
```

#### Success Response (`200 OK`)
```json
{
  "success": true,
  "message": "Faculty updated.",
  "data": {
    "id": "5ddcc745-b419-40c3-a60b-4d8fb4138fda",
    "user_id": "b0a9d4bb-5d40-4751-8cfe-7344a4e148e8",
    "employee_id": "EMP-MUM-0001",
    "full_name": "Prof. Rohit Sharma",
    "email": "rohit.sharma@example.com",
    "phone": "9876543210",
    "qualification": "FCS, LL.M",
    "specialization": "Corporate Restructuring, IBC & Securities",
    "level": "professional",
    "level_display": "CS Professional",
    "levels": [
      {
        "id": "333c44a8-24ba-41e1-89a9-92c565cf4fda",
        "name": "CS Professional"
      }
    ],
    "levels_details": [
      {
        "id": "333c44a8-24ba-41e1-89a9-92c565cf4fda",
        "name": "CS Professional",
        "course_id": "60886ef6-9e04-40bc-9ace-87e457e4c359",
        "course_name": "Company Secretary (CS)",
        "course_type": "standard"
      }
    ],
    "employment_type": "visiting",
    "hourly_rate": "2800.00",
    "is_active": true
  }
}
```

---

### 2.3 Get Faculty Detail

Retrieves complete faculty profile details, including assigned academic levels, assigned chapters, and batch allocations.

- **URL**: `/api/v1/faculty/<faculty_id>/`
- **Method**: `GET`
- **Authentication**: Bearer Token
- **Allowed Roles**: `super_admin`, `branch_manager`, `admin_senior_executive`, `accountant`, or the faculty member themselves (`role='faculty'` accessing their own profile).

#### Success Response (`200 OK`)
```json
{
  "success": true,
  "data": {
    "id": "5ddcc745-b419-40c3-a60b-4d8fb4138fda",
    "user_id": "b0a9d4bb-5d40-4751-8cfe-7344a4e148e8",
    "employee_id": "EMP-MUM-0001",
    "full_name": "Prof. Rohit Sharma",
    "email": "rohit.sharma@example.com",
    "phone": "9876543210",
    "qualification": "FCS, LL.M",
    "specialization": "Corporate Restructuring & Tax",
    "subject_expertise": "Direct Tax, IBC",
    "level": "executive",
    "level_display": "CS Executive, CS Professional",
    "levels": [
      {
        "id": "4a221d6b-0f58-4b0b-8680-f28b36f8102d",
        "name": "CS Executive"
      },
      {
        "id": "333c44a8-24ba-41e1-89a9-92c565cf4fda",
        "name": "CS Professional"
      }
    ],
    "levels_details": [
      {
        "id": "4a221d6b-0f58-4b0b-8680-f28b36f8102d",
        "name": "CS Executive",
        "course_id": "60886ef6-9e04-40bc-9ace-87e457e4c359",
        "course_name": "Company Secretary (CS)",
        "course_type": "standard"
      },
      {
        "id": "333c44a8-24ba-41e1-89a9-92c565cf4fda",
        "name": "CS Professional",
        "course_id": "60886ef6-9e04-40bc-9ace-87e457e4c359",
        "course_name": "Company Secretary (CS)",
        "course_type": "standard"
      }
    ],
    "chapters": [
      {
        "id": "82555c60-d82b-46fb-9e48-2ea0c8ce2e2e",
        "name": "Introduction to Companies Act",
        "order": 1,
        "subject_id": "f5f306bf-2ce9-4606-bdb2-5b30b2a280b4",
        "subject_name": "Corporate Laws"
      }
    ],
    "employment_type": "visiting",
    "joining_date": "2026-02-01",
    "salary": "0.00",
    "hourly_rate": "2500.00",
    "branch_id": "b97a2cb4-8a4d-44a0-9701-d0074f07a7d4",
    "branch_name": "Mumbai Central",
    "is_active": true,
    "photo_url": null,
    "qr_code_url": "https://hrmsknowcraftstorage.blob.core.windows.net/media/qr/faculty/EMP-MUM-0001.png"
  }
}
```

---

### 2.4 List Faculty Profiles (with Level Filtering)

Returns the list of faculty members with support for multi-level filtering.

- **URL**: `/api/v1/faculty/`
- **Method**: `GET`
- **Authentication**: Bearer Token
- **Allowed Roles**: `super_admin`, `branch_manager`, `admin_senior_executive`, `accountant`

#### Query Parameters
| Parameter | Type | Description | Example |
|---|---|---|---|
| `level_id` | UUID | Filter faculties assigned to this `CourseLevel` UUID | `?level_id=4a221d6b-0f58-4b0b-8680-f28b36f8102d` |
| `level` | String | Filter faculties matching level name or slug (`executive`, `professional`, `cseet`) | `?level=executive` |
| `employment_type` | String | `full_time` or `visiting` | `?employment_type=visiting` |
| `is_active` | Boolean | `true` or `false` | `?is_active=true` |
| `search` | String | Search by name, employee ID, or specialization | `?search=sharma` |

#### Success Response (`200 OK`)
```json
{
  "success": true,
  "data": [
    {
      "id": "5ddcc745-b419-40c3-a60b-4d8fb4138fda",
      "employee_id": "EMP-MUM-0001",
      "full_name": "Prof. Rohit Sharma",
      "email": "rohit.sharma@example.com",
      "phone": "9876543210",
      "specialization": "Corporate Law & Securities",
      "level": "executive",
      "level_display": "CS Executive, CS Professional",
      "levels": [
        "4a221d6b-0f58-4b0b-8680-f28b36f8102d",
        "333c44a8-24ba-41e1-89a9-92c565cf4fda"
      ],
      "levels_details": [
        {
          "id": "4a221d6b-0f58-4b0b-8680-f28b36f8102d",
          "name": "CS Executive",
          "course_id": "60886ef6-9e04-40bc-9ace-87e457e4c359",
          "course_name": "Company Secretary (CS)",
          "course_type": "standard"
        },
        {
          "id": "333c44a8-24ba-41e1-89a9-92c565cf4fda",
          "name": "CS Professional",
          "course_id": "60886ef6-9e04-40bc-9ace-87e457e4c359",
          "course_name": "Company Secretary (CS)",
          "course_type": "standard"
        }
      ],
      "employment_type": "visiting",
      "branch_id": "b97a2cb4-8a4d-44a0-9701-d0074f07a7d4",
      "branch_name": "Mumbai Central",
      "batch_count": 2,
      "is_active": true,
      "photo_url": null,
      "qr_code_url": "https://hrmsknowcraftstorage.blob.core.windows.net/media/qr/faculty/EMP-MUM-0001.png"
    }
  ]
}
```

---

### 2.5 Deactivate / Delete Faculty

Soft-deactivates the faculty profile and their user account.

- **URL**: `/api/v1/faculty/<faculty_id>/`
- **Method**: `DELETE`
- **Authentication**: Bearer Token
- **Allowed Roles**: `super_admin`, `branch_manager`, `admin_senior_executive`

#### Success Response (`200 OK`)
```json
{
  "success": true,
  "message": "Faculty deactivated."
}
```

---

## 3. Chapter APIs

### 3.1 Create Chapter

Creates a new chapter under a subject and assigns one or multiple faculties to it.

- **URL**: `/api/v1/subjects/<subject_id>/chapters/`
- **Method**: `POST`
- **Content-Type**: `application/json`
- **Authentication**: Bearer Token
- **Allowed Roles**: `super_admin`, `branch_manager`, `academic_coordinator`, `faculty`

#### Step-by-Step Logic
1. Checks that the target `Subject` exists and belongs to the user's organization.
2. Validates that `order` is unique for this subject.
3. If `faculties` is passed:
   - Must be an array of `User` UUIDs where `user.role == 'faculty'`.
   - Links all users using `chapter.faculties.set(...)`.
4. Returns the created chapter with `faculties` (User UUIDs) and `faculties_details`.

#### Request Body
| Field | Type | Required | Description | Example |
|---|---|---|---|---|
| `name` | String | **Yes** | Name of the chapter | `"Incorporation of Companies"` |
| `order` | Integer | **Yes** | Order index within the subject (must be unique for subject) | `1` |
| `description` | String | No | Detailed chapter syllabus / notes | `"Memorandum, Articles, ROC filings"` |
| `duration_hours` | Number | No | Estimated duration in hours | `14.5` |
| `is_active` | Boolean | No | Active status (default `true`) | `true` |
| `faculties` | Array[UUID] | No | Array of **User** UUIDs with `role='faculty'` | `["b0a9d4bb-5d40-4751-8cfe-7344a4e148e8", "7882c1e0-8a99-433a-8cc0-3cbcd1464d94"]` |

#### Example Request Body
```json
{
  "name": "Incorporation of Companies",
  "order": 1,
  "description": "Memorandum, Articles, SPICe+ ROC filing procedures",
  "duration_hours": 14.5,
  "is_active": true,
  "faculties": [
    "b0a9d4bb-5d40-4751-8cfe-7344a4e148e8",
    "7882c1e0-8a99-433a-8cc0-3cbcd1464d94"
  ]
}
```

#### Success Response (`201 Created`)
```json
{
  "success": true,
  "message": "Chapter created.",
  "data": {
    "id": "82555c60-d82b-46fb-9e48-2ea0c8ce2e2e",
    "subject": "f5f306bf-2ce9-4606-bdb2-5b30b2a280b4",
    "name": "Incorporation of Companies",
    "order": 1,
    "description": "Memorandum, Articles, SPICe+ ROC filing procedures",
    "is_active": true,
    "duration_hours": 14.5,
    "faculties": [
      "b0a9d4bb-5d40-4751-8cfe-7344a4e148e8",
      "7882c1e0-8a99-433a-8cc0-3cbcd1464d94"
    ],
    "faculties_details": [
      {
        "id": "b0a9d4bb-5d40-4751-8cfe-7344a4e148e8",
        "user_id": "b0a9d4bb-5d40-4751-8cfe-7344a4e148e8",
        "name": "Prof. Rohit Sharma",
        "email": "rohit.sharma@example.com",
        "phone": "9876543210",
        "level": "professional",
        "levels": [
          {
            "id": "333c44a8-24ba-41e1-89a9-92c565cf4fda",
            "name": "CS Professional"
          }
        ]
      },
      {
        "id": "7882c1e0-8a99-433a-8cc0-3cbcd1464d94",
        "user_id": "7882c1e0-8a99-433a-8cc0-3cbcd1464d94",
        "name": "Prof. Anita Desai",
        "email": "anita.desai@example.com",
        "phone": "9876543211",
        "level": "executive",
        "levels": [
          {
            "id": "444d55b9-35cb-52f2-90ba-03d676dg5geb",
            "name": "CS Executive"
          }
        ]
      }
    ]
  }
}
```

---

### 3.2 Update Chapter

Updates chapter metadata and modifies the assigned faculties.

- **URL**: `/api/v1/subjects/<subject_id>/chapters/<chapter_id>/`
- **Method**: `PATCH`
- **Content-Type**: `application/json`
- **Authentication**: Bearer Token
- **Allowed Roles**: `super_admin`, `branch_manager`, `academic_coordinator`

#### Example Request Body
```json
{
  "name": "Incorporation of Companies (Revised)",
  "duration_hours": 16.0,
  "faculties": [
    "b0a9d4bb-5d40-4751-8cfe-7344a4e148e8"
  ]
}
```
> **Note**: Sending `"faculties": []` unassigns all faculties. `faculties` must be **User UUIDs** (not FacultyProfile IDs).

#### Success Response (`200 OK`)
```json
{
  "success": true,
  "message": "Chapter updated.",
  "data": {
    "id": "82555c60-d82b-46fb-9e48-2ea0c8ce2e2e",
    "subject": "f5f306bf-2ce9-4606-bdb2-5b30b2a280b4",
    "name": "Incorporation of Companies (Revised)",
    "order": 1,
    "description": "Memorandum, Articles, SPICe+ ROC filing procedures",
    "is_active": true,
    "duration_hours": 16.0,
    "faculties": [
      "b0a9d4bb-5d40-4751-8cfe-7344a4e148e8"
    ],
    "faculties_details": [
      {
        "id": "b0a9d4bb-5d40-4751-8cfe-7344a4e148e8",
        "user_id": "b0a9d4bb-5d40-4751-8cfe-7344a4e148e8",
        "name": "Prof. Rohit Sharma",
        "email": "rohit.sharma@example.com",
        "phone": "9876543210",
        "level": "professional",
        "levels": ["333c44a8-24ba-41e1-89a9-92c565cf4fda"]
      }
    ]
  }
}
```

---

### 3.3 Get Chapter Detail

Retrieves chapter details with assigned faculties and faculty details.

- **URL**: `/api/v1/subjects/<subject_id>/chapters/<chapter_id>/`
- **Method**: `GET`
- **Authentication**: Bearer Token

#### Success Response (`200 OK`)
```json
{
  "success": true,
  "data": {
    "id": "82555c60-d82b-46fb-9e48-2ea0c8ce2e2e",
    "subject": "f5f306bf-2ce9-4606-bdb2-5b30b2a280b4",
    "name": "Incorporation of Companies",
    "order": 1,
    "description": "Memorandum, Articles, SPICe+ ROC filing procedures",
    "is_active": true,
    "duration_hours": 14.5,
    "faculties": [
      "b0a9d4bb-5d40-4751-8cfe-7344a4e148e8"
    ],
    "faculties_details": [
      {
        "id": "b0a9d4bb-5d40-4751-8cfe-7344a4e148e8",
        "user_id": "b0a9d4bb-5d40-4751-8cfe-7344a4e148e8",
        "name": "Prof. Rohit Sharma",
        "email": "rohit.sharma@example.com",
        "phone": "9876543210",
        "level": "professional",
        "levels": [
          {
            "id": "333c44a8-24ba-41e1-89a9-92c565cf4fda",
            "name": "CS Professional"
          }
        ]
      }
    ]
  }
}
```

---

### 3.4 List Chapters (with Faculty Filtering)

Lists all chapters for a given subject ordered by `order`, with optional filtering by assigned faculty.

- **URL**: `/api/v1/subjects/<subject_id>/chapters/`
- **Method**: `GET`
- **Authentication**: Bearer Token

#### Query Parameters
| Parameter | Type | Description | Example |
|---|---|---|---|
| `faculty_id` | UUID | Filter chapters assigned to a specific **User** (User ID) | `?faculty_id=b0a9d4bb-5d40-4751-8cfe-7344a4e148e8` |
| `faculty` | UUID | Alias for `faculty_id` | `?faculty=b0a9d4bb-5d40-4751-8cfe-7344a4e148e8` |

#### Success Response (`200 OK`)
```json
{
  "success": true,
  "data": [
    {
      "id": "82555c60-d82b-46fb-9e48-2ea0c8ce2e2e",
      "subject": "f5f306bf-2ce9-4606-bdb2-5b30b2a280b4",
      "name": "Incorporation of Companies",
      "order": 1,
      "description": "Memorandum, Articles, SPICe+ ROC filing procedures",
      "is_active": true,
      "duration_hours": 14.5,
      "faculties": [
        "5ddcc745-b419-40c3-a60b-4d8fb4138fda"
      ],
      "faculties_details": [
        {
          "id": "5ddcc745-b419-40c3-a60b-4d8fb4138fda",
          "user_id": "b0a9d4bb-5d40-4751-8cfe-7344a4e148e8",
          "employee_id": "EMP-MUM-0001",
          "name": "Prof. Rohit Sharma",
          "email": "rohit.sharma@example.com",
          "specialization": "Corporate Law & Securities"
        }
      ]
    }
  ]
}
```

---

### 3.5 Delete Chapter

Deletes a chapter from the subject.

- **URL**: `/api/v1/subjects/<subject_id>/chapters/<chapter_id>/`
- **Method**: `DELETE`
- **Authentication**: Bearer Token
- **Allowed Roles**: `super_admin`, `branch_manager`

#### Success Response (`200 OK`)
```json
{
  "success": true,
  "message": "Chapter deleted."
}
```

---

### 3.6 Academic Dropdowns

Retrieves hierarchical courses, levels, subjects, and chapters for form dropdowns. Each chapter item includes `faculty_ids`.

- **URL**: `/api/v1/batches/dropdowns/`
- **Method**: `GET`
- **Authentication**: Bearer Token

#### Success Response (`200 OK`)
```json
{
  "success": true,
  "data": {
    "courses": [ ... ],
    "levels": [ ... ],
    "subjects": [
      {
        "id": "f5f306bf-2ce9-4606-bdb2-5b30b2a280b4",
        "name": "Corporate Laws",
        "code": "CL01",
        "level_id": "4a221d6b-0f58-4b0b-8680-f28b36f8102d",
        "chapters": [
          {
            "id": "82555c60-d82b-46fb-9e48-2ea0c8ce2e2e",
            "name": "Incorporation of Companies",
            "order": 1,
            "faculty_ids": [
              "5ddcc745-b419-40c3-a60b-4d8fb4138fda",
              "bdefb505-e0be-4346-9b8e-2294de3033f7"
            ]
          }
        ]
      }
    ],
    "classrooms": [ ... ]
  }
}
```

---

## 4. Auth & User Management APIs

### 4.1 Add User (Faculty Role)

Allows administrators to add users. When `role='faculty'`, multiple `levels` can be passed. The system creates both the `User` and `FacultyProfile` and synchronizes their level assignments.

- **URL**: `/api/auth/users/add/`
- **Method**: `POST`
- **Content-Type**: `application/json`
- **Authentication**: Bearer Token
- **Allowed Roles**: `super_admin`, `branch_manager`, `hr_admin`

#### Request Body
```json
{
  "name": "Prof. Deepak Gupta",
  "email": "deepak.gupta@example.com",
  "phone": "9811223344",
  "role": "faculty",
  "branch_id": "b97a2cb4-8a4d-44a0-9701-d0074f07a7d4",
  "qualification": "FCS, Ph.D.",
  "specialization": "Economic Laws & Jurisprudence",
  "levels": [
    "4a221d6b-0f58-4b0b-8680-f28b36f8102d",
    "333c44a8-24ba-41e1-89a9-92c565cf4fda"
  ],
  "employment_type": "full_time",
  "joining_date": "2026-02-15",
  "salary": 80000
}
```

#### Step-by-Step Logic
1. Creates `User` model with `role='faculty'`.
2. Resolves `levels` array and attaches to `user.levels`.
3. If no legacy `level` string was passed, defaults to the resolved level or `'cseet'`.
4. Automatically initializes `FacultyProfile` with matching `user`, `branch`, `qualification`, `specialization`, and generates QR code.
5. Copies `user.levels` directly to `fp.levels`.

#### Success Response (`201 Created`)
```json
{
  "success": true,
  "message": "User added successfully.",
  "data": {
    "id": "3c72e27b-2321-4dcb-a734-7389dfae5f11",
    "name": "Prof. Deepak Gupta",
    "email": "deepak.gupta@example.com",
    "role": "faculty",
    "levels": [
      {
        "id": "4a221d6b-0f58-4b0b-8680-f28b36f8102d",
        "name": "CS Executive"
      },
      {
        "id": "333c44a8-24ba-41e1-89a9-92c565cf4fda",
        "name": "CS Professional"
      }
    ],
    "levels_details": [
      {
        "id": "4a221d6b-0f58-4b0b-8680-f28b36f8102d",
        "name": "CS Executive",
        "course_id": "60886ef6-9e04-40bc-9ace-87e457e4c359",
        "course_name": "Company Secretary (CS)"
      },
      {
        "id": "333c44a8-24ba-41e1-89a9-92c565cf4fda",
        "name": "CS Professional",
        "course_id": "60886ef6-9e04-40bc-9ace-87e457e4c359",
        "course_name": "Company Secretary (CS)"
      }
    ],
    "is_active": true
  }
}
```

---

### 4.2 Update User (Faculty Role)

Updates user record and automatically synchronizes changed `levels` to the user's `FacultyProfile`.

- **URL**: `/api/auth/users/<user_id>/`
- **Method**: `PATCH`
- **Content-Type**: `application/json`
- **Authentication**: Bearer Token
- **Allowed Roles**: `super_admin`, `branch_manager`, `hr_admin`

#### Request Body
```json
{
  "levels": [
    "e39e7690-38f7-4fb3-a0cb-496ac6fdbd00"
  ]
}
```

#### Success Response (`200 OK`)
```json
{
  "success": true,
  "message": "User updated successfully.",
  "data": {
    "id": "3c72e27b-2321-4dcb-a734-7389dfae5f11",
    "name": "Prof. Deepak Gupta",
    "email": "deepak.gupta@example.com",
    "role": "faculty",
    "levels": [
      {
        "id": "e39e7690-38f7-4fb3-a0cb-496ac6fdbd00",
        "name": "CSEET"
      }
    ],
    "levels_details": [
      {
        "id": "e39e7690-38f7-4fb3-a0cb-496ac6fdbd00",
        "name": "CSEET",
        "course_id": "60886ef6-9e04-40bc-9ace-87e457e4c359",
        "course_name": "Company Secretary (CS)"
      }
    ]
  }
}
```

---

### 4.3 User List & Profile Representation

When querying `/api/auth/users/` or `/api/auth/me/`, users with `role='faculty'` include `levels` (list of `{"id": "...", "name": "..."}` objects) and `levels_details` (with full course metadata) in their response object.

---

## 5. Common Errors & Status Codes

| Status Code | Error Response | Cause | Resolution |
|---|---|---|---|
| **400 Bad Request** | `{"success": false, "message": "Email already exists."}` | Email address already taken | Provide a unique email address |
| **400 Bad Request** | `{"success": false, "errors": {"order": ["A chapter with order X already exists for this subject."]}}` | Duplicate chapter order | Assign a different order index |
| **400 Bad Request** | `{"success": false, "message": "Branch is required."}` | Super admin creating faculty without specifying branch | Pass `"branch": "<uuid>"` in request body |
| **403 Forbidden** | `{"success": false, "message": "Permission denied."}` | User lacks the required role or permission | Ensure user has valid admin or manager role |
| **404 Not Found** | `{"success": false, "message": "Subject not found."}` | Invalid subject UUID in URL | Verify subject UUID exists in organization |
| **404 Not Found** | `{"success": false, "message": "Chapter not found."}` | Invalid chapter UUID in URL | Verify chapter UUID exists |
| **404 Not Found** | `{"success": false, "message": "Not found."}` | Faculty profile does not exist | Verify faculty profile UUID |
