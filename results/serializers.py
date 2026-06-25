from rest_framework import serializers
from .models import MarkSheet, PublishedResult, RecheckRequest, CheckerQuery


class MarkSheetSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    roll_number = serializers.SerializerMethodField()
    checker_name = serializers.SerializerMethodField()
    exam_title = serializers.SerializerMethodField()
    exam_scheduled_date = serializers.SerializerMethodField()
    exam_total_marks = serializers.SerializerMethodField()
    exam_pass_marks = serializers.SerializerMethodField()
    batch_name = serializers.SerializerMethodField()
    subject_name = serializers.SerializerMethodField()
    has_open_query = serializers.SerializerMethodField()

    class Meta:
        model = MarkSheet
        fields = [
            'id', 'exam', 'student', 'student_name', 'roll_number',
            'paper_checker', 'checker_name', 'marks_obtained', 'is_pass',
            'remarks', 'checked_at', 'is_submitted', 'is_rechecked', 'is_absent',
            'has_open_query',
            'exam_title', 'exam_scheduled_date', 'exam_total_marks',
            'exam_pass_marks', 'batch_name', 'subject_name',
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

    def get_has_open_query(self, obj):
        """Indicates if there is an open checker query preventing payroll inclusion."""
        return obj.queries.filter(status='open').exists()

    def get_exam_title(self, obj):
        try:
            return obj.exam.title
        except Exception:
            return None

    def get_exam_scheduled_date(self, obj):
        try:
            return obj.exam.scheduled_date
        except Exception:
            return None

    def get_exam_total_marks(self, obj):
        try:
            return obj.exam.total_marks
        except Exception:
            return None

    def get_exam_pass_marks(self, obj):
        try:
            return obj.exam.pass_marks
        except Exception:
            return None

    def get_batch_name(self, obj):
        try:
            return obj.exam.batch.name if obj.exam.batch else None
        except Exception:
            return None

    def get_subject_name(self, obj):
        try:
            return obj.exam.subject.name if obj.exam.subject else None
        except Exception:
            return None


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


# v2 NEW: Recheck Request serializers (FRD §4.6.2 + upload/bulk/answerkey support)
class RecheckRequestSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    student_name = serializers.SerializerMethodField()
    roll_number = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    new_checker_name = serializers.SerializerMethodField()
    uploaded_marksheet_url = serializers.SerializerMethodField()

    class Meta:
        model = RecheckRequest
        fields = [
            'id', 'marksheet', 'requested_by', 'student_name', 'roll_number',
            'reason', 'uploaded_marksheet', 'uploaded_marksheet_url', 'checker_notes',
            'status', 'status_display', 'reviewed_by', 'reviewed_by_name',
            'reviewed_at', 'new_checker', 'new_checker_name', 'created_at',
        ]

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

    def get_uploaded_marksheet_url(self, obj):
        if obj.uploaded_marksheet:
            return obj.uploaded_marksheet.url
        return None


class RecheckRequestCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecheckRequest
        fields = ['reason', 'uploaded_marksheet']
        extra_kwargs = {
            'reason': {'required': True, 'min_length': 10},
        }


class RecheckRequestActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['approve', 'reject'])
    new_checker_id = serializers.UUIDField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        if data['action'] == 'approve' and not data.get('new_checker_id'):
            raise serializers.ValidationError({"new_checker_id": "Required when approving."})
        return data


class CheckerQueryCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CheckerQuery
        fields = ['query_type', 'description']
        extra_kwargs = {
            'query_type': {'required': True, 'allow_blank': False},
        }


class CheckerQuerySerializer(serializers.ModelSerializer):
    """Serializer for paper checker queries (e.g. 'answer key not available')."""
    query_type_display = serializers.CharField(source='get_query_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    raised_by_name = serializers.SerializerMethodField()
    resolved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CheckerQuery
        fields = [
            'id', 'marksheet', 'raised_by', 'raised_by_name', 'query_type',
            'query_type_display', 'description', 'status', 'status_display',
            'resolved_by', 'resolved_by_name', 'resolved_at', 'created_at',
        ]
        read_only_fields = ['marksheet', 'raised_by', 'status', 'resolved_by', 'resolved_at', 'created_at']

    def get_raised_by_name(self, obj):
        return obj.raised_by.name if obj.raised_by else None

    def get_resolved_by_name(self, obj):
        return obj.resolved_by.name if obj.resolved_by else None
