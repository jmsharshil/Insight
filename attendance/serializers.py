from rest_framework import serializers
from .models import (
    AttendanceRecord, QRScanLog, AlertLog, ViolationRecord,
    SESSION_CHOICES, ATTENDANCE_STATUS_CHOICES, SCAN_TYPE_CHOICES,
    VIOLATION_TYPE_CHOICES,
)
from django.utils import timezone


# ═══════════════════════════════════════════════════════════════════════════════
# AttendanceRecord Serializers
# ═══════════════════════════════════════════════════════════════════════════════

class AttendanceRecordListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    """Read-only serializer for listing attendance records."""
    student_name = serializers.SerializerMethodField()
    roll_number = serializers.SerializerMethodField()
    batch_name = serializers.SerializerMethodField()
    marked_by_name = serializers.SerializerMethodField()
    corrected_by_name = serializers.SerializerMethodField()
    session_display = serializers.CharField(source="get_session_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = [
            'id', 'student', 'student_name', 'roll_number',
            'batch', 'batch_name', 'branch', 'date', 'session',
            'status', 'status_display', 'checked_in_at', 'checked_out_at',
            'marked_by', 'marked_by_name', 'marked_at',
            'is_corrected', 'corrected_by', 'corrected_by_name',
            'correction_note',
         'session_display', 'status_display']

    def get_student_name(self, obj):
        try:
            return obj.student.user.name if hasattr(obj.student, 'user') else str(obj.student)
        except Exception:
            return str(obj.student_id)

    def get_roll_number(self, obj):
        try:
            return obj.student.roll_number if hasattr(obj.student, 'roll_number') else ''
        except Exception:
            return ''

    def get_batch_name(self, obj):
        try:
            return obj.batch.name if obj.batch else None
        except Exception:
            return str(obj.batch_id)

    def get_marked_by_name(self, obj):
        return obj.marked_by.name if obj.marked_by else None

    def get_corrected_by_name(self, obj):
        return obj.corrected_by.name if obj.corrected_by else None


# ── Batch POST payload ───────────────────────────────────────────────────────

class StudentRecordInputSerializer(serializers.Serializer):
    """A single {student_id, status} pair inside the batch POST body."""
    student_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=ATTENDANCE_STATUS_CHOICES)


class BatchAttendanceCreateSerializer(serializers.Serializer):
    """POST /api/v1/attendance/ — bulk mark attendance for a batch."""
    batch_id = serializers.UUIDField()
    date = serializers.DateField()
    session = serializers.ChoiceField(choices=SESSION_CHOICES)
    records = StudentRecordInputSerializer(many=True)

    def validate_date(self, value):
        if value > timezone.now().date():
            raise serializers.ValidationError("Cannot mark attendance for a future date.")
        return value

    def validate_records(self, value):
        if not value:
            raise serializers.ValidationError("At least one student record is required.")
        return value


# ── Correction PATCH ──────────────────────────────────────────────────────────

class AttendanceCorrectionSerializer(serializers.Serializer):
    """PATCH /api/v1/attendance/{id}/ — only ASE or BM can correct."""
    status = serializers.ChoiceField(choices=ATTENDANCE_STATUS_CHOICES, required=False)
    checked_in_at = serializers.DateTimeField(required=False, allow_null=True)
    checked_out_at = serializers.DateTimeField(required=False, allow_null=True)
    correction_note = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        if not any(k in data for k in ('status', 'checked_in_at', 'checked_out_at')):
            raise serializers.ValidationError(
                "At least one of status, checked_in_at, or checked_out_at is required."
            )
        return data


# ═══════════════════════════════════════════════════════════════════════════════
# QR Scan Serializers  (v3: added device_id per FRD §4.4.1)
# ═══════════════════════════════════════════════════════════════════════════════

class QRScanInputSerializer(serializers.Serializer):
    """POST /api/v1/attendance/qr-scan/ — v3: device_id is required."""
    qr_data = serializers.CharField(
        max_length=255,
        help_text='Roll number or student UUID from the QR code.',
    )
    scan_type = serializers.ChoiceField(choices=SCAN_TYPE_CHOICES)
    device_id = serializers.CharField(
        max_length=255,
        required=True,
        help_text='ID of the QR reader device or "mobile_app" for in-app scan.',
    )
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)


