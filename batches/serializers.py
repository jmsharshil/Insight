from datetime import datetime, timedelta

from rest_framework import serializers
from .models import (
    Course, Subject, Batch, BatchStudent, BatchFaculty,
    Classroom, TimetableSlot, DAY_CHOICES, SESSION_CHOICES,
    CourseLevel, Chapter,
    SESSION_TYPE_CHOICES, SLOT_CODE_CHOICES,
)
from django.conf import settings


# ═══════════════════════════════════════════════════════════════════════════════
#  Course Serializers
# ═══════════════════════════════════════════════════════════════════════════════

# E2 — forward declare so CourseDetailSerializer can reference it
class CourseLevelSerializer(serializers.ModelSerializer):
    """Read/write serializer for CourseLevel (E2)."""
    course_type_display = serializers.CharField(source="get_course_type_display", read_only=True)
    subjects = serializers.SerializerMethodField()

    class Meta:
        model = CourseLevel
        fields = ['id', 'course', 'name', 'course_type', 'course_type_display', 'duration_months', 'fee_amount', 'order', 'description', 'is_active', 'subjects']
        read_only_fields = ['id', 'course']

    def get_subjects(self, obj):
        qs = Subject.objects.filter(level=obj, is_active=True)
        return SubjectListSerializer(qs, many=True).data

    def validate(self, data):
        # Duplicate order check (create only)
        course = self.context.get('course')
        order = data.get('order')
        if course and order is not None:
            qs = CourseLevel.objects.filter(course=course, order=order)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {'order': f'A level with order {order} already exists for this course.'}
                )
        return data


class CourseListSerializer(serializers.ModelSerializer):
    subject_count = serializers.IntegerField(read_only=True, default=0)
    levels = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = ['id', 'name', 'code', 'is_active', 'subject_count', 'created_at', 'levels']

    def get_levels(self, obj):
        qs = obj.levels.filter(is_active=True)
        return CourseLevelSerializer(qs, many=True).data


class CourseDetailSerializer(serializers.ModelSerializer):
    subjects = serializers.SerializerMethodField()
    levels   = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = '__all__'

    def get_subjects(self, obj):
        from batches.models import Subject
        qs = Subject.objects.filter(level__course=obj, is_active=True)
        return SubjectListSerializer(qs, many=True).data

    def get_levels(self, obj):
        qs = obj.levels.filter(is_active=True)
        return CourseLevelSerializer(qs, many=True).data


class CourseCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ['name', 'description', 'is_active', 'organization']

    def validate_code(self, value):
        if not value:
            return ''
        return value.upper().strip()

    def create(self, validated_data):
        if 'organization' not in validated_data or validated_data['organization'] is None:
            validated_data['organization'] = self.context['request'].user.organization
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'organization' not in validated_data or validated_data['organization'] is None:
            validated_data['organization'] = instance.organization or self.context['request'].user.organization
        return super().update(instance, validated_data)


# ═══════════════════════════════════════════════════════════════════════════════
#  Subject Serializers
# ═══════════════════════════════════════════════════════════════════════════════

# E2 — forward declare so SubjectListSerializer can reference it
class ChapterSerializer(serializers.ModelSerializer):
    """Read/write serializer for Chapter (E2)."""

    class Meta:
        model = Chapter
        fields = ['id', 'subject', 'name', 'order', 'description', 'is_active','duration_hours']
        read_only_fields = ['id', 'subject']

    def validate(self, data):
        subject = self.context.get('subject')
        order = data.get('order')
        if subject and order is not None:
            qs = Chapter.objects.filter(subject=subject, order=order)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {'order': f'A chapter with order {order} already exists for this subject.'}
                )
        return data


