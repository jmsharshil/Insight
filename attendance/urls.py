from django.urls import path
from .views import (
    AttendanceListCreateView, QRScanView, AttendanceCorrectionView,
    StudentAttendanceView, BatchAttendanceSheetView,
    AttendanceReportView, AttendanceAlertView,
    ViolationListCreateView, ViolationResolveView,
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

    # H. Violations — GET list, POST manual create (FRD §4.4.3), PATCH resolve
    path('attendance/violations/', ViolationListCreateView.as_view(), name='violation-list-create'),
    path('attendance/violations/<uuid:violation_id>/', ViolationResolveView.as_view(), name='violation-resolve'),
]
