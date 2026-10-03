# Curriculum Hierarchy & Syllabus Flow

This document outlines the updated hierarchy for the course curriculum, specifically detailing the introduction of the `Syllabus` layer.

## 1. Updated Hierarchy
The curriculum data is structured in the following top-down hierarchy:

1. **Course**: The highest-level container (e.g., "CS Executive").
2. **Course Level**: Sub-divisions within a course.
3. **Syllabus (NEW)**: Represents a specific syllabus structure for a given year/period within a course level.
4. **Subject**: Individual subjects that belong to a syllabus (and maintain backward compatibility with `CourseLevel`).
5. **Chapter**: Topics within a subject.

`Course` ➔ `CourseLevel` ➔ `Syllabus` ➔ `Subject` ➔ `Chapter`

---

## 2. Model Structure

### Syllabus Model (`batches.models.Syllabus`)
The newly introduced model sits between `CourseLevel` and `Subject`.
*   **id**: UUID (Primary Key)
*   **organization**: Foreign Key to `Organization`
*   **level**: Foreign Key to `CourseLevel`
*   **name**: String (Max 200 chars)
*   **year**: Positive Integer (Optional, used to track syllabus year)
*   **description**: Text
*   **is_active**: Boolean (Default: True)
*   **created_at**: Datetime

### Subject Model Updates (`batches.models.Subject`)
*   **syllabus**: Foreign Key to `Syllabus` (nullable). Subjects can now be grouped explicitly by syllabus.
*   **level**: Kept for backwards compatibility but logically superseded by `syllabus`.

---

## 3. API Endpoints

### A. Managing Syllabuses
Syllabuses are managed under a specific Course and Course Level. 

*   **List Syllabuses for a Level**
    *   `GET /api/v1/courses/<course_id>/levels/<level_id>/syllabuses/`
*   **Create a Syllabus**
    *   `POST /api/v1/courses/<course_id>/levels/<level_id>/syllabuses/`
    *   *Payload:* `{ "name": "2024 Syllabus", "year": 2024, "description": "...", "is_active": true }`
*   **Retrieve a Syllabus**
    *   `GET /api/v1/courses/<course_id>/levels/<level_id>/syllabuses/<syllabus_id>/`
*   **Update a Syllabus**
    *   `PATCH /api/v1/courses/<course_id>/levels/<level_id>/syllabuses/<syllabus_id>/`
    *   *Payload:* `{ "year": 2025 }`
*   **Delete a Syllabus**
    *   `DELETE /api/v1/courses/<course_id>/levels/<level_id>/syllabuses/<syllabus_id>/`

### B. Nested Syllabus Data in Course Levels
When fetching a `CourseLevel` via `GET /courses/<course_id>/levels/`, the response will automatically include an array of its active syllabuses under the `syllabuses` key:
```json
{
  "id": "uuid",
  "name": "Level 1",
  "syllabuses": [
    {
      "id": "uuid",
      "name": "2024 Syllabus",
      "year": 2024,
      "subjects": [ /* Nested subjects belonging to this syllabus */ ]
    }
  ]
}
```

### C. Subjects API Updates
*   **List Subjects**: `GET /api/v1/subjects/`
*   **Filter by Syllabus**: You can now filter the global subjects list by a specific syllabus.
    *   `GET /api/v1/subjects/?syllabus_id=<uuid>`
*   **Response Payload**: Subject objects now return `syllabus` (UUID) and `syllabus_name` (String).
*   **Create/Update Subject**: 
    *   `POST /api/v1/subjects/`
### D. Batch Association
*   **Batch Creation**: When creating a `Batch`, you must explicitly select a `syllabus`.
    *   *Payload:* `{ "course": "<uuid>", "syllabus": "<uuid>", ... }`
*   **Batch Retrieval**: `BatchListSerializer` and `BatchDetailSerializer` now include `syllabus` (UUID) and `syllabus_name` (String).
