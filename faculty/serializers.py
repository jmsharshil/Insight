from rest_framework import serializers
from .models import FacultyProfile, FacultyQRScanLog, SessionReport, SubjectHourlyRate


# ═══ Faculty Profile ══════════════════════════════════════════════════════════

class FacultyListSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    branch_name = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()
    batch_count = serializers.IntegerField(read_only=True, default=0)
    level_display = serializers.CharField(source="get_level_display", read_only=True)
    employment_type_display = serializers.CharField(source="get_employment_type_display", read_only=True)

    class Meta:
        model = FacultyProfile
        fields = [
            'id', 'employee_id', 'full_name', 'email', 'phone', 'photo_url', 'branch', 'branch_name',
            'level', 'employment_type', 'specialization', 'subject_expertise',
            'joining_date', 'is_active', 'batch_count', 'created_at',
         'level_display', 'employment_type_display']

    def get_full_name(self, obj):
        return obj.user.name if obj.user else ''

    def get_email(self, obj):
        return obj.user.email if obj.user else ''

    def get_phone(self, obj):
        return getattr(obj.user, 'phone', '') if obj.user else ''

    def get_branch_name(self, obj):
        return obj.branch.name if obj.branch else ''

    def get_photo_url(self, obj):
        if obj.photo and hasattr(obj.photo, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.photo.url)
            return obj.photo.url
        return None


class FacultyDetailSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()
    qr_code_url = serializers.SerializerMethodField()
    level_display = serializers.CharField(source="get_level_display", read_only=True)
    employment_type_display = serializers.CharField(source="get_employment_type_display", read_only=True)

    class Meta:
        model = FacultyProfile
        fields = [
            'id', 'employee_id', 'full_name', 'email', 'phone', 'photo_url',
            'branch', 'qualification', 'specialization', 'subject_expertise',
            'level', 'employment_type', 'joining_date',
            'salary', 'hourly_rate', 'bank_account', 'ifsc_code', 'pan_number',
            'qr_code', 'qr_code_url', 'is_active', 'created_at',
         'level_display', 'employment_type_display']

    def get_full_name(self, obj):
        return obj.user.name if obj.user else ''

    def get_email(self, obj):
        return obj.user.email if obj.user else ''

    def get_phone(self, obj):
        return getattr(obj.user, 'phone', '') if obj.user else ''

    def get_photo_url(self, obj):
        if obj.photo and hasattr(obj.photo, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.photo.url)
            return obj.photo.url
        return None

    def get_qr_code_url(self, obj):
        if obj.qr_code and hasattr(obj.qr_code, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.qr_code.url)
            return obj.qr_code.url
        return None


class FacultyCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=20, required=False, default='')
    photo = serializers.ImageField(required=False, allow_null=True)
    # NEW (FRD §4.8.1): photo upload on creation
    qualification = serializers.CharField(max_length=200)
    specialization = serializers.CharField(max_length=200)
    subject_expertise = serializers.CharField(max_length=300, required=False, default='')
    level = serializers.ChoiceField(choices=['executive', 'professional'], default='executive')
    employment_type = serializers.ChoiceField(choices=['full_time', 'part_time', 'contract'], default='full_time')
    joining_date = serializers.DateField()
    salary = serializers.DecimalField(max_digits=10, decimal_places=2, default=0)
    hourly_rate = serializers.DecimalField(max_digits=8, decimal_places=2, default=0)
    bank_account = serializers.CharField(max_length=30, required=False, default='')
    ifsc_code = serializers.CharField(max_length=15, required=False, default='')
    pan_number = serializers.CharField(max_length=15, required=False, default='')
    branch = serializers.UUIDField(required=False, allow_null=True)


