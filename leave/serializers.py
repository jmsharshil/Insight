from rest_framework import serializers
from .models import LeavePolicy, LeaveBalance, LeaveApplication, LateEntryRecord, PublicHoliday


class LeavePolicySerializer(serializers.ModelSerializer):

    leave_type_display = serializers.CharField(source="get_leave_type_display", read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = LeavePolicy
        fields = [
            'id', 'branch', 'branch_name', 'leave_type', 'annual_quota', 'max_club_days',
            'carry_forward', 'max_carry_days', 'min_advance_days',
            'allow_half_day', 'sandwich_rule', 'is_active',
         'leave_type_display']
        read_only_fields = ['id']


class LeavePolicyInputSerializer(serializers.Serializer):
    leave_type = serializers.ChoiceField(choices=['paid', 'sick', 'casual', 'club', 'unpaid'])
    annual_quota = serializers.IntegerField()
    max_club_days = serializers.IntegerField(default=5)
    min_advance_days = serializers.IntegerField(default=3)
    allow_half_day = serializers.BooleanField(default=True)
    sandwich_rule = serializers.BooleanField(default=False)
    carry_forward = serializers.BooleanField(default=False)
    max_carry_days = serializers.IntegerField(default=0)


class LeaveBalanceSerializer(serializers.ModelSerializer):
    remaining_days = serializers.DecimalField(max_digits=5, decimal_places=1, read_only=True)


    leave_type_display = serializers.CharField(source="get_leave_type_display", read_only=True)

    class Meta:
        model = LeaveBalance
        fields = ['id', 'leave_type', 'year', 'total_days', 'used_days', 'carried_forward', 'remaining_days', 'leave_type_display']


class LeaveApplicationListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    applied_by_name = serializers.SerializerMethodField()
    applied_by_role = serializers.SerializerMethodField()
    supporting_document_url = serializers.SerializerMethodField()
    is_first_approval_done = serializers.SerializerMethodField()

    leave_type_display = serializers.CharField(source="get_leave_type_display", read_only=True)
    half_day_session_display = serializers.CharField(source="get_half_day_session_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = LeaveApplication
        fields = [
            'id', 'applied_by', 'applied_by_name', 'applied_by_role', 'leave_type',
            'from_date', 'to_date', 'is_half_day', 'total_days',
            'status', 'status_display', 'is_auto_generated', 'supporting_document_url', 'created_at',
            'leave_type_display', 'half_day_session_display', 'status_display', 'is_first_approval_done'
        ]

    def get_is_first_approval_done(self, obj):
        return obj.first_approver is not None
           

    def get_applied_by_name(self, obj):
        return obj.applied_by.name if obj.applied_by else ''
        
    def get_applied_by_role(self, obj):
        return getattr(obj.applied_by, 'role', '') if obj.applied_by else ''

    def get_supporting_document_url(self, obj):
        if obj.supporting_document and hasattr(obj.supporting_document, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.supporting_document.url)
            return obj.supporting_document.url
        return None


class LeaveApplicationDetailSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    applied_by_name = serializers.SerializerMethodField()
    applied_by_role = serializers.SerializerMethodField()
    first_approver_name = serializers.SerializerMethodField()
    second_approver_name = serializers.SerializerMethodField()
    supporting_document_url = serializers.SerializerMethodField()


    leave_type_display = serializers.CharField(source="get_leave_type_display", read_only=True)
    half_day_session_display = serializers.CharField(source="get_half_day_session_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = LeaveApplication
        fields = [
            'id', 'applied_by', 'applied_by_name', 'applied_by_role', 'branch', 'leave_type',
            'from_date', 'to_date', 'is_half_day', 'half_day_session', 'total_days',
            'reason', 'supporting_document', 'supporting_document_url',
            'is_auto_generated', 'status', 'status_display',
            'first_approver', 'first_approver_name', 'first_approved_at',
            'second_approver', 'second_approver_name', 'second_approved_at',
            'reviewed_by', 'reviewed_at', 'rejection_reason', 'created_at',
         'leave_type_display', 'half_day_session_display', 'status_display']

    def get_applied_by_name(self, obj):
        return obj.applied_by.name if obj.applied_by else ''
        
    def get_applied_by_role(self, obj):
        return getattr(obj.applied_by, 'role', '') if obj.applied_by else ''

    def get_first_approver_name(self, obj):
        return obj.first_approver.name if obj.first_approver else ''

    def get_second_approver_name(self, obj):
        return obj.second_approver.name if obj.second_approver else ''

    def get_supporting_document_url(self, obj):
        if obj.supporting_document and hasattr(obj.supporting_document, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.supporting_document.url)
            return obj.supporting_document.url
        return None


class LeaveApplicationCreateSerializer(serializers.Serializer):
    leave_type = serializers.ChoiceField(choices=['paid', 'sick', 'casual', 'club', 'unpaid'], required=False, default='casual')
    from_date = serializers.DateField()
    to_date = serializers.DateField()
    is_half_day = serializers.BooleanField(default=False)
    half_day_session = serializers.ChoiceField(choices=['morning', 'afternoon'], required=False, default='')
    reason = serializers.CharField()
    supporting_document = serializers.FileField(required=False, allow_null=True)
    # NEW (FRD §4.9.2 + §4.9.1): optional upload, required for sick > 2 days

    def validate(self, data):
        if data['from_date'] > data['to_date']:
            raise serializers.ValidationError({'to_date': 'to_date must be >= from_date.'})
        if data['is_half_day'] and data['from_date'] != data['to_date']:
            raise serializers.ValidationError({'is_half_day': 'Half-day leave must be a single date.'})
        return data


class LateEntryRecordSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()


    penalty_type_display = serializers.CharField(source="get_penalty_type_display", read_only=True)

    class Meta:
        model = LateEntryRecord
        fields = [
            'id', 'user', 'user_name', 'date', 'expected_time', 'actual_time',
            'late_minutes', 'grace_minutes', 'is_penalized', 'penalty_type',
            'auto_deduction_triggered', 'notes', 'created_at',
         'penalty_type_display']

    def get_user_name(self, obj):
        return obj.user.name if obj.user else ''


class LateEntryCreateSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    date = serializers.DateField()
    expected_time = serializers.TimeField()
    actual_time = serializers.TimeField()
    penalty_type = serializers.ChoiceField(
        choices=['half_day_deduction', 'salary_deduction', 'warning'], required=False, default=''
    )
    notes = serializers.CharField(required=False, default='')


class PublicHolidaySerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = PublicHoliday
        fields = ['id', 'branch', 'branch_name', 'date', 'name', 'year', 'created_at']
        read_only_fields = ['id', 'year', 'created_at']


class PublicHolidayCreateSerializer(serializers.Serializer):
    date = serializers.DateField()
    name = serializers.CharField(max_length=200)
