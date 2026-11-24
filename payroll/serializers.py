from decimal import Decimal
from django.db import models
from rest_framework import serializers
from .models import LateEntryPolicy, PayrollRun, PaySlip, SessionLatePenaltyLog
from branch.models import Branch


class LateEntryPolicySerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = LateEntryPolicy
        fields = [
            'id', 'branch', 'branch_name', 'grace_period_minutes', 'deduction_per_minute',
            'max_deduction_per_session', 'absence_deduction_per_day',
            'late_entry_threshold', 'auto_halfday_deduction',
            'is_active', 'updated_at',
        ]
        read_only_fields = ['id', 'updated_at']


class LateEntryPolicyInputSerializer(serializers.Serializer):
    grace_period_minutes = serializers.IntegerField(default=5)
    deduction_per_minute = serializers.DecimalField(max_digits=6, decimal_places=2, default=0)
    max_deduction_per_session = serializers.DecimalField(max_digits=8, decimal_places=2, default=0)
    absence_deduction_per_day = serializers.DecimalField(max_digits=8, decimal_places=2, default=0)
    late_entry_threshold = serializers.IntegerField(default=3)
    auto_halfday_deduction = serializers.BooleanField(default=True)


class SessionLatePenaltyLogSerializer(serializers.ModelSerializer):
    scheduled_end = serializers.SerializerMethodField()
    actual_end = serializers.SerializerMethodField()
    early_out_minutes = serializers.SerializerMethodField()
    penalty_minutes = serializers.SerializerMethodField()

    class Meta:
        model = SessionLatePenaltyLog
        fields = [
            'id', 'session_report', 'scheduled_time', 'scheduled_end',
            'actual_start', 'actual_end',
            'late_minutes', 'early_out_minutes', 'penalty_minutes',
            'penalty_amount', 'grace_applied'
        ]

    def get_scheduled_end(self, obj):
        sr = getattr(obj, 'session_report', None)
        if sr:
            from batches.models import TimetableSlot
            from datetime import datetime
            dow = sr.session_date.weekday()
            slot = TimetableSlot.objects.filter(
                models.Q(day_of_week=dow) | models.Q(session_date=sr.session_date),
                batch_id=sr.batch_id, subject_id=sr.subject_id
            ).first()
            if not slot and getattr(sr, 'faculty', None):
                ref_time = obj.scheduled_time or sr.start_time
                fac_slots = TimetableSlot.objects.filter(
                    models.Q(day_of_week=dow) | models.Q(session_date=sr.session_date),
                    faculty=sr.faculty,
                )
                if ref_time:
                    s_dt = datetime.combine(sr.session_date, ref_time)
                    best_slot = None
                    best_diff = 999999
                    for cand_slot in fac_slots:
                        if cand_slot.start_time:
                            c_dt = datetime.combine(sr.session_date, cand_slot.start_time)
                            diff_sec = abs((c_dt - s_dt).total_seconds())
                            if diff_sec < best_diff and diff_sec <= 60 * 60:
                                best_diff = diff_sec
                                best_slot = cand_slot
                    slot = best_slot
                else:
                    slot = fac_slots.first()
            if slot and slot.end_time:
                return slot.end_time.strftime('%H:%M:%S')
            if sr.end_time:
                return sr.end_time.strftime('%H:%M:%S')
        return None

    def get_actual_end(self, obj):
        sr = getattr(obj, 'session_report', None)
        if sr:
            from attendance.models import EmployeeAttendanceRecord
            from django.utils import timezone as dj_timezone
            from datetime import datetime
            ref_time = obj.actual_start or sr.start_time
            if ref_time:
                s_dt = datetime.combine(sr.session_date, ref_time)
                candidate_atts = EmployeeAttendanceRecord.objects.filter(
                    user=sr.faculty.user,
                    date=sr.session_date,
                    checked_in_at__isnull=False,
                )
                best_att = None
                best_diff = 999999
                for cand in candidate_atts:
                    cand_in = dj_timezone.localtime(cand.checked_in_at).replace(tzinfo=None)
                    diff_sec = abs((cand_in - s_dt).total_seconds())
                    if diff_sec < best_diff and diff_sec <= 60 * 60:
                        best_diff = diff_sec
                        best_att = cand
                if best_att and best_att.checked_out_at:
                    return dj_timezone.localtime(best_att.checked_out_at).time().strftime('%H:%M:%S')
            if sr.end_time:
                return sr.end_time.strftime('%H:%M:%S')
        return None

    def get_early_out_minutes(self, obj):
        sched_end = self.get_scheduled_end(obj)
        act_end = self.get_actual_end(obj)
        if sched_end and act_end:
            from datetime import datetime
            try:
                t_sched = datetime.strptime(sched_end, '%H:%M:%S')
                t_act = datetime.strptime(act_end, '%H:%M:%S')
                diff = (t_sched - t_act).total_seconds() / 60
                return max(0, int(diff))
            except Exception:
                pass
        return 0

    def get_penalty_minutes(self, obj):
        late_min = getattr(obj, 'late_minutes', 0) or 0
        early_min = self.get_early_out_minutes(obj)
        total_dev = late_min + early_min
        return max(0, total_dev - 5) if total_dev > 5 else 0