class FacultyUpdateSerializer(serializers.ModelSerializer):
    photo = serializers.ImageField(required=False, allow_null=True)
    full_name = serializers.CharField(max_length=150, required=False)
    name = serializers.CharField(max_length=150, required=False, write_only=True)
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(max_length=20, required=False)
    branch_id = serializers.UUIDField(required=False, write_only=True)
    branch = serializers.UUIDField(required=False, write_only=True)

    class Meta:
        model = FacultyProfile
        fields = [
            'qualification', 'specialization', 'subject_expertise',
            'level', 'employment_type', 'salary', 'hourly_rate',
            'bank_account', 'ifsc_code', 'pan_number', 'is_active', 'photo',
            'full_name', 'name', 'email', 'phone', 'branch_id', 'branch',
        ]

    def update(self, instance, validated_data):
        user_data_keys = ['full_name', 'name', 'email', 'phone']
        user_updates = {}
        for key in user_data_keys:
            if key in validated_data:
                user_updates[key] = validated_data.pop(key)

        branch_val = validated_data.pop('branch_id', None) or validated_data.pop('branch', None)
        if branch_val:
            from branch.models import Branch
            try:
                branch_obj = Branch.objects.get(id=branch_val)
                instance.branch = branch_obj
            except Branch.DoesNotExist:
                pass

        if user_updates and instance.user:
            user = instance.user
            full_name_val = user_updates.get('full_name') or user_updates.get('name')
            if full_name_val:
                user.name = full_name_val
            if 'email' in user_updates:
                # Need to update username if email changes? Optional, let's just update email
                user.email = user_updates['email']
            if 'phone' in user_updates:
                user.phone = user_updates['phone']
            user.save()

        return super().update(instance, validated_data)


# ═══ Subject Hourly Rate ═════════════════════════════════════════════════════

class SubjectHourlyRateSerializer(serializers.ModelSerializer):
    subject_name = serializers.SerializerMethodField()

    class Meta:
        model = SubjectHourlyRate
        fields = ['id', 'subject', 'subject_name', 'hourly_rate', 'effective_from', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_subject_name(self, obj):
        return obj.subject.name if obj.subject else ''


class SubjectHourlyRateCreateSerializer(serializers.Serializer):
    subject_id = serializers.UUIDField()
    hourly_rate = serializers.DecimalField(max_digits=8, decimal_places=2)
    effective_from = serializers.DateField()


# ═══ QR Check-in ══════════════════════════════════════════════════════════════

class FacultyQRCheckinSerializer(serializers.Serializer):
    qr_data = serializers.CharField()
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    scan_type = serializers.ChoiceField(choices=['check_in', 'check_out'], default='check_in')


class FacultyQRScanLogSerializer(serializers.ModelSerializer):
    faculty_name = serializers.SerializerMethodField()
    scan_type_display = serializers.CharField(source="get_scan_type_display", read_only=True)

    class Meta:
        model = FacultyQRScanLog
        fields = ['id', 'faculty', 'faculty_name', 'scanned_at', 'scan_type', 'is_late', 'late_minutes', 'scan_type_display']

    def get_faculty_name(self, obj):
        return obj.faculty.user.name if obj.faculty and obj.faculty.user else ''


# ═══ Session Report ═══════════════════════════════════════════════════════════

class SessionReportSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    faculty_name = serializers.SerializerMethodField()
    batch_name = serializers.SerializerMethodField()
    subject_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = SessionReport
        fields = [
            'id', 'faculty', 'faculty_name', 'batch', 'batch_name',
            'subject', 'subject_name', 'session_date',
            'chapter_covered', 'topics_covered', 'completion_percentage',
            'status', 'status_display', 'start_time', 'end_time', 'duration_minutes', 'notes',
            'created_at', 'updated_at',
         'status_display']

    def get_faculty_name(self, obj):
        return obj.faculty.user.name if obj.faculty and obj.faculty.user else ''

    def get_batch_name(self, obj):
        return obj.batch.name if obj.batch else ''

    def get_subject_name(self, obj):
        return obj.subject.name if obj.subject else ''


class SessionReportCreateSerializer(serializers.Serializer):
    batch_id = serializers.UUIDField()
    subject_id = serializers.UUIDField()
    timetable_slot_id = serializers.UUIDField(required=False, allow_null=True)
    session_date = serializers.DateField()
    chapter_covered = serializers.CharField(max_length=300)
    topics_covered = serializers.CharField()
    completion_percentage = serializers.IntegerField(default=100, min_value=0, max_value=100)
    # NEW (FRD §4.8.3): completion percentage 0-100
    status = serializers.ChoiceField(choices=['in_progress', 'completed'], default='completed')
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    notes = serializers.CharField(required=False, default='')

    def validate(self, data):
        if data['end_time'] <= data['start_time']:
            raise serializers.ValidationError({'end_time': 'Must be after start_time.'})
        from django.utils import timezone
        if data['session_date'] > timezone.now().date():
            raise serializers.ValidationError({'session_date': 'Cannot be a future date.'})
        return data


class SessionReportUpdateSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    class Meta:
        model = SessionReport
        fields = [
            'chapter_covered', 'topics_covered', 'completion_percentage',
            'status', 'status_display', 'start_time', 'end_time', 'notes',
        ]
