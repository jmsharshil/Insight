import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

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

    def get(self, request):
        # Optimized: prefetch_related for related objects
        queryset = Course.objects.all().prefetch_related('subjects', 'batches')

        course_type = request.GET.get('course_type')
        is_active = request.GET.get('is_active')
        search = request.GET.get('search')

        if course_type:
            queryset = queryset.filter(course_type=course_type)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        if search:
            queryset = queryset.filter(name__icontains=search) | queryset.filter(code__icontains=search)

        queryset = queryset.annotate(
            subject_count=models.Count('subjects')
        )

        serializer = CourseListSerializer(queryset, many=True)
        return Response(
            {'success': True, 'count': queryset.count(), 'data': serializer.data},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = CourseCreateUpdateSerializer(data=request.data)
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
            return Course.objects.get(pk=pk)
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
        serializer = CourseCreateUpdateSerializer(course, data=request.data, partial=True)
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

    def get(self, request):
        queryset = Subject.objects.select_related('course').all()

        course_id = request.GET.get('course_id')
        if course_id:
            queryset = queryset.filter(course_id=course_id)

        is_active = request.GET.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        serializer = SubjectListSerializer(queryset, many=True)
        return Response(
            {'success': True, 'count': queryset.count(), 'data': serializer.data},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = SubjectCreateUpdateSerializer(data=request.data)
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
            return Subject.objects.get(pk=pk)
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
        serializer = SubjectCreateUpdateSerializer(subject, data=request.data, partial=True)
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

    def get(self, request):
        # Optimized: prefetch_related for many-to-many and reverse relations
        queryset = Batch.objects.select_related('course').prefetch_related('batch_students').all()

        course_id = request.GET.get('course_id')
        is_active = request.GET.get('is_active')
        search = request.GET.get('search')

        if course_id:
            queryset = queryset.filter(course_id=course_id)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        if search:
            queryset = queryset.filter(name__icontains=search) | queryset.filter(batch_code__icontains=search)

        # Annotate enrolled student count
        queryset = queryset.annotate(
            enrolled_count=models.Count('batch_students')
        )

        serializer = BatchListSerializer(queryset, many=True)
        return Response(
            {'success': True, 'count': queryset.count(), 'data': serializer.data},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = BatchCreateUpdateSerializer(data=request.data)
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
            return Batch.objects.select_related('course').get(pk=pk)
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
        serializer = BatchCreateUpdateSerializer(batch, data=request.data, partial=True)
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

class BatchAssignStudentsView(APIView):

    def post(self, request, pk):
        try:
            batch = Batch.objects.get(pk=pk)
        except Batch.DoesNotExist:
            return Response({'success': False, 'message': 'Batch not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = AssignStudentsSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        student_ids = serializer.validated_data['student_ids']
        User = settings.AUTH_USER_MODEL

        # Validate students exist and have role=student
        from auth_user.models import User
        students = User.objects.filter(id__in=student_ids, role='student')
        found_ids = set(students.values_list('id', flat=True))
        invalid_ids = set(student_ids) - found_ids
        if invalid_ids:
            return Response(
                {'success': False, 'message': f'Invalid student IDs: {invalid_ids}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check max_students constraint
        current_count = BatchStudent.objects.filter(batch=batch).count()
        new_count = len(student_ids)
        # Filter out already enrolled
        already_enrolled = set(
            BatchStudent.objects.filter(batch=batch, student_id__in=student_ids)
            .values_list('student_id', flat=True)
        )
        to_enroll = [sid for sid in student_ids if sid not in already_enrolled]

        if current_count + len(to_enroll) > batch.max_students:
            remaining = batch.max_students - current_count
            return Response(
                {'success': False, 'message': f'Batch capacity exceeded. Only {remaining} seats remaining.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = []
        for sid in to_enroll:
            bs = BatchStudent.objects.create(batch=batch, student_id=sid)
            created.append(bs)

        return Response({
            'success': True,
            'message': f'{len(created)} student(s) enrolled. {len(already_enrolled)} already enrolled.',
            'data': BatchStudentReadSerializer(created, many=True).data if created else [],
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class BatchRemoveStudentView(APIView):

    def post(self, request, pk, student_id):
        try:
            bs = BatchStudent.objects.get(batch_id=pk, student_id=student_id)
        except BatchStudent.DoesNotExist:
            return Response({'success': False, 'message': 'Student not enrolled in this batch.'}, status=status.HTTP_404_NOT_FOUND)
        bs.delete()
        return Response({'success': True, 'message': 'Student removed from batch.'})


# ── Batch Faculty Assignment ──────────────────────────────────────────────────

class BatchAssignFacultyView(APIView):

    def post(self, request, pk):
        try:
            batch = Batch.objects.get(pk=pk)
        except Batch.DoesNotExist:
            return Response({'success': False, 'message': 'Batch not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = AssignFacultySerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        faculty_id = serializer.validated_data['faculty_id']
        subject_id = serializer.validated_data.get('subject_id')

        from auth_user.models import User
        if not User.objects.filter(id=faculty_id, role='faculty').exists():
            return Response({'success': False, 'message': 'Invalid faculty ID.'}, status=status.HTTP_400_BAD_REQUEST)

        bf, created = BatchFaculty.objects.get_or_create(
            batch=batch, faculty_id=faculty_id, subject_id=subject_id,
        )
        if not created:
            return Response({'success': False, 'message': 'Faculty already assigned to this batch/subject.'},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'success': True, 'message': 'Faculty assigned successfully.',
            'data': BatchFacultyReadSerializer(bf).data,
        }, status=status.HTTP_201_CREATED)


class BatchRemoveFacultyView(APIView):

    def post(self, request, pk, faculty_id):
        subject_id = request.data.get('subject_id')
        try:
            bf = BatchFaculty.objects.get(batch_id=pk, faculty_id=faculty_id, subject_id=subject_id)
        except BatchFaculty.DoesNotExist:
            return Response({'success': False, 'message': 'Faculty assignment not found.'}, status=status.HTTP_404_NOT_FOUND)
        bf.delete()
        return Response({'success': True, 'message': 'Faculty removed from batch.'})


# ═══════════════════════════════════════════════════════════════════════════════
#  Classroom Views
# ═══════════════════════════════════════════════════════════════════════════════

class ClassroomListView(APIView):

    def get(self, request):
        queryset = Classroom.objects.all()
        is_active = request.GET.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        serializer = ClassroomListSerializer(queryset, many=True)
        return Response({'success': True, 'count': queryset.count(), 'data': serializer.data})

    def post(self, request):
        serializer = ClassroomCreateUpdateSerializer(data=request.data)
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
            return Classroom.objects.get(pk=pk)
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
        serializer = ClassroomCreateUpdateSerializer(classroom, data=request.data, partial=True)
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

    def get(self, request):
        queryset = TimetableSlot.objects.select_related(
            'batch', 'subject', 'faculty', 'classroom'
        ).all()

        batch_id = request.GET.get('batch_id')
        day_of_week = request.GET.get('day_of_week')
        faculty_id = request.GET.get('faculty_id')
        subject_id = request.GET.get('subject_id')

        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)
        if day_of_week is not None:
            queryset = queryset.filter(day_of_week=int(day_of_week))
        if faculty_id:
            queryset = queryset.filter(faculty_id=faculty_id)
        if subject_id:
            queryset = queryset.filter(subject_id=subject_id)

        serializer = TimetableSlotListSerializer(queryset, many=True)
        return Response({'success': True, 'count': queryset.count(), 'data': serializer.data})

    def post(self, request):
        serializer = TimetableSlotCreateUpdateSerializer(data=request.data)
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
            return TimetableSlot.objects.select_related(
                'batch', 'subject', 'faculty', 'classroom'
            ).get(pk=pk)
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

        serializer = TimetableSlotCreateUpdateSerializer(slot, data=request.data, partial=True)
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
        ).filter(faculty_id=faculty_id).order_by('day_of_week', 'start_time')

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
        ).filter(batch_id__in=batch_ids).order_by('day_of_week', 'start_time')

        serializer = StudentTimetableSerializer(slots, many=True)

        grouped = {}
        for s in serializer.data:
            day = s['day_label']
            grouped.setdefault(day, []).append(s)

        return Response({'success': True, 'data': grouped})


