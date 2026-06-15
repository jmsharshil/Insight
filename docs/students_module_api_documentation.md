# Students Module — API Documentation

The `students` module manages the active student database, including profiles, digital ID cards, document storage, batch history, and inventory.

---

## Data Model

| Model | Purpose |
|---|---|
| `Student` | Core student profile (created upon Admission enrollment) |
| `ParentLink` | Links parent user accounts to students |
| `BatchHistory` | Immutable log of a student's batch movements |
| `InventoryIssue` | Logs items issued to students (e.g., uniform, ID card, books) |
| `DigitalIDCard` | QR-based digital identity card for attendance |
| `StudentStatusHistory` | Immutable log of status transitions |

### Student Statuses
`active`, `inactive`, `transferred`, `alumni`, `suspended`

---

## API Endpoints

### 1. List & View Students
**`GET /api/v1/students/`**
**`GET /api/v1/students/<uuid>/`**

### 2. Student Self-Profile
**`GET /api/v1/students/<uuid>/profile/`**
Special view optimized for the student portal / app to fetch their own details.

### 3. QR Identity
**`GET /api/v1/students/<uuid>/qr-id/`**
**`POST /api/v1/students/<uuid>/regenerate-id-card/`**
Generates and serves the digital ID card (image + QR code) for attendance check-ins. A photo is mandatory before generation.

### 4. Update Status
**`POST /api/v1/students/<uuid>/status/`**
Updates student status (e.g., marking as `alumni` or `suspended`) and records reason.

### 5. Batch Allocation
**`POST /api/v1/students/<uuid>/batch/`**
Assigns or changes a student's current batch and creates an immutable `BatchHistory` log.

### 6. Document Upload
**`POST /api/v1/students/<uuid>/documents/`**
Upload supporting documentation directly to the student profile.

### 7. Inventory Tracking
**`GET /api/v1/students/<uuid>/inventory/`**
**`POST /api/v1/students/<uuid>/inventory/`**
Issue new inventory items (books, uniforms) to a student.
