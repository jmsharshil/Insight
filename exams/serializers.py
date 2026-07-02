from rest_framework import serializers
from django.utils import timezone
from django.contrib.auth import get_user_model
from .models import (
    Exam, Question, Choice, ExamSession, StudentAnswer,
    SeatArrangement, MalpracticeReport, ScreenEvent,
    SubjectPaper,
)

User = get_user_model()


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
        fields = ['id', 'question_text', 'question_type', 'marks', 'order', 'image',
                  'paragraph_text', 'choices', 'question_type_display']


class QuestionStudentSerializer(serializers.ModelSerializer):
    """Strips is_correct from choices."""
    choices = ChoiceStudentSerializer(many=True, read_only=True)
    question_type_display = serializers.CharField(source="get_question_type_display", read_only=True)

    class Meta:
        model = Question
        fields = ['id', 'question_text', 'question_type', 'marks', 'order',
                  'paragraph_text', 'choices', 'question_type_display']


class QuestionInputSerializer(serializers.Serializer):
    question_text = serializers.CharField()
    question_type = serializers.ChoiceField(choices=['mcq', 'paragraph_mcq', 'subjective', 'true_false'])
    marks = serializers.IntegerField(min_value=1)
    order = serializers.IntegerField(min_value=1)
    choices = ChoiceInputSerializer(many=True, required=False, default=[])
    # For paragraph_mcq: the comprehension passage
    paragraph_text = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        qt = data['question_type']
        choices = data.get('choices', [])
        if qt in ('mcq', 'true_false', 'paragraph_mcq'):
            if not choices:
                raise serializers.ValidationError("MCQ/True-False/Paragraph MCQ questions require at least one choice.")
            if not any(c['is_correct'] for c in choices):
                raise serializers.ValidationError("At least one choice must be marked correct.")
        if qt == 'paragraph_mcq' and not data.get('paragraph_text', '').strip():
            raise serializers.ValidationError("Paragraph MCQ questions require paragraph_text.")
        return data


# ═══ Exam ═════════════════════════════════════════════════════════════════════

class SubjectPaperSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    set_name = serializers.CharField(
        max_length=50, required=False, allow_blank=True, default='',
        help_text='Optional label, e.g. "Set A". Auto-derived from filename if omitted.'
    )

    class Meta:
        model = SubjectPaper
        fields = ['id', 'subject', 'subject_name', 'set_name', 'file', 'answer_key', 'created_at']
        read_only_fields = ['id', 'created_at', 'subject_name']


class ExamListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    batch_name = serializers.SerializerMethodField()
    subject_name = serializers.SerializerMethodField()
    faculty_id = serializers.SerializerMethodField()
    faculty_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    exam_type_display = serializers.CharField(source="get_exam_type_display", read_only=True)
    exam_mode_display = serializers.CharField(source="get_exam_mode_display", read_only=True)
    screen_lock_action_display = serializers.CharField(source="get_screen_lock_action_display", read_only=True)
    split_screen_action_display = serializers.CharField(source="get_split_screen_action_display", read_only=True)
    result_release_mode_display = serializers.CharField(source="get_result_release_mode_display", read_only=True)
    paper_checkers = serializers.SerializerMethodField()
    selected_papers = SubjectPaperSerializer(many=True, read_only=True)
    can_start_exam = serializers.SerializerMethodField()
    questions_count = serializers.SerializerMethodField()
    is_upcoming = serializers.SerializerMethodField()

    class Meta:
        model = Exam
        fields = [
            'id', 'title', 'exam_type', 'exam_mode', 'total_marks', 'pass_marks',
            'duration_minutes', 'scheduled_date', 'start_time', 'end_time',
            'status', 'status_display', 'batch', 'batch_name', 'subject', 'subject_name',
            'faculty', 'faculty_id', 'faculty_name', 'branch', 'created_by', 'created_by_name', 'created_at',
            # v2 fields
            'geo_radius_meters', 'geo_check_interval_minutes',
            'screen_lock_max_violations', 'screen_lock_action',
            'split_screen_max_warnings', 'split_screen_action',
            'result_release_mode',
            'exam_type_display', 'exam_mode_display', 'status_display', 'screen_lock_action_display',
            'split_screen_action_display', 'result_release_mode_display', 'paper_checkers',
            'selected_papers',
            'can_start_exam', 'questions_count', 'is_upcoming']

    def get_is_upcoming(self, obj):
        from django.utils import timezone
        import datetime
        now = timezone.now()
        
        if not obj.scheduled_date or not obj.start_time:
            return False
            
        dt_start_naive = datetime.datetime.combine(obj.scheduled_date, obj.start_time)
        if timezone.is_naive(dt_start_naive):
            dt_start = timezone.make_aware(dt_start_naive)
        else:
            dt_start = dt_start_naive
            
        return now < dt_start

    def get_questions_count(self, obj):
        return obj.questions.count()

    def get_can_start_exam(self, obj):
        request = self.context.get('request')
        if not request or getattr(request.user, 'role', None) != 'student':
            print(f"can_start_exam=False: Role is not student. user={getattr(request, 'user', None)}, role={getattr(getattr(request, 'user', None), 'role', None)}")
            return False

        student = getattr(request, '_cached_student', None)
        if student is None:
            try:
                from students.models import Student
                student = Student.objects.filter(user=request.user).first()
                if student:
                    request._cached_student = student
                else:
                    request._cached_student = False
                    print("can_start_exam=False: No Student profile found for this user.")
                    return False
            except Exception as e:
                request._cached_student = False
                print(f"can_start_exam=False: Exception fetching student: {e}")
                return False
        elif student is False:
            return False

        if student.batch_id != obj.batch_id:
            print(f"can_start_exam=False: Batch mismatch. student.batch_id={student.batch_id}, exam.batch_id={obj.batch_id}")
            return False

        # Block only on terminal statuses — time is the primary gate
        if obj.status in ['draft', 'completed', 'results_published']:
            print(f"can_start_exam=False: Status is blocked. obj.status={obj.status}")
            return False

        from django.utils import timezone
        import datetime
        now = timezone.now()
        
        # Build naive datetime from exam schedule
        dt_start_naive = datetime.datetime.combine(obj.scheduled_date, obj.start_time)
        dt_end_naive = datetime.datetime.combine(obj.scheduled_date, obj.end_time)
        
        # Safely convert to aware datetime
        if timezone.is_naive(dt_start_naive):
            dt_start = timezone.make_aware(dt_start_naive)
            dt_end = timezone.make_aware(dt_end_naive)
        else:
            dt_start = dt_start_naive
            dt_end = dt_end_naive

        # can_start_exam becomes True exactly when the scheduled time is reached,
        # OR if the exam status has been explicitly set to 'ongoing'
        if not (dt_start <= now <= dt_end) and obj.status != 'ongoing':
            print(f"can_start_exam=False: Time out of bounds and not ongoing. dt_start={dt_start}, now={now}, dt_end={dt_end}")
            return False

        from .models import ExamSession
        if ExamSession.objects.filter(exam=obj, student=student, is_submitted=True).exists():
            print("can_start_exam=False: ExamSession already submitted for this student.")
            return False

        return True


    def get_batch_name(self, obj):
        return obj.batch.name if obj.batch else None

    def get_subject_name(self, obj):
        return obj.subject.name if obj.subject else None

    def get_faculty_id(self, obj):
        return obj.faculty.id if obj.faculty else None

    def get_faculty_name(self, obj):
        return obj.faculty.user.name if obj.faculty and obj.faculty.user else None

    def get_created_by_name(self, obj):
        return obj.created_by.name if obj.created_by else None

    def get_paper_checkers(self, obj):
        """Return list of paper checkers with id and name for frontend display."""
        return [
            {'id': user.id, 'name': user.name, 'email': user.email}
            for user in obj.paper_checkers.all()
        ]


