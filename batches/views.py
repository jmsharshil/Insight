import logging
from core.pagination import paginate_queryset

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from core.utils import apply_filters

from django.conf import settings
from django.db import models

from .models import (
    Course, Subject, Batch, BatchStudent, BatchFaculty,
    Classroom, TimetableSlot,
)
from .serializers import (
    CourseListSerializer, CourseDetailSerializer, CourseCreateUpdateSerializer,
    SubjectListSerializer, SubjectCreateUpdateSerializer,
    BatchListSerializer, BatchDetailSerializer, BatchCreateUpdateSerializer,
    BatchStudentReadSerializer, AssignStudentsSerializer,
    BatchFacultyReadSerializer, AssignFacultySerializer,
    ClassroomListSerializer, ClassroomCreateUpdateSerializer,
    TimetableSlotListSerializer, TimetableSlotCreateUpdateSerializer,
    FacultyTimetableSerializer, StudentTimetableSerializer,
)
from .validators import check_faculty_clash, check_classroom_clash

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  Course Views
# ═══════════════════════════════════════════════════════════════════════════════

class CourseListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['course_type', 'is_active']
    search_fields = ['name', 'code']
    ordering_fields = '__all__'

    def get(self, request):
        # Filter by user's organization
        queryset = Course.objects.prefetch_related('subjects', 'batches').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(organization=request.user.organization)

        course_type = request.GET.get('course_type')
        is_active = request.GET.get('is_active')

        if course_type:
            queryset = queryset.filter(course_type=course_type)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        queryset = queryset.annotate(
            subject_count=models.Count('subjects')
        )

        queryset = apply_filters(self, request, queryset)

        return paginate_queryset(queryset, request, CourseListSerializer)

    def post(self, request):
        serializer = CourseCreateUpdateSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        course = serializer.save()
        return Response(
            {'success': True, 'message': 'Course created successfully.',
             'data': CourseDetailSerializer(course).data},
            status=status.HTTP_201_CREATED,
        )


