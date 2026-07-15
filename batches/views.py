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
    CourseLevel, Chapter,
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
    CourseLevelSerializer, ChapterSerializer,
)
from .validators import check_faculty_clash, check_classroom_clash, check_batch_clash

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  Course Views
# ═══════════════════════════════════════════════════════════════════════════════

class CourseListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'code']
    ordering_fields = '__all__'

    def get(self, request):
        # Filter by user's organization
        queryset = Course.objects.prefetch_related('levels__subjects', 'batches').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(organization=request.user.organization)

        is_active = request.GET.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        queryset = queryset.annotate(
            subject_count=models.Count('levels__subjects', distinct=True)
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
#  CourseLevel Views (E2)
# ═══════════════════════════════════════════════════════════════════════════════

class CourseLevelListView(APIView):
    def get(self, request, course_id):
        levels = CourseLevel.objects.filter(course_id=course_id)
        if getattr(request.user, 'organization', None):
            levels = levels.filter(organization=request.user.organization)
        levels = levels.order_by('order')
        return Response({'success': True, 'data': CourseLevelSerializer(levels, many=True).data})

    def post(self, request, course_id):
        # Ensure course belongs to user's org
        try:
            qs = Course.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(organization=request.user.organization)
            course = qs.get(pk=course_id)
        except Course.DoesNotExist:
            return Response({'success': False, 'message': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = CourseLevelSerializer(data=request.data, context={'course': course})
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        
        level = serializer.save(course=course, organization=getattr(request.user, 'organization', None))
        return Response({'success': True, 'message': 'Course level created.', 'data': CourseLevelSerializer(level).data}, status=status.HTTP_201_CREATED)


class CourseLevelDetailView(APIView):
    def _get_level(self, course_id, level_id):
        try:
            qs = CourseLevel.objects.filter(course_id=course_id)
            if getattr(self.request.user, 'organization', None):
                qs = qs.filter(organization=self.request.user.organization)
            return qs.get(pk=level_id)
        except CourseLevel.DoesNotExist:
            return None

    def get(self, request, course_id, level_id):
        level = self._get_level(course_id, level_id)
        if not level:
            return Response({'success': False, 'message': 'Course level not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': CourseLevelSerializer(level).data})

    def patch(self, request, course_id, level_id):
        level = self._get_level(course_id, level_id)
        if not level:
            return Response({'success': False, 'message': 'Course level not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = CourseLevelSerializer(level, data=request.data, partial=True, context={'course': level.course})
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response({'success': True, 'message': 'Course level updated.', 'data': CourseLevelSerializer(level).data})

    def delete(self, request, course_id, level_id):
        level = self._get_level(course_id, level_id)
        if not level:
            return Response({'success': False, 'message': 'Course level not found.'}, status=status.HTTP_404_NOT_FOUND)
        level.delete()
        return Response({'success': True, 'message': 'Course level deleted.'})


# ═══════════════════════════════════════════════════════════════════════════════
#  Subject Views
# ═══════════════════════════════════════════════════════════════════════════════

class SubjectListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['level', 'level__course', 'is_active']
    search_fields = ['name', 'code']
    ordering_fields = '__all__'

    def get(self, request):
        queryset = Subject.objects.select_related('level', 'level__course').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(organization=request.user.organization)

        level_id = request.GET.get('level_id')
        course_id = request.GET.get('course_id')
        if level_id:
            queryset = queryset.filter(level_id=level_id)
        if course_id:
            queryset = queryset.filter(level__course_id=course_id)

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
#  Chapter Views (E2)
# ═══════════════════════════════════════════════════════════════════════════════

class ChapterListView(APIView):
    def get(self, request, subject_id):
        chapters = Chapter.objects.filter(subject_id=subject_id).order_by('order')
        if getattr(request.user, 'organization', None):
            chapters = chapters.filter(subject__organization=request.user.organization)
        return Response({'success': True, 'data': ChapterSerializer(chapters, many=True).data})

    def post(self, request, subject_id):
        try:
            qs = Subject.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(organization=request.user.organization)
            subject = qs.get(pk=subject_id)
        except Subject.DoesNotExist:
            return Response({'success': False, 'message': 'Subject not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = ChapterSerializer(data=request.data, context={'subject': subject})
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        
        chapter = serializer.save(subject=subject)
        return Response({'success': True, 'message': 'Chapter created.', 'data': ChapterSerializer(chapter).data}, status=status.HTTP_201_CREATED)


class ChapterDetailView(APIView):
    def _get_chapter(self, subject_id, chapter_id):
        try:
            qs = Chapter.objects.filter(subject_id=subject_id)
            if getattr(self.request.user, 'organization', None):
                qs = qs.filter(subject__organization=self.request.user.organization)
            return qs.get(pk=chapter_id)
        except Chapter.DoesNotExist:
            return None

    def get(self, request, subject_id, chapter_id):
        chapter = self._get_chapter(subject_id, chapter_id)
        if not chapter:
            return Response({'success': False, 'message': 'Chapter not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': ChapterSerializer(chapter).data})

    def patch(self, request, subject_id, chapter_id):
        chapter = self._get_chapter(subject_id, chapter_id)
        if not chapter:
            return Response({'success': False, 'message': 'Chapter not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ChapterSerializer(chapter, data=request.data, partial=True, context={'subject': chapter.subject})
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response({'success': True, 'message': 'Chapter updated.', 'data': ChapterSerializer(chapter).data})

    def delete(self, request, subject_id, chapter_id):
        chapter = self._get_chapter(subject_id, chapter_id)
        if not chapter:
            return Response({'success': False, 'message': 'Chapter not found.'}, status=status.HTTP_404_NOT_FOUND)
        chapter.delete()
        return Response({'success': True, 'message': 'Chapter deleted.'})

# ═══════════════════════════════════════════════════════════════════════════════
#  Batch Views
# ═══════════════════════════════════════════════════════════════════════════════

class BatchListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['course', 'is_active', 'branch']
    search_fields = ['name', 'batch_code']
    ordering_fields = '__all__'

    def get(self, request):
        queryset = Batch.objects.select_related('course').prefetch_related('batch_students').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(organization=request.user.organization)

        course_id = request.GET.get('course_id')
        is_active = request.GET.get('is_active')
        branch_id = request.GET.get('branch_id') or request.GET.get('branch')

        if course_id:
            queryset = queryset.filter(course_id=course_id)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

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

        qs = BatchFaculty.objects.filter(batch_id=pk, faculty_id=faculty.id)
        if getattr(request.user, 'organization', None):
            qs = qs.filter(batch__organization=request.user.organization)
        
        if subject_id:
            qs = qs.filter(subject_id=subject_id)

        if not qs.exists():
            return Response(
                {
                    'success': False,
                    'message': 'Faculty assignment not found.'
                },
                status=status.HTTP_404_NOT_FOUND
            )

        qs.delete()

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
    filterset_fields = ['batch', 'day_of_week', 'faculty', 'subject', 'batch__course', 'session_type']
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
        session_type = request.GET.get('session_type')

        if batch_id:
            # allow comma-separated batch IDs for E4 filter
            batch_ids = [b.strip() for b in batch_id.split(',')]
            queryset = queryset.filter(batch_id__in=batch_ids)
        if day_of_week is not None:
            queryset = queryset.filter(day_of_week=int(day_of_week))
        if faculty_id:
            queryset = queryset.filter(faculty_id=faculty_id)
        if subject_id:
            queryset = queryset.filter(subject_id=subject_id)
        if course_id:
            queryset = queryset.filter(batch__course_id=course_id)
        if session_type:
            queryset = queryset.filter(session_type=session_type)

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

        day_of_week = data.get('day_of_week')
        session_date = data.get('session_date')
        if day_of_week is None and session_date:
            day_of_week = session_date.weekday()

        start_time = data.get('start_time')
        end_time = data.get('end_time')
        conflicts = []
        all_clash_details = []

        # Clash detection — batch
        if data.get('batch') and start_time and end_time:
            batch_clashes = check_batch_clash(
                batch_id=data['batch'].id,
                day_of_week=day_of_week,
                start_time=start_time,
                end_time=end_time,
            )
            if batch_clashes:
                c = batch_clashes[0]
                conflicts.append(
                    f"Batch '{c['batch_name']}' already has a slot from "
                    f"{c['start_time']}–{c['end_time']} on this day."
                )
                all_clash_details.extend(batch_clashes)

        # Clash detection — faculty
        if data.get('faculty') and start_time and end_time:
            faculty_clashes = check_faculty_clash(
                faculty_id=data['faculty'].id,
                day_of_week=day_of_week,
                start_time=start_time,
                end_time=end_time,
            )
            if faculty_clashes:
                c = faculty_clashes[0]
                conflicts.append(
                    f"Faculty '{c['faculty_name']}' is already scheduled from "
                    f"{c['start_time']}–{c['end_time']} in batch '{c['batch_name']}' on this day."
                )
                all_clash_details.extend(faculty_clashes)

        # Clash detection — classroom
        if data.get('classroom') and start_time and end_time:
            classroom_clashes = check_classroom_clash(
                classroom_id=data['classroom'].id,
                day_of_week=day_of_week,
                start_time=start_time,
                end_time=end_time,
            )
            if classroom_clashes:
                c = classroom_clashes[0]
                conflicts.append(
                    f"Classroom '{c['classroom_name']}' is already booked from "
                    f"{c['start_time']}–{c['end_time']} for batch '{c['batch_name']}' on this day."
                )
                all_clash_details.extend(classroom_clashes)

        if conflicts:
            seen = set()
            unique_clashes = []
            for cl in all_clash_details:
                if cl['id'] not in seen:
                    seen.add(cl['id'])
                    unique_clashes.append(cl)
            return Response(
                {
                    'success': False,
                    'message': ' | '.join(conflicts),
                    'conflicts': conflicts,
                    'clashing_slots': unique_clashes,
                    'can_force': True,
                },
                status=status.HTTP_409_CONFLICT,
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
        batch = data.get('batch', slot.batch)
        faculty = data.get('faculty', slot.faculty)
        classroom = data.get('classroom', slot.classroom)
        day = data.get('day_of_week', slot.day_of_week)
        session_date = data.get('session_date', slot.session_date)
        if day is None and session_date:
            day = session_date.weekday()
        start = data.get('start_time', slot.start_time)
        end = data.get('end_time', slot.end_time)

        conflicts = []
        all_clash_details = []

        # Re-run clash detection — batch
        if batch and start and end:
            batch_clashes = check_batch_clash(
                batch_id=batch.id, day_of_week=day,
                start_time=start, end_time=end, exclude_id=slot.id,
            )
            if batch_clashes:
                c = batch_clashes[0]
                conflicts.append(
                    f"Batch '{c['batch_name']}' already has a slot from "
                    f"{c['start_time']}–{c['end_time']} on this day."
                )
                all_clash_details.extend(batch_clashes)

        # Re-run clash detection — faculty
        if faculty and start and end:
            faculty_clashes = check_faculty_clash(
                faculty_id=faculty.id, day_of_week=day,
                start_time=start, end_time=end, exclude_id=slot.id,
            )
            if faculty_clashes:
                c = faculty_clashes[0]
                conflicts.append(
                    f"Faculty '{c['faculty_name']}' is already scheduled from "
                    f"{c['start_time']}–{c['end_time']} in batch '{c['batch_name']}' on this day."
                )
                all_clash_details.extend(faculty_clashes)

        # Re-run clash detection — classroom
        if classroom and start and end:
            classroom_clashes = check_classroom_clash(
                classroom_id=classroom.id, day_of_week=day,
                start_time=start, end_time=end, exclude_id=slot.id,
            )
            if classroom_clashes:
                c = classroom_clashes[0]
                conflicts.append(
                    f"Classroom '{c['classroom_name']}' is already booked from "
                    f"{c['start_time']}–{c['end_time']} for batch '{c['batch_name']}' on this day."
                )
                all_clash_details.extend(classroom_clashes)

        if conflicts:
            seen = set()
            unique_clashes = []
            for cl in all_clash_details:
                if cl['id'] not in seen:
                    seen.add(cl['id'])
                    unique_clashes.append(cl)
            return Response(
                {
                    'success': False,
                    'message': ' | '.join(conflicts),
                    'conflicts': conflicts,
                    'clashing_slots': unique_clashes,
                    'can_force': True,
                },
                status=status.HTTP_409_CONFLICT,
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


class TimetableDuplicateSlotView(APIView):
    """
    POST /api/v1/timetable/<uuid:pk>/duplicate/
    Duplicates a regular-session timetable slot to a new day + slot code.

    Body: { "slot_code": "P2", "day_of_week": 3 }
    """

    def post(self, request, pk):
        # 1. Fetch the source slot
        try:
            qs = TimetableSlot.objects.select_related(
                'batch', 'subject', 'faculty', 'classroom'
            ).all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(organization=request.user.organization)
            source = qs.get(pk=pk)
        except TimetableSlot.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Source timetable slot not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 2. Only regular sessions may be duplicated
        if source.session_type != 'regular':
            return Response(
                {'success': False, 'message': 'Only regular sessions can be duplicated.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3. Validate inputs
        slot_code = request.data.get('slot_code')
        day_of_week = request.data.get('day_of_week')
        session_date = request.data.get('session_date')

        from batches.constants import FIXED_SLOTS
        from batches.models import SLOT_CODE_CHOICES, DAY_CHOICES

        valid_codes = [c[0] for c in SLOT_CODE_CHOICES]
        valid_days  = [d[0] for d in DAY_CHOICES]

        if not slot_code or slot_code not in valid_codes:
            return Response(
                {'success': False, 'message': f"Invalid slot_code. Choose from {valid_codes}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if day_of_week is None and session_date is None:
            return Response(
                {'success': False, 'message': 'day_of_week or session_date is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if day_of_week is not None:
            try:
                day_of_week = int(day_of_week)
            except (ValueError, TypeError):
                return Response(
                    {'success': False, 'message': 'day_of_week must be an integer.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if day_of_week not in valid_days:
                return Response(
                    {'success': False, 'message': f"Invalid day_of_week. Choose from {valid_days}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif session_date:
            from datetime import date
            if isinstance(session_date, str):
                try:
                    parsed_date = date.fromisoformat(session_date)
                    day_of_week = parsed_date.weekday()
                    session_date = parsed_date
                except ValueError:
                    return Response({'success': False, 'message': 'Invalid session_date format.'}, status=400)
            else:
                day_of_week = session_date.weekday()

        # 4. Resolve start/end times from slot code
        if slot_code in ['P5', 'P6']:
            from datetime import time
            start_time_str = request.data.get('start_time')
            end_time_str = request.data.get('end_time')
            if not start_time_str or not end_time_str:
                return Response(
                    {'success': False, 'message': 'start_time and end_time required for P5/P6.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                start_time = time.fromisoformat(start_time_str)
                end_time = time.fromisoformat(end_time_str)
            except ValueError:
                return Response({'success': False, 'message': 'Invalid time format.'}, status=400)
                
            if start_time >= end_time:
                return Response(
                    {'success': False, 'message': 'end_time must be after start_time.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            start_time, end_time = FIXED_SLOTS[slot_code]

        # 5. Clash detection — batch, faculty, classroom
        conflicts = []
        all_clash_details = []

        if source.batch_id:
            batch_clashes = check_batch_clash(
                batch_id=source.batch_id,
                day_of_week=day_of_week,
                start_time=start_time,
                end_time=end_time,
            )
            if batch_clashes:
                c = batch_clashes[0]
                conflicts.append(
                    f"Batch '{c['batch_name']}' already has a slot from "
                    f"{c['start_time']}–{c['end_time']} on this day."
                )
                all_clash_details.extend(batch_clashes)

        if source.faculty_id:
            faculty_clashes = check_faculty_clash(
                faculty_id=source.faculty_id,
                day_of_week=day_of_week,
                start_time=start_time,
                end_time=end_time,
            )
            if faculty_clashes:
                c = faculty_clashes[0]
                conflicts.append(
                    f"Faculty '{c['faculty_name']}' is already scheduled from "
                    f"{c['start_time']}–{c['end_time']} in batch '{c['batch_name']}' on this day."
                )
                all_clash_details.extend(faculty_clashes)

        # 6. Clash detection — classroom
        if source.classroom_id:
            classroom_clashes = check_classroom_clash(
                classroom_id=source.classroom_id,
                day_of_week=day_of_week,
                start_time=start_time,
                end_time=end_time,
            )
            if classroom_clashes:
                c = classroom_clashes[0]
                conflicts.append(
                    f"Classroom '{c['classroom_name']}' is already booked from "
                    f"{c['start_time']}–{c['end_time']} for batch '{c['batch_name']}' on this day."
                )
                all_clash_details.extend(classroom_clashes)

        if conflicts:
            seen = set()
            unique_clashes = []
            for cl in all_clash_details:
                if cl['id'] not in seen:
                    seen.add(cl['id'])
                    unique_clashes.append(cl)
            return Response(
                {
                    'success': False,
                    'message': ' | '.join(conflicts),
                    'conflicts': conflicts,
                    'clashing_slots': unique_clashes,
                    'can_force': True,
                },
                status=status.HTTP_409_CONFLICT,
            )

        # 7. Create the duplicate slot
        new_slot = TimetableSlot.objects.create(
            organization=source.organization,
            batch=source.batch,
            subject=source.subject,
            faculty=source.faculty,
            classroom=source.classroom,
            day_of_week=day_of_week,
            start_time=start_time,
            end_time=end_time,
            is_recurring=source.is_recurring,
            effective_from=source.effective_from,
            effective_to=source.effective_to,
            session_type='regular',
            session_name=source.session_name,
            slot_code=slot_code,
            created_by=request.user if request.user.is_authenticated else None,
        )

        return Response(
            {'success': True, 'message': 'Timetable slot duplicated.',
             'data': TimetableSlotListSerializer(new_slot).data},
            status=status.HTTP_201_CREATED,
        )


# ── Personal Timetable Views ─────────────────────────────────────────────────

# ── Force-create (confirm) View ─────────────────────────────────────────────

class TimetableConfirmView(APIView):
    """
    POST /api/v1/timetable/confirm/
    Force-creates a timetable slot, bypassing all faculty / classroom / batch
    clash checks.  Accepts the same payload as TimetableListView.post.
    """

    def post(self, request):
        serializer = TimetableSlotCreateUpdateSerializer(
            data=request.data, context={'request': request}
        )
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        slot = serializer.save(
            created_by=request.user if request.user.is_authenticated else None
        )
        return Response(
            {
                'success': True,
                'message': 'Timetable slot force-created (conflicts ignored).',
                'data': TimetableSlotListSerializer(slot).data,
            },
            status=status.HTTP_201_CREATED,
        )


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


from branch.models import Branch

class AcademicDropdownsView(APIView):
    """
    GET /api/v1/batches/dropdowns/
    Returns minimal dropdown data for course, level, batch, subject, branch, and classroom.
    """
    def get(self, request):
        user = request.user
        org_id = user.organization_id if hasattr(user, 'organization_id') and user.organization_id else None

        courses_qs = Course.objects.all()
        levels_qs = CourseLevel.objects.all()
        batches_qs = Batch.objects.all()
        subjects_qs = Subject.objects.all()
        branches_qs = Branch.objects.all()
        classrooms_qs = Classroom.objects.all()
        chapters_qs = Chapter.objects.all()

        from exams.models import SubjectPaper
        papers_qs = SubjectPaper.objects.all()

        if org_id:
            courses_qs = courses_qs.filter(organization_id=org_id)
            levels_qs = levels_qs.filter(organization_id=org_id)
            batches_qs = batches_qs.filter(organization_id=org_id)
            subjects_qs = subjects_qs.filter(organization_id=org_id)
            branches_qs = branches_qs.filter(organization_id=org_id)
            classrooms_qs = classrooms_qs.filter(organization_id=org_id)
            chapters_qs = chapters_qs.filter(subject__organization_id=org_id)
            papers_qs = papers_qs.filter(subject__organization_id=org_id)
        
        branch_id = request.GET.get('branch_id')
        if branch_id:
            batches_qs = batches_qs.filter(branch_id=branch_id)
            branches_qs = branches_qs.filter(id=branch_id)
 
        subjects = list(subjects_qs.values('id', 'name', 'level_id'))
        chapters = list(chapters_qs.values('id', 'name', 'subject_id', 'order'))
        papers = list(papers_qs.values('id', 'set_name', 'subject_id', 'file', 'answer_key'))

        chapters_by_subject = {}
        for chapter in chapters:
            subj_id = chapter['subject_id']
            if subj_id not in chapters_by_subject:
                chapters_by_subject[subj_id] = []
            chapters_by_subject[subj_id].append({
                'id': chapter['id'],
                'name': chapter['name'],
                'order': chapter['order']
            })
            
        papers_by_subject = {}
        for paper in papers:
            subj_id = paper['subject_id']
            if subj_id not in papers_by_subject:
                papers_by_subject[subj_id] = []
            papers_by_subject[subj_id].append({
                'id': paper['id'],
                'set_name': paper['set_name'],
                'file': paper['file'],
                'answer_key': paper['answer_key']
            })
        
        for subject in subjects:
            subject['chapters'] = chapters_by_subject.get(subject['id'], [])
            subject['papers'] = papers_by_subject.get(subject['id'], [])

        return Response({
            "success": True,
            "data": {
                "courses": list(courses_qs.values('id', 'name')),
                "levels": list(levels_qs.values('id', 'name', 'course_id')),
                "batches": list(batches_qs.values('id', 'name', 'course_id')),
                "subjects": subjects,
                "branches": list(branches_qs.values('id', 'name', 'city')),
                "classrooms": list(classrooms_qs.values('id', 'name', 'capacity')),
            }
        })