class QRScanResponseSerializer(serializers.Serializer):
    """Response for a successful QR scan."""
    student_name = serializers.CharField()
    roll_number = serializers.CharField()
    scan_time = serializers.DateTimeField()
    scan_type = serializers.CharField()
    device_id = serializers.CharField()
    is_valid = serializers.BooleanField()
    attendance_status = serializers.CharField(allow_null=True)
    checked_in_at = serializers.DateTimeField(allow_null=True)
    checked_out_at = serializers.DateTimeField(allow_null=True)
    message = serializers.CharField(required=False)


# ═══════════════════════════════════════════════════════════════════════════════
# Alert Serializers
# ═══════════════════════════════════════════════════════════════════════════════

class AlertTriggerSerializer(serializers.Serializer):
    """POST /api/v1/attendance/alert/"""
    branch_id = serializers.UUIDField()
    threshold = serializers.FloatField(default=75.0)

    def validate_threshold(self, value):
        if not (0 < value <= 100):
            raise serializers.ValidationError("Threshold must be between 0 and 100.")
        return value


class AlertLogSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    alert_type_display = serializers.CharField(source="get_alert_type_display", read_only=True)

    class Meta:
        model = AlertLog
        fields = [
            'id', 'student', 'student_name', 'alert_type',
            'message', 'threshold', 'current_pct', 'sent_at',
            'notified_parent', 'notified_admin',
         'alert_type_display']

    def get_student_name(self, obj):
        try:
            return obj.student.user.name if hasattr(obj.student, 'user') else str(obj.student)
        except Exception:
            return str(obj.student_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Violation Serializers  (v3: added logged_by_admin, created_by per FRD §4.4.3)
# ═══════════════════════════════════════════════════════════════════════════════

class ViolationRecordSerializer(serializers.ModelSerializer):
    """Read-only serializer for listing violations."""
    student_name = serializers.SerializerMethodField()
    roll_number = serializers.SerializerMethodField()
    resolved_by_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    violation_type_display = serializers.CharField(source="get_violation_type_display", read_only=True)

    class Meta:
        model = ViolationRecord
        fields = [
            'id', 'student', 'student_name', 'roll_number',
            'violation_type', 'date', 'description',
            'logged_by_admin', 'is_resolved',
            'resolved_by', 'resolved_by_name', 'resolved_at',
            'created_by', 'created_by_name', 'created_at',
         'violation_type_display']

    def get_student_name(self, obj):
        try:
            return obj.student.user.name if hasattr(obj.student, 'user') else str(obj.student)
        except Exception:
            return str(obj.student_id)

    def get_roll_number(self, obj):
        try:
            return obj.student.roll_number if hasattr(obj.student, 'roll_number') else ''
        except Exception:
            return ''

    def get_resolved_by_name(self, obj):
        return obj.resolved_by.name if obj.resolved_by else None

    def get_created_by_name(self, obj):
        return obj.created_by.name if obj.created_by else None


class ViolationResolveSerializer(serializers.Serializer):
    """PATCH /api/v1/attendance/violations/{id}/"""
    is_resolved = serializers.BooleanField()


class ViolationCreateSerializer(serializers.Serializer):
    """POST /api/v1/attendance/violations/ — admin manual violation (FRD §4.4.3)."""
    student_id = serializers.UUIDField()
    violation_type = serializers.ChoiceField(
        choices=['unauthorised_absence', 'repeated_delay'],
        help_text='Only admin-loggable violation types.',
    )
    date = serializers.DateField()
    description = serializers.CharField(required=False, default='')


class AttendanceReportRowSerializer(serializers.Serializer):
    """One row in the attendance report response (v3: includes violations_breakdown)."""
    student_id = serializers.UUIDField()
    roll_number = serializers.CharField()
    name = serializers.CharField()
    present_days = serializers.IntegerField()
    total_days = serializers.IntegerField()
    percentage = serializers.FloatField()
    avg_checkin_time = serializers.CharField(allow_null=True)
    avg_checkout_time = serializers.CharField(allow_null=True)
    violations_count = serializers.IntegerField()
    violations_breakdown = serializers.DictField()
    status = serializers.CharField()
