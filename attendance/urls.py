from django.urls import path
from .views import (
    AttendanceListCreateView, QRScanView, AttendanceCorrectionView,
    StudentAttendanceView, BatchAttendanceSheetView,
    AttendanceReportView, AttendanceAlertView,
    EmployeeAttendanceListCreateView, EmployeeCheckInOutView, EmployeeAttendanceHistoryView,
    EmployeeDropdownView,
)
from .analytics_views import (
    DashboardSummaryAPIView, StudentAttendanceListAPIView, StudentAttendanceDetailAPIView,
    AttendanceHistoryAPIView, BatchAttendanceRegisterAPIView, FacultyAttendanceAPIView,
    FacultyAttendanceDetailAPIView, AttendanceAnalyticsAPIView, DefaulterStudentsAPIView,
    ViolationsAPIView, ViolationDetailAPIView, AttendanceExportAPIView, AttendanceAuditAPIView,
    BatchWiseAttendanceAPIView, EmployeeAttendanceDetailAPIView,
    EmployeeViolationsAPIView,
)

urlpatterns = [
    # A. List & batch-create attendance
    path('attendance/', AttendanceListCreateView.as_view(), name='attendance-list-create'),

    # B. QR scan check-in / check-out / exam entry (FRD §4.4.1)
    path('attendance/qr-scan/', QRScanView.as_view(), name='attendance-qr-scan'),

    # C. Attendance correction (ASE / BM only)
    path('attendance/<uuid:record_id>/', AttendanceCorrectionView.as_view(), name='attendance-correction'),

    # D. Student attendance history + summary + violations (FRD §4.4.3)
    path('attendance/student/<uuid:student_id>/', StudentAttendanceView.as_view(), name='attendance-student'),

    # E. Batch attendance sheet (register format)
    path('attendance/batch/<uuid:batch_id>/', BatchAttendanceSheetView.as_view(), name='attendance-batch-sheet'),

    # F. Attendance percentage report (includes violations_breakdown)
    path('attendance/report/', AttendanceReportView.as_view(), name='attendance-report'),

    # G. Trigger low-attendance alerts
    path('attendance/alert/', AttendanceAlertView.as_view(), name='attendance-alert'),

    # H. New Role-Based Reporting and Analytics APIs
    path('attendance/dashboard/', DashboardSummaryAPIView.as_view(), name='attendance-dashboard'),
    path('attendance/students/', StudentAttendanceListAPIView.as_view(), name='attendance-students-list'),
    path('attendance/students/<uuid:student_id>/', StudentAttendanceDetailAPIView.as_view(), name='attendance-students-detail'),
    path('attendance/history/', AttendanceHistoryAPIView.as_view(), name='attendance-history'),
    path('attendance/batches/register/', BatchAttendanceRegisterAPIView.as_view(), name='attendance-all-register'),
    path('attendance/batches/<uuid:batch_id>/register/', BatchAttendanceRegisterAPIView.as_view(), name='attendance-batch-register'),
    path('attendance/faculty/', FacultyAttendanceAPIView.as_view(), name='attendance-faculty-list'),
    path('attendance/faculty/<uuid:faculty_id>/', FacultyAttendanceDetailAPIView.as_view(), name='attendance-faculty-detail'),
    path('attendance/batch-wise/', BatchWiseAttendanceAPIView.as_view(), name='attendance-batch-wise'),
    path('attendance/analytics/', AttendanceAnalyticsAPIView.as_view(), name='attendance-analytics'),
    path('attendance/defaulters/', DefaulterStudentsAPIView.as_view(), name='attendance-defaulters'),
    path('attendance/violations/', ViolationsAPIView.as_view(), name='attendance-violations'),
    path('attendance/violations/<uuid:violation_id>/', ViolationDetailAPIView.as_view(), name='attendance-violations-detail'),
    path('attendance/export/', AttendanceExportAPIView.as_view(), name='attendance-export'),
    path('attendance/audit-logs/', AttendanceAuditAPIView.as_view(), name='attendance-audit-logs'),

    # I. Employee (Staff) Attendance — for ALL non-student users
    path('attendance/employee/', EmployeeAttendanceListCreateView.as_view(), name='employee-attendance-list-create'),
    path('attendance/employee/scan/', EmployeeCheckInOutView.as_view(), name='employee-attendance-scan'),
    path('attendance/employee/history/', EmployeeAttendanceHistoryView.as_view(), name='employee-attendance-history'),
    path('attendance/employee/violations/', EmployeeViolationsAPIView.as_view(), name='employee-violations'),
    path('attendance/employee/<uuid:user_id>/', EmployeeAttendanceDetailAPIView.as_view(), name='employee-attendance-detail'),
    # Dropdown for assigning employees (paper checkers, faculty, staff)
    path('attendance/employees/dropdown/', EmployeeDropdownView.as_view(), name='employee-dropdown'),
]

