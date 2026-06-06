from rest_framework import serializers
from .models import (
    Course, Subject, Batch, BatchStudent, BatchFaculty,
    Classroom, TimetableSlot, DAY_CHOICES, SESSION_CHOICES,
)
from django.conf import settings


# ═══════════════════════════════════════════════════════════════════════════════
#  Course Serializers
# ═══════════════════════════════════════════════════════════════════════════════

class CourseListSerializer(serializers.ModelSerializer):
    subject_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Course
        fields = ['id', 'name', 'code', 'course_type', 'duration_months',
                  'fee_amount', 'is_active', 'subject_count', 'created_at']


class CourseDetailSerializer(serializers.ModelSerializer):
    subjects = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = '__all__'

    def get_subjects(self, obj):
        qs = obj.subjects.filter(is_active=True)
        return SubjectListSerializer(qs, many=True).data


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

class SubjectListSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True)

    class Meta:
        model = Subject
        fields = ['id', 'course', 'course_name', 'name', 'code',
                  'total_hours', 'is_active']


class SubjectCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ['course', 'name', 'code', 'total_hours', 'is_active', 'organization']

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

    class Meta:
        model = Batch
        fields = ['id', 'course', 'course_name', 'name', 'batch_code',
                  'group_module', 'batch_attempt', 'location',
                  'start_date', 'end_date', 'max_students', 'enrolled_count',
                  'timing', 'is_active', 'created_at']


class BatchDetailSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True)
    enrolled_students = serializers.SerializerMethodField()
    assigned_faculty = serializers.SerializerMethodField()

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
                  'max_students', 'timing', 'is_active', 'organization']

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

class BatchStudentReadSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.name', read_only=True)
    student_email = serializers.CharField(source='student.email', read_only=True)

    class Meta:
        model = BatchStudent
        fields = ['id', 'student', 'student_name', 'student_email', 'enrolled_at']


class AssignStudentsSerializer(serializers.Serializer):
    student_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False
    )


class BatchFacultyReadSerializer(serializers.ModelSerializer):
    faculty_name = serializers.CharField(source='faculty.name', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True, default=None)

    class Meta:
        model = BatchFaculty
        fields = ['id', 'faculty', 'faculty_name', 'subject', 'subject_name', 'assigned_at']


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
#  Timetable Slot Serializers
# ═══════════════════════════════════════════════════════════════════════════════

class TimetableSlotListSerializer(serializers.ModelSerializer):
    batch_name = serializers.CharField(source='batch.name', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True, default=None)
    faculty_name = serializers.CharField(source='faculty.name', read_only=True, default=None)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True, default=None)
    day_label = serializers.SerializerMethodField()

    class Meta:
        model = TimetableSlot
        fields = ['id', 'batch', 'batch_name', 'subject', 'subject_name',
                  'faculty', 'faculty_name', 'classroom', 'classroom_name',
                  'day_of_week', 'day_label', 'start_time', 'end_time',
                  'session', 'is_recurring', 'effective_from', 'effective_to']

    def get_day_label(self, obj):
        return dict(DAY_CHOICES).get(obj.day_of_week, '')


class TimetableSlotCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimetableSlot
        fields = ['batch', 'subject', 'faculty', 'classroom',
                  'day_of_week', 'start_time', 'end_time', 'session',
                  'is_recurring', 'effective_from', 'effective_to', 'organization']

    def validate(self, data):
        start = data.get('start_time')
        end = data.get('end_time')
        if start and end and start >= end:
            raise serializers.ValidationError(
                {'end_time': 'End time must be after start time.'}
            )
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

    class Meta:
        model = TimetableSlot
        fields = ['id', 'batch', 'batch_name', 'batch_code',
                  'subject', 'subject_name', 'classroom', 'classroom_name',
                  'day_of_week', 'day_label', 'start_time', 'end_time', 'session']

    def get_day_label(self, obj):
        return dict(DAY_CHOICES).get(obj.day_of_week, '')


class StudentTimetableSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source='subject.name', read_only=True, default=None)
    faculty_name = serializers.CharField(source='faculty.name', read_only=True, default=None)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True, default=None)
    day_label = serializers.SerializerMethodField()

    class Meta:
        model = TimetableSlot
        fields = ['id', 'subject', 'subject_name', 'faculty', 'faculty_name',
                  'classroom', 'classroom_name',
                  'day_of_week', 'day_label', 'start_time', 'end_time', 'session']

    def get_day_label(self, obj):
        return dict(DAY_CHOICES).get(obj.day_of_week, '')
