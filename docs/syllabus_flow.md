# Curriculum Hierarchy & Syllabus Flow

This document provides complete documentation for the curriculum hierarchy, covering the `Syllabus` layer, optional `SyllabusModule` layer, flexible chapter structures, and exhaustive API reference with request bodies and responses.

---

## 1. Hierarchy & Flexibility Overview

The curriculum data supports both **modular** (e.g., CS Executive Module 1 & 2) and **flat** (e.g., CSEET direct subjects/chapters) syllabus structures:

```
Course ➔ CourseLevel ➔ Syllabus
                          ├── start_date, end_date (optional)
                          ├── Modules (Optional: Module 1, Module 2, etc.)
                          │     ├── Chapters (inside Module)
                          │     └── Subjects (inside Module)
                          ├── Direct Chapters (without Module)
                          └── Direct Subjects (without Module) ➔ Chapters
```

---

## 2. Models & Fields

### Syllabus Model (`batches.models.Syllabus`)
* `id`: UUID (Primary Key)
* `organization`: Foreign Key to `Organization` (auto-assigned from request user)
* `level`: Foreign Key to `CourseLevel`
* `name`: String (Max 200 chars)
* `year`: Positive Integer (Optional, e.g., `2026`)
* `description`: Text
* `start_date`: Date (`YYYY-MM-DD`, start of syllabus period)
* `end_date`: Date (`YYYY-MM-DD`, optional end date; validated to be `>= start_date`)
* `is_active`: Boolean (Default: `true`)
* `created_at`: Datetime

### SyllabusModule Model (`batches.models.SyllabusModule`)
Optional grouping layer inside a Syllabus:
* `id`: UUID (Primary Key)
* `organization`: Foreign Key to `Organization`
* `syllabus`: Foreign Key to `Syllabus`
* `name`: String (e.g., `"Module 1"`, `"Module 2"`)
* `order`: Positive Small Integer (Optional sorting index)
* `description`: Text
* `is_active`: Boolean (Default: `true`)
* `created_at`: Datetime

### Chapter Model (`batches.models.Chapter`)
Chapters can be attached to a module, directly to a syllabus, or to a subject:
* `id`: UUID (Primary Key)
* `subject`: Foreign Key to `Subject` (nullable)
* `syllabus`: Foreign Key to `Syllabus` (nullable, auto-linked if parent has syllabus)
* `module`: Foreign Key to `SyllabusModule` (nullable, for chapters grouped in a module)
* `name`: String (Max 200 chars)
* `order`: Positive Small Integer (Optional)
* `duration_hours`: Positive Integer (Default: `0`)
* `description`: Text
* `faculties`: Many-to-Many to `User` (`role='faculty'`)
* `is_active`: Boolean (Default: `true`)

### Subject Model (`batches.models.Subject`)
* `id`: UUID (Primary Key)
* `level`: Foreign Key to `CourseLevel`
* `syllabus`: Foreign Key to `Syllabus` (nullable)
* `module`: Foreign Key to `SyllabusModule` (nullable)
* `name`: String (Max 200 chars)
* `code`: String (Max 30 chars)
* `total_hours`: Positive Integer (auto-updated from chapter duration hours)
* `is_active`: Boolean (Default: `true`)

---

## 3. Comprehensive API Reference

All requests must include an authorization header:
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

---

### A. Syllabus Endpoints

#### 1. List Syllabuses for a Level
Returns all syllabuses configured under a course level.

* **Endpoint:** `GET /api/v1/courses/<course_id>/levels/<level_id>/syllabuses/`
* **Request Body:** None
* **Response:** `200 OK`
```json
{
  "success": true,
  "data": [
    {
      "id": "c1f7b822-4411-4ae2-a129-37f28734e561",
      "level": "8349d898-4538-418b-971b-2bddbacff786",
      "name": "2026 New Syllabus",
      "year": 2026,
      "description": "Applicable for batches starting June 2026 onwards.",
      "start_date": "2026-06-01",
      "end_date": "2027-05-31",
      "is_active": true,
      "created_at": "2026-10-15 11:00:00",
      "modules": [
        {
          "id": "b3e21124-3456-4cf8-a921-239102431289",
          "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
          "name": "Module 1",
          "order": 1,
          "description": "Module 1 subjects and chapters",
          "is_active": true,
          "created_at": "2026-10-15 11:05:00",
          "subjects": [],
          "chapters": []
        }
      ],
      "subjects": [],
      "chapters": []
    }
  ]
}
```

