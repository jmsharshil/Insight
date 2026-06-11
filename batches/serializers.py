from datetime import datetime, timedelta

from rest_framework import serializers
from .models import (
    Course, Subject, Batch, BatchStudent, BatchFaculty,
    Classroom, TimetableSlot, DAY_CHOICES, SESSION_CHOICES,
    CourseLevel, Chapter, TimetableExamType,
    SESSION_TYPE_CHOICES, SLOT_CODE_CHOICES,
)
from django.conf import settings


# ═══════════════════════════════════════════════════════════════════════════════
#  Course Serializers
# ═══════════════════════════════════════════════════════════════════════════════

# E2 — forward declare so CourseDetailSerializer can reference it
class CourseLevelSerializer(serializers.ModelSerializer):
    """Read/write serializer for CourseLevel (E2)."""

    class Meta:
        model = CourseLevel
        fields = ['id', 'course', 'name', 'order', 'description', 'is_active']
        read_only_fields = ['id', 'course']

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
    course_type_display = serializers.CharField(source="get_course_type_display", read_only=True)

    class Meta:
        model = Course
        fields = ['id', 'name', 'code', 'course_type', 'duration_months',
                  'fee_amount', 'is_active', 'subject_count', 'created_at', 'course_type_display']


class CourseDetailSerializer(serializers.ModelSerializer):
    subjects = serializers.SerializerMethodField()
    levels   = serializers.SerializerMethodField()
    course_type_display = serializers.CharField(source="get_course_type_display", read_only=True)

    class Meta:
        model = Course
        fields = '__all__'

    def get_subjects(self, obj):
        qs = obj.subjects.filter(is_active=True)
        return SubjectListSerializer(qs, many=True).data

    def get_levels(self, obj):
        qs = obj.levels.filter(is_active=True)
        return CourseLevelSerializer(qs, many=True).data


class CourseCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ['name', 'code', 'course_type', 'duration_months',
                  'fee_amount', 'description', 'is_active', 'organization']

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
        fields = ['id', 'subject', 'name', 'order', 'description', 'is_active']
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

    class Meta:
        model = Subject
        fields = ['id', 'level', 'level_name', 'course_name', 'name', 'code',
                  'total_hours', 'is_active', 'chapters']

    def get_chapters(self, obj):
        qs = obj.chapters.filter(is_active=True)
        return ChapterSerializer(qs, many=True).data


class SubjectCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ['level', 'name', 'code', 'total_hours', 'is_active', 'organization']

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
#  Batch Serializers
# ═══════════════════════════════════════════════════════════════════════════════

class BatchListSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True)
    enrolled_count = serializers.IntegerField(read_only=True, default=0)
    group_module_display = serializers.CharField(source="get_group_module_display", read_only=True)
    batch_attempt_display = serializers.CharField(source="get_batch_attempt_display", read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)

    class Meta:
        model = Batch
        fields = ['id', 'course', 'course_name', 'branch', 'branch_name', 'name', 'batch_code',
                  'group_module', 'batch_attempt', 'location',
                  'start_date', 'end_date', 'max_students', 'enrolled_count',
                  'timing', 'is_active', 'created_at', 'group_module_display', 'batch_attempt_display']


class BatchDetailSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True)
    enrolled_students = serializers.SerializerMethodField()
    assigned_faculty = serializers.SerializerMethodField()
    group_module_display = serializers.CharField(source="get_group_module_display", read_only=True)
    batch_attempt_display = serializers.CharField(source="get_batch_attempt_display", read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)

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
                  'batch_attempt', 'location', 'start_date', 'end_date',
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
#  TimetableExamType Serializer (E4)
# ═══════════════════════════════════════════════════════════════════════════════

