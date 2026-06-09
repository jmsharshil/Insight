from rest_framework import serializers
from .models import LateEntryPolicy, PayrollRun, PaySlip, SessionLatePenaltyLog
from branch.models import Branch


class LateEntryPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = LateEntryPolicy
        fields = [
            'id', 'branch', 'grace_period_minutes', 'deduction_per_minute',
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
    class Meta:
        model = SessionLatePenaltyLog
        fields = ['id', 'session_report', 'scheduled_time', 'actual_start',
                  'late_minutes', 'penalty_amount', 'grace_applied']


class PaySlipSerializer(serializers.ModelSerializer):
    faculty_name = serializers.SerializerMethodField()
    employee_id = serializers.SerializerMethodField()
    late_logs = SessionLatePenaltyLogSerializer(many=True, read_only=True)

    class Meta:
        model = PaySlip
        fields = [
            'id', 'faculty', 'faculty_name', 'employee_id',
            'basic_salary', 'total_session_hours', 'hour_based_amount',
            'late_penalty', 'absence_deductions', 'leave_deductions',
            'other_deductions', 'deduction_note',
            'bonus', 'net_salary', 'leaves_taken', 'working_days',
            'sessions_conducted', 'is_disbursed', 'late_logs',
        ]

    def get_faculty_name(self, obj):
        return obj.faculty.user.name if obj.faculty else ''

    def get_employee_id(self, obj):
        return obj.faculty.employee_id if obj.faculty else ''


class PayrollRunListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    faculty_count = serializers.SerializerMethodField()
    branch_name = serializers.SerializerMethodField()


    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PayrollRun
        fields = [
            'id', 'branch', 'branch_name', 'month', 'year', 'status', 'status_display',
            'total_amount', 'faculty_count', 'generated_at', 'approved_at', 'disbursed_at',
         'status_display']

    def get_faculty_count(self, obj):
        return obj.payslips.count()

    def get_branch_name(self, obj):
        return obj.branch.name if obj.branch else ''


class PayrollRunDetailSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payslips = PaySlipSerializer(many=True, read_only=True)
    generated_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()


    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PayrollRun
        fields = [
            'id', 'branch', 'month', 'year', 'status', 'status_display', 'total_amount',
            'generated_by', 'generated_by_name', 'approved_by', 'approved_by_name',
            'generated_at', 'approved_at', 'disbursed_at', 'notes', 'payslips',
         'status_display']

    def get_generated_by_name(self, obj):
        return obj.generated_by.name if obj.generated_by else ''

    def get_approved_by_name(self, obj):
        return obj.approved_by.name if obj.approved_by else ''


class PayrollGenerateSerializer(serializers.Serializer):
    branch_id = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.all())
    month = serializers.IntegerField(min_value=1, max_value=12)
    year = serializers.IntegerField(min_value=2020)


class PaySlipAdjustSerializer(serializers.Serializer):
    """PATCH /api/v1/payroll/{id}/payslips/{slip_id}/ — adjust payslip amounts."""
    bonus = serializers.DecimalField(max_digits=8, decimal_places=2, required=False)
    other_deductions = serializers.DecimalField(max_digits=8, decimal_places=2, required=False)
    deduction_note = serializers.CharField(max_length=300, required=False, allow_blank=True)
    leave_deductions = serializers.DecimalField(max_digits=8, decimal_places=2, required=False)