---

#### 2. Create a Syllabus
Creates a new syllabus under a specific course level. `end_date` is optional.

* **Endpoint:** `POST /api/v1/courses/<course_id>/levels/<level_id>/syllabuses/`
* **Request Body:**
```json
{
  "name": "2026 New Syllabus",
  "year": 2026,
  "start_date": "2026-06-01",
  "end_date": null,
  "description": "Applicable for batches starting June 2026 onwards.",
  "is_active": true
}
```
*(Note: `end_date` is optional and can be `null` or omitted. If provided, it must be `>= start_date`.)*

* **Response:** `201 Created`
```json
{
  "success": true,
  "message": "Syllabus created.",
  "data": {
    "id": "c1f7b822-4411-4ae2-a129-37f28734e561",
    "level": "8349d898-4538-418b-971b-2bddbacff786",
    "name": "2026 New Syllabus",
    "year": 2026,
    "description": "Applicable for batches starting June 2026 onwards.",
    "start_date": "2026-06-01",
    "end_date": null,
    "is_active": true,
    "created_at": "2026-10-15 11:00:00",
    "modules": [],
    "subjects": [],
    "chapters": []
  }
}
```

* **Error Response:** `400 Bad Request` (when `end_date < start_date`)
```json
{
  "success": false,
  "errors": {
    "end_date": [
      "End date cannot be earlier than start date."
    ]
  }
}
```

---

#### 3. Retrieve Syllabus Details
Returns detailed nested structure including all modules (with their chapters and subjects), as well as direct chapters and subjects without any module.

* **Endpoint:** `GET /api/v1/courses/<course_id>/levels/<level_id>/syllabuses/<syllabus_id>/`
* **Request Body:** None
* **Response:** `200 OK`
```json
{
  "success": true,
  "data": {
    "id": "c1f7b822-4411-4ae2-a129-37f28734e561",
    "level": "8349d898-4538-418b-971b-2bddbacff786",
    "name": "2026 New Syllabus",
    "year": 2026,
    "description": "Applicable for batches starting June 2026 onwards.",
    "start_date": "2026-06-01",
    "end_date": null,
    "is_active": true,
    "created_at": "2026-10-15 11:00:00",
    "modules": [
      {
        "id": "b3e21124-3456-4cf8-a921-239102431289",
        "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
        "name": "Module 1",
        "order": 1,
        "description": "Module 1 topics",
        "is_active": true,
        "created_at": "2026-10-15 11:05:00",
        "subjects": [
          {
            "id": "782bb211-1234-4ae2-b111-987654321012",
            "name": "Jurisprudence, Interpretation & General Laws",
            "code": "JIGL",
            "level": "8349d898-4538-418b-971b-2bddbacff786",
            "level_name": "Executive",
            "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
            "syllabus_name": "2026 New Syllabus",
            "module": "b3e21124-3456-4cf8-a921-239102431289",
            "module_name": "Module 1",
            "total_hours": 35,
            "is_active": true,
            "chapters": [
              {
                "id": "f51239aa-0912-4c21-9988-123456789abc",
                "name": "Sources of Law",
                "order": 1,
                "duration_hours": 10,
                "module": "b3e21124-3456-4cf8-a921-239102431289",
                "module_name": "Module 1",
                "subject": "782bb211-1234-4ae2-b111-987654321012",
                "subject_name": "Jurisprudence, Interpretation & General Laws"
              }
            ]
          }
        ],
        "chapters": [
          {
            "id": "d1234567-89ab-cdef-0123-456789abcdef",
            "name": "General Orientation",
            "order": 1,
            "duration_hours": 4,
            "module": "b3e21124-3456-4cf8-a921-239102431289",
            "module_name": "Module 1",
            "subject": null,
            "subject_name": null,
            "faculties": [],
            "faculties_details": []
          }
        ]
      }
    ],
    "subjects": [],
    "chapters": [
      {
        "id": "a9876543-210f-edcb-a987-654321fedcba",
        "name": "Soft Skills & Ethics Seminar",
        "order": 1,
        "duration_hours": 5,
        "module": null,
        "module_name": null,
        "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
        "syllabus_name": "2026 New Syllabus",
        "subject": null,
        "subject_name": null,
        "faculties": [],
        "faculties_details": []
      }
    ]
  }
}
```

