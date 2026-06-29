import logging
from core.pagination import paginate_queryset
import uuid
import hashlib
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from core.utils import apply_filters

from .models import (
    Exam, Question, Choice, ExamSession, StudentAnswer,
    SeatArrangement, MalpracticeReport, ScreenEvent,
    AnswerKeyDistributionLog, CheckerToken, SubjectPaper,
)
from .serializers import (
    ExamListSerializer, ExamCreateSerializer, QuestionSerializer,
    QuestionStudentSerializer, QuestionInputSerializer, ExamStartSerializer,
    ExamSubmitSerializer, AutosaveSerializer, ScreenEventSerializer,
    SeatInputSerializer, SeatArrangementSerializer, MalpracticeInputSerializer,
    MalpracticeSerializer, MarksInputSerializer, GeoCheckSerializer,
    SubjectPaperSerializer,
)
from .utils import (
    auto_submit_session, check_geo_boundary, assign_papers_to_checker,
)
from .emails import send_answer_key_email

logger = logging.getLogger(__name__)

# ── Role constants ────────────────────────────────────────────────────────────
ADMIN_ROLES = ['super_admin', 'branch_manager', 'admin_senior_executive', 'admin_executive']
EXAM_CREATE_ROLES = ['super_admin', 'branch_manager', 'admin_senior_executive', 'faculty']
EXAM_EDIT_ROLES = ['super_admin', 'branch_manager', 'admin_senior_executive']
EXAM_DELETE_ROLES = ['super_admin', 'branch_manager']
SEATING_VIEW_ROLES = ['super_admin', 'exam_supervisor', 'admin_senior_executive', 'branch_manager']
SEATING_EDIT_ROLES = ['super_admin', 'exam_supervisor', 'admin_senior_executive']
MALPRACTICE_VIEW_ROLES = ['super_admin', 'exam_supervisor', 'admin_senior_executive', 'branch_manager']
MALPRACTICE_CREATE_ROLES = ['super_admin', 'exam_supervisor']
ANSWER_KEY_ROLES = ['super_admin', 'admin_senior_executive', 'branch_manager']


def _user_role(user):
    return getattr(user, 'role', None)


def _user_branch_id(user):
    if hasattr(user, 'branch_id') and user.branch_id:
        return user.branch_id
    if hasattr(user, 'profile') and hasattr(user.profile, 'branch_id'):
        return user.profile.branch_id
    try:
        from faculty.models import FacultyProfile
        fp = FacultyProfile.objects.only('branch_id').get(user=user)
        return fp.branch_id
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 1. GET & POST  /api/v1/exams/
# ═══════════════════════════════════════════════════════════════════════════════

class ExamListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['exam_type', 'status', 'batch_id', 'scheduled_date']
    search_fields = ['title', 'description']
    ordering_fields = '__all__'

    def _get_queryset(self, request):
        user = request.user
        role = _user_role(user)
        qs = Exam.objects.filter(is_deleted=False).select_related('batch', 'subject', 'branch', 'created_by')
        if getattr(request.user, 'organization', None):
            qs = qs.filter(branch__organization=request.user.organization)

        if role == 'student':
            try:
                from students.models import Student
                from batches.models import BatchStudent
                sp = Student.objects.select_related('batch').get(user=user)
                # Support both direct batch_id and many-to-many via BatchStudent
                if sp.batch_id:
                    qs = qs.filter(batch_id=sp.batch_id)
                else:
                    # Fallback for students enrolled via BatchStudent relation
                    enrolled_batch_ids = BatchStudent.objects.filter(
                        student=sp
                    ).values_list('batch_id', flat=True)
                    if enrolled_batch_ids:
                        qs = qs.filter(batch_id__in=enrolled_batch_ids)
                    else:
                        logger.warning(f"Student {user.email} has no batch assignment")
                        qs = qs.none()
                # Students should see scheduled, ongoing, and results (for viewing marks)
                qs = qs.filter(status__in=['scheduled', 'ongoing', 'completed', 'results_published'])
                logger.info(f"Student {user.email} (batch={sp.batch_id}) can see {qs.count()} exams")
            except Student.DoesNotExist:
                logger.error(f"No Student profile found for user {user.email} (role=student)")
                qs = qs.none()
            except Exception as e:
                logger.error(f"Student exam filter error for {user.email}: {e}")
                qs = qs.none()
        elif role == 'faculty':
            try:
                from faculty.models import FacultyProfile
                fp = FacultyProfile.objects.only('id').get(user=user)
                faculty_id = fp.id
                qs = qs.filter(
                    Q(created_by=user) | 
                    Q(faculty_id=faculty_id) |
                    Q(batch__batch_faculty__faculty_id=faculty_id)
                ).distinct()
            except Exception:
                # Fallback: just show what they created
                qs = qs.filter(created_by=user)
        elif role == 'exam_supervisor':
            bid = _user_branch_id(user)
            if bid:
                qs = qs.filter(branch_id=bid)
        elif role == 'paper_checker':
            try:
                qs = qs.filter(Q(marksheets__paper_checker=user) | Q(paper_checkers=user)).distinct()
                count = qs.count()
                logger.info(
                    f"Paper checker {getattr(user, 'email', getattr(user, 'id', 'unknown'))} "
                    f"can see {count} assigned exams "
                    f"(marksheets__paper_checker OR paper_checkers M2M)"
                )
            except Exception as e:
                logger.error(f"Paper checker exam filter error for {getattr(user, 'email', user)}: {e}")
                qs = qs.none()
        elif role != 'super_admin':
            bid = _user_branch_id(user)
            if bid:
                qs = qs.filter(branch_id=bid)

        qs = apply_filters(self, request, qs)
        return qs


    def get(self, request):
        qs = self._get_queryset(request)
        return paginate_queryset(qs, request, ExamListSerializer)

    def post(self, request):
        user = request.user
        role = _user_role(user)
        if role not in EXAM_CREATE_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = ExamCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        branch_id = _user_branch_id(user)
        if not branch_id:
            batch = serializer.validated_data.get('batch')
            if batch:
                branch_id = batch.branch_id
            else:
                branch_id = request.data.get('branch_id') or request.data.get('branch')
        if not branch_id:
            return Response({'success': False, 'message': 'Branch is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            exam = serializer.save(created_by=user, branch_id=branch_id)
        except Exception as e:
            logger.error(f"Exam creation error: {e}")
            return Response({'success': False, 'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Ensure paper checkers are added to the exam (populates M2M using available checkers
        # or fallback to faculty/creator if none configured). This fixes paper checkers
        # not being associated with the exam for visibility in paper_checker role queries
        # and for auto-assignment of marksheets.
        try:
            assign_papers_to_checker(exam.id)
        except Exception as e:
            logger.warning(f"Failed to auto-assign paper checkers for new exam {exam.id}: {e}")

        return Response({
            'success': True, 'message': 'Exam created.',
            'data': ExamListSerializer(exam).data,
        }, status=status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. GET, PATCH, DELETE  /api/v1/exams/{id}/
# ═══════════════════════════════════════════════════════════════════════════════

class ExamDetailView(APIView):
    # permission_classes = [IsAuthenticated]

    def _get_exam(self, request, exam_id):
        try:
            qs = Exam.objects.filter(is_deleted=False)
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            return qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return None

    def get(self, request, exam_id):
        exam = self._get_exam(request, exam_id)
        if exam is None:
            return Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': ExamListSerializer(exam).data})

    def patch(self, request, exam_id):
        role = _user_role(request.user)
        if role not in EXAM_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        exam = self._get_exam(request, exam_id)
        if exam is None:
            return Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)

        if exam.status in ['ongoing', 'completed', 'results_published']:
            return Response({'success': False, 'message': 'Cannot edit exam in current status.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ExamCreateSerializer(exam, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response({'success': True, 'message': 'Exam updated.', 'data': ExamListSerializer(exam).data})

    def delete(self, request, exam_id):
        role = _user_role(request.user)
        if role not in EXAM_DELETE_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        exam = self._get_exam(request, exam_id)
        if exam is None:
            return Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)

        if ExamSession.objects.filter(exam=exam).exists():
            return Response({'success': False, 'message': 'Cannot delete exam with active sessions.'}, status=status.HTTP_400_BAD_REQUEST)

        exam.is_deleted = True
        exam.save()
        return Response({'success': True, 'message': 'Exam deleted.'})


class SubjectPaperListCreateView(APIView):
    """GET/POST /api/v1/subjects/<subject_id>/papers/ — Manage reusable subject papers."""

    def get(self, request, subject_id):
        from batches.models import Subject
        try:
            subject = Subject.objects.get(id=subject_id)
        except Subject.DoesNotExist:
            return Response({'success': False, 'message': 'Subject not found.'}, status=status.HTTP_404_NOT_FOUND)
        papers = SubjectPaper.objects.filter(subject=subject)
        return Response({'success': True, 'data': SubjectPaperSerializer(papers, many=True).data})

    def post(self, request, subject_id):
        from batches.models import Subject
        try:
            subject = Subject.objects.get(id=subject_id)
        except Subject.DoesNotExist:
            return Response({'success': False, 'message': 'Subject not found.'}, status=status.HTTP_404_NOT_FOUND)

        role = _user_role(request.user)
        if role not in EXAM_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        data = request.data.copy()
        data['subject'] = str(subject_id)
        serializer = SubjectPaperSerializer(data=data)
        if serializer.is_valid():
            paper = serializer.save()
            # Auto-set set_name from the uploaded filename if left blank
            if not paper.set_name and paper.file:
                import os
                paper.set_name = os.path.splitext(os.path.basename(paper.file.name))[0]
                paper.save(update_fields=['set_name'])
            return Response({'success': True, 'data': SubjectPaperSerializer(paper).data}, status=status.HTTP_201_CREATED)
        return Response({'success': False, 'message': 'Validation failed.', 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class SubjectPaperDetailView(APIView):
    """GET/PATCH/DELETE /api/v1/subjects/<subject_id>/papers/<paper_id>/"""

    def _get_paper(self, subject_id, paper_id):
        try:
            return SubjectPaper.objects.get(id=paper_id, subject_id=subject_id)
        except SubjectPaper.DoesNotExist:
            return None

    def get(self, request, subject_id, paper_id):
        paper = self._get_paper(subject_id, paper_id)
        if not paper:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': SubjectPaperSerializer(paper).data})

    def patch(self, request, subject_id, paper_id):
        paper = self._get_paper(subject_id, paper_id)
        if not paper:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        role = _user_role(request.user)
        if role not in EXAM_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        serializer = SubjectPaperSerializer(paper, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({'success': True, 'data': serializer.data})
        return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, subject_id, paper_id):
        paper = self._get_paper(subject_id, paper_id)
        if not paper:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        role = _user_role(request.user)
        if role not in EXAM_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        paper.delete()
        return Response({'success': True, 'message': 'Paper deleted.'})


class QuestionView(APIView):
    # permission_classes = [IsAuthenticated]


    def get(self, request, exam_id):
        role = _user_role(request.user)
        try:
            qs = Exam.objects.filter(is_deleted=False)
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

        questions = Question.objects.filter(exam=exam).prefetch_related('choices')

        if role == 'student':
            try:
                from students.models import Student
                sp = Student.objects.get(user=request.user)
                # Only allow question fetch if student has an active session for this exam
                if not ExamSession.objects.filter(exam=exam, student=sp).exists() or exam.status not in ('ongoing', 'completed'):
                    return Response({'success': False, 'message': 'Exam session not active'}, status=status.HTTP_403_FORBIDDEN)
                return Response(QuestionStudentSerializer(questions, many=True).data)
            except Student.DoesNotExist:
                logger.error(f"No Student profile for user {request.user.email} trying to access questions")
                return Response({'success': False, 'message': 'Student profile not found'}, status=status.HTTP_403_FORBIDDEN)
            except Exception as e:
                logger.error(f"Student question access error: {e}")
                return Response({'success': False, 'message': 'Student profile error'}, status=status.HTTP_403_FORBIDDEN)
        elif role in ['super_admin', 'branch_manager', 'admin_senior_executive', 'admin_executive']:
            return Response(QuestionSerializer(questions, many=True).data)
        elif role == 'faculty' and exam.created_by == request.user:
            return Response(QuestionSerializer(questions, many=True).data)
        
        return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)


    def post(self, request, exam_id):
        role = _user_role(request.user)
        try:
            qs = Exam.objects.filter(is_deleted=False)
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

        is_assigned_faculty = False
        if role == 'faculty':
            is_assigned_faculty = hasattr(exam, 'faculty') and exam.faculty and getattr(exam.faculty, 'user', None) == request.user
 
        if role not in ['super_admin', 'admin_senior_executive'] and not (exam.created_by == request.user or is_assigned_faculty):
            return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
 

        serializer = QuestionInputSerializer(data=request.data, many=True)
        if not serializer.is_valid():
            return Response({'success': False, 'message': 'Validation failed', 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            created_qs = []
            for q_data in serializer.validated_data:
                q = Question.objects.create(
                    exam=exam, question_text=q_data['question_text'],
                    question_type=q_data['question_type'], marks=q_data['marks'],
                    order=q_data['order']
                )
                for c_data in q_data.get('choices', []):
                    Choice.objects.create(
                        question=q, choice_text=c_data['text'],
                        is_correct=c_data['is_correct']
                    )
                created_qs.append(q)
            # Signals will auto-trigger, but explicitly recalculate once at end for efficiency
            exam.recalculate_total_marks()
        
        return Response({
            'success': True, 
            'message': 'Questions added. total_marks auto-updated.',
            'total_marks': exam.total_marks,
            'questions_count': len(created_qs)
        }, status=status.HTTP_201_CREATED)


class QuestionDetailView(APIView):
    """PATCH, DELETE /api/v1/exams/{exam_id}/questions/{question_id}/"""
    # permission_classes = [IsAuthenticated]

    def _get_question(self, request, exam_id, question_id):
        role = _user_role(request.user)
        try:
            qs = Exam.objects.filter(is_deleted=False)
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return None, None, Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)
        is_assigned_faculty = False
        if role == 'faculty':
            is_assigned_faculty = hasattr(exam, 'faculty') and exam.faculty and getattr(exam.faculty, 'user', None) == request.user
        if role not in ['super_admin', 'admin_senior_executive'] and not (exam.created_by == request.user or is_assigned_faculty):
            return None, None, Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if exam.status in ['ongoing', 'completed', 'results_published']:
            return None, None, Response({'success': False, 'message': 'Cannot modify questions in current exam status.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            q = Question.objects.get(id=question_id, exam=exam)
        except Question.DoesNotExist:
            return None, None, Response({'success': False, 'message': 'Question not found.'}, status=status.HTTP_404_NOT_FOUND)
        return exam, q, None

    def patch(self, request, exam_id, question_id):
        exam, q, err = self._get_question(request, exam_id, question_id)
        if err:
            return err
        for field in ['question_text', 'question_type', 'marks', 'order']:
            if field in request.data:
                setattr(q, field, request.data[field])
        q.save()
        
        if 'choices' in request.data:
            from .models import Choice
            q.choices.all().delete()
            for c_data in request.data['choices']:
                Choice.objects.create(
                    question=q, choice_text=c_data.get('text', ''),
                    is_correct=c_data.get('is_correct', False)
                )

        exam.recalculate_total_marks()  # auto-update total_marks via signal or explicit
        return Response({'success': True, 'message': 'Question updated.', 'data': QuestionSerializer(q).data, 'total_marks': exam.total_marks})

    def delete(self, request, exam_id, question_id):
        exam, q, err = self._get_question(request, exam_id, question_id)
        if err:
            return err
        q.delete()
        exam.recalculate_total_marks()  # trigger via signal or explicit after delete
        return Response({
            'success': True, 
            'message': 'Question deleted. total_marks auto-updated.',
            'total_marks': exam.total_marks
        }, status=status.HTTP_200_OK)


class SeatingView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request, exam_id):
        role = _user_role(request.user)
        if role not in ['super_admin', 'exam_supervisor', 'admin_senior_executive', 'branch_manager']:
            return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        seats = SeatArrangement.objects.filter(exam_id=exam_id).select_related('student__user')
        if getattr(request.user, 'organization', None):
            seats = seats.filter(exam__branch__organization=request.user.organization)
        return Response(SeatArrangementSerializer(seats, many=True).data)

    def post(self, request, exam_id):
        role = _user_role(request.user)
        if role not in SEATING_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        
        try:
            qs = Exam.objects.filter(is_deleted=False)
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Auto-assign: POST {"auto": true}
        is_auto = isinstance(request.data, dict) and request.data.get('auto')
        if is_auto:
            from students.models import Student
            students = list(Student.objects.filter(batch=exam.batch).order_by('user__name'))
            SeatArrangement.objects.filter(exam=exam).delete()
            created = []
            for i, st in enumerate(students):
                created.append(SeatArrangement(
                    exam=exam, student=st, room_name='Auto Room',
                    seat_number=f'S-{i+1}', assigned_by=request.user,
                ))
            SeatArrangement.objects.bulk_create(created)
            return Response({'success': True, 'message': f'Auto-assigned {len(created)} seats.'}, status=status.HTTP_201_CREATED)

        # Manual assign: POST [ {student_id, room_name, seat_number}, ... ]
        data = request.data if isinstance(request.data, list) else [request.data]
        serializer = SeatInputSerializer(data=data, many=True)
        if not serializer.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        
        created = []
        for item in serializer.validated_data:
            if SeatArrangement.objects.filter(exam=exam, room_name=item['room_name'], seat_number=item['seat_number']).exists():
                return Response({'success': False, 'message': f"Duplicate seat: {item['room_name']}/{item['seat_number']}"}, status=status.HTTP_400_BAD_REQUEST)
            created.append(SeatArrangement(
                exam=exam, student_id=item['student_id'],
                room_name=item['room_name'], seat_number=item['seat_number'],
                row_number=item.get('row_number'), assigned_by=request.user,
            ))
        SeatArrangement.objects.bulk_create(created)
        return Response({'success': True, 'message': f'Assigned {len(created)} seats.'}, status=status.HTTP_201_CREATED)


class SeatingDetailView(APIView):
    """PATCH, DELETE /api/v1/exams/{exam_id}/seating/{seat_id}/"""
    # permission_classes = [IsAuthenticated]

    def _get_seat(self, request, exam_id, seat_id):
        role = _user_role(request.user)
        if role not in SEATING_EDIT_ROLES:
            return None, Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = SeatArrangement.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(exam__branch__organization=request.user.organization)
            seat = qs.get(id=seat_id, exam_id=exam_id)
        except SeatArrangement.DoesNotExist:
            return None, Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return seat, None

    def patch(self, request, exam_id, seat_id):
        seat, err = self._get_seat(request, exam_id, seat_id)
        if err:
            return err
        for field in ['room_name', 'seat_number', 'row_number']:
            if field in request.data:
                setattr(seat, field, request.data[field])
        seat.save()
        return Response({'success': True, 'message': 'Seat updated.', 'data': SeatArrangementSerializer(seat).data})

    def delete(self, request, exam_id, seat_id):
        seat, err = self._get_seat(request, exam_id, seat_id)
        if err:
            return err
        seat.delete()
        return Response({'success': True, 'message': 'Seat removed.'}, status=status.HTTP_200_OK)


class ExamStartView(APIView):
    # permission_classes = [IsAuthenticated]


    def post(self, request, exam_id):
        if _user_role(request.user) != 'student':
            return Response({'success': False, 'message': 'Only students can start exams.'}, status=status.HTTP_403_FORBIDDEN)

        # Validate full request body up front via ExamStartSerializer
        ser = ExamStartSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Invalid start data.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        lat = ser.validated_data.get('student_lat')
        lon = ser.validated_data.get('student_lon')
        # Prefer body fingerprint; fall back to X-Device-Fingerprint header
        fingerprint = ser.validated_data.get('device_fingerprint') or request.headers.get('X-Device-Fingerprint', '')
        # if not fingerprint:
        #     logger.warning(f"Exam start without device fingerprint — user={request.user.email}")
        # Prefer body IP; fall back to REMOTE_ADDR
        ip_address = ser.validated_data.get('ip_address') or request.META.get('REMOTE_ADDR')

        try:
            from students.models import Student
            from batches.models import BatchStudent
            student = Student.objects.get(user=request.user)
            enrolled_batch_ids = list(BatchStudent.objects.filter(student=student).values_list('batch_id', flat=True))
            if student.batch_id and student.batch_id not in enrolled_batch_ids:
                enrolled_batch_ids.append(student.batch_id)
        except Exception:
            return Response({'success': False, 'message': 'Student profile not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            qs = Exam.objects.filter(is_deleted=False)
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)

        if exam.batch_id not in enrolled_batch_ids:
            return Response({'success': False, 'message': 'Not enrolled in this exam batch'}, status=status.HTTP_403_FORBIDDEN)
        # if exam.status != 'scheduled':
        if exam.status not in ['scheduled', 'ongoing']:
            return Response({'success': False, 'message': 'Exam is not scheduled'}, status=status.HTTP_403_FORBIDDEN)
        
        now = timezone.now()
        dt_start = timezone.make_aware(timezone.datetime.combine(exam.scheduled_date, exam.start_time))
        dt_end = timezone.make_aware(timezone.datetime.combine(exam.scheduled_date, exam.end_time))
        
        # REMOVED TIME VALIDATION AS REQUESTED
        # if not (dt_start <= now <= dt_end):
        #     return Response({'success': False, 'message': 'Exam is not currently active'}, status=status.HTTP_403_FORBIDDEN)
        
        if ExamSession.objects.filter(exam=exam, student=student).exists():
            return Response({'success': False, 'message': 'Session already exists'}, status=status.HTTP_409_CONFLICT)

        if exam.geo_radius_meters > 0:
            if not lat or not lon:
                return Response({'success': False, 'message': 'Location required for geo check'}, status=status.HTTP_400_BAD_REQUEST)
            allowed, dist = check_geo_boundary(exam, lat, lon)
            if not allowed:
                return Response({
                    'success': False,
                    'message': 'You are outside the allowed exam zone.',
                    'distance_m': dist, 'allowed_m': exam.geo_radius_meters,
                }, status=status.HTTP_403_FORBIDDEN)

        session = ExamSession.objects.create(
            exam=exam, student=student,
            device_fingerprint=fingerprint,
            ip_address=ip_address,
            student_lat=lat,
            student_lon=lon,
            last_geo_check_at=timezone.now() if exam.geo_radius_meters > 0 else None,
        )

        # Round-robin paper assignment from exam's selected_papers
        papers = list(exam.selected_papers.order_by('set_name').values_list('id', flat=True))
        if papers:
            # Count how many sessions already have each paper assigned
            from django.db.models import Count
            sessions_count = ExamSession.objects.filter(
                exam=exam, assigned_paper__isnull=False
            ).values('assigned_paper').annotate(cnt=Count('id'))
            paper_counts = {str(row['assigned_paper']): row['cnt'] for row in sessions_count}
            # Pick the paper with the lowest assignment count (round-robin)
            chosen_paper_id = min(papers, key=lambda pid: paper_counts.get(str(pid), 0))
            session.assigned_paper_id = chosen_paper_id
            session.save(update_fields=['assigned_paper_id'])

        # update exam status if first student
        if exam.status == 'scheduled':
            exam.status = 'ongoing'
            exam.save(update_fields=['status'])

        questions = Question.objects.filter(exam=exam).prefetch_related('choices')
        
        return Response({
            'session_id': session.id,
            'remaining_seconds': exam.duration_minutes * 60,
            'autosave_interval_seconds': 30,
            'geo_check_interval_minutes': exam.geo_check_interval_minutes,
            'exam_title': exam.title,
            'total_marks': exam.total_marks,
            'questions': QuestionStudentSerializer(questions, many=True).data,
        })


class ExamSubmitView(APIView):
    # permission_classes = [IsAuthenticated]


    def post(self, request, exam_id):
        if _user_role(request.user) != 'student':
            return Response({'success': False, 'message': 'Only students can submit'}, status=status.HTTP_403_FORBIDDEN)

        ser = ExamSubmitSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Invalid data'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            qs = ExamSession.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(exam__branch__organization=request.user.organization)
            session = qs.get(id=ser.validated_data['session_id'], exam_id=exam_id)
        except ExamSession.DoesNotExist:
            return Response({'success': False, 'message': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)

        if session.student.user != request.user:
            return Response({'success': False, 'message': 'Not your session'}, status=status.HTTP_403_FORBIDDEN)
        if session.is_submitted:
            return Response({'success': False, 'message': 'Already submitted'}, status=status.HTTP_409_CONFLICT)

        # Upsert answers
        for ans in ser.validated_data.get('answers', []):
            StudentAnswer.objects.update_or_create(
                session=session, question_id=ans['question_id'],
                defaults={
                    'selected_choice_id': ans.get('selected_choice_id'),
                    'text_answer': ans.get('text_answer', '')
                }
            )

        now = timezone.now()
        deadline = session.started_at + timezone.timedelta(minutes=session.exam.duration_minutes)
        if now > deadline:
            session.auto_submitted = True

        from .utils import auto_grade_mcq
        has_subj = Question.objects.filter(exam_id=exam_id, question_type='subjective').exists()
        
        session.is_submitted = True
        session.submitted_at = now
        session.save()

        if not has_subj:
            marks, pct, passed = auto_grade_mcq(session.id)
            if session.exam.result_release_mode == 'instant':
                return Response({'submitted': True, 'marks_obtained': marks, 'percentage': pct, 'is_pass': passed})
            else:
                return Response({'submitted': True, 'message': 'Answers submitted. Results will be released by the faculty.'})
        else:
            from results.models import MarkSheet
            # Create MarkSheet but delay paper_checker assignment until exam completion
            # (all marksheets submitted/absent-marked). This matches user request.
            MarkSheet.objects.get_or_create(
                exam=session.exam,
                student=session.student,
                defaults={'is_submitted': True, 'checked_at': timezone.now()}
            )
            assign_papers_to_checker(session.exam.id)
            return Response({'submitted': True, 'message': 'Answers submitted. Results pending review by assigned checker.'})


class AutosaveView(APIView):
    # permission_classes = [IsAuthenticated]


    def post(self, request, exam_id, session_id):
        if _user_role(request.user) != 'student':
            return Response({'success': False, 'message': 'Only students can autosave'}, status=status.HTTP_403_FORBIDDEN)
        
        ser = AutosaveSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Invalid data'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            qs = ExamSession.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(exam__branch__organization=request.user.organization)
            session = qs.get(id=session_id, exam_id=exam_id)
        except ExamSession.DoesNotExist:
            return Response({'success': False, 'message': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
            
        if session.student.user != request.user or session.is_submitted:
            return Response({'success': False, 'message': 'Cannot autosave'}, status=status.HTTP_403_FORBIDDEN)

        StudentAnswer.objects.update_or_create(
            session=session, question_id=ser.validated_data['question_id'],
            defaults={
                'selected_choice_id': ser.validated_data.get('selected_choice_id'),
                'text_answer': ser.validated_data.get('text_answer', '')
            }
        )
        
        remaining = max(0, int((session.started_at + timezone.timedelta(minutes=session.exam.duration_minutes) - timezone.now()).total_seconds()))
        return Response({'saved': True, 'question_id': ser.validated_data['question_id'], 'remaining_seconds': remaining})


class ScreenEventView(APIView):
    """v2: configurable per-exam screen_lock_action / split_screen_action (FRD §4.6.1)."""
    # permission_classes = [IsAuthenticated]

    def post(self, request, exam_id, session_id):
        if _user_role(request.user) != 'student':
            return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        ser = ScreenEventSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Invalid event'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            qs = ExamSession.objects.select_related('exam').all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(exam__branch__organization=request.user.organization)
            session = qs.get(id=session_id, exam_id=exam_id, student__user=request.user)
        except ExamSession.DoesNotExist:
            return Response({'success': False, 'message': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

        event = ser.validated_data['event']
        exam = session.exam
        action = 'logged'
        res = {'event_logged': True}

        if event == 'lock_breach':
            session.screen_lock_violations += 1
            count = session.screen_lock_violations
            max_v = exam.screen_lock_max_violations
            if count < max_v:
                action = 'warning_issued'
                res.update({'warning': True, 'violations': count, 'remaining_before_action': max_v - count})
            else:
                if exam.screen_lock_action == 'auto_submit':
                    auto_submit_session(session)
                    action = 'auto_submitted'
                    res.update({'auto_submitted': True, 'reason': 'Screen lock violation limit reached'})
                else:
                    action = 'flagged'
                    res.update({'flagged': True, 'message': 'Violation logged. Admin will review.'})

        elif event == 'split_screen':
            session.split_screen_warnings += 1
            count = session.split_screen_warnings
            max_w = exam.split_screen_max_warnings
            if count < max_w:
                action = 'warning_issued'
                res.update({'warning': True, 'warnings': count, 'remaining_before_action': max_w - count})
            else:
                if exam.split_screen_action == 'auto_submit':
                    auto_submit_session(session)
                    action = 'auto_submitted'
                    res.update({'auto_submitted': True, 'reason': 'Split-screen violation limit reached'})
                else:
                    action = 'flagged'
                    res.update({'flagged': True, 'message': 'Split-screen logged. Admin will review.'})

        session.save()
        ScreenEvent.objects.create(session=session, event_type=event, action_taken=action)
        res['action'] = action
        return Response(res)


class GeoCheckView(APIView):
    """v2 NEW: periodic geo-check during exam (FRD §4.6.1)."""
    # permission_classes = [IsAuthenticated]

    def post(self, request, exam_id, session_id):
        if _user_role(request.user) != 'student':
            return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        try:
            qs = ExamSession.objects.select_related('exam').all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(exam__branch__organization=request.user.organization)
            session = qs.get(id=session_id, exam_id=exam_id, student__user=request.user)
        except ExamSession.DoesNotExist:
            return Response({'success': False, 'message': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

        if session.is_submitted:
            return Response({'success': False, 'message': 'Session already submitted'}, status=status.HTTP_409_CONFLICT)

        exam = session.exam
        if exam.geo_check_interval_minutes == 0:
            return Response({'success': False, 'message': 'Geo checks not enabled for this exam'}, status=status.HTTP_400_BAD_REQUEST)

        ser = GeoCheckSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        lat = ser.validated_data['student_lat']
        lon = ser.validated_data['student_lon']
        allowed, dist = check_geo_boundary(exam, lat, lon)

        session.last_geo_check_at = timezone.now()
        session.student_lat = lat
        session.student_lon = lon
        session.save(update_fields=['last_geo_check_at', 'student_lat', 'student_lon'])

        if not allowed:
            ScreenEvent.objects.create(
                session=session, event_type='lock_breach',
                action_taken='flagged',
            )
            return Response({
                'error': 'Location check failed. You are outside the exam zone.',
                'distance_m': dist, 'allowed_m': exam.geo_radius_meters, 'action': 'flagged',
            }, status=status.HTTP_403_FORBIDDEN)

        return Response({'geo_check': 'passed', 'distance_m': dist})


class AnswerKeyDistributeView(APIView):
    # permission_classes = [IsAuthenticated]

    def post(self, request, exam_id):
        role = _user_role(request.user)
        if role not in ['super_admin', 'admin_senior_executive', 'branch_manager']:
            return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
            
        from results.models import MarkSheet
        checkers = set(MarkSheet.objects.filter(exam_id=exam_id, paper_checker__isnull=False).values_list('paper_checker_id', flat=True))
        
        if not checkers:
            return Response({'success': False, 'message': 'No checkers assigned'}, status=status.HTTP_400_BAD_REQUEST)
            
        sent = []
        try:
            qs = Exam.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
        for cid in checkers:
            checker = get_user_model().objects.get(id=cid)
            log = AnswerKeyDistributionLog.objects.create(
                exam_id=exam_id, sent_to=checker,
                link_expires=timezone.now() + timezone.timedelta(hours=48)
            )
            token = hashlib.sha256(f"{log.id}{django_settings.SECRET_KEY}".encode()).hexdigest()
            url = f"/api/v1/answer-key/{exam_id}/?token={log.id}_{token}"
            send_answer_key_email(checker, exam, url)
            sent.append(checker.name)
            
        return Response({'sent_to': sent, 'count': len(sent)})


class AnswerKeyView(APIView):
    permission_classes = [AllowAny] # EXEMPT from auth

    def get(self, request, exam_id):
        token_param = request.query_params.get('token')
        if not token_param or '_' not in token_param:
            return Response({'success': False, 'message': 'Invalid token'}, status=status.HTTP_403_FORBIDDEN)
            
        log_id, token_hash = token_param.split('_', 1)
        try:
            log = AnswerKeyDistributionLog.objects.get(id=log_id, exam_id=exam_id)
        except:
            return Response({'success': False, 'message': 'Invalid link'}, status=status.HTTP_403_FORBIDDEN)
            
        expected = hashlib.sha256(f"{log.id}{django_settings.SECRET_KEY}".encode()).hexdigest()
        if token_hash != expected:
            return Response({'success': False, 'message': 'Token tampered'}, status=status.HTTP_403_FORBIDDEN)
            
        if timezone.now() > log.link_expires:
            return Response({'success': False, 'message': 'Link expired'}, status=status.HTTP_403_FORBIDDEN)
            
        questions = Question.objects.filter(exam_id=exam_id).prefetch_related('choices')
        return Response(QuestionSerializer(questions, many=True).data)


class MalpracticeView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request, exam_id):
        role = _user_role(request.user)
        if role not in ['super_admin', 'exam_supervisor', 'admin_senior_executive', 'branch_manager']:
            return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        reps = MalpracticeReport.objects.filter(exam_id=exam_id).select_related('student__user', 'reported_by')
        if getattr(request.user, 'organization', None):
            reps = reps.filter(exam__branch__organization=request.user.organization)
        return Response(MalpracticeSerializer(reps, many=True).data)


    def post(self, request, exam_id):
        if _user_role(request.user) not in ['super_admin', 'exam_supervisor']:
            return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
            
        qs = Exam.objects.all()
        if getattr(request.user, 'organization', None):
            qs = qs.filter(branch__organization=request.user.organization)
        if not qs.filter(id=exam_id).exists():
            return Response({'success': False, 'message': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)

        ser = MalpracticeInputSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Invalid data'}, status=status.HTTP_400_BAD_REQUEST)
            
        rep = MalpracticeReport.objects.create(
            exam_id=exam_id, student_id=ser.validated_data['student_id'],
            reported_by=request.user, description=ser.validated_data['description'],
            severity=ser.validated_data['severity']
        )
        
        if rep.severity == 'disqualified':
            sess = ExamSession.objects.filter(exam_id=exam_id, student_id=rep.student_id).first()
            if sess:
                auto_submit_session(sess)
                
        return Response({'success': True, 'report_id': rep.id})


class MalpracticeDetailView(APIView):
    """PATCH, DELETE /api/v1/exams/{exam_id}/malpractice/{report_id}/"""
    # permission_classes = [IsAuthenticated]

    def _get_report(self, request, exam_id, report_id):
        role = _user_role(request.user)
        if role not in MALPRACTICE_VIEW_ROLES:
            return None, Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = MalpracticeReport.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(exam__branch__organization=request.user.organization)
            rep = qs.get(id=report_id, exam_id=exam_id)
        except MalpracticeReport.DoesNotExist:
            return None, Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return rep, None

    def patch(self, request, exam_id, report_id):
        """Update action_taken or severity on a malpractice report."""
        rep, err = self._get_report(request, exam_id, report_id)
        if err:
            return err
        for field in ['action_taken', 'severity', 'description']:
            if field in request.data:
                setattr(rep, field, request.data[field])
        rep.save()
        return Response({'success': True, 'message': 'Report updated.', 'data': MalpracticeSerializer(rep).data})

    def delete(self, request, exam_id, report_id):
        rep, err = self._get_report(request, exam_id, report_id)
        if err:
            return err
        if _user_role(request.user) not in ['super_admin', 'admin_senior_executive']:
            return Response({'success': False, 'message': 'Only super_admin or ASE can delete.'}, status=status.HTTP_403_FORBIDDEN)
        rep.delete()
        return Response({'success': True, 'message': 'Report deleted.'}, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. POST  /api/v1/exams/{exam_id}/schedule/  — transition draft → scheduled
# ═══════════════════════════════════════════════════════════════════════════════

class ExamScheduleView(APIView):
    """Dedicated API to schedule an exam (sets status='scheduled').
    Can only be done on 'draft' exams with future scheduled_date.
    """

    def post(self, request, exam_id):
        role = _user_role(request.user)
        if role not in EXAM_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            qs = Exam.objects.filter(is_deleted=False)
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)

        if exam.status != 'draft':
            return Response({
                'success': False,
                'message': f'Cannot schedule exam. Current status is "{exam.status}". Must be "draft".'
            }, status=status.HTTP_400_BAD_REQUEST)

        if exam.scheduled_date < timezone.now().date():
            return Response({
                'success': False,
                'message': 'Cannot schedule an exam for a past date.'
            }, status=status.HTTP_400_BAD_REQUEST)

        exam.status = 'scheduled'
        exam.save(update_fields=['status'])

        # Ensure paper checkers M2M is populated when scheduling (if not done at create)
        try:
            exam.ensure_paper_checkers()
        except Exception as e:
            logger.warning(f"Failed to ensure paper checkers on schedule for exam {exam_id}: {e}")

        return Response({
            'success': True,
            'message': 'Exam has been scheduled successfully.',
            'data': ExamListSerializer(exam).data
        })