class PaySlipSerializer(serializers.ModelSerializer):
    faculty_name = serializers.SerializerMethodField()
    employee_id = serializers.SerializerMethodField()
    user_id = serializers.SerializerMethodField()
    late_logs = SessionLatePenaltyLogSerializer(many=True, read_only=True)
    extra_shift_allowance = serializers.DecimalField(source='bonus', max_digits=12, decimal_places=2, read_only=True)
    odometer_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    reimbursement_notes = serializers.SerializerMethodField()
    odometer_notes = serializers.SerializerMethodField()
    leave_notes = serializers.SerializerMethodField()
    total_hours = serializers.SerializerMethodField()
    gross_salary = serializers.SerializerMethodField()
    late_deduction_log = serializers.SerializerMethodField()
    absence_deduction_log = serializers.SerializerMethodField()

    def get_total_hours(self, obj):
        return str(round(getattr(obj, 'total_session_hours', 0) or 0, 2))

    def get_gross_salary(self, obj):
        return str(round((getattr(obj, 'basic_salary', 0) or 0) + (getattr(obj, 'hour_based_amount', 0) or 0), 2))

    class Meta:
        model = PaySlip
        fields = [
            'id', 'faculty', 'user_id', 'faculty_name', 'employee_id',
            'basic_salary', 'gross_salary', 'total_hours', 'total_session_hours', 'hour_based_amount',
            'late_penalty', 'late_penalty_minutes', 'per_day_deduction_log',
            'late_deduction_log', 'absence_deduction_log',
            'absence_deductions', 'leave_deductions',
            'retention_deduction', 'retention_refund_amount', 'other_deductions', 'deduction_note',
            'attendance_bonus', 'leave_encashment', 'bonus', 'extra_shift_allowance',
            'reimbursements_amount', 'reimbursement_notes',
            'odometer_amount', 'odometer_notes',
            'leave_notes',
            'net_salary', 'leaves_taken', 'working_days',
            'sessions_conducted', 'is_disbursed', 'is_manually_adjusted', 'late_logs',
            'hourly_rate', 'per_paper_rate', 'employment_type', 'session_hours', 'salary', 'visiting_count'
        ]

    hourly_rate = serializers.SerializerMethodField()
    per_paper_rate = serializers.SerializerMethodField()
    employment_type = serializers.SerializerMethodField()
    session_hours = serializers.SerializerMethodField()
    salary = serializers.SerializerMethodField()
    visiting_count = serializers.SerializerMethodField()

    def get_visiting_count(self, obj):
        if self.get_employment_type(obj) != 'full_time':
            return obj.working_days
        return 0

    def get_reimbursement_notes(self, obj):
        notes = []
        if hasattr(obj, 'reimbursements'):
            for reimbursement in obj.reimbursements.all():
                if getattr(reimbursement, 'status', 'approved') != 'approved':
                    continue
                expense_date = reimbursement.expense_date
                if (
                    expense_date is None
                    or expense_date.year != obj.payroll_run.year
                    or expense_date.month != obj.payroll_run.month
                ):
                    continue
                notes.append({
                    'date': str(reimbursement.expense_date or ''),
                    'event': reimbursement.title or 'Reimbursement',
                    'description': reimbursement.description or '',
                    'expense': float(reimbursement.amount),
                })
        return notes

    def get_odometer_notes(self, obj):
        notes = []
        if hasattr(obj, 'odometer_readings'):
            for reading in obj.odometer_readings.all():
                activity_date = (
                    reading.activity.activity_date
                    if reading.activity and hasattr(reading.activity, 'activity_date')
                    else None
                )
                if reading.status != 'approved':
                    continue
                if (
                    activity_date is None
                    or activity_date.year != obj.payroll_run.year
                    or activity_date.month != obj.payroll_run.month
                ):
                    continue
                event_name = reading.activity.name if hasattr(reading, 'activity') and reading.activity else 'General Travel'
                notes.append({
                    'date': str(activity_date),
                    'event': event_name,
                    'vehicle_type': getattr(reading, 'vehicle_type', ''),
                    'kms': float(reading.total_kms),
                    'rate_per_km': float(reading.expense_per_km) if hasattr(reading, 'expense_per_km') else 0.0,
                    'expense': float(reading.total_expense)
                })
        return notes

    def get_leave_notes(self, obj):
        import calendar
        import datetime
        from decimal import Decimal
        from leave.models import LeaveApplication

        employee = obj.faculty.user if getattr(obj, 'faculty_id', None) and obj.faculty else obj.user
        if not employee:
            return []

        month = obj.payroll_run.month
        year = obj.payroll_run.year
        month_start = datetime.date(year, month, 1)
        month_end = month_start.replace(day=calendar.monthrange(year, month)[1])

        leaves = LeaveApplication.objects.filter(
            applied_by=employee,
            status='approved',
            from_date__lte=month_end,
            to_date__gte=month_start,
        ).order_by('from_date')

        notes = []
        for leave in leaves:
            start = max(leave.from_date, month_start)
            end = min(leave.to_date, month_end)
            days = Decimal('0.5') if leave.is_half_day else Decimal(str((end - start).days + 1))
            notes.append({
                'date_from': str(start),
                'date_to': str(end),
                'leave_type': leave.leave_type,
                'is_unpaid': leave.leave_type in ('unpaid', 'casual'),
                'is_half_day': leave.is_half_day,
                'days': float(days),
            })
        return notes


    def get_hourly_rate(self, obj):
        if obj.faculty and obj.faculty.hourly_rate > 0:
            return str(obj.faculty.hourly_rate)
        if obj.user and obj.user.hourly_rate:
            return str(obj.user.hourly_rate)
        return "0.00"

    def get_per_paper_rate(self, obj):
        if obj.user:
            return str(obj.user.per_paper_rate)
        if obj.faculty and obj.faculty.user:
            return str(obj.faculty.user.per_paper_rate)
        return "0.00"

    def get_employment_type(self, obj):
        if obj.faculty:
            return obj.faculty.employment_type
        if obj.user:
            return obj.user.employment_type
        return ""

    def get_salary(self, obj):
        if obj.faculty and obj.faculty.salary > 0:
            return str(obj.faculty.salary)
        if obj.user:
            return str(obj.user.salary)
        return "0.00"

    def get_session_hours(self, obj):
        if obj.faculty and obj.faculty.session_hours > 0:
            return str(obj.faculty.session_hours)
        if obj.user:
            return str(obj.user.session_hours)
        return "0.00"



    def get_faculty_name(self, obj):
        if obj.faculty:
            return obj.faculty.user.name
        if obj.user:
            return obj.user.name
        return ''

    def get_employee_id(self, obj):
        if obj.faculty:
            return obj.faculty.employee_id
        if obj.user:
            return obj.user.employee_id or ''
        return ''

    def get_user_id(self, obj):
        if obj.user_id:
            return str(obj.user_id)
        if obj.faculty:
            return str(obj.faculty.user_id)
        return None

    def get_late_deduction_log(self, obj):
        raw_log = getattr(obj, 'per_day_deduction_log', []) or []
        results = []
        for item in raw_log:
            late_mins = item.get('late_minutes', 0) or 0
            early_mins = item.get('early_out_minutes', 0) or 0
            penalty_mins = item.get('penalty_minutes', 0) or 0
            penalty_amt = Decimal(str(item.get('penalty_amount', '0') or 0))
            if late_mins > 0 or early_mins > 0 or penalty_mins > 0 or penalty_amt > 0:
                results.append({
                    'date': item.get('date'),
                    'total_hours': item.get('total_hours', '0.00'),
                    'gross_salary': item.get('gross_salary', '0.00'),
                    'late_minutes': late_mins,
                    'early_out_minutes': early_mins,
                    'penalty_minutes': penalty_mins,
                    'penalty_amount': str(item.get('penalty_amount', '0.00')),
                    'deduction': str(item.get('penalty_amount', '0.00')),
                    'net_salary': item.get('net_salary', '0.00'),
                    'sessions': item.get('sessions', []),
                })
        return results

    def get_absence_deduction_log(self, obj):
        raw_log = getattr(obj, 'per_day_deduction_log', []) or []
        results = []
        for item in raw_log:
            abs_ded = Decimal(str(item.get('absence_deduction', '0') or 0))
            if abs_ded > 0:
                results.append({
                    'date': item.get('date'),
                    'absence_deduction': str(abs_ded),
                    'deduction': str(abs_ded),
                    'total_hours': item.get('total_hours', '0.00'),
                    'gross_salary': item.get('gross_salary', '0.00'),
                    'net_salary': item.get('net_salary', '0.00'),
                    'sessions': item.get('sessions', []),
                })
        return results


class PayrollRunListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    faculty_count = serializers.SerializerMethodField()
    branch_name = serializers.SerializerMethodField()

    class Meta:
        model = PayrollRun
        fields = [
            'id', 'branch', 'branch_name', 'month', 'year', 'status', 'status_display',
            'total_amount', 'faculty_count', 'generated_at', 'approved_at', 'disbursed_at',
        ]

    def get_faculty_count(self, obj):
        return obj.payslips.count()

    def get_branch_name(self, obj):
        return obj.branch.name if obj.branch else ''


class PayrollRunDetailSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payslips = PaySlipSerializer(many=True, read_only=True)
    generated_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    branch_name = serializers.SerializerMethodField()

    class Meta:
        model = PayrollRun
        fields = [
            'id', 'branch', 'branch_name', 'month', 'year', 'status', 'status_display', 'total_amount',
            'generated_by', 'generated_by_name', 'approved_by', 'approved_by_name',
            'generated_at', 'approved_at', 'disbursed_at', 'notes', 'payslips',
        ]

    def get_generated_by_name(self, obj):
        return obj.generated_by.name if obj.generated_by else ''

    def get_approved_by_name(self, obj):
        return obj.approved_by.name if obj.approved_by else ''

    def get_branch_name(self, obj):
        return obj.branch.name if obj.branch else ''