---

#### 4. Update a Syllabus
* **Endpoint:** `PATCH /api/v1/courses/<course_id>/levels/<level_id>/syllabuses/<syllabus_id>/`
* **Request Body:**
```json
{
  "end_date": "2028-12-31",
  "description": "Extended validity period."
}
```
* **Response:** `200 OK`
```json
{
  "success": true,
  "message": "Syllabus updated.",
  "data": {
    "id": "c1f7b822-4411-4ae2-a129-37f28734e561",
    "level": "8349d898-4538-418b-971b-2bddbacff786",
    "name": "2026 New Syllabus",
    "year": 2026,
    "description": "Extended validity period.",
    "start_date": "2026-06-01",
    "end_date": "2028-12-31",
    "is_active": true,
    "created_at": "2026-10-15 11:00:00",
    "modules": [],
    "subjects": [],
    "chapters": []
  }
}
```

---

#### 5. Delete a Syllabus
* **Endpoint:** `DELETE /api/v1/courses/<course_id>/levels/<level_id>/syllabuses/<syllabus_id>/`
* **Request Body:** None
* **Response:** `200 OK`
```json
{
  "success": true,
  "message": "Syllabus deleted."
}
```

---

### B. Syllabus Modules Endpoints (Optional)

#### 1. List Modules for a Syllabus
* **Endpoint:** `GET /api/v1/syllabuses/<syllabus_id>/modules/`
* **Request Body:** None
* **Response:** `200 OK`
```json
{
  "success": true,
  "data": [
    {
      "id": "b3e21124-3456-4cf8-a921-239102431289",
      "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
      "name": "Module 1",
      "order": 1,
      "description": "Module 1 description",
      "is_active": true,
      "created_at": "2026-10-15 11:05:00",
      "subjects": [],
      "chapters": []
    },
    {
      "id": "d8a11987-6543-41ef-bb22-998877665544",
      "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
      "name": "Module 2",
      "order": 2,
      "description": "Module 2 description",
      "is_active": true,
      "created_at": "2026-10-15 11:06:00",
      "subjects": [],
      "chapters": []
    }
  ]
}
```

---

#### 2. Create a Module under a Syllabus
* **Endpoint:** `POST /api/v1/syllabuses/<syllabus_id>/modules/`
* **Request Body:**
```json
{
  "name": "Module 1",
  "order": 1,
  "description": "First group of syllabus papers",
  "is_active": true
}
```
* **Response:** `201 Created`
```json
{
  "success": true,
  "message": "Module created.",
  "data": {
    "id": "b3e21124-3456-4cf8-a921-239102431289",
    "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
    "name": "Module 1",
    "order": 1,
    "description": "First group of syllabus papers",
    "is_active": true,
    "created_at": "2026-10-15 11:05:00",
    "subjects": [],
    "chapters": []
  }
}
```

---

#### 3. Retrieve a Single Module
* **Endpoint:** `GET /api/v1/syllabuses/<syllabus_id>/modules/<module_id>/`
* **Request Body:** None
* **Response:** `200 OK`
```json
{
  "success": true,
  "data": {
    "id": "b3e21124-3456-4cf8-a921-239102431289",
    "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
    "name": "Module 1",
    "order": 1,
    "description": "First group of syllabus papers",
    "is_active": true,
    "created_at": "2026-10-15 11:05:00",
    "subjects": [],
    "chapters": []
  }
}
```