class SubjectListSerializer(serializers.ModelSerializer):
    level_name = serializers.CharField(source='level.name', read_only=True)
    course_name = serializers.CharField(source='level.course.name', read_only=True)
    chapters    = serializers.SerializerMethodField()
    papers = serializers.SerializerMethodField()

    class Meta:
        model = Subject
        fields = ['id', 'level', 'level_name', 'course_name', 'name', 'code',
                  'total_hours', 'is_active', 'chapters','papers']

    def get_chapters(self, obj):
        qs = obj.chapters.filter(is_active=True)
        return ChapterSerializer(qs, many=True).data

    def get_papers(self, obj):
        from exams.serializers import SubjectPaperSerializer
        qs = obj.papers.all()
        return SubjectPaperSerializer(qs, many=True).data


class SubjectCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ['level', 'name', 'is_active', 'organization']
        # total_hours is now auto-managed via Chapter.duration_hours signals

    # def validate_code(self, value):
    #     if not value:
    #         return ''
    #     return value.upper().strip()

    def create(self, validated_data):
        if 'organization' not in validated_data or validated_data['organization'] is None:
            validated_data['organization'] = self.context['request'].user.organization
        instance = super().create(validated_data)
        # Ensure total_hours is calculated after creation (in case chapters are added via nested later)
        instance.update_total_hours()
        return instance

    def update(self, instance, validated_data):
        if 'organization' not in validated_data or validated_data['organization'] is None:
            validated_data['organization'] = instance.organization or self.context['request'].user.organization
        instance = super().update(instance, validated_data)
        instance.update_total_hours()
        return instance


# ═══════════════════════════════════════════════════════════════════════════════
#  Batch Serializers
# ═══════════════════════════════════════════════════════════════════════════════

class BatchListSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True)
    enrolled_count = serializers.IntegerField(read_only=True, default=0)
    group_module_display = serializers.CharField(source="get_group_module_display", read_only=True)
    batch_attempt_display = serializers.CharField(source="get_batch_attempt_display", read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    qr_image_url = serializers.ImageField(source='qr_image', read_only=True)

    class Meta:
        model = Batch
        fields = ['id', 'course', 'course_name', 'branch', 'branch_name', 'name', 'batch_code',
                  'group_module', 'batch_attempt',
                  'start_date', 'end_date', 'max_students', 'enrolled_count',
                  'timing', 'is_active', 'created_at', 'group_module_display', 'batch_attempt_display', 'qr_image_url']


class BatchDetailSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True)
    enrolled_students = serializers.SerializerMethodField()
    assigned_faculty = serializers.SerializerMethodField()
    group_module_display = serializers.CharField(source="get_group_module_display", read_only=True)
    batch_attempt_display = serializers.CharField(source="get_batch_attempt_display", read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    qr_image_url = serializers.ImageField(source='qr_image', read_only=True)

    class Meta:
        model = Batch
        fields = '__all__'

    def get_enrolled_students(self, obj):
        qs = obj.batch_students.select_related('student').all()
        return BatchStudentReadSerializer(qs, many=True).data

    def get_assigned_faculty(self, obj):
        qs = obj.batch_faculty.select_related('faculty', 'subject').all()
        return BatchFacultyReadSerializer(qs, many=True).data


class BatchCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Batch
        fields = ['course', 'name', 'batch_code', 'group_module',
                  'batch_attempt', 'start_date', 'end_date',
                  'max_students', 'timing', 'is_active', 'organization', 'branch']

    def validate(self, data):
        start = data.get('start_date')
        end = data.get('end_date')
        if start and end and start >= end:
            raise serializers.ValidationError(
                {'end_date': 'End date must be after start date.'}
            )
        return data

    def validate_batch_code(self, value):
        if not value:
            return ''
        return value.upper().strip()

    def create(self, validated_data):
        if 'organization' not in validated_data or validated_data['organization'] is None:
            validated_data['organization'] = self.context['request'].user.organization
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'organization' not in validated_data or validated_data['organization'] is None:
            validated_data['organization'] = instance.organization or self.context['request'].user.organization
        return super().update(instance, validated_data)


# ── Batch-Student / Faculty link serializers ──────────────────────────────────

from students.models import Student


class BatchStudentReadSerializer(serializers.ModelSerializer):
    student_id = serializers.SerializerMethodField()
    admission_number = serializers.SerializerMethodField()
    student_name = serializers.SerializerMethodField()
    student_email = serializers.SerializerMethodField()

    class Meta:
        model = BatchStudent
        fields = ['id', 'student_id', 'admission_number', 'student_name', 'student_email', 'enrolled_at']

    def get_student_id(self, obj):
        return str(obj.student.id) if obj.student else None

    def get_admission_number(self, obj):
        return obj.student.admission_number if obj.student else None

    def get_student_name(self, obj):
        return obj.student.full_name if obj.student else None

    def get_student_email(self, obj):
        return obj.student.email if obj.student else None

class AssignStudentsSerializer(serializers.Serializer):
    student_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False
    )


