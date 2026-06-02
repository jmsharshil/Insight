"""
reports/serializers.py — Read-only response serializers for analytics endpoints.

All serializers are plain Serializer classes (no ModelSerializer) because
this module does not own any database table.  They exist only to document
and validate the shape of the JSON that each view returns.
"""

from rest_framework import serializers


# ═══════════════════════════════════════════════════════════════════════════════
#  Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

class BranchAttendanceSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    branch_name = serializers.CharField()
    attendance_rate = serializers.FloatField()

class BatchAttendanceSerializer(serializers.Serializer):
    batch_id = serializers.UUIDField()
    batch_name = serializers.CharField()
    attendance_rate = serializers.FloatField()

class CRMPipelineSerializer(serializers.Serializer):
    stage = serializers.CharField()
    count = serializers.IntegerField()

class UpcomingExamSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    scheduled_date = serializers.DateField()
    batch_name = serializers.CharField(allow_null=True)
    subject_name = serializers.CharField(allow_null=True)

class DashboardSerializer(serializers.Serializer):
    total_active_students = serializers.IntegerField()
    new_admissions_this_month = serializers.IntegerField()
    dropout_rate = serializers.FloatField()
    attendance_rate = serializers.FloatField()
    attendance_by_branch = BranchAttendanceSerializer(many=True)
    attendance_by_batch = BatchAttendanceSerializer(many=True)
    fee_collected = serializers.DecimalField(max_digits=14, decimal_places=2)
    fee_due = serializers.DecimalField(max_digits=14, decimal_places=2)
    overdue_fees = serializers.DecimalField(max_digits=14, decimal_places=2)
    upcoming_exams = UpcomingExamSerializer(many=True)
    pending_results = serializers.IntegerField()
    open_crm_leads = serializers.IntegerField()
    crm_pipeline = CRMPipelineSerializer(many=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Student Report
# ═══════════════════════════════════════════════════════════════════════════════

class CourseBreakdownSerializer(serializers.Serializer):
    course = serializers.CharField()
    count = serializers.IntegerField()

class BatchBreakdownSerializer(serializers.Serializer):
    batch_id = serializers.UUIDField(allow_null=True)
    batch_name = serializers.CharField()
    count = serializers.IntegerField()

class EnrollmentTrendSerializer(serializers.Serializer):
    month = serializers.CharField()
    count = serializers.IntegerField()

class StudentReportSerializer(serializers.Serializer):
    total_students = serializers.IntegerField()
    active_students = serializers.IntegerField()
    inactive_students = serializers.IntegerField()
    new_admissions = serializers.IntegerField()
    by_course = CourseBreakdownSerializer(many=True)
    by_batch = BatchBreakdownSerializer(many=True)
    enrollment_trend = EnrollmentTrendSerializer(many=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Attendance Report
# ═══════════════════════════════════════════════════════════════════════════════

class DailyTrendSerializer(serializers.Serializer):
    date = serializers.DateField()
    present = serializers.IntegerField()
    absent = serializers.IntegerField()
    total = serializers.IntegerField()
    rate = serializers.FloatField()

class WeeklyTrendSerializer(serializers.Serializer):
    week = serializers.IntegerField()
    rate = serializers.FloatField()

class MonthlyTrendSerializer(serializers.Serializer):
    month = serializers.CharField()
    rate = serializers.FloatField()

class StudentAttendanceRowSerializer(serializers.Serializer):
    student_id = serializers.UUIDField()
    student_name = serializers.CharField()
    admission_number = serializers.CharField()
    total_days = serializers.IntegerField()
    present_days = serializers.IntegerField()
    attendance_pct = serializers.FloatField()

class ViolationSummarySerializer(serializers.Serializer):
    type = serializers.CharField()
    count = serializers.IntegerField()

class AttendanceReportSerializer(serializers.Serializer):
    attendance_percentage = serializers.FloatField()
    students_below_75 = serializers.IntegerField()
    daily_trend = DailyTrendSerializer(many=True)
    weekly_trend = WeeklyTrendSerializer(many=True)
    monthly_trend = MonthlyTrendSerializer(many=True)
    absentee_list = StudentAttendanceRowSerializer(many=True)
    violation_summary = ViolationSummarySerializer(many=True)
    students = StudentAttendanceRowSerializer(many=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Fee Collection Report
# ═══════════════════════════════════════════════════════════════════════════════

class PaymentModeBreakdownSerializer(serializers.Serializer):
    mode = serializers.CharField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    count = serializers.IntegerField()

class StudentFeeRowSerializer(serializers.Serializer):
    student_id = serializers.UUIDField()
    student_name = serializers.CharField()
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = serializers.DecimalField(max_digits=12, decimal_places=2)
    amount_due = serializers.DecimalField(max_digits=12, decimal_places=2)
    status = serializers.CharField()

class FeeMonthlyTrendSerializer(serializers.Serializer):
    month = serializers.CharField()
    collected = serializers.DecimalField(max_digits=14, decimal_places=2)

class FeeReportSerializer(serializers.Serializer):
    total_collected = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_due = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_pending = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_overdue = serializers.DecimalField(max_digits=14, decimal_places=2)
    payment_mode_breakdown = PaymentModeBreakdownSerializer(many=True)
    student_wise_breakdown = StudentFeeRowSerializer(many=True)
    monthly_trend = FeeMonthlyTrendSerializer(many=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Timetable Utilisation
# ═══════════════════════════════════════════════════════════════════════════════

class FacultyLoadSerializer(serializers.Serializer):
    faculty_id = serializers.UUIDField()
    faculty_name = serializers.CharField()
    total_slots = serializers.IntegerField()
    total_hours = serializers.FloatField()

class FreeSlotSerializer(serializers.Serializer):
    classroom_id = serializers.UUIDField()
    classroom_name = serializers.CharField()
    day_of_week = serializers.IntegerField()
    day_label = serializers.CharField()
    free_slots = serializers.IntegerField()

class TimetableReportSerializer(serializers.Serializer):
    classroom_occupancy_rate = serializers.FloatField()
    faculty_load = FacultyLoadSerializer(many=True)
    free_slot_analysis = FreeSlotSerializer(many=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Student Performance / Exams
# ═══════════════════════════════════════════════════════════════════════════════

class TopScorerSerializer(serializers.Serializer):
    student_id = serializers.UUIDField(allow_null=True)
    student_name = serializers.CharField(allow_blank=True)
    marks = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    percentage = serializers.FloatField(allow_null=True)

class SubjectPerformanceSerializer(serializers.Serializer):
    subject_id = serializers.UUIDField(allow_null=True)
    subject_name = serializers.CharField()
    average_score = serializers.FloatField()
    pass_rate = serializers.FloatField()

class StudentPerformanceRowSerializer(serializers.Serializer):
    student_id = serializers.UUIDField()
    student_name = serializers.CharField()
    total_exams = serializers.IntegerField()
    average_score = serializers.FloatField()
    pass_count = serializers.IntegerField()
    fail_count = serializers.IntegerField()

class ExamReportSerializer(serializers.Serializer):
    total_exams = serializers.IntegerField()
    pass_count = serializers.IntegerField()
    fail_count = serializers.IntegerField()
    average_score = serializers.FloatField()
    top_scorer = TopScorerSerializer()
    subject_performance = SubjectPerformanceSerializer(many=True)
    student_performance = StudentPerformanceRowSerializer(many=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Payroll Report
# ═══════════════════════════════════════════════════════════════════════════════

class PayrollSummaryRowSerializer(serializers.Serializer):
    faculty_id = serializers.UUIDField()
    faculty_name = serializers.CharField()
    employee_id = serializers.CharField()
    basic_salary = serializers.DecimalField(max_digits=10, decimal_places=2)
    hour_based_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    late_penalty = serializers.DecimalField(max_digits=8, decimal_places=2)
    absence_deductions = serializers.DecimalField(max_digits=8, decimal_places=2)
    leave_deductions = serializers.DecimalField(max_digits=8, decimal_places=2)
    bonus = serializers.DecimalField(max_digits=8, decimal_places=2)
    net_salary = serializers.DecimalField(max_digits=10, decimal_places=2)
    is_disbursed = serializers.BooleanField()

class PenaltyRowSerializer(serializers.Serializer):
    faculty_name = serializers.CharField()
    late_minutes = serializers.IntegerField()
    penalty_amount = serializers.DecimalField(max_digits=8, decimal_places=2)
    session_date = serializers.DateField()

class DisbursementStatusSerializer(serializers.Serializer):
    status = serializers.CharField()
    count = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2)

class HoursTaughtSerializer(serializers.Serializer):
    faculty_id = serializers.UUIDField()
    faculty_name = serializers.CharField()
    total_hours = serializers.FloatField()
    sessions_conducted = serializers.IntegerField()

class PayrollReportSerializer(serializers.Serializer):
    total_disbursed = serializers.DecimalField(max_digits=14, decimal_places=2)
    faculty_count = serializers.IntegerField()
    average_salary = serializers.DecimalField(max_digits=12, decimal_places=2)
    hours_taught = HoursTaughtSerializer(many=True)
    payroll_summary = PayrollSummaryRowSerializer(many=True)
    penalties = PenaltyRowSerializer(many=True)
    disbursement_status = DisbursementStatusSerializer(many=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  CRM / Lead Report
# ═══════════════════════════════════════════════════════════════════════════════

class LeadSourceSerializer(serializers.Serializer):
    source = serializers.CharField()
    count = serializers.IntegerField()

class CounsellorPerformanceSerializer(serializers.Serializer):
    counsellor_id = serializers.UUIDField(allow_null=True)
    counsellor_name = serializers.CharField()
    total_leads = serializers.IntegerField()
    converted = serializers.IntegerField()
    conversion_rate = serializers.FloatField()

class LeadDailyTrendSerializer(serializers.Serializer):
    date = serializers.DateField()
    count = serializers.IntegerField()

class LeadReportSerializer(serializers.Serializer):
    total_leads = serializers.IntegerField()
    new = serializers.IntegerField()
    contacted = serializers.IntegerField()
    interested = serializers.IntegerField()
    converted = serializers.IntegerField()
    lost = serializers.IntegerField()
    conversion_rate = serializers.FloatField()
    avg_conversion_days = serializers.FloatField()
    by_source = LeadSourceSerializer(many=True)
    by_counsellor = CounsellorPerformanceSerializer(many=True)
    daily_trend = LeadDailyTrendSerializer(many=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Leave Report
# ═══════════════════════════════════════════════════════════════════════════════

class LeaveBalanceRowSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    user_name = serializers.CharField()
    leave_type = serializers.CharField()
    total_days = serializers.DecimalField(max_digits=5, decimal_places=1)
    used_days = serializers.DecimalField(max_digits=5, decimal_places=1)
    remaining = serializers.DecimalField(max_digits=5, decimal_places=1)

class LeaveTakenByTypeSerializer(serializers.Serializer):
    leave_type = serializers.CharField()
    total_days = serializers.DecimalField(max_digits=8, decimal_places=1)
    count = serializers.IntegerField()

class LeaveReportSerializer(serializers.Serializer):
    leave_balance = LeaveBalanceRowSerializer(many=True)
    leave_taken_by_type = LeaveTakenByTypeSerializer(many=True)
    pending_approvals = serializers.IntegerField()