class PayrollGenerateSerializer(serializers.Serializer):
    branch_id = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.all())
    month = serializers.IntegerField(min_value=1, max_value=12)
    year = serializers.IntegerField(min_value=2020)


class PaySlipAdjustSerializer(serializers.Serializer):
    """PATCH /api/v1/payroll/{id}/payslips/{slip_id}/ — adjust payslip amounts."""
    bonus = serializers.DecimalField(max_digits=8, decimal_places=2, required=False)
    extra_shift_allowance = serializers.DecimalField(max_digits=8, decimal_places=2, required=False)
    other_deductions = serializers.DecimalField(max_digits=8, decimal_places=2, required=False)
    deduction_note = serializers.CharField(max_length=300, required=False, allow_blank=True)
    leave_deductions = serializers.DecimalField(max_digits=8, decimal_places=2, required=False)

class ExtraHoursApprovalSerializer(serializers.ModelSerializer):
    faculty_name = serializers.CharField(source='faculty.user.name', read_only=True)
    chapter_name = serializers.CharField(source='chapter.name', read_only=True)
    subject_name = serializers.CharField(source='chapter.subject.name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.name', read_only=True)

    class Meta:
        from .models import ExtraHoursApproval
        model = ExtraHoursApproval
        fields = [
            'id', 'faculty', 'faculty_name', 'chapter', 'chapter_name', 'subject_name',
            'payroll_month', 'payroll_year', 'extra_minutes', 'non_approved_extra_minutes',
            'daily_details', 'approval_reason', 'status',
            'approved_by', 'approved_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

class ExtraHoursApprovalUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['pending', 'approved', 'rejected'])
    non_approved_extra_minutes = serializers.IntegerField(required=False, min_value=0)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class MyPaySlipSerializer(PaySlipSerializer):
    """Personal payslip view — used in 'My Payroll' API for the logged-in faculty."""
    payroll_month = serializers.IntegerField(source='payroll_run.month', read_only=True)
    payroll_year = serializers.IntegerField(source='payroll_run.year', read_only=True)
    payroll_status = serializers.CharField(source='payroll_run.get_status_display', read_only=True)
    branch_name = serializers.CharField(source='payroll_run.branch.name', read_only=True)

    class Meta:
        model = PaySlip
        fields = [
            'id', 'payroll_month', 'payroll_year', 'payroll_status', 'branch_name',
            'basic_salary', 'gross_salary', 'total_hours', 'total_session_hours', 'hour_based_amount',
            'late_penalty', 'late_penalty_minutes', 'per_day_deduction_log',
            'late_deduction_log', 'absence_deduction_log',
            'absence_deductions', 'leave_deductions',
            'retention_deduction', 'retention_refund_amount', 'other_deductions', 'deduction_note',
            'attendance_bonus', 'leave_encashment', 'bonus', 'extra_shift_allowance',
            'reimbursements_amount', 'reimbursement_notes',
            'odometer_amount', 'odometer_notes',
            'leave_notes',
            'net_salary', 'leaves_taken', 'working_days',
            'sessions_conducted', 'is_disbursed', 'is_manually_adjusted', 'late_logs',
            'hourly_rate', 'per_paper_rate', 'employment_type', 'session_hours', 'salary', 'visiting_count'
        ]