---

#### 4. Update a Module
* **Endpoint:** `PATCH /api/v1/syllabuses/<syllabus_id>/modules/<module_id>/`
* **Request Body:**
```json
{
  "name": "Module 1 (Group A)",
  "order": 1
}
```
* **Response:** `200 OK`
```json
{
  "success": true,
  "message": "Module updated.",
  "data": {
    "id": "b3e21124-3456-4cf8-a921-239102431289",
    "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
    "name": "Module 1 (Group A)",
    "order": 1,
    "description": "First group of syllabus papers",
    "is_active": true,
    "created_at": "2026-10-15 11:05:00",
    "subjects": [],
    "chapters": []
  }
}
```

---

#### 5. Delete a Module
* **Endpoint:** `DELETE /api/v1/syllabuses/<syllabus_id>/modules/<module_id>/`
* **Request Body:** None
* **Response:** `200 OK`
```json
{
  "success": true,
  "message": "Module deleted."
}
```

---

### C. Chapters in Modules or Directly in Syllabus

#### 1. Add Chapter Inside a Module
Allows directly creating and assigning a chapter to a module.

* **Endpoint:** `POST /api/v1/syllabuses/<syllabus_id>/modules/<module_id>/chapters/`
* **Request Body:**
```json
{
  "name": "Sources of Law & Jurisprudence",
  "order": 1,
  "duration_hours": 12,
  "description": "Overview of jurisprudence sources",
  "faculties": [
    "550e8400-e29b-41d4-a716-446655440000"
  ],
  "is_active": true
}
```
* **Response:** `201 Created`
```json
{
  "success": true,
  "message": "Chapter created in module.",
  "data": {
    "id": "d1234567-89ab-cdef-0123-456789abcdef",
    "subject": null,
    "subject_name": null,
    "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
    "syllabus_name": "2026 New Syllabus",
    "module": "b3e21124-3456-4cf8-a921-239102431289",
    "module_name": "Module 1",
    "name": "Sources of Law & Jurisprudence",
    "order": 1,
    "description": "Overview of jurisprudence sources",
    "is_active": true,
    "duration_hours": 12,
    "faculties": [
      "550e8400-e29b-41d4-a716-446655440000"
    ],
    "faculties_details": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "user_id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "Prof. Sharma",
        "email": "sharma@institute.com",
        "phone": "9876543210",
        "level": "",
        "levels": []
      }
    ]
  }
}
```

---

#### 2. List Chapters Inside a Specific Module
* **Endpoint:** `GET /api/v1/syllabuses/<syllabus_id>/modules/<module_id>/chapters/`
* **Request Body:** None
* **Response:** `200 OK`
```json
{
  "success": true,
  "data": [
    {
      "id": "d1234567-89ab-cdef-0123-456789abcdef",
      "subject": null,
      "subject_name": null,
      "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
      "syllabus_name": "2026 New Syllabus",
      "module": "b3e21124-3456-4cf8-a921-239102431289",
      "module_name": "Module 1",
      "name": "Sources of Law & Jurisprudence",
      "order": 1,
      "description": "Overview of jurisprudence sources",
      "is_active": true,
      "duration_hours": 12,
      "faculties": ["550e8400-e29b-41d4-a716-446655440000"],
      "faculties_details": [
        {
          "id": "550e8400-e29b-41d4-a716-446655440000",
          "user_id": "550e8400-e29b-41d4-a716-446655440000",
          "name": "Prof. Sharma",
          "email": "sharma@institute.com",
          "phone": "9876543210",
          "level": "",
          "levels": []
        }
      ]
    }
  ]
}
```

---

#### 3. Add Chapter Directly to Syllabus WITHOUT a Module
If no module is needed, chapters can be added directly to the syllabus container.