class CourseDetailView(APIView):

    def _get_course(self, pk):
        try:
            qs = Course.objects.all()
            if getattr(self.request.user, 'organization', None):
                qs = qs.filter(organization=self.request.user.organization)
            return qs.get(pk=pk)
        except Course.DoesNotExist:
            return None

    def get(self, request, pk):
        course = self._get_course(pk)
        if course is None:
            return Response({'success': False, 'message': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': CourseDetailSerializer(course).data})

    def patch(self, request, pk):
        course = self._get_course(pk)
        if course is None:
            return Response({'success': False, 'message': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = CourseCreateUpdateSerializer(course, data=request.data, partial=True, context={'request': request})
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response({'success': True, 'message': 'Course updated.', 'data': CourseDetailSerializer(course).data})

    def delete(self, request, pk):
        course = self._get_course(pk)
        if course is None:
            return Response({'success': False, 'message': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)
        course.delete()
        return Response({'success': True, 'message': 'Course deleted.'})


# ═══════════════════════════════════════════════════════════════════════════════
#  Subject Views
# ═══════════════════════════════════════════════════════════════════════════════

class SubjectListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['course', 'is_active']
    search_fields = ['name', 'code']
    ordering_fields = '__all__'

    def get(self, request):
        queryset = Subject.objects.select_related('course').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(organization=request.user.organization)

        course_id = request.GET.get('course_id')
        if course_id:
            queryset = queryset.filter(course_id=course_id)

        is_active = request.GET.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        queryset = apply_filters(self, request, queryset)

        return paginate_queryset(queryset, request, SubjectListSerializer)

    def post(self, request):
        serializer = SubjectCreateUpdateSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        subject = serializer.save()
        return Response(
            {'success': True, 'message': 'Subject created successfully.',
             'data': SubjectListSerializer(subject).data},
            status=status.HTTP_201_CREATED,
        )


class SubjectDetailView(APIView):

    def _get_subject(self, pk):
        try:
            qs = Subject.objects.all()
            if getattr(self.request.user, 'organization', None):
                qs = qs.filter(organization=self.request.user.organization)
            return qs.get(pk=pk)
        except Subject.DoesNotExist:
            return None

    def get(self, request, pk):
        subject = self._get_subject(pk)
        if subject is None:
            return Response({'success': False, 'message': 'Subject not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': SubjectListSerializer(subject).data})

    def patch(self, request, pk):
        subject = self._get_subject(pk)
        if subject is None:
            return Response({'success': False, 'message': 'Subject not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = SubjectCreateUpdateSerializer(subject, data=request.data, partial=True, context={'request': request})
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response({'success': True, 'message': 'Subject updated.', 'data': SubjectListSerializer(subject).data})

    def delete(self, request, pk):
        subject = self._get_subject(pk)
        if subject is None:
            return Response({'success': False, 'message': 'Subject not found.'}, status=status.HTTP_404_NOT_FOUND)
        subject.delete()
        return Response({'success': True, 'message': 'Subject deleted.'})


# ═══════════════════════════════════════════════════════════════════════════════
#  Batch Views
# ═══════════════════════════════════════════════════════════════════════════════

class BatchListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['course', 'is_active']
    search_fields = ['name', 'batch_code']
    ordering_fields = '__all__'

    def get(self, request):
        queryset = Batch.objects.select_related('course').prefetch_related('batch_students').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(organization=request.user.organization)

        course_id = request.GET.get('course_id')
        is_active = request.GET.get('is_active')

        if course_id:
            queryset = queryset.filter(course_id=course_id)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        # Annotate enrolled student count
        queryset = queryset.annotate(
            enrolled_count=models.Count('batch_students')
        )

        queryset = apply_filters(self, request, queryset)

        return paginate_queryset(queryset, request, BatchListSerializer)

    def post(self, request):
        serializer = BatchCreateUpdateSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        batch = serializer.save()
        return Response(
            {'success': True, 'message': 'Batch created successfully.',
             'data': BatchDetailSerializer(batch).data},
            status=status.HTTP_201_CREATED,
        )


class BatchDetailView(APIView):

    def _get_batch(self, pk):
        try:
            qs = Batch.objects.select_related('course').all()
            if getattr(self.request.user, 'organization', None):
                qs = qs.filter(organization=self.request.user.organization)
            return qs.get(pk=pk)
        except Batch.DoesNotExist:
            return None

    def get(self, request, pk):
        batch = self._get_batch(pk)
        if batch is None:
            return Response({'success': False, 'message': 'Batch not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': BatchDetailSerializer(batch).data})

    def patch(self, request, pk):
        batch = self._get_batch(pk)
        if batch is None:
            return Response({'success': False, 'message': 'Batch not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = BatchCreateUpdateSerializer(batch, data=request.data, partial=True, context={'request': request})
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response({'success': True, 'message': 'Batch updated.', 'data': BatchDetailSerializer(batch).data})

    def delete(self, request, pk):
        batch = self._get_batch(pk)
        if batch is None:
            return Response({'success': False, 'message': 'Batch not found.'}, status=status.HTTP_404_NOT_FOUND)
        batch.delete()
        return Response({'success': True, 'message': 'Batch deleted.'})


# ── Batch Student Assignment ──────────────────────────────────────────────────

from students.models import Student

class BatchAssignStudentsView(APIView):

    def post(self, request, pk):
        try:
            qs = Batch.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(organization=request.user.organization)

            batch = qs.get(pk=pk)

        except Batch.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'Batch not found.'
                },
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = AssignStudentsSerializer(
            data=request.data,
            context={'request': request}
        )

        if not serializer.is_valid():
            return Response(
                {
                    'success': False,
                    'errors': serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        student_ids = serializer.validated_data['student_ids']

        # Fetch Student records
        students = Student.objects.select_related('user').filter(
            id__in=student_ids,
            is_active=True
        )

        found_student_ids = {
            str(student.id)
            for student in students
        }

        requested_student_ids = {
            str(student_id)
            for student_id in student_ids
        }

        invalid_ids = requested_student_ids - found_student_ids

        if invalid_ids:
            return Response(
                {
                    'success': False,
                    'message': f'Invalid student IDs: {list(invalid_ids)}'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        student_ids_list = [
            student.id
            for student in students
        ]

        current_count = BatchStudent.objects.filter(batch=batch).count()
        already_enrolled = set(
            BatchStudent.objects.filter(batch=batch, student_id__in=student_ids_list)
            .values_list('student_id', flat=True)
        )
        to_enroll = [
            student_id
            for student_id in student_ids_list
            if student_id not in already_enrolled
        ]

        if current_count + len(to_enroll) > batch.max_students:
            remaining = batch.max_students - current_count
            return Response(
                {
                    'success': False,
                    'message': f'Batch capacity exceeded. Only {remaining} seats remaining.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        created = []

        for student_id in to_enroll:
            enrollment = BatchStudent.objects.create(
                batch=batch,
                student_id=student_id
            )
            Student.objects.filter(
                id=student_id
            ).update(
                batch=batch,
                current_batch_name=batch.name 
            )
            created.append(enrollment)

        return Response(
            {
                'success': True,
                'message': (
                    f'{len(created)} student(s) enrolled. '
                    f'{len(already_enrolled)} already enrolled.'
                ),
                'data': BatchStudentReadSerializer(
                    created,
                    many=True
                ).data if created else []
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

class BatchRemoveStudentView(APIView):

    def post(self, request, pk, student_id):
        try:
            student = Student.objects.select_related('user').get(
                id=student_id
            )
        except Student.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'Student not found.'
                },
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            qs = BatchStudent.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(batch__organization=request.user.organization)

            enrollment = qs.get(batch_id=pk, student_id=student.id)

        except BatchStudent.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'Student not enrolled in this batch.'
                },
                status=status.HTTP_404_NOT_FOUND
            )

        enrollment.delete()
        
         # Clear student's current batch
        student.batch = None
        student.current_batch_name = ''
        student.save(
            update_fields=[
                'batch',
                'current_batch_name',
                'updated_at'
            ]
        )

        return Response(
            {
                'success': True,
                'message': 'Student removed from batch.'
            }
        )

# ── Batch Faculty Assignment ──────────────────────────────────────────────────
from faculty.models import FacultyProfile

class BatchAssignFacultyView(APIView):

    def post(self, request, pk):
        try:
            qs = Batch.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(organization=request.user.organization)
            batch = qs.get(pk=pk)
        except Batch.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'Batch not found.'
                },
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = AssignFacultySerializer(
            data=request.data,
            context={'request': request}
        )

        if not serializer.is_valid():
            return Response(
                {
                    'success': False,
                    'errors': serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        faculty_id = serializer.validated_data['faculty_id']
        subject_id = serializer.validated_data.get('subject_id')

        try:
            faculty = FacultyProfile.objects.select_related('user').get(
                id=faculty_id,
                is_active=True
            )

        except FacultyProfile.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'Invalid faculty ID.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        bf, created = BatchFaculty.objects.get_or_create(
            batch=batch,
            faculty_id=faculty.id,
            subject_id=subject_id,
        )

        if not created:
            return Response(
                {
                    'success': False,
                    'message': 'Faculty already assigned to this batch/subject.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                'success': True,
                'message': 'Faculty assigned successfully.',
                'data': BatchFacultyReadSerializer(bf).data,
            },
            status=status.HTTP_201_CREATED
        )

class BatchRemoveFacultyView(APIView):

    def post(self, request, pk, faculty_id):
        subject_id = request.data.get('subject_id')

        try:
            faculty = FacultyProfile.objects.get(
                id=faculty_id
            )

        except FacultyProfile.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'Faculty not found.'
                },
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            qs = BatchFaculty.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(batch__organization=request.user.organization)
            if subject_id:
                qs = qs.filter(subject=subject_id)
            assignment = qs.get(batch_id=pk, faculty_id=faculty.id)
        except BatchFaculty.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'Faculty assignment not found.'
                },
                status=status.HTTP_404_NOT_FOUND
            )

        assignment.delete()

        return Response(
            {
                'success': True,
                'message': 'Faculty removed from batch.'
            }
        )

# ═══════════════════════════════════════════════════════════════════════════════
#  Classroom Views
# ═══════════════════════════════════════════════════════════════════════════════

class ClassroomListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'building', 'room_number']
    ordering_fields = '__all__'

    def get(self, request):
        queryset = Classroom.objects.all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(organization=request.user.organization)
        is_active = request.GET.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
            
        queryset = apply_filters(self, request, queryset)
        
        serializer = ClassroomListSerializer(queryset, many=True)
        return Response({'success': True, 'count': queryset.count(), 'data': serializer.data})

    def post(self, request):
        serializer = ClassroomCreateUpdateSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        classroom = serializer.save()
        return Response(
            {'success': True, 'message': 'Classroom created.', 'data': ClassroomListSerializer(classroom).data},
            status=status.HTTP_201_CREATED,
        )


class ClassroomDetailView(APIView):

    def _get_classroom(self, pk):
        try:
            qs = Classroom.objects.all()
            if getattr(self.request.user, 'organization', None):
                qs = qs.filter(organization=self.request.user.organization)
            return qs.get(pk=pk)
        except Classroom.DoesNotExist:
            return None

    def get(self, request, pk):
        classroom = self._get_classroom(pk)
        if classroom is None:
            return Response({'success': False, 'message': 'Classroom not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': ClassroomListSerializer(classroom).data})

    def patch(self, request, pk):
        classroom = self._get_classroom(pk)
        if classroom is None:
            return Response({'success': False, 'message': 'Classroom not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ClassroomCreateUpdateSerializer(classroom, data=request.data, partial=True, context={'request': request})
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response({'success': True, 'message': 'Classroom updated.', 'data': ClassroomListSerializer(classroom).data})

    def delete(self, request, pk):
        classroom = self._get_classroom(pk)
        if classroom is None:
            return Response({'success': False, 'message': 'Classroom not found.'}, status=status.HTTP_404_NOT_FOUND)
        classroom.delete()
        return Response({'success': True, 'message': 'Classroom deleted.'})


# ═══════════════════════════════════════════════════════════════════════════════
#  Timetable Views
# ═══════════════════════════════════════════════════════════════════════════════

class TimetableListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['batch', 'day_of_week', 'faculty', 'subject', 'batch__course']
    search_fields = []
    ordering_fields = '__all__'

    def get(self, request):
        queryset = TimetableSlot.objects.select_related(
            'batch', 'batch__course', 'subject', 'faculty', 'classroom'
        ).all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(organization=request.user.organization)

        batch_id = request.GET.get('batch_id')
        day_of_week = request.GET.get('day_of_week')
        faculty_id = request.GET.get('faculty_id')
        subject_id = request.GET.get('subject_id')
        course_id = request.GET.get('course_id')

        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)
        if day_of_week is not None:
            queryset = queryset.filter(day_of_week=int(day_of_week))
        if faculty_id:
            queryset = queryset.filter(faculty_id=faculty_id)
        if subject_id:
            queryset = queryset.filter(subject_id=subject_id)
        if course_id:
            queryset = queryset.filter(batch__course_id=course_id)

        queryset = apply_filters(self, request, queryset)

        serializer = TimetableSlotListSerializer(queryset, many=True)
        return Response({'success': True, 'count': queryset.count(), 'data': serializer.data})

    def post(self, request):
        serializer = TimetableSlotCreateUpdateSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data

        # Clash detection — faculty
        if data.get('faculty'):
            faculty_clashes = check_faculty_clash(
                faculty_id=data['faculty'].id,
                day_of_week=data['day_of_week'],
                start_time=data['start_time'],
                end_time=data['end_time'],
            )
            if faculty_clashes:
                return Response(
                    {'success': False, 'message': 'Faculty has a scheduling conflict.',
                     'clashing_slots': faculty_clashes},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Clash detection — classroom
        if data.get('classroom'):
            classroom_clashes = check_classroom_clash(
                classroom_id=data['classroom'].id,
                day_of_week=data['day_of_week'],
                start_time=data['start_time'],
                end_time=data['end_time'],
            )
            if classroom_clashes:
                return Response(
                    {'success': False, 'message': 'Classroom has a scheduling conflict.',
                     'clashing_slots': classroom_clashes},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        slot = serializer.save(created_by=request.user if request.user.is_authenticated else None)
        return Response(
            {'success': True, 'message': 'Timetable slot created.',
             'data': TimetableSlotListSerializer(slot).data},
            status=status.HTTP_201_CREATED,
        )


class TimetableDetailView(APIView):

    def _get_slot(self, pk):
        try:
            qs = TimetableSlot.objects.select_related(
                'batch', 'subject', 'faculty', 'classroom'
            ).all()
            if getattr(self.request.user, 'organization', None):
                qs = qs.filter(organization=self.request.user.organization)
            return qs.get(pk=pk)
        except TimetableSlot.DoesNotExist:
            return None

    def get(self, request, pk):
        slot = self._get_slot(pk)
        if slot is None:
            return Response({'success': False, 'message': 'Timetable slot not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': TimetableSlotListSerializer(slot).data})

    def patch(self, request, pk):
        slot = self._get_slot(pk)
        if slot is None:
            return Response({'success': False, 'message': 'Timetable slot not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = TimetableSlotCreateUpdateSerializer(slot, data=request.data, partial=True, context={'request': request})
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        faculty = data.get('faculty', slot.faculty)
        classroom = data.get('classroom', slot.classroom)
        day = data.get('day_of_week', slot.day_of_week)
        start = data.get('start_time', slot.start_time)
        end = data.get('end_time', slot.end_time)

        # Re-run clash detection
        if faculty:
            faculty_clashes = check_faculty_clash(
                faculty_id=faculty.id, day_of_week=day,
                start_time=start, end_time=end, exclude_id=slot.id,
            )
            if faculty_clashes:
                return Response(
                    {'success': False, 'message': 'Faculty has a scheduling conflict.',
                     'clashing_slots': faculty_clashes},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if classroom:
            classroom_clashes = check_classroom_clash(
                classroom_id=classroom.id, day_of_week=day,
                start_time=start, end_time=end, exclude_id=slot.id,
            )
            if classroom_clashes:
                return Response(
                    {'success': False, 'message': 'Classroom has a scheduling conflict.',
                     'clashing_slots': classroom_clashes},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        serializer.save()
        return Response({'success': True, 'message': 'Timetable slot updated.',
                         'data': TimetableSlotListSerializer(slot).data})

    def delete(self, request, pk):
        slot = self._get_slot(pk)
        if slot is None:
            return Response({'success': False, 'message': 'Timetable slot not found.'}, status=status.HTTP_404_NOT_FOUND)
        slot.delete()
        return Response({'success': True, 'message': 'Timetable slot deleted.'})


# ── Personal Timetable Views ─────────────────────────────────────────────────

class FacultyTimetableView(APIView):
    """GET /api/v1/timetable/faculty/<faculty_id>/ — weekly schedule for a faculty member."""

    def get(self, request, faculty_id):
        slots = TimetableSlot.objects.select_related(
            'batch', 'subject', 'classroom'
        ).filter(faculty_id=faculty_id)
        if getattr(request.user, 'organization', None):
            slots = slots.filter(organization=request.user.organization)
        slots = slots.order_by('day_of_week', 'start_time')

        serializer = FacultyTimetableSerializer(slots, many=True)

        # Group by day
        grouped = {}
        for s in serializer.data:
            day = s['day_label']
            grouped.setdefault(day, []).append(s)

        return Response({'success': True, 'data': grouped})


class StudentTimetableView(APIView):
    """GET /api/v1/timetable/student/<student_id>/ — weekly schedule for a student."""

    def get(self, request, student_id):
        # Find all batches the student is enrolled in
        batch_ids = BatchStudent.objects.filter(
            student_id=student_id
        ).values_list('batch_id', flat=True)

        slots = TimetableSlot.objects.select_related(
            'subject', 'faculty', 'classroom'
        ).filter(batch_id__in=batch_ids)
        if getattr(request.user, 'organization', None):
            slots = slots.filter(organization=request.user.organization)
        slots = slots.order_by('day_of_week', 'start_time')

        serializer = StudentTimetableSerializer(slots, many=True)

        grouped = {}
        for s in serializer.data:
            day = s['day_label']
            grouped.setdefault(day, []).append(s)

        return Response({'success': True, 'data': grouped})
