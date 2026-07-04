# Dashboard API Documentation

## Overview
The Dashboard at `/api/v1/dashboard/` provides **role-scoped, low-latency KPIs, trends, charts, and widgets** tailored to each user role in the Insight LMS/ERP system. 

It eliminates all static/demo data, using **optimized Django ORM aggregates**, `select_related`/`prefetch_related`, `values()`, `annotate()`, `Q-object` based scoping, and per-user Redis caching (300s TTL).

**Key Features:**
- **Role Dispatch**: `get_role_dashboard()` routes to `_get_management_dashboard`, `_get_faculty_dashboard`, `_get_student_dashboard`, `_get_sales_dashboard`, or `_get_default_dashboard`.
- **Caching**: Key format `dashboard:{role}:{id}:{branch}:{org}` with 5-min TTL. Supports `?refresh=true` to bypass. Uses `@vary_on_headers('Authorization')` and `clear_dashboard_cache()`.
- **Scoping**: `_branch_filter(user)` uses Q-objects for `organization`/`branch` filtering. `super_admin` bypasses restrictions.
- **Performance**: Single `aggregate()` calls per KPI group, limited slicing `[:5]/[:8]/[:10]`, iterator() for large sets, no N+1 queries.
- **Common Data**: Shared `NotificationHistory` (unread count + recent 5 notifications) across all roles.
- **Response Format**: `{success: true, role: string, data: {...}, timestamp: iso}`

**Rate Limiting**: `DashboardRateThrottle(60/min)`.

**Endpoint**: `GET /api/v1/dashboard/?refresh=true`

## Role-Specific Dashboards

### 1. Management Dashboard (`super_admin`, `branch_manager`, `admin_*`, `accountant`)
- **KPIs**: total_active_students, new_admissions, attendance_rate, fee_collected, pending_fees, overdue_fees, open_leads.
- **Data**: upcoming_exams (Exam), lead_pipeline (by current_stage), attendance_trend (7 days), fee_collection_trend (30 days via Payments), recent_activities.
- **Charts**: attendance_by_batch, enrollment_by_course.
- **Queries**: Student.aggregate(), AttendanceRecord (with status filter), StudentFee (using F-expressions for due = total - discount - paid), Lead.values('current_stage').annotate(Count), Exam.filter(scheduled_date__gte).
- **Scoping**: Full org/branch filter via `_branch_filter`.

### 2. Faculty Dashboard (`faculty`, `exam_supervisor`, `paper_checker`)
- **KPIs**: today_sessions, monthly_sessions, attendance_rate (from FacultyQRScanLog), pending_tasks, avg_session_completion.
- **Data**: today_schedule (SessionReport), pending_tasks (MarkSheet where paper_checker=user & ~is_submitted), recent_sessions, payroll_summary (from latest PaySlip).
- **Special**: Uses FacultyProfile for faculty-specific, falls back gracefully. QR scans for att_rate, SessionReport for completion %.
- **Charts**: my_attendance_trend.
- **Model Updates**: FacultyProfile.qr_scans, SessionReport, MarkSheet.paper_checker (replaces checked_by).