* **Endpoint:** `POST /api/v1/syllabuses/<syllabus_id>/chapters/`
* **Request Body:**
```json
{
  "name": "Orientation & Foundation Topics",
  "order": 1,
  "duration_hours": 6,
  "description": "Mandatory introductory workshop",
  "is_active": true
}
```
* **Response:** `201 Created`
```json
{
  "success": true,
  "message": "Chapter created.",
  "data": {
    "id": "a9876543-210f-edcb-a987-654321fedcba",
    "subject": null,
    "subject_name": null,
    "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
    "syllabus_name": "2026 New Syllabus",
    "module": null,
    "module_name": null,
    "name": "Orientation & Foundation Topics",
    "order": 1,
    "description": "Mandatory introductory workshop",
    "is_active": true,
    "duration_hours": 6,
    "faculties": [],
    "faculties_details": []
  }
}
```

---

#### 4. List Chapters in a Syllabus (With Filters)
Supports querying direct chapters or chapters belonging to a specific module.

* **Query Parameters:**
  * `?without_module=true`: Returns only chapters not in any module.
  * `?module_id=<uuid>`: Returns only chapters in the specified module.

* **Endpoint:** `GET /api/v1/syllabuses/<syllabus_id>/chapters/?without_module=true`
* **Request Body:** None
* **Response:** `200 OK`
```json
{
  "success": true,
  "data": [
    {
      "id": "a9876543-210f-edcb-a987-654321fedcba",
      "subject": null,
      "subject_name": null,
      "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
      "syllabus_name": "2026 New Syllabus",
      "module": null,
      "module_name": null,
      "name": "Orientation & Foundation Topics",
      "order": 1,
      "description": "Mandatory introductory workshop",
      "is_active": true,
      "duration_hours": 6,
      "faculties": [],
      "faculties_details": []
    }
  ]
}
```

---

#### 5. Subject Chapters Endpoints (Standard & Filterable by Module)

##### List Chapters of a Subject
* **Endpoint:** `GET /api/v1/subjects/<subject_id>/chapters/`
* **Query Parameters:** `?module_id=<uuid>` (optional)
* **Response:** `200 OK`
```json
{
  "success": true,
  "data": [
    {
      "id": "f51239aa-0912-4c21-9988-123456789abc",
      "subject": "782bb211-1234-4ae2-b111-987654321012",
      "subject_name": "Jurisprudence, Interpretation & General Laws",
      "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
      "syllabus_name": "2026 New Syllabus",
      "module": "b3e21124-3456-4cf8-a921-239102431289",
      "module_name": "Module 1",
      "name": "Sources of Law",
      "order": 1,
      "description": "Primary and secondary sources",
      "is_active": true,
      "duration_hours": 10,
      "faculties": ["550e8400-e29b-41d4-a716-446655440000"],
      "faculties_details": []
    }
  ]
}
```

##### Add Chapter to a Subject
* **Endpoint:** `POST /api/v1/subjects/<subject_id>/chapters/`
* **Request Body:**
```json
{
  "name": "Constitution of India",
  "order": 2,
  "duration_hours": 15,
  "description": "Fundamental Rights and Directive Principles",
  "module": "b3e21124-3456-4cf8-a921-239102431289",
  "faculties": ["550e8400-e29b-41d4-a716-446655440000"]
}
```
*(Note: If `module` is omitted, and the subject has a module, it is automatically inherited.)*

* **Response:** `201 Created`
```json
{
  "success": true,
  "message": "Chapter created.",
  "data": {
    "id": "e4412399-5566-4c77-a889-9988776655aa",
    "subject": "782bb211-1234-4ae2-b111-987654321012",
    "subject_name": "Jurisprudence, Interpretation & General Laws",
    "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
    "syllabus_name": "2026 New Syllabus",
    "module": "b3e21124-3456-4cf8-a921-239102431289",
    "module_name": "Module 1",
    "name": "Constitution of India",
    "order": 2,
    "description": "Fundamental Rights and Directive Principles",
    "is_active": true,
    "duration_hours": 15,
    "faculties": ["550e8400-e29b-41d4-a716-446655440000"],
    "faculties_details": []
  }
}
```