class TimetableExamTypeSerializer(serializers.ModelSerializer):
    """Serializer for TimetableExamType CRUD (E4)."""

    class Meta:
        model = TimetableExamType
        fields = ['id', 'organization', 'name', 'description', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']

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
    session_display = serializers.CharField(source="get_session_display", read_only=True)
    session_type_display = serializers.CharField(source="get_session_type_display", read_only=True)
    course = serializers.UUIDField(source='batch.course.id', read_only=True, default=None)
    course_name = serializers.CharField(source='batch.course.name', read_only=True, default=None)
    course_code = serializers.CharField(source='batch.course.code', read_only=True, default=None)
    examiner_name = serializers.CharField(source='examiner.user.name', read_only=True, default=None)
    paper_checker_name = serializers.CharField(source='paper_checker.user.name', read_only=True, default=None)
    chapter_name = serializers.CharField(source='chapter.name', read_only=True, default=None)
    exam_type_name = serializers.CharField(source='timetable_exam_type.name', read_only=True, default=None)

    class Meta:
        model = TimetableSlot
        fields = ['id', 'batch', 'batch_name',
                  'course', 'course_name', 'course_code',
                  'subject', 'subject_name', 'faculty_employee_id',
                  'faculty', 'faculty_name', 'classroom', 'classroom_name',
                  'day_of_week', 'day_label', 'start_time', 'end_time',
                  'session', 'is_recurring', 'effective_from', 'effective_to',
                  'day_of_week_display', 'session_display',
                  # E4 fields
                  'session_type', 'session_type_display', 'slot_code',
                  'session_date', 'chapter', 'chapter_name',
                  'examiner', 'examiner_name',
                  'paper_checker', 'paper_checker_name',
                  'timetable_exam_type', 'exam_type_name',
                  ]

    def get_day_label(self, obj):
        if obj.day_of_week is None:
            return None
        return dict(DAY_CHOICES).get(obj.day_of_week, '')

    def get_day_of_week_display(self, obj):
        if obj.day_of_week is None:
            return None
        return dict(DAY_CHOICES).get(obj.day_of_week, '')


class TimetableSlotCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimetableSlot
        fields = [
            'batch', 'subject', 'faculty', 'classroom',
            'day_of_week', 'start_time', 'end_time', 'session',
            'is_recurring', 'effective_from', 'effective_to', 'organization',
            # E4 new fields
            'session_type', 'slot_code', 'session_date',
            'chapter', 'examiner', 'paper_checker', 'timetable_exam_type',
        ]

    def validate(self, data):  # noqa: C901  (long but intentionally complete)
        from batches.constants import FIXED_SLOTS, SESSION_DURATIONS
        from datetime import datetime, time as dt_time

        session_type = data.get('session_type', 'regular')

        def _require(field, label=None):
            label = label or field
            if not data.get(field):
                raise serializers.ValidationError({field: f'{label} is required for {session_type} session.'})

        def _forbid(field, label=None):
            label = label or field
            if data.get(field):
                raise serializers.ValidationError({field: f'{label} must be blank for {session_type} session.'})

        def _add_minutes(t, minutes):
            dt = datetime.combine(datetime(2000, 1, 1), t) + timedelta(minutes=minutes)
            return dt.time()

        if session_type == 'regular':
            _require('slot_code')
            _require('day_of_week')
            _require('faculty')
            _forbid('examiner')
            _forbid('paper_checker')
            _forbid('timetable_exam_type')
            # Auto-fill times from FIXED_SLOTS
            slot_code = data.get('slot_code')
            if slot_code and slot_code in FIXED_SLOTS:
                data['start_time'], data['end_time'] = FIXED_SLOTS[slot_code]
            else:
                raise serializers.ValidationError({'slot_code': f"Invalid slot_code '{slot_code}'. Choose P1–P4."})

        elif session_type == 'class_test':
            _forbid('slot_code')
            _require('session_date')
            _require('start_time')
            _require('chapter')
            _require('faculty')
            _require('examiner')
            _require('paper_checker')
            _require('timetable_exam_type')
            # Auto-set end time
            start = data.get('start_time')
            if start:
                data['end_time'] = _add_minutes(start, SESSION_DURATIONS['class_test'])
            # Chapter cross-validation
            chapter = data.get('chapter')
            subject = data.get('subject')
            if chapter:
                if subject and chapter.subject_id != subject.pk:
                    raise serializers.ValidationError(
                        {'chapter': 'Chapter must belong to the selected subject.'}
                    )
                if chapter.order > 2:
                    raise serializers.ValidationError(
                        {'chapter': 'class_test allows only chapters with order ≤ 2.'}
                    )

        elif session_type == 'prelim':
            _forbid('slot_code')
            _require('session_date')
            _require('start_time')
            _require('end_time')
            _forbid('faculty')
            _require('examiner')
            _forbid('paper_checker')
            _require('timetable_exam_type')
            start = data.get('start_time')
            end = data.get('end_time')
            if start and end and start >= end:
                raise serializers.ValidationError({'end_time': 'End time must be after start time.'})

        elif session_type == 'practice':
            _forbid('slot_code')
            _require('session_date')
            _require('start_time')
            _require('faculty')
            _forbid('examiner')
            _forbid('paper_checker')
            _forbid('timetable_exam_type')
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

    def create(self, validated_data):
        if 'organization' not in validated_data or validated_data['organization'] is None:
            validated_data['organization'] = self.context['request'].user.organization
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'organization' not in validated_data or validated_data['organization'] is None:
            validated_data['organization'] = instance.organization or self.context['request'].user.organization
        return super().update(instance, validated_data)


# ── Faculty / Student personal timetable views ────────────────────────────────

class FacultyTimetableSerializer(serializers.ModelSerializer):
    batch_name = serializers.CharField(source='batch.name', read_only=True)
    batch_code = serializers.CharField(source='batch.batch_code', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True, default=None)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True, default=None)
    day_label = serializers.SerializerMethodField()
    day_of_week_display = serializers.SerializerMethodField()
    session_display = serializers.CharField(source="get_session_display", read_only=True)

    class Meta:
        model = TimetableSlot
        fields = ['id', 'batch', 'batch_name', 'batch_code',
                  'subject', 'subject_name', 'classroom', 'classroom_name',
                  'day_of_week', 'day_label', 'start_time', 'end_time', 'session',
                  'day_of_week_display', 'session_display',
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
    session_display = serializers.CharField(source="get_session_display", read_only=True)

    class Meta:
        model = TimetableSlot
        fields = ['id', 'subject', 'subject_name', 'faculty', 'faculty_name',
                  'classroom', 'classroom_name', 'faculty_employee_id',
                  'day_of_week', 'day_label', 'start_time', 'end_time', 'session',
                  'day_of_week_display', 'session_display',
                  'session_type', 'session_date', 'slot_code']

    def get_day_label(self, obj):
        if obj.day_of_week is None:
            return None
        return dict(DAY_CHOICES).get(obj.day_of_week, '')

    def get_day_of_week_display(self, obj):
        if obj.day_of_week is None:
            return None
        return dict(DAY_CHOICES).get(obj.day_of_week, '')
