# Batches Module — API Documentation

The `batches` module manages academic structures, including courses, subjects, batches (class sections), classrooms, and timetables.

---

## Data Model

| Model | Purpose |
|---|---|
| `Course` | High-level course (e.g., CSEET, CS Executive) |
| `CourseLevel` | Levels within a course (e.g., Module 1, Module 2) |
| `Subject` | Subjects taught within a CourseLevel |
| `Chapter` | Chapters within a Subject |
| `Batch` | A specific class of students for a Course |
| `BatchStudent` | Links students to batches |
| `BatchFaculty` | Links faculty to batches and specific subjects |
| `Classroom` | Physical rooms available for scheduling |
| `TimetableSlot` | Specific scheduled sessions |
| `TimetableExamType` | Types of exams scheduled via timetable |

---

## API Endpoints

### 1. Courses
**`GET /api/v1/courses/`**
**`GET /api/v1/courses/<uuid>/`**

### 2. Course Levels
**`GET /api/v1/courses/<course_id>/levels/`**
**`GET /api/v1/courses/<course_id>/levels/<level_id>/`**

### 3. Subjects
**`GET /api/v1/subjects/`**
**`GET /api/v1/subjects/<uuid>/`**

### 4. Chapters
**`GET /api/v1/subjects/<subject_id>/chapters/`**
**`GET /api/v1/subjects/<subject_id>/chapters/<chapter_id>/`**

### 5. Batches
**`GET /api/v1/batches/`**
**`GET /api/v1/batches/<uuid>/`**

**`POST /api/v1/batches/<batch_id>/assign-students/`**
**`DELETE /api/v1/batches/<batch_id>/remove-student/<student_id>/`**

**`POST /api/v1/batches/<batch_id>/assign-faculty/`**
**`DELETE /api/v1/batches/<batch_id>/remove-faculty/<faculty_id>/`**

### 6. Classrooms
**`GET /api/v1/classrooms/`**
**`GET /api/v1/classrooms/<uuid>/`**

### 7. Timetable Slots
**`GET /api/v1/timetable/`**
**`GET /api/v1/timetable/<uuid>/`**

- Retrieves and creates timetable slots.
- Slots usually follow a daily fixed schedule, but new slot codes `P5` and `P6` allow for custom, flexible timings (with specific date and start/end time support) without a fixed predefined timetable pattern.
- Creating a slot with `exam_data` (for `class_test` or `prelim`) will automatically generate an `Exam` record.

### 8. Faculty / Student Timetable
**`GET /api/v1/timetable/faculty/<faculty_id>/`**
**`GET /api/v1/timetable/student/<student_id>/`**

### 9. Dropdowns
**`GET /api/v1/batches/dropdowns/`**
Provides available choices for frontend forms (e.g., attempt types, days, sessions).
