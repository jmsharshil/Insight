from rest_framework import serializers
from django.utils import timezone
from .models import (
    Exam, Question, Choice, ExamSession, StudentAnswer,
    SeatArrangement, MalpracticeReport, ScreenEvent,
)


# ═══ Choices ══════════════════════════════════════════════════════════════════

class ChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Choice
        fields = ['id', 'choice_text', 'is_correct']


class ChoiceStudentSerializer(serializers.ModelSerializer):
    """Strips is_correct — for students during exam."""
    class Meta:
        model = Choice
        fields = ['id', 'choice_text']


class ChoiceInputSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=500)
    is_correct = serializers.BooleanField(default=False)


# ═══ Questions ════════════════════════════════════════════════════════════════

class QuestionSerializer(serializers.ModelSerializer):
    choices = ChoiceSerializer(many=True, read_only=True)
    question_type_display = serializers.CharField(source="get_question_type_display", read_only=True)

    class Meta:
        model = Question
        fields = ['id', 'question_text', 'question_type', 'marks', 'order', 'image', 'choices', 'question_type_display']


class QuestionStudentSerializer(serializers.ModelSerializer):
    """Strips is_correct from choices."""
    choices = ChoiceStudentSerializer(many=True, read_only=True)
    question_type_display = serializers.CharField(source="get_question_type_display", read_only=True)

    class Meta:
        model = Question
        fields = ['id', 'question_text', 'question_type', 'marks', 'order', 'choices', 'question_type_display']


class QuestionInputSerializer(serializers.Serializer):
    question_text = serializers.CharField()
    question_type = serializers.ChoiceField(choices=['mcq', 'subjective', 'true_false'])
    marks = serializers.IntegerField(min_value=1)
    order = serializers.IntegerField(min_value=1)
    choices = ChoiceInputSerializer(many=True, required=False, default=[])

    def validate(self, data):
        qt = data['question_type']
        choices = data.get('choices', [])
        if qt in ('mcq', 'true_false'):
            if not choices:
                raise serializers.ValidationError("MCQ/True-False questions require at least one choice.")
            if not any(c['is_correct'] for c in choices):
                raise serializers.ValidationError("At least one choice must be marked correct.")
        return data


# ═══ Exam ═════════════════════════════════════════════════════════════════════

class ExamListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    batch_name = serializers.SerializerMethodField()
    subject_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    exam_type_display = serializers.CharField(source="get_exam_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    screen_lock_action_display = serializers.CharField(source="get_screen_lock_action_display", read_only=True)
    split_screen_action_display = serializers.CharField(source="get_split_screen_action_display", read_only=True)
    result_release_mode_display = serializers.CharField(source="get_result_release_mode_display", read_only=True)
    can_start_exam = serializers.SerializerMethodField()

    class Meta:
        model = Exam
        fields = [
            'id', 'title', 'exam_type', 'total_marks', 'pass_marks',
            'duration_minutes', 'scheduled_date', 'start_time', 'end_time',
            'status', 'status_display', 'batch', 'batch_name', 'subject', 'subject_name',
            'branch', 'created_by', 'created_by_name', 'created_at',
            # v2 fields
            'geo_radius_meters', 'geo_check_interval_minutes',
            'screen_lock_max_violations', 'screen_lock_action',
            'split_screen_max_warnings', 'split_screen_action',
            'result_release_mode',
         'exam_type_display', 'status_display', 'screen_lock_action_display', 
         'split_screen_action_display', 'result_release_mode_display', 'can_start_exam']

    def get_can_start_exam(self, obj):
        request = self.context.get('request')
        if not request or getattr(request.user, 'role', None) != 'student':
            return False

        student = getattr(request, '_cached_student', None)
        if student is None:
            try:
                from students.models import Student
                student = Student.objects.get(user=request.user)
                request._cached_student = student
            except Exception:
                request._cached_student = False
                return False
        elif student is False:
            return False

        if student.batch_id != obj.batch_id:
            return False

        if obj.status not in ['scheduled', 'ongoing']:
            return False

        from django.utils import timezone
        now = timezone.now()
        dt_start = timezone.make_aware(timezone.datetime.combine(obj.scheduled_date, obj.start_time))
        dt_end = timezone.make_aware(timezone.datetime.combine(obj.scheduled_date, obj.end_time))

        if not (dt_start <= now <= dt_end):
            return False

        from .models import ExamSession
        if ExamSession.objects.filter(exam=obj, student=student).exists():
            return False

        return True

    def get_batch_name(self, obj):
        return obj.batch.name if obj.batch else None

    def get_subject_name(self, obj):
        return obj.subject.name if obj.subject else None

    def get_created_by_name(self, obj):
        return obj.created_by.name if obj.created_by else None


class ExamCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exam
        fields = [
            'title', 'exam_type', 'batch', 'subject', 'total_marks', 'pass_marks',
            'duration_minutes', 'scheduled_date', 'start_time', 'end_time',
            'instructions', 'geo_lat', 'geo_lon', 'geo_radius_meters',
            'status',
            # v2 fields
            'geo_check_interval_minutes',
            'screen_lock_max_violations', 'screen_lock_action',
            'split_screen_max_warnings', 'split_screen_action',
            'result_release_mode',
        ]

    def validate(self, data):
        # Only check past dates if creating a new exam or changing the date
        if data.get('scheduled_date'):
            is_new_date = not self.instance or self.instance.scheduled_date != data['scheduled_date']
            if is_new_date and data['scheduled_date'] < timezone.now().date():
                raise serializers.ValidationError({"scheduled_date": "Cannot schedule in the past."})
        if data.get('pass_marks', 0) > data.get('total_marks', 0):
            raise serializers.ValidationError({"pass_marks": "Cannot exceed total marks."})
        if data.get('start_time') and data.get('end_time') and data['end_time'] <= data['start_time']:
            raise serializers.ValidationError({"end_time": "Must be after start time."})
        radius = data.get('geo_radius_meters', 0)
        if radius > 0 and (not data.get('geo_lat') or not data.get('geo_lon')):
            raise serializers.ValidationError({"geo_lat": "Required when geo_radius > 0."})
        return data


# ═══ Session ══════════════════════════════════════════════════════════════════

class ExamStartSerializer(serializers.Serializer):
    student_lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    student_lon = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    device_fingerprint = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    ip_address = serializers.IPAddressField(required=False, allow_null=True, default=None)


class AnswerInputSerializer(serializers.Serializer):
    question_id = serializers.UUIDField()
    selected_choice_id = serializers.UUIDField(required=False, allow_null=True)
    text_answer = serializers.CharField(required=False, allow_blank=True, default='')


class ExamSubmitSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    answers = AnswerInputSerializer(many=True, required=False, default=[])


class AutosaveSerializer(serializers.Serializer):
    question_id = serializers.UUIDField()
    selected_choice_id = serializers.UUIDField(required=False, allow_null=True)
    text_answer = serializers.CharField(required=False, allow_blank=True, default='')


class ScreenEventSerializer(serializers.Serializer):
    event = serializers.ChoiceField(choices=['lock_breach', 'split_screen'])


# v2 NEW: geo-check serializer
class GeoCheckSerializer(serializers.Serializer):
    student_lat = serializers.DecimalField(max_digits=9, decimal_places=6)
    student_lon = serializers.DecimalField(max_digits=9, decimal_places=6)


# ═══ Seating ══════════════════════════════════════════════════════════════════

class SeatInputSerializer(serializers.Serializer):
    student_id = serializers.UUIDField()
    room_name = serializers.CharField(max_length=100)
    seat_number = serializers.CharField(max_length=20)
    row_number = serializers.IntegerField(required=False, allow_null=True)


class SeatArrangementSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    roll_number = serializers.SerializerMethodField()

    class Meta:
        model = SeatArrangement
        fields = ['id', 'student', 'student_name', 'roll_number', 'room_name', 'seat_number', 'row_number']

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


# ═══ Malpractice ══════════════════════════════════════════════════════════════

class MalpracticeInputSerializer(serializers.Serializer):
    student_id = serializers.UUIDField()
    description = serializers.CharField()
    severity = serializers.ChoiceField(choices=['minor', 'major', 'disqualified'])


class MalpracticeSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    reported_by_name = serializers.SerializerMethodField()
    severity_display = serializers.CharField(source="get_severity_display", read_only=True)

    class Meta:
        model = MalpracticeReport
        fields = ['id', 'student', 'student_name', 'reported_by', 'reported_by_name',
                  'description', 'severity', 'reported_at', 'action_taken', 'severity_display']

    def get_student_name(self, obj):
        try:
            return obj.student.user.name
        except Exception:
            return str(obj.student_id)

    def get_reported_by_name(self, obj):
        return obj.reported_by.name if obj.reported_by else None


# ═══ Marks / Checker ══════════════════════════════════════════════════════════

class MarksInputSerializer(serializers.Serializer):
    marks_obtained = serializers.DecimalField(max_digits=6, decimal_places=2)
    remarks = serializers.CharField(required=False, allow_blank=True, default='')
