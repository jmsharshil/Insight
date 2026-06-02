"""
reports/views.py — Thin API views delegating to services.
"""
import logging
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from . import services
from .exporters import export_csv, export_pdf

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

class DashboardView(APIView):
    """GET /api/v1/reports/dashboard/"""

    @method_decorator(cache_page(60 * 5))  # 5-minute cache
    def get(self, request):
        data = services.get_dashboard_data(request.user)
        return Response({'success': True, 'data': data})


# ═══════════════════════════════════════════════════════════════════════════════
#  Student Report
# ═══════════════════════════════════════════════════════════════════════════════

class StudentReportView(APIView):
    """GET /api/v1/reports/students/"""

    def get(self, request):
        data = services.get_student_report(request.user, request.GET.dict())
        return Response({'success': True, 'data': data})


# ═══════════════════════════════════════════════════════════════════════════════
#  Attendance Report
# ═══════════════════════════════════════════════════════════════════════════════

class AttendanceReportView(APIView):
    """GET /api/v1/reports/attendance/"""

    def get(self, request):
        data = services.get_attendance_report(request.user, request.GET.dict())
        return Response({'success': True, 'data': data})


# ═══════════════════════════════════════════════════════════════════════════════
#  Fee Collection Report
# ═══════════════════════════════════════════════════════════════════════════════

class FeeReportView(APIView):
    """GET /api/v1/reports/fees/"""

    def get(self, request):
        data = services.get_fee_report(request.user, request.GET.dict())
        return Response({'success': True, 'data': data})


# ═══════════════════════════════════════════════════════════════════════════════
#  Timetable Utilisation Report
# ═══════════════════════════════════════════════════════════════════════════════

class TimetableReportView(APIView):
    """GET /api/v1/reports/timetable/"""

    def get(self, request):
        data = services.get_timetable_report(request.user, request.GET.dict())
        return Response({'success': True, 'data': data})


# ═══════════════════════════════════════════════════════════════════════════════
#  Exam / Student Performance Report
# ═══════════════════════════════════════════════════════════════════════════════

class ExamReportView(APIView):
    """GET /api/v1/reports/exams/"""

    def get(self, request):
        data = services.get_exam_report(request.user, request.GET.dict())
        return Response({'success': True, 'data': data})


# ═══════════════════════════════════════════════════════════════════════════════
#  Faculty Payroll Report
# ═══════════════════════════════════════════════════════════════════════════════

class PayrollReportView(APIView):
    """GET /api/v1/reports/payroll/"""

    def get(self, request):
        data = services.get_payroll_report(request.user, request.GET.dict())
        return Response({'success': True, 'data': data})


# ═══════════════════════════════════════════════════════════════════════════════
#  CRM Conversion Report
# ═══════════════════════════════════════════════════════════════════════════════

class LeadReportView(APIView):
    """GET /api/v1/reports/leads/"""

    def get(self, request):
        data = services.get_lead_report(request.user, request.GET.dict())
        return Response({'success': True, 'data': data})


# ═══════════════════════════════════════════════════════════════════════════════
#  Leave Report
# ═══════════════════════════════════════════════════════════════════════════════

class LeaveReportView(APIView):
    """GET /api/v1/reports/leaves/"""

    def get(self, request):
        data = services.get_leave_report(request.user, request.GET.dict())
        return Response({'success': True, 'data': data})


# ═══════════════════════════════════════════════════════════════════════════════
#  Export API
# ═══════════════════════════════════════════════════════════════════════════════

EXPORT_CONFIGS = {
    'students': {
        'service': 'get_student_report',
        'title': 'Student Report',
        'headers': ['Course', 'Count'],
        'row_key': 'by_course',
        'row_fields': ['course', 'count'],
    },
    'attendance': {
        'service': 'get_attendance_report',
        'title': 'Attendance Report',
        'headers': ['Student ID', 'Name', 'Admission No', 'Total Days', 'Present Days', 'Attendance %'],
        'row_key': 'students',
        'row_fields': ['student_id', 'student_name', 'admission_number', 'total_days', 'present_days', 'attendance_pct'],
    },
    'fees': {
        'service': 'get_fee_report',
        'title': 'Fee Collection Report',
        'headers': ['Student ID', 'Name', 'Total Amount', 'Amount Paid', 'Amount Due', 'Status'],
        'row_key': 'student_wise_breakdown',
        'row_fields': ['student_id', 'student_name', 'total_amount', 'amount_paid', 'amount_due', 'status'],
    },
    'timetable': {
        'service': 'get_timetable_report',
        'title': 'Timetable Utilisation Report',
        'headers': ['Faculty ID', 'Faculty Name', 'Total Slots', 'Total Hours'],
        'row_key': 'faculty_load',
        'row_fields': ['faculty_id', 'faculty_name', 'total_slots', 'total_hours'],
    },
    'exams': {
        'service': 'get_exam_report',
        'title': 'Exam Performance Report',
        'headers': ['Student ID', 'Name', 'Total Exams', 'Avg Score', 'Pass', 'Fail'],
        'row_key': 'student_performance',
        'row_fields': ['student_id', 'student_name', 'total_exams', 'average_score', 'pass_count', 'fail_count'],
    },
    'payroll': {
        'service': 'get_payroll_report',
        'title': 'Payroll Report',
        'headers': ['Faculty ID', 'Name', 'Employee ID', 'Basic', 'Hour-based', 'Penalty', 'Net Salary', 'Disbursed'],
        'row_key': 'payroll_summary',
        'row_fields': ['faculty_id', 'faculty_name', 'employee_id', 'basic_salary', 'hour_based_amount', 'late_penalty', 'net_salary', 'is_disbursed'],
    },
    'leads': {
        'service': 'get_lead_report',
        'title': 'CRM Lead Report',
        'headers': ['Source', 'Count'],
        'row_key': 'by_source',
        'row_fields': ['source', 'count'],
    },
    'leaves': {
        'service': 'get_leave_report',
        'title': 'Leave Report',
        'headers': ['User ID', 'Name', 'Leave Type', 'Total Days', 'Used Days', 'Remaining'],
        'row_key': 'leave_balance',
        'row_fields': ['user_id', 'user_name', 'leave_type', 'total_days', 'used_days', 'remaining'],
    },
}


class ExportView(APIView):
    """GET /api/v1/reports/export/<report_type>/?format=csv|pdf"""

    def get(self, request, report_type):
        config = EXPORT_CONFIGS.get(report_type)
        if not config:
            return Response(
                {'success': False, 'message': f'Unknown report type: {report_type}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service_fn = getattr(services, config['service'])
        data = service_fn(request.user, request.GET.dict())

        rows_data = data.get(config['row_key'], [])
        rows = [
            [row.get(f, '') for f in config['row_fields']]
            for row in rows_data
        ]

        fmt = request.GET.get('format', 'csv').lower()
        filename = f"{report_type}_report"

        if fmt == 'pdf':
            return export_pdf(
                config['title'], config['headers'], rows,
                filename=f'{filename}.pdf',
                landscape=len(config['headers']) > 5,
            )
        else:
            return export_csv(config['headers'], rows, filename=f'{filename}.csv')