class ExamCreateSerializer(serializers.ModelSerializer):
    total_marks = serializers.IntegerField(required=False, default=0)
    paper_checkers = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role='paper_checker', is_active=True),
        many=True, required=False, allow_empty=True, write_only=True
    )
    selected_papers = serializers.PrimaryKeyRelatedField(
        queryset=SubjectPaper.objects.all(),
        many=True, required=False, allow_empty=True
    )

    class Meta:
        model = Exam
        fields = [
            'title', 'exam_type', 'exam_mode', 'batch', 'subject', 'faculty', 'total_marks', 'pass_marks',
            'duration_minutes', 'scheduled_date', 'start_time', 'end_time',
            'instructions', 'geo_lat', 'geo_lon', 'geo_radius_meters',
            'status',
            # v2 fields
            'geo_check_interval_minutes',
            'screen_lock_max_violations', 'screen_lock_action',
            'split_screen_max_warnings', 'split_screen_action',
            'result_release_mode', 'paper_checkers', 'selected_papers',
        ]

    def validate(self, data):
        # Only check past dates if creating a new exam or changing the date
        if data.get('scheduled_date'):
            is_new_date = not self.instance or self.instance.scheduled_date != data['scheduled_date']
            if is_new_date and data['scheduled_date'] < timezone.now().date():
                raise serializers.ValidationError({"scheduled_date": "Cannot schedule in the past."})
        # pass_marks <= total_marks retained (but total_marks may be 0 until questions added;
        # if total_marks==0 we skip strict check as it will be auto-computed later)
        total_m = data.get('total_marks', 0)
        if total_m > 0 and data.get('pass_marks', 0) > total_m:
            raise serializers.ValidationError({"pass_marks": "Cannot exceed total marks."})
        if data.get('start_time') and data.get('end_time') and data['end_time'] <= data['start_time']:
            raise serializers.ValidationError({"end_time": "Must be after start time."})
        radius = data.get('geo_radius_meters', 0)
        if radius > 0 and (not data.get('geo_lat') or not data.get('geo_lon')):
            raise serializers.ValidationError({"geo_lat": "Required when geo_radius > 0."})
        return data

    def create(self, validated_data):
        paper_checkers = validated_data.pop('paper_checkers', [])
        selected_papers = validated_data.pop('selected_papers', [])
        exam = super().create(validated_data)
        if paper_checkers:
            exam.paper_checkers.set(paper_checkers)
        if selected_papers:
            exam.selected_papers.set(selected_papers)
        return exam

    def update(self, instance, validated_data):
        paper_checkers = validated_data.pop('paper_checkers', None)
        selected_papers = validated_data.pop('selected_papers', None)
        exam = super().update(instance, validated_data)
        if paper_checkers is not None:
            exam.paper_checkers.set(paper_checkers)
        if selected_papers is not None:
            exam.selected_papers.set(selected_papers)
        return exam


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