### 3. Student/Parent Dashboard (`student`, `parents`)
- **KPIs**: attendance_rate, fees_due, upcoming_exams_count, avg_score.
- **Data**: upcoming_exams (for student's batch), recent_results (PublishedResult with percentage, rank), timetable (TimetableSlot), fee_details, performance trend.
- **Personalization**: For parents uses ParentLink to linked student; uses Student.linked_student proxy.
- **Queries**: AttendanceRecord per student, StudentFee with F-expr, PublishedResult.aggregate(Avg('percentage')), TimetableSlot.filter(batch).
- **Model Updates**: StudentProfile, BatchHistory, DigitalIDCard, StudentStatusHistory, AttendanceRecord.status/percentage, StudentFee(discount,amount_due), Payment.receipt_number, exam proctoring/recheck.

### 4. Sales Dashboard (`sales_*`, `counsellor`, `tele_caller`, `front_desk`)
- **KPIs**: total_leads, new_leads_this_month, conversion_rate, active_leads.
- **Data**: pipeline (by current_stage), recent_leads, conversion_trend, top_sources (by reference).
- **Queries**: Lead.aggregate with current_stage filter + LeadStage/LeadAssignmentLog support.
- **Model Updates**: Lead.current_stage, LeadStage, LeadAssignmentLog.

### 5. Default/Fallback
- Generic message for other roles.

## Technical Implementation Details

### services.py (~460 LOC)
- `_get_cache_key(user)`
- `_branch_filter(user, model=None)`: Handles super_admin bypass, org/branch Q() objects. Supports model-specific FK checks.
- Role-specific functions with heavy use of:
  - `Count('id', filter=Q(...))`
  - `Sum(F('total_amount') - F('discount') - F('amount_paid'))`
  - `Avg('percentage')`, `Case/When`
  - `.iterator()` for payments
  - `select_related('batch', 'subject', 'student', 'exam')`
  - `values()` + list() for JSON serialization
- Helpers:
  - `_get_attendance_trend(bq, days)`: Daily rates over N days.
  - `_get_fee_trend(user, days)`: Weekly collections from verified Payments.
  - `_get_attendance_by_batch(bq)`, `_get_enrollment_by_course(bq)`
  - `_get_student_timetable(student)`, `_get_student_performance_trend(student)`
  - `_get_recent_activities(user)`, `_get_simple_trend()`

**No static data**: All placeholders removed per requirements. References real models from `leads`, `students`, `faculty`, `attendance`, `fees`, `exams`, `results`, `batches`, `payroll`, `auth_user`.

### views.py
- `DashboardAPIView` with `@cache_page(300)`, `@vary_on_headers('Authorization')`, `?refresh=true` handling via `clear_dashboard_cache()`.
- Uses `DashboardRateThrottle`.
- Full OpenAPI schema with drf-spectacular.

### Supporting Model Changes (from requirements)
- `leads/models.py`: STAGE_CHOICES, LeadStage, LeadAssignmentLog, `current_stage`.
- `students/models.py`: Student + proxies (linked_student), ParentLink, BatchHistory, DigitalIDCard, StudentStatusHistory.
- `faculty/models.py`: FacultyProfile (qr_scans), SessionReport, FacultyQRScanLog, SubjectHourlyRate, MarkSheet updates.
- `attendance/models.py`: AttendanceRecord (status, percentage), QRScanLog, AlertLog, ViolationRecord, EmployeeAttendanceRecord.
- `fees/models.py`: StudentFee (discount, amount_due), Payment (receipt_number), InstallmentPlan, Refund, etc.
- `exams/models.py`: Exam (proctoring/recheck), Question, Session, etc.
- `results/models.py`: MarkSheet.paper_checker/is_submitted, RecheckRequest, PublishedResult.
- `batches/models.py`: TimetableSlot, Batch, Course/Subject/Chapter.
- `payroll/models.py`: PayrollRun, PaySlip, LateEntryPolicy, etc.
- `auth_user/models.py`: User (linked_student, employee_id, per_paper_rate, NotificationHistory).
- `branch/models.py`: Enhanced scoping.

See `reports/services/dashboard.py` for similar aggregate patterns.

## Caching & Performance
- TTL: 300 seconds.
- Invalidation: `clear_dashboard_cache(user)` on refresh or updates (e.g. after lead conversion, fee payment, session report).
- Cache key includes role, user.id, branch, org for perfect isolation.
- All queries scoped to prevent data leaks across branches/orgs.

## Error Handling & Edge Cases
- No FacultyProfile → graceful empty lists/rates=100.
- Division by zero in rates → default to 0 or 100.
- No student linked for parents → friendly message.
- Super admin sees global data.
- Unknown roles → default dashboard.
- DB empty → zeroed KPIs, empty lists.
- Throttling at 60 req/min.

## Testing
See `dashboard/tests.py` for unit tests covering:
- All major roles
- Unauthenticated access (401)
- Refresh bypass
- Cache isolation
- Response structure validation
- Throttling simulation
- Default/fallback role
- Mocked service layer for isolation

**Related Files**:
- `dashboard/urls.py`, `insight/urls.py`
- `dashboard/views.py`
- `dashboard/services.py`
- Model files listed above
- `tests/test_dashboard.py` (if separate)

**Version**: 2.0 (Fully ORM-driven, no demo data)

Last Updated: Based on final implementation eliminating static data.
