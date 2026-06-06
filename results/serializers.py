from rest_framework import serializers
from .models import MarkSheet, PublishedResult, RecheckRequest


class MarkSheetSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    roll_number = serializers.SerializerMethodField()
    checker_name = serializers.SerializerMethodField()

    class Meta:
        model = MarkSheet
        fields = [
            'id', 'exam', 'student', 'student_name', 'roll_number',
            'paper_checker', 'checker_name', 'marks_obtained', 'is_pass',
            'remarks', 'checked_at', 'is_submitted', 'is_rechecked',
        ]

    def get_student_name(self, obj):
        try:
            return obj.student.user.name
        except Exception:
            return str(obj.student_id)

    def get_roll_number(self, obj):
        try:
            return obj.student.roll_number
        except Exception:
            return ''

    def get_checker_name(self, obj):
        return obj.paper_checker.name if obj.paper_checker else None


class PublishedResultSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    roll_number = serializers.SerializerMethodField()

    class Meta:
        model = PublishedResult
        fields = [
            'id', 'exam', 'student', 'student_name', 'roll_number',
            'marks_obtained', 'total_marks', 'percentage', 'is_pass',
            'rank', 'published_at',
        ]

    def get_student_name(self, obj):
        try:
            return obj.student.user.name
        except Exception:
            return str(obj.student_id)

    def get_roll_number(self, obj):
        try:
            return obj.student.roll_number
        except Exception:
            return ''


# v2 NEW: Recheck Request serializers (FRD §4.6.2)

class RecheckRequestSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    roll_number = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    new_checker_name = serializers.SerializerMethodField()


    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = RecheckRequest
        fields = [
            'id', 'marksheet', 'requested_by', 'student_name', 'roll_number',
            'reason', 'status', 'reviewed_by', 'reviewed_by_name',
            'reviewed_at', 'new_checker', 'new_checker_name', 'created_at',
         'status_display']

    def get_student_name(self, obj):
        try:
            return obj.requested_by.user.name
        except Exception:
            return str(obj.requested_by_id)

    def get_roll_number(self, obj):
        try:
            return obj.requested_by.roll_number
        except Exception:
            return ''

    def get_reviewed_by_name(self, obj):
        return obj.reviewed_by.name if obj.reviewed_by else None

    def get_new_checker_name(self, obj):
        return obj.new_checker.name if obj.new_checker else None


class RecheckRequestCreateSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default='')


class RecheckRequestActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['approve', 'reject'])
    new_checker_id = serializers.UUIDField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        if data['action'] == 'approve' and not data.get('new_checker_id'):
            raise serializers.ValidationError({"new_checker_id": "Required when approving."})
        return data