from faculty.models import FacultyProfile


class BatchFacultyReadSerializer(serializers.ModelSerializer):
    faculty_id = serializers.SerializerMethodField()
    employee_id = serializers.SerializerMethodField()
    faculty_name = serializers.SerializerMethodField()
    subject_name = serializers.CharField(
        source='subject.name',
        read_only=True,
        default=None
    )

    class Meta:
        model = BatchFaculty
        fields = [
            'id',
            'faculty_id',
            'employee_id',
            'faculty_name',
            'subject',
            'subject_name',
            'assigned_at',
        ]

    def get_faculty_id(self, obj):
        return str(obj.faculty.id) if obj.faculty else None

    def get_employee_id(self, obj):
        return obj.faculty.employee_id if obj.faculty else None

    def get_faculty_name(self, obj):
        return obj.faculty.user.name if obj.faculty and obj.faculty.user else ''

class AssignFacultySerializer(serializers.Serializer):
    faculty_id = serializers.UUIDField()
    subject_id = serializers.UUIDField(required=False, allow_null=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Classroom Serializers
# ═══════════════════════════════════════════════════════════════════════════════

class ClassroomListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Classroom
        fields = ['id', 'name', 'capacity', 'is_active']


class ClassroomCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Classroom
        fields = ['name', 'capacity', 'is_active', 'organization']

    def create(self, validated_data):
        if 'organization' not in validated_data or validated_data['organization'] is None:
            validated_data['organization'] = self.context['request'].user.organization
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'organization' not in validated_data or validated_data['organization'] is None:
            validated_data['organization'] = instance.organization or self.context['request'].user.organization
        return super().update(instance, validated_data)


# ═══════════════════════════════════════════════════════════════════════════════
#  Timetable Slot Serializers (updated for E4)
# ═══════════════════════════════════════════════════════════════════════════════

class TimetableSlotListSerializer(serializers.ModelSerializer):
    batch_name = serializers.CharField(source='batch.name', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True, default=None)
    faculty_name = serializers.CharField(source='faculty.user.name', read_only=True, default=None)
    faculty_employee_id = serializers.CharField(source='faculty.employee_id',read_only=True,default=None)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True, default=None)
    day_label = serializers.SerializerMethodField()
    day_of_week_display = serializers.SerializerMethodField()
    session_type_display = serializers.CharField(source="get_session_type_display", read_only=True)
    course = serializers.UUIDField(source='batch.course.id', read_only=True, default=None)
    course_name = serializers.CharField(source='batch.course.name', read_only=True, default=None)
    course_code = serializers.CharField(source='batch.course.code', read_only=True, default=None)
    examiners_names = serializers.SerializerMethodField()
    paper_checkers_names = serializers.SerializerMethodField()
    chapters_names = serializers.SerializerMethodField()

    class Meta:
        model = TimetableSlot
        fields = ['id', 'batch', 'batch_name',
                  'course', 'course_name', 'course_code',
                  'subject', 'subject_name', 'faculty_employee_id',
                  'faculty', 'faculty_name', 'classroom', 'classroom_name',
                  'day_of_week', 'day_label', 'start_time', 'end_time',
                  'is_recurring', 'effective_from', 'effective_to',
                  'day_of_week_display',
                  # E4 fields
                  'session_type', 'session_type_display', 'session_name', 'slot_code',
                  'session_date', 'chapters', 'chapters_names',
                  'examiners', 'examiners_names',
                  'paper_checkers', 'paper_checkers_names',
                  'exam',
                  ]

    exam = serializers.UUIDField(source='exam.id', read_only=True, default=None)

    def get_chapters_names(self, obj):
        return [c.name for c in obj.chapters.all()]

    def get_examiners_names(self, obj):
        return [e.name for e in obj.examiners.all()]

    def get_paper_checkers_names(self, obj):
        return [pc.name for pc in obj.paper_checkers.all()]

    def get_day_label(self, obj):
        if obj.day_of_week is None:
            return None
        return dict(DAY_CHOICES).get(obj.day_of_week, '')

    def get_day_of_week_display(self, obj):
        if obj.day_of_week is None:
            return None
        return dict(DAY_CHOICES).get(obj.day_of_week, '')


class ExamDataSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    exam_type = serializers.CharField(max_length=20, default='offline')
    total_marks = serializers.IntegerField(required=True)
    pass_marks = serializers.IntegerField(required=True)
    duration_minutes = serializers.IntegerField(required=False)
    instructions = serializers.CharField(required=False, allow_blank=True)
    result_release_mode = serializers.CharField(max_length=20, default='instant')
    selected_papers = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        help_text='List of SubjectPaper UUIDs to link to the exam.'
    )


class TimetableSlotCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimetableSlot
        fields = [
            'batch', 'subject', 'faculty', 'classroom',
            'day_of_week', 'start_time', 'end_time',
            'is_recurring', 'effective_from', 'effective_to', 'organization',
            # E4 new fields
            'session_type', 'session_name', 'slot_code', 'session_date',
            'chapters', 'examiners', 'paper_checkers',
            'exam_data',
        ]

    exam_data = ExamDataSerializer(write_only=True, required=False, allow_null=True)

    def validate(self, data):  # noqa: C901  (long but intentionally complete)
        from batches.constants import FIXED_SLOTS, SESSION_DURATIONS
        from datetime import datetime, time as dt_time

        session_type = data.get('session_type', 'regular')

        if session_type in ['class_test', 'prelim']:
            if not data.get('exam_data'):
                raise serializers.ValidationError({'exam_data': f'exam_data is required for {session_type} session.'})
        elif session_type in ['regular', 'practice']:
            if data.get('exam_data'):
                raise serializers.ValidationError({'exam_data': f'exam_data must be blank for {session_type} session.'})

        def _require(field, label=None):
            label = label or field
            val = data.get(field)
            if val is None or val == '':
                raise serializers.ValidationError({field: f'{label} is required for {session_type} session.'})

        def _forbid(field, label=None):
            label = label or field
            val = data.get(field)
            if val is not None and val != '' and val != []:
                raise serializers.ValidationError({field: f'{label} must be blank for {session_type} session.'})

        def _add_minutes(t, minutes):
            dt = datetime.combine(datetime(2000, 1, 1), t) + timedelta(minutes=minutes)
            return dt.time()

        if session_type == 'regular':
            _require('slot_code')
            _require('faculty')
            _forbid('examiners')
            _forbid('paper_checkers')
            
            slot_code = data.get('slot_code')
            if slot_code in ['P5', 'P6']:
                _require('start_time')
                _require('end_time')
                if data.get('start_time') and data.get('end_time') and data['start_time'] >= data['end_time']:
                    raise serializers.ValidationError({'end_time': 'End time must be after start time.'})
                
                # They can provide either day_of_week or session_date.
                if data.get('session_date'):
                    data['day_of_week'] = data['session_date'].weekday()
                elif data.get('day_of_week') is None:
                    raise serializers.ValidationError({'day_of_week': 'day_of_week or session_date is required for P5/P6.'})
            else:
                _require('day_of_week')
                if slot_code and slot_code in FIXED_SLOTS:
                    data['start_time'], data['end_time'] = FIXED_SLOTS[slot_code]
                else:
                    raise serializers.ValidationError({'slot_code': f"Invalid slot_code '{slot_code}'. Choose P1–P6."})

        elif session_type == 'class_test':
            _forbid('slot_code')
            _require('session_date')
            _require('start_time')
            _require('chapters')
            _require('faculty')
            _require('examiners')
            _require('paper_checkers')
            # Auto-set end time
            start = data.get('start_time')
            if start:
                data['end_time'] = _add_minutes(start, SESSION_DURATIONS['class_test'])
            # Chapter cross-validation
            chapters = data.get('chapters', [])
            subject = data.get('subject')
            if chapters:
                for chapter in chapters:
                    if subject and chapter.subject_id != subject.pk:
                        raise serializers.ValidationError(
                            {'chapters': 'All chapters must belong to the selected subject.'}
                        )


        elif session_type == 'prelim':
            _forbid('slot_code')
            _require('session_date')
            _require('start_time')
            _require('end_time')
            _require('chapters')
            _require('faculty')
            _require('examiners')
            _require('paper_checkers')
            start = data.get('start_time')
            end = data.get('end_time')
            if start and end and start >= end:
                raise serializers.ValidationError({'end_time': 'End time must be after start time.'})

        elif session_type == 'practice':
            _forbid('slot_code')
            _require('session_date')
            _require('start_time')
            _require('faculty')
            _require('examiners')
            _forbid('paper_checkers')
            start = data.get('start_time')
            if start:
                data['end_time'] = _add_minutes(start, SESSION_DURATIONS['practice'])

        elif session_type == 'custom':
            _forbid('slot_code')
            _require('session_date')
            _require('start_time')
            _require('end_time')
            start = data.get('start_time')
            end = data.get('end_time')
            if start and end and start >= end:
                raise serializers.ValidationError({'end_time': 'End time must be after start time.'})

        return data

    def _handle_exam(self, slot, exam_data):
        if not exam_data:
            return
            
        from datetime import datetime, date, timedelta
        start = slot.start_time
        end = slot.end_time
        duration = exam_data.get('duration_minutes')
        if not duration and start and end:
            s = datetime.combine(date.today(), start)
            e = datetime.combine(date.today(), end)
            if e < s:
                e += timedelta(days=1)
            duration = int((e - s).total_seconds() / 60)
            
        title = exam_data.get('title')
        if not title:
            subject_name = slot.subject.name if slot.subject else 'Custom'
            title = f"{subject_name} - {slot.get_session_type_display()} ({slot.session_date})"
            
        if not slot.exam:
            from exams.models import Exam
            
            branch_id = slot.batch.branch_id if slot.batch and slot.batch.branch_id else None
            if not branch_id:
                request = self.context.get('request')
                if request and hasattr(request, 'user') and request.user:
                    branch_id = getattr(request.user, 'branch_id', None)
                    if not branch_id and hasattr(request.user, 'profile'):
                        branch_id = getattr(request.user.profile, 'branch_id', None)

            exam = Exam.objects.create(
                branch_id=branch_id,
                batch=slot.batch,
                subject=slot.subject,
                faculty=slot.faculty,
                title=title,
                exam_type=exam_data.get('exam_type', 'offline'),
                total_marks=exam_data.get('total_marks', 100),
                pass_marks=exam_data.get('pass_marks', 35),
                duration_minutes=duration or 60,
                scheduled_date=slot.session_date,
                start_time=slot.start_time,
                end_time=slot.end_time,
                instructions=exam_data.get('instructions', ''),
                result_release_mode=exam_data.get('result_release_mode', 'instant'),
                created_by=slot.created_by,
            )
            slot.exam = exam
            slot.save(update_fields=['exam'])

            # Sync paper checkers from slot to exam
            if slot.paper_checkers.exists():
                exam.paper_checkers.set(slot.paper_checkers.all())

            # Sync selected_papers from exam_data to exam
            selected_paper_ids = exam_data.get('selected_papers', [])
            if selected_paper_ids:
                from exams.models import SubjectPaper
                papers = SubjectPaper.objects.filter(id__in=selected_paper_ids)
                exam.selected_papers.set(papers)
        else:
            exam = slot.exam
            exam.title = title
            exam.faculty = slot.faculty
            exam.exam_type = exam_data.get('exam_type', exam.exam_type)
            exam.total_marks = exam_data.get('total_marks', exam.total_marks)
            exam.pass_marks = exam_data.get('pass_marks', exam.pass_marks)
            exam.duration_minutes = duration or exam.duration_minutes
            exam.instructions = exam_data.get('instructions', exam.instructions)
            exam.result_release_mode = exam_data.get('result_release_mode', exam.result_release_mode)
            exam.scheduled_date = slot.session_date
            exam.start_time = slot.start_time
            exam.end_time = slot.end_time
            exam.save()
            
            # Sync paper checkers from slot to exam
            exam.paper_checkers.set(slot.paper_checkers.all())

            # Sync selected_papers from exam_data to exam (only if provided)
            selected_paper_ids = exam_data.get('selected_papers')
            if selected_paper_ids is not None:
                from exams.models import SubjectPaper
                papers = SubjectPaper.objects.filter(id__in=selected_paper_ids)
                exam.selected_papers.set(papers)

    def create(self, validated_data):
        exam_data = validated_data.pop('exam_data', None)
        if 'organization' not in validated_data or validated_data['organization'] is None:
            validated_data['organization'] = self.context['request'].user.organization
        slot = super().create(validated_data)
        self._handle_exam(slot, exam_data)
        return slot

    def update(self, instance, validated_data):
        exam_data = validated_data.pop('exam_data', None)
        if 'organization' not in validated_data or validated_data['organization'] is None:
            validated_data['organization'] = instance.organization or self.context['request'].user.organization
        slot = super().update(instance, validated_data)
        self._handle_exam(slot, exam_data)
        return slot