##### Update Chapter
* **Endpoint:** `PATCH /api/v1/subjects/<subject_id>/chapters/<chapter_id>/`
* **Request Body:**
```json
{
  "duration_hours": 18,
  "order": 2
}
```
* **Response:** `200 OK`
```json
{
  "success": true,
  "message": "Chapter updated.",
  "data": {
    "id": "e4412399-5566-4c77-a889-9988776655aa",
    "name": "Constitution of India",
    "duration_hours": 18,
    "order": 2
  }
}
```

##### Delete Chapter
* **Endpoint:** `DELETE /api/v1/subjects/<subject_id>/chapters/<chapter_id>/`
* **Request Body:** None
* **Response:** `200 OK`
```json
{
  "success": true,
  "message": "Chapter deleted."
}
```

---

### D. Subjects Association with Syllabus and Module

#### Create a Subject with Syllabus and Optional Module
* **Endpoint:** `POST /api/v1/subjects/`
* **Request Body:**
```json
{
  "level": "8349d898-4538-418b-971b-2bddbacff786",
  "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
  "module": "b3e21124-3456-4cf8-a921-239102431289",
  "name": "Company Law & Practice",
  "code": "CLAW",
  "is_active": true
}
```
*(Note: `module` is optional; omit or pass `null` for subjects without a module.)*

* **Response:** `201 Created`
```json
{
  "success": true,
  "message": "Subject created.",
  "data": {
    "id": "89ab0123-45cd-67ef-8901-234567890abc",
    "level": "8349d898-4538-418b-971b-2bddbacff786",
    "level_name": "Executive",
    "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
    "syllabus_name": "2026 New Syllabus",
    "module": "b3e21124-3456-4cf8-a921-239102431289",
    "module_name": "Module 1",
    "name": "Company Law & Practice",
    "code": "CLAW",
    "total_hours": 0,
    "is_active": true,
    "chapters": [],
    "papers": [],
    "exams": []
  }
}
```

#### Filter Subjects by Syllabus
* **Endpoint:** `GET /api/v1/subjects/?syllabus_id=<syllabus_id>`
* **Request Body:** None
* **Response:** `200 OK`
```json
{
  "success": true,
  "data": [
    {
      "id": "89ab0123-45cd-67ef-8901-234567890abc",
      "level": "8349d898-4538-418b-971b-2bddbacff786",
      "level_name": "Executive",
      "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
      "syllabus_name": "2026 New Syllabus",
      "module": "b3e21124-3456-4cf8-a921-239102431289",
      "module_name": "Module 1",
      "name": "Company Law & Practice",
      "code": "CLAW",
      "total_hours": 0,
      "is_active": true,
      "chapters": [],
      "papers": [],
      "exams": []
    }
  ]
}
```

---

### E. Batch Association with Syllabus

#### Create a Batch Linked to Syllabus
* **Endpoint:** `POST /api/v1/batches/`
* **Request Body:**
```json
{
  "course": "11223344-5566-7788-99aa-bbccddeeff00",
  "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
  "branch": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
  "name": "Morning Executive Batch June 2026",
  "start_date": "2026-06-01",
  "group_module": "module_1",
  "max_students": 60
}
```
* **Response:** `201 Created`
```json
{
  "success": true,
  "message": "Batch created successfully.",
  "data": {
    "id": "fa123456-7890-bcde-f123-456789abcdef",
    "batch_code": "BAT-0042",
    "name": "Morning Executive Batch June 2026",
    "course": "11223344-5566-7788-99aa-bbccddeeff00",
    "course_name": "CS Executive",
    "syllabus": "c1f7b822-4411-4ae2-a129-37f28734e561",
    "syllabus_name": "2026 New Syllabus",
    "group_module": "module_1",
    "start_date": "2026-06-01",
    "is_active": true
  }
}
```
