# Additional Roles Feature Documentation

## Overview

The **Additional Roles** feature allows users to have multiple roles in addition to their primary role. When additional roles are assigned to a user, their `accessible_modules` are automatically updated to include all modules from both their primary role and any additional roles.

## Key Components

### 1. User Model Changes

Added a new field to the `User` model:

```python
additional_roles = models.JSONField(
    null=True, blank=True, default=list,
    help_text="List of additional roles for this user. Modules from these roles are merged into accessible_modules."
)
```

### 2. Permission Logic Enhancement

Added a helper function in `auth_user/permissions.py`:

```python
def merge_modules_from_roles(primary_role, additional_roles_list):
    """
    Merge modules from a primary role and a list of additional roles.
    Returns a sorted list of unique modules.
    """
```

This function:
- Takes a primary role and a list of additional roles
- Gets the default modules for each role from `ROLE_PERMISSIONS`
- Returns a merged, sorted list of unique modules

### 3. Serializer Updates

#### AddUserSerializer
- Added `additional_roles` field (ListField with validation)
- Updated `validate_additional_roles()` to validate that roles exist in `ROLE_PERMISSIONS`
- Updated `create()` method to:
  - Extract additional_roles from input
  - Call `merge_modules_from_roles()` to compute merged modules
  - Set `accessible_modules` to the merged modules
  - Store `additional_roles` on the user instance

#### UpdateUserSerializer
- Added `additional_roles` field
- Updated validation and update logic similar to AddUserSerializer
- Allows partial updates (PATCH requests)

#### Response Serializers
Updated the following serializers to include `additional_roles` in their output fields:
- `UserSerializer`
- `UserListSerializer`

### 4. API Behavior

#### Creating a User with Additional Roles

**Request:**
```json
POST /api/v1/add-user/
{
    "email": "user@example.com",
    "name": "User Name",
    "phone": "9999999999",
    "role": "admin_executive",
    "branch": "branch-id",
    "additional_roles": ["accountant", "counsellor"]
}
```

**Response:**
```json
{
    "id": "user-id",
    "email": "user@example.com",
    "name": "User Name",
    "role": "admin_executive",
    "additional_roles": ["accountant", "counsellor"],
    "accessible_modules": [
        "support", "students", "attendance", "courses_batches", 
        "timetable", "payroll", "settings", "notifications", "leave",
        "crm", "fees", "chat", "notifications"
    ],
    ...
}
```

#### Updating a User's Additional Roles

**Request:**
```json
PATCH /api/v1/users/{user-id}/
{
    "additional_roles": ["accountant"]
}
```

The serializer will:
1. Merge the new additional_roles with the primary role's modules
2. Update `accessible_modules` to include all merged modules
3. Store the new `additional_roles` list

#### Login Response

The login response now includes `additional_roles`:

```json
{
    "user": {
        ...
        "role": "admin_executive",
        "additional_roles": ["accountant"],
        "accessible_modules": [...]
    }
}
```

## Backward Compatibility

✅ **Fully backward compatible**

- Users without `additional_roles` continue to work as before
- The `additional_roles` field defaults to an empty list
- Permission logic first checks `accessible_modules`, which is populated with default role modules if `additional_roles` is not set
- Existing API calls without `additional_roles` continue to work

## Module Access Logic

The permission system uses this logic to determine which modules a user can access:

1. If user has a custom `accessible_modules` list, use that
2. Otherwise, use the default modules for the user's primary role
3. When `additional_roles` are assigned, `accessible_modules` is set to the union of:
   - Primary role's default modules
   - All additional roles' default modules

## Validation

- Only valid roles from `ROLE_PERMISSIONS` can be used in `additional_roles`
- Invalid roles will raise a `ValidationError` with the message: `Invalid roles: {role1}, {role2}`
- The primary role cannot be duplicated in `additional_roles`

## Database Migration

Migration `auth_user/migrations/0015_user_additional_roles.py` adds the new field to the database.

Run migrations with:
```bash
python manage.py migrate
```

## Testing

Comprehensive tests are included in `auth_user/test_additional_roles.py`:

- Test merging modules from multiple roles
- Test creating users with additional_roles
- Test updating users with additional_roles  
- Test validation of invalid roles
- Test serializer output includes additional_roles
- Test accessible_modules computation

Run tests with:
```bash
python manage.py test auth_user.test_additional_roles -v 2
```

## Example Scenarios

### Scenario 1: Counsellor with Accounting Responsibilities

Create a counsellor user who also needs access to accounting features:

```json
{
    "email": "counselor@institute.com",
    "name": "John Counselor",
    "role": "counsellor",
    "additional_roles": ["accountant"]
}
```

Result: User gets all modules from both `counsellor` and `accountant` roles:
- Counsellor modules: support, crm, students, payroll, settings, attendance, notifications, leave
- Accountant modules: support, attendance, fees, payroll, notifications, settings, leave
- Union: support, crm, students, payroll, settings, attendance, notifications, leave, fees

### Scenario 2: Faculty with Exam Supervision

Create a faculty member who can also supervise exams:

```json
{
    "email": "faculty@institute.com",
    "name": "Dr. Smith",
    "role": "faculty",
    "additional_roles": ["exam_supervisor"]
}
```

Result: User gets access to exam supervision features in addition to their faculty responsibilities.

## Future Enhancements

Potential improvements:
- UI for managing additional roles
- Role hierarchy/inheritance system
- Granular module-level permissions
- Role templates for common combinations
- Audit logging of role changes