# ── Faculty / Student personal timetable views ────────────────────────────────

class FacultyTimetableSerializer(serializers.ModelSerializer):
    batch_name = serializers.CharField(source='batch.name', read_only=True)
    batch_code = serializers.CharField(source='batch.batch_code', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True, default=None)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True, default=None)
    day_label = serializers.SerializerMethodField()
    day_of_week_display = serializers.SerializerMethodField()


    class Meta:
        model = TimetableSlot
        fields = ['id', 'batch', 'batch_name', 'batch_code',
                  'subject', 'subject_name', 'classroom', 'classroom_name',
                  'day_of_week', 'day_label', 'start_time', 'end_time',
                  'day_of_week_display',
                  'session_type', 'session_date', 'slot_code']

    def get_day_label(self, obj):
        if obj.day_of_week is None:
            return None
        return dict(DAY_CHOICES).get(obj.day_of_week, '')

    def get_day_of_week_display(self, obj):
        if obj.day_of_week is None:
            return None
        return dict(DAY_CHOICES).get(obj.day_of_week, '')


class StudentTimetableSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source='subject.name', read_only=True, default=None)
    faculty_name = serializers.CharField(source='faculty.user.name', read_only=True, default=None)
    faculty_employee_id = serializers.CharField(source='faculty.employee_id',read_only=True,default=None)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True, default=None)
    day_label = serializers.SerializerMethodField()
    day_of_week_display = serializers.SerializerMethodField()


    class Meta:
        model = TimetableSlot
        fields = ['id', 'subject', 'subject_name', 'faculty', 'faculty_name',
                  'classroom', 'classroom_name', 'faculty_employee_id',
                  'day_of_week', 'day_label', 'start_time', 'end_time',
                  'day_of_week_display',
                  'session_type', 'session_date', 'slot_code']

    def get_day_label(self, obj):
        if obj.day_of_week is None:
            return None
        return dict(DAY_CHOICES).get(obj.day_of_week, '')

    def get_day_of_week_display(self, obj):
        if obj.day_of_week is None:
            return None
        return dict(DAY_CHOICES).get(obj.day_of_week, '')
