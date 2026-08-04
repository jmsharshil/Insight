import logging
from core.pagination import paginate_queryset
import uuid
import hashlib
from django.utils import timezone
import decimal
from django.db import transaction
from django.db.models import Q
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from core.utils import apply_filters, get_user_branch_id, get_user_branch_ids, has_user_branch_access

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
    calculate_ranks, build_absolute_url,
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


# ═══════════════════════════════════════════════════════════════════════════════
# 1. GET & POST  /api/v1/exams/
# ═══════════════════════════════════════════════════════════════════════════════

class ExamListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['exam_mode', 'exam_type', 'status', 'batch_id', 'scheduled_date','branch_id','subject_id']
    search_fields = ['title']
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
            branch_ids = get_user_branch_ids(user)
            if branch_ids:
                qs = qs.filter(branch_id__in=branch_ids)
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
            branch_ids = get_user_branch_ids(user)
            if branch_ids:
                qs = qs.filter(branch_id__in=branch_ids)

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

        branch_id = get_user_branch_id(user)
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

        # Send notifications
        from .services import notify_exam_scheduled
        try:
            notify_exam_scheduled(exam)
        except Exception as e:
            logger.error(f"Failed to send exam schedule notifications for exam {exam.id}: {e}")

        return Response({
            'success': True, 'message': 'Exam created.',
            'data': ExamListSerializer(exam, context={'request': request}).data,
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
        return Response({'success': True, 'data': ExamListSerializer(exam, context={'request': request}).data})

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
        return Response({'success': True, 'message': 'Exam updated.', 'data': ExamListSerializer(exam, context={'request': request}).data})
        
    def put(self, request, exam_id):
        # Handle PUT as a full update or alias to patch to be forgiving
        role = _user_role(request.user)
        if role not in EXAM_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        exam = self._get_exam(request, exam_id)
        if exam is None:
            return Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)

        if exam.status in ['ongoing', 'completed', 'results_published']:
            return Response({'success': False, 'message': 'Cannot edit exam in current status.'}, status=status.HTTP_400_BAD_REQUEST)

        # Using partial=True here as well to be forgiving to clients that use PUT for partial updates
        serializer = ExamCreateSerializer(exam, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response({'success': True, 'message': 'Exam updated.', 'data': ExamListSerializer(exam, context={'request': request}).data})

    def delete(self, request, exam_id):
        role = _user_role(request.user)
        if role not in EXAM_DELETE_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        exam = self._get_exam(request, exam_id)
        if exam is None:
            return Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)

        # if ExamSession.objects.filter(exam=exam).exists():
        #     return Response({'success': False, 'message': 'Cannot delete exam with active sessions.'}, status=status.HTTP_400_BAD_REQUEST)

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
                # Only allow question fetch if student has an active session for THIS exam
                active_sessions = ExamSession.objects.filter(exam=exam, student=sp)
                if not active_sessions.exists():
                    return Response({'success': False, 'message': 'Exam session not active'}, status=status.HTTP_403_FORBIDDEN)
                from .utils import group_questions
                return Response(group_questions(QuestionStudentSerializer(questions, many=True).data))
            except Student.DoesNotExist:
                logger.error(f"No Student profile for user {request.user.email} trying to access questions")
                return Response({'success': False, 'message': 'Student profile not found'}, status=status.HTTP_403_FORBIDDEN)
            except Exception as e:
                logger.error(f"Student question access error: {e}")
                return Response({'success': False, 'message': 'Student profile error'}, status=status.HTTP_403_FORBIDDEN)
        elif role in ['super_admin', 'branch_manager', 'admin_senior_executive', 'admin_executive', 'faculty']:
            from .utils import group_questions
            return Response(group_questions(QuestionSerializer(questions, many=True).data))
        
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

        if role not in ['super_admin', 'admin_senior_executive', 'branch_manager', 'faculty']:
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
                    order=q_data['order'],
                    paragraph_text=q_data.get('paragraph_text', ''),
                )
                for c_data in q_data.get('choices', []):
                    Choice.objects.create(
                        question=q, choice_text=c_data['text'],
                        is_correct=c_data['is_correct']
                    )
                created_qs.append(q)
            # recalculate_total_marks is handled by signals
        
        return Response({
            'success': True, 
            'message': 'Questions added. total_marks auto-updated.',
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

        if role not in ['super_admin', 'admin_senior_executive', 'branch_manager', 'faculty']:
            return None, None, Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            q = Question.objects.get(id=question_id, exam=exam)
        except Question.DoesNotExist:
            return None, None, Response({'success': False, 'message': 'Question not found.'}, status=status.HTTP_404_NOT_FOUND)
        return exam, q, None

    def patch(self, request, exam_id, question_id):
        exam, q, err = self._get_question(request, exam_id, question_id)
        if err:
            return err
        for field in ['question_text', 'question_type', 'marks', 'order', 'paragraph_text']:
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

        return Response({'success': True, 'message': 'Question updated.', 'data': QuestionSerializer(q).data})

    def delete(self, request, exam_id, question_id):
        exam, q, err = self._get_question(request, exam_id, question_id)
        if err:
            return err
        q.delete()
        return Response({
            'success': True, 
            'message': 'Question deleted. total_marks auto-updated.'
        }, status=status.HTTP_200_OK)


class SubjectQuestionBankView(APIView):
    def get(self, request, subject_id):
        role = _user_role(request.user)
        if role not in ['super_admin', 'branch_manager', 'admin_senior_executive', 'admin_executive', 'faculty']:
            return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        from batches.models import Subject
        try:
            subject = Subject.objects.get(id=subject_id)
        except Subject.DoesNotExist:
            return Response({'success': False, 'message': 'Subject not found'}, status=status.HTTP_404_NOT_FOUND)

        questions = Question.objects.filter(subject=subject).prefetch_related('choices')
        from .utils import group_questions
        return Response(group_questions(QuestionSerializer(questions, many=True).data))

    def post(self, request, subject_id):
        role = _user_role(request.user)
        if role not in ['super_admin', 'admin_senior_executive', 'branch_manager', 'faculty']:
            return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        from batches.models import Subject
        try:
            subject = Subject.objects.get(id=subject_id)
        except Subject.DoesNotExist:
            return Response({'success': False, 'message': 'Subject not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = QuestionInputSerializer(data=request.data, many=True)
        if not serializer.is_valid():
            return Response({'success': False, 'message': 'Validation failed', 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            created_qs = []
            for q_data in serializer.validated_data:
                q = Question.objects.create(
                    subject=subject, question_text=q_data['question_text'],
                    question_type=q_data['question_type'], marks=q_data['marks'],
                    order=q_data['order'],
                    paragraph_text=q_data.get('paragraph_text', ''),
                )
                for c_data in q_data.get('choices', []):
                    Choice.objects.create(
                        question=q, choice_text=c_data['text'],
                        is_correct=c_data['is_correct']
                    )
                created_qs.append(q)
        
        return Response({
            'success': True, 
            'message': 'Questions added to subject bank.',
            'questions_count': len(created_qs)
        }, status=status.HTTP_201_CREATED)


class SubjectQuestionBankDetailView(APIView):
    def _get_question(self, request, subject_id, question_id):
        role = _user_role(request.user)
        if role not in ['super_admin', 'admin_senior_executive', 'branch_manager', 'faculty']:
            return None, Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            q = Question.objects.get(id=question_id, subject_id=subject_id)
        except Question.DoesNotExist:
            return None, Response({'success': False, 'message': 'Question not found.'}, status=status.HTTP_404_NOT_FOUND)
        return q, None

    def patch(self, request, subject_id, question_id):
        q, err = self._get_question(request, subject_id, question_id)
        if err:
            return err
        for field in ['question_text', 'question_type', 'marks', 'order', 'paragraph_text']:
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

        return Response({'success': True, 'message': 'Bank question updated.', 'data': QuestionSerializer(q).data})

    def delete(self, request, subject_id, question_id):
        q, err = self._get_question(request, subject_id, question_id)
        if err:
            return err
        q.delete()
        return Response({'success': True, 'message': 'Bank question deleted.'}, status=status.HTTP_200_OK)


class ExamImportQuestionsView(APIView):
    def post(self, request, exam_id):
        role = _user_role(request.user)
        if role not in ['super_admin', 'admin_senior_executive', 'branch_manager', 'faculty']:
            return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        try:
            qs = Exam.objects.filter(is_deleted=False)
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)

        question_ids = request.data.get('question_ids', [])
        if not question_ids:
            return Response({'success': False, 'message': 'Please provide a list of question_ids to import.'}, status=status.HTTP_400_BAD_REQUEST)

        questions_to_copy = Question.objects.filter(id__in=question_ids, subject__isnull=False)
        
        with transaction.atomic():
            created_count = 0
            for bank_q in questions_to_copy:
                new_q = Question.objects.create(
                    exam=exam,
                    question_text=bank_q.question_text,
                    question_type=bank_q.question_type,
                    marks=bank_q.marks,
                    order=bank_q.order,
                    paragraph_text=bank_q.paragraph_text
                )
                for c in bank_q.choices.all():
                    Choice.objects.create(
                        question=new_q, choice_text=c.choice_text, is_correct=c.is_correct
                    )
                created_count += 1

        return Response({
            'success': True, 
            'message': f'{created_count} questions imported into the exam.',
            'questions_count': created_count
        }, status=status.HTTP_201_CREATED)


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

        # Sanitize empty strings and stringified nulls from mobile frontend
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        for field in ['student_lat', 'student_lon', 'ip_address', 'device_fingerprint']:
            if field in data and str(data[field]).strip().lower() in ['', 'null', 'undefined', 'none']:
                data[field] = None

        # Validate full request body up front via ExamStartSerializer
        ser = ExamStartSerializer(data=data)
        if not ser.is_valid():
            logger.error(f"Exam start validation failed: {ser.errors} | Data: {data}")
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
            if lat is None or lon is None:
                return Response({'success': False, 'message': 'Location required for geo check'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                allowed, dist = check_geo_boundary(exam, lat, lon)
                if not allowed:
                    return Response({
                        'success': False,
                        'message': 'You are outside the allowed exam zone.',
                        'distance_m': dist, 'allowed_m': exam.geo_radius_meters,
                    }, status=status.HTTP_403_FORBIDDEN)
            except Exception as e:
                logger.error(f"Geo check failed for exam {exam_id}: {e}")
                # Continue without blocking (fail-open for geo to prevent 502 crashes)

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
        from .utils import group_questions
        
        return Response({
            'session_id': session.id,
            'remaining_seconds': exam.duration_minutes * 60,
            'autosave_interval_seconds': 30,
            'geo_check_interval_minutes': exam.geo_check_interval_minutes,
            'exam_title': exam.title,
            'exam_type': exam.exam_type,
            'exam_mode': exam.exam_mode,
            'exam_type_display': exam.get_exam_type_display(),
            'exam_mode_display': exam.get_exam_mode_display(),
            'total_marks': exam.total_marks,
            'questions': group_questions(QuestionStudentSerializer(questions, many=True).data),
        })


class ExamSubmitView(APIView):
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    # permission_classes = [IsAuthenticated]


    def post(self, request, exam_id):
        if _user_role(request.user) != 'student':
            return Response({'success': False, 'message': 'Only students can submit'}, status=status.HTTP_403_FORBIDDEN)

        # Make a mutable copy of the data
        if hasattr(request.data, 'copy'):
            data = request.data.copy()
        else:
            data = dict(request.data)

        # Parse answers if sent as JSON string (happens in multipart/form-data for offline exams)
        if 'answers' in data and isinstance(data['answers'], str):
            import json
            val = data['answers'].strip()
            if not val:
                data['answers'] = []
            else:
                try:
                    data['answers'] = json.loads(val)
                except json.JSONDecodeError:
                    return Response({'success': False, 'message': 'Invalid answers format', 'errors': {'answers': ['Must be valid JSON.']}}, status=status.HTTP_400_BAD_REQUEST)

        ser = ExamSubmitSerializer(data=data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Invalid data', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

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

        # Handle subjective file upload (supports offline/subjective per FRD)
        answer_sheet = request.FILES.get('answer_sheet') or ser.validated_data.get('answer_sheet')
        if answer_sheet:
            session.uploaded_answer_sheet = answer_sheet

        # Upsert answers (for MCQ + text answers; subjective may use file instead)
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

        from .utils import auto_grade_mcq, requires_paper_checking
        has_subj = Question.objects.filter(exam=session.exam, question_type='subjective').exists()
        
        session.is_submitted = True
        session.submitted_at = now
        session.save()

        if not requires_paper_checking(session.exam, has_subjective_questions=has_subj):
            marks, pct, passed = auto_grade_mcq(session.id)
            if session.exam.result_release_mode == 'instant':
                # Also call calculate_ranks for instant publish (per core decisions)
                calculate_ranks(session.exam.id)
                return Response({'submitted': True, 'marks_obtained': marks, 'percentage': pct, 'is_pass': passed})
            else:
                return Response({'submitted': True, 'message': 'Answers submitted. Results will be released by the faculty.'})
        else:
            from results.models import MarkSheet
            # Create MarkSheet and assign paper checker immediately
            MarkSheet.objects.get_or_create(
                exam=session.exam,
                student=session.student,
                defaults={'is_submitted': False, 'is_absent': False}
            )
            # Assign paper checker immediately per user request
            assign_papers_to_checker(session.exam.id)
            return Response({'submitted': True, 'message': 'Answers submitted (with optional answer sheet). Results pending review by assigned checker.'})


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


class ExamScreenEventsView(APIView):
    """v2: get all screen events for an exam."""
    # permission_classes = [IsAuthenticated]

    def get(self, request, exam_id):
        role = _user_role(request.user)
        if role not in ['super_admin', 'exam_supervisor', 'admin_senior_executive', 'branch_manager', 'faculty']:
            return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            qs = ScreenEvent.objects.select_related('session__student__user').all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(session__exam__branch__organization=request.user.organization)
            
            events = qs.filter(session__exam_id=exam_id).order_by('-occurred_at')
            event_description = ''

            data = []
            for event in events:
                student = event.session.student
                if event.event_type == 'lock_breach':
                    event_description = f"Student tried to switch screens or open new tabs"
                elif event.event_type == 'split_screen':
                    event_description = f"Student tried to open multiple screens"
                data.append({
                    "id": event.id,
                    "student_id": student.id,
                    "student_name": student.user.name if student and student.user else str(student.id),
                    "session_id": event.session.id,
                    "event_type": event.event_type,
                    "event_type_display": event.get_event_type_display(),
                    "event_description": event_description,
                    "action_taken": event.action_taken,
                    "action_taken_display": event.get_action_taken_display(),
                    "occurred_at": event.occurred_at,
                })
            return Response({'success': True, 'data': data})
        except Exception as e:
            return Response({'success': False, 'message': str(e)}, status=status.HTTP_400_BAD_REQUEST)


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
        try:
            allowed, dist = check_geo_boundary(exam, lat, lon)
        except Exception as e:
            logger.error(f"Periodic geo check failed for exam {exam_id}, session {session_id}: {e}")
            allowed = True  # fail-open
            dist = 0.0

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
            
        try:
            qs = Exam.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)

        # Get checkers from the exam's M2M relation
        checkers = set(exam.paper_checkers.values_list('id', flat=True))
        
        # Also include any assigned via MarkSheets (just in case)
        from results.models import MarkSheet
        marksheet_checkers = set(MarkSheet.objects.filter(exam_id=exam_id, paper_checker__isnull=False).values_list('paper_checker_id', flat=True))
        checkers.update(marksheet_checkers)
        
        if not checkers:
            return Response({'success': False, 'message': 'No checkers assigned'}, status=status.HTTP_400_BAD_REQUEST)
            
        sent = []
        for cid in checkers:
            checker = get_user_model().objects.get(id=cid)
            log = AnswerKeyDistributionLog.objects.create(
                exam_id=exam_id, sent_to=checker,
                link_expires=timezone.now() + timezone.timedelta(hours=48)
            )
            token = hashlib.sha256(f"{log.id}{django_settings.SECRET_KEY}".encode()).hexdigest()
            path = f"/api/v1/answer-key/{exam_id}/?token={log.id}_{token}"
            url = build_absolute_url(path, request=request)
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
            
        questions = Question.objects.filter(exam=log.exam).prefetch_related('choices')
        
        # If the exam itself has a global answer_key uploaded, redirect there first
        from django.http import HttpResponseRedirect
        if log.exam.answer_key:
            return HttpResponseRedirect(log.exam.answer_key.url)

        # Otherwise, if no questions exist, fallback to the SubjectPaper's answer_key or file
        if not questions.exists() and log.exam.selected_papers.exists():
            paper = log.exam.selected_papers.first()
            if paper.answer_key:
                return HttpResponseRedirect(paper.answer_key.url)
            elif paper.file:
                return HttpResponseRedirect(paper.file.url)
                
        from .utils import group_questions
        return Response(group_questions(QuestionSerializer(questions, many=True).data))


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


# ═══════════════════════════════════════════════════════════════════════════════
# 12. POST  /api/v1/exams/{exam_id}/upload-materials/
# ═══════════════════════════════════════════════════════════════════════════════

class ExamUploadMaterialsView(APIView):
    """
    Dedicated API to upload answer_key and/or question_paper directly to an Exam.
    Accepts multipart/form-data.
    """
    def post(self, request, exam_id):
        role = _user_role(request.user)
        # Check if the user is authorized (super_admin, ASE, branch_manager, OR the assigned faculty)
        qs = Exam.objects.filter(is_deleted=False)
        if getattr(request.user, 'organization', None):
            qs = qs.filter(branch__organization=request.user.organization)
            
        try:
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)
            
        is_faculty = False
        if role == 'faculty':
            from faculty.models import FacultyProfile
            try:
                fp = FacultyProfile.objects.get(user=request.user)
                if exam.faculty_id != fp.id:
                    return Response({'success': False, 'message': 'You are not assigned to this exam.'}, status=status.HTTP_403_FORBIDDEN)
                is_faculty = True
            except Exception:
                return Response({'success': False, 'message': 'Faculty profile not found.'}, status=status.HTTP_403_FORBIDDEN)
        elif role not in EXAM_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        answer_key = request.FILES.get('answer_key')
        question_paper = request.FILES.get('question_paper')
        no_of_questions = request.data.get('no_of_questions')

        if not answer_key and not question_paper:
            return Response({'success': False, 'message': 'Please provide either answer_key or question_paper file.'}, status=status.HTTP_400_BAD_REQUEST)

        uploaded = []
        if answer_key:
            exam.answer_key = answer_key
            exam.save(update_fields=['answer_key'])
            uploaded.append('Answer Key')
            
        if question_paper:
            if not exam.subject:
                return Response({
                    'success': False, 
                    'message': 'Cannot upload a question paper directly because this exam has no Subject assigned.'
                }, status=status.HTTP_400_BAD_REQUEST)
                
            from .models import SubjectPaper
            sp = SubjectPaper.objects.create(
                subject=exam.subject,
                file=question_paper,
                set_name=f"{exam.title}",
                no_of_questions=no_of_questions
            )
            exam.selected_papers.add(sp)
            uploaded.append('Question Paper')

        msg = " and ".join(uploaded) + " uploaded successfully."
        return Response({
            'success': True,
            'message': msg
        })

# ═══════════════════════════════════════════════════════════════════════════════
# 13. POST  /api/v1/exams/{exam_id}/grace-marks/
# ═══════════════════════════════════════════════════════════════════════════════

class ExamGraceMarksView(APIView):
    """
    API to add grace marks to an exam and auto-update results.
    Payload: { 'grace_marks': 5, 'grace_marks_note': 'Due to out of syllabus question' }
    """
    def post(self, request, exam_id):
        role = _user_role(request.user)
        if role not in ['super_admin', 'admin_senior_executive', 'branch_manager']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
            
        qs = Exam.objects.filter(is_deleted=False)
        if getattr(request.user, 'organization', None):
            qs = qs.filter(branch__organization=request.user.organization)
            
        try:
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)
            
        # Parse payload
        grace_marks_val = request.data.get('grace_marks')
        grace_marks_note = request.data.get('grace_marks_note', '')
        
        try:
            from decimal import Decimal
            grace_marks_val = Decimal(str(grace_marks_val))
            if grace_marks_val < 0:
                raise ValueError
        except (TypeError, ValueError, decimal.InvalidOperation):
            return Response({'success': False, 'message': 'Invalid grace_marks. Must be a positive number.'}, status=status.HTTP_400_BAD_REQUEST)

        # Apply to Exam
        exam.grace_marks = grace_marks_val
        exam.grace_marks_note = grace_marks_note
        exam.save(update_fields=['grace_marks', 'grace_marks_note'])

        # Apply to MarkSheets
        from results.models import MarkSheet, PublishedResult
        
        updated_marksheets = 0
        marksheets = MarkSheet.objects.filter(exam=exam, is_submitted=True, is_absent=False)
        for ms in marksheets:
            if ms.marks_obtained is not None:
                new_marks = ms.marks_obtained + grace_marks_val
                # Cap at total marks if applicable
                if exam.total_marks:
                    if new_marks > exam.total_marks:
                        new_marks = Decimal(str(exam.total_marks))
                ms.marks_obtained = new_marks
                ms.is_pass = new_marks >= (exam.pass_marks or 0)
                
                # Append note
                if grace_marks_note:
                    if ms.remarks:
                        if "Grace Marks:" not in ms.remarks:
                            ms.remarks += f" | Grace Marks: {grace_marks_note}"
                    else:
                        ms.remarks = f"Grace Marks: {grace_marks_note}"
                        
                ms.save(update_fields=['marks_obtained', 'is_pass', 'remarks'])
                updated_marksheets += 1
                
        # Apply to PublishedResult (if any exist yet)
        updated_published = 0
        published = PublishedResult.objects.filter(exam=exam)
        for pr in published:
            new_marks = pr.marks_obtained + grace_marks_val
            if pr.total_marks and new_marks > pr.total_marks:
                new_marks = Decimal(str(pr.total_marks))
            pr.marks_obtained = new_marks
            pr.is_pass = new_marks >= (exam.pass_marks or 0)
            if pr.total_marks and pr.total_marks > 0:
                pr.percentage = round(float(new_marks) / pr.total_marks * 100, 2)
            pr.save(update_fields=['marks_obtained', 'is_pass', 'percentage'])
            updated_published += 1
            
        # Re-calculate ranks if published results exist
        if updated_published > 0:
            from results.utils import calculate_ranks
            calculate_ranks(exam_id)

        return Response({
            'success': True,
            'message': f'Grace marks of {grace_marks_val} added to Exam and applied to {updated_marksheets} student results.'
        })


# ═══════════════════════════════════════════════════════════════════════════════
def _find_student_from_sheet_metadata(sheet_metadata, exam):
    from django.db.models import Q
    from students.models import Student

    admission_number = sheet_metadata.get('admission_number')
    roll_number = sheet_metadata.get('roll_number')
    student_name = sheet_metadata.get('student_name')

    qs = Student.objects.all()
    if exam.batch_id:
        qs = qs.filter(batch_id=exam.batch_id)
    if exam.branch_id:
        qs = qs.filter(branch_id=exam.branch_id)

    if admission_number:
        try:
            return qs.get(admission_number__iexact=admission_number)
        except Student.DoesNotExist:
            return None
        except Student.MultipleObjectsReturned:
            return None

    if roll_number:
        roll_qs = qs.filter(roll_number__iexact=roll_number)
        if roll_qs.count() == 1:
            return roll_qs.first()
        return None

    if student_name:
        name_parts = student_name.split()
        if len(name_parts) >= 2:
            first_name = name_parts[0]
            surname = name_parts[-1]
            exact = qs.filter(first_name__iexact=first_name, surname__iexact=surname)
            if exact.count() == 1:
                return exact.first()

    return None


# OMR Upload — POST /api/v1/exams/exams/{exam_id}/students/{student_id}/omr-upload/
# ═══════════════════════════════════════════════════════════════════════════════

class OMRUploadView(APIView):
    """
    Student uploads a scanned OMR answer sheet for an offline MCQ exam.

    The endpoint:
      1. Validates the exam is offline + mcq and has an answer_key file.
      2. Reads the existing Exam.answer_key to extract correct answers.
      3. Reads the uploaded OMR sheet to detect the student's answers.
      4. Grades the result and updates / creates the student's MarkSheet.

    Request  : multipart/form-data  { "answer_sheet": <image|pdf> }
               Optional fields      : "n_questions" (int, default from exam.total_marks or 100)
                                      "marks_per_question" (float, default 1.0)
                                      "negative_marks" (float, default 0.0)

    Response : {
        "success": true,
        "score": 45.0,
        "total": 60,
        "breakdown": [...],
        "marksheet_id": "...",
        "method": "weasyprint|bubble_detection|ocr"
    }
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, exam_id, student_id):
        # from .omr import extract_answer_key_from_file, detect_student_answers, grade_omr
        if getattr(django_settings,'OMR_ENGINE') == 'azure' and getattr(django_settings,"AZURE_OPENAI_KEY"):
            from .omr_azure import (
                extract_answer_key_from_file_azure as extract_answer_key_from_file,
                detect_student_answers_azure as detect_student_answers,
                parse_student_identity_from_sheet_azure as parse_student_identity_from_sheet,
            )
        else:
            from .omr import extract_answer_key_from_file, detect_student_answers, parse_student_identity_from_sheet
        from results.models import MarkSheet
        import tempfile, os

        role = _user_role(request.user)

        # ── 1. Fetch Exam ──────────────────────────────────────────────────
        try:
            qs = Exam.objects.filter(is_deleted=False)
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)

        # ── 2. Resolve student and validate offline exam upload ──────────────
        try:
            from students.models import Student
            student = Student.objects.get(id=student_id)
        except Student.DoesNotExist:
            return Response({'success': False, 'message': 'Student not found.'}, status=status.HTTP_404_NOT_FOUND)

        if exam.exam_mode != 'offline' or exam.exam_type != 'mcq':
            return Response({
                'success': False,
                'message': 'OMR grading is only available for offline MCQ exams.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if not exam.answer_key:
            return Response({
                'success': False,
                'message': 'No answer key uploaded for this exam. Please ask your admin to upload one.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if getattr(exam, 'branch_id', None) and getattr(student, 'branch_id', None) and exam.branch_id != student.branch_id:
            return Response({'success': False, 'message': 'Student does not belong to the exam branch.'}, status=status.HTTP_403_FORBIDDEN)

        if exam.batch_id and student.batch_id != exam.batch_id:
            try:
                from batches.models import BatchStudent
                if not BatchStudent.objects.filter(student=student, batch_id=exam.batch_id).exists():
                    return Response({'success': False, 'message': 'Student is not enrolled in this exam batch.'}, status=status.HTTP_403_FORBIDDEN)
            except Exception:
                return Response({'success': False, 'message': 'Student is not enrolled in this exam batch.'}, status=status.HTTP_403_FORBIDDEN)

        is_own_session = (role == 'student' and student.user == request.user)
        is_admin = role in ADMIN_ROLES
        is_faculty = False
        if role == 'faculty':
            from faculty.models import FacultyProfile
            try:
                fp = FacultyProfile.objects.get(user=request.user)
                if exam.faculty_id == fp.id or exam.batch_id in list(fp.batch_assignments.values_list('batch_id', flat=True)):
                    is_faculty = True
                else:
                    return Response({'success': False, 'message': 'You are not assigned to this exam or batch.'}, status=status.HTTP_403_FORBIDDEN)
            except FacultyProfile.DoesNotExist:
                return Response({'success': False, 'message': 'Faculty profile not found.'}, status=status.HTTP_403_FORBIDDEN)

        if is_admin and not has_user_branch_access(request.user, exam.branch_id):
            return Response({'success': False, 'message': 'You do not have access to this exam branch.'}, status=status.HTTP_403_FORBIDDEN)

        if not (is_own_session or is_admin or is_faculty):
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        session, _ = ExamSession.objects.get_or_create(exam=exam, student=student)
        if session.is_submitted:
            return Response({'success': False, 'message': 'OMR has already been submitted for this student.'}, status=status.HTTP_409_CONFLICT)

        # ── 4. Get uploaded answer sheet ───────────────────────────────────
        answer_sheet = request.FILES.get('answer_sheet')
        if not answer_sheet:
            return Response({'success': False, 'message': 'Please upload an answer_sheet file.'}, status=status.HTTP_400_BAD_REQUEST)

        # ── 5. Parse parameters ────────────────────────────────────────────
        try:
            n_questions = int(request.data.get('n_questions', 0)) or exam.total_marks or 100
        except (TypeError, ValueError):
            n_questions = exam.total_marks or 100

        try:
            marks_per_q = float(request.data.get('marks_per_question', 1.0))
        except (TypeError, ValueError):
            marks_per_q = 1.0

        try:
            negative_per_q = float(request.data.get('negative_marks', 0.0))
        except (TypeError, ValueError):
            negative_per_q = 0.0

        n_options = 4  # A B C D

        # ── 6. Write uploads to temp files for OpenCV ──────────────────────
        errors = []
        answer_key_dict = {}
        student_answers_dict = {}

        # --- Answer key extraction ---
        key_suffix = os.path.splitext(exam.answer_key.name)[1] or '.jpg'
        try:
            with tempfile.NamedTemporaryFile(suffix=key_suffix, delete=False) as kf:
                for chunk in exam.answer_key.chunks():
                    kf.write(chunk)
                key_tmp = kf.name

            answer_key_dict = extract_answer_key_from_file(key_tmp, n_questions=n_questions, n_options=n_options)
        except Exception as exc:
            logger.error("OMR answer key extraction failed for exam %s: %s", exam_id, exc)
            errors.append(f"Answer key parse error: {exc}")
        finally:
            try:
                os.unlink(key_tmp)
            except Exception:
                pass

        if not answer_key_dict:
            return Response({
                'success': False,
                'message': 'Could not parse the answer key file. Ensure it is a clear OMR image or a text/PDF listing answers.',
                'detail': errors,
            }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        # --- Student sheet detection ---
        sheet_suffix = os.path.splitext(answer_sheet.name)[1] or '.jpg'
        try:
            with tempfile.NamedTemporaryFile(suffix=sheet_suffix, delete=False) as sf:
                for chunk in answer_sheet.chunks():
                    sf.write(chunk)
                sheet_tmp = sf.name

            # Also save it to the session's uploaded_answer_sheet field
            session.uploaded_answer_sheet.save(answer_sheet.name, answer_sheet, save=False)

            # Parse student identity from the uploaded OMR sheet itself.
            from .omr import parse_student_identity_from_sheet
            sheet_metadata = parse_student_identity_from_sheet(sheet_tmp)

            if not sheet_metadata:
                return Response({
                    'success': False,
                    'message': 'Could not extract student identity from the OMR sheet. Please ensure name, roll number, or admission number is visible on the sheet.',
                }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

            sheet_name = sheet_metadata.get('student_name')
            sheet_roll = sheet_metadata.get('roll_number')
            sheet_admission = sheet_metadata.get('admission_number')

            if sheet_name and sheet_name.lower() != student.full_name.lower():
                return Response({'success': False, 'message': 'Student name on sheet does not match the selected student.'}, status=status.HTTP_403_FORBIDDEN)

            if sheet_roll:
                if not student.roll_number:
                    return Response({'success': False, 'message': 'Selected student does not have a roll number on record.'}, status=status.HTTP_400_BAD_REQUEST)
                if sheet_roll.lower() != student.roll_number.lower():
                    return Response({'success': False, 'message': 'Roll number on sheet does not match the selected student.'}, status=status.HTTP_403_FORBIDDEN)

            if sheet_admission and sheet_admission != student.admission_number:
                return Response({'success': False, 'message': 'Admission number on sheet does not match the selected student.'}, status=status.HTTP_403_FORBIDDEN)

            student_answers_dict = detect_student_answers(sheet_tmp, n_questions=n_questions, n_options=n_options)
        except ImportError as exc:
            return Response({
                'success': False,
                'message': str(exc),
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.error("OMR student sheet detection failed for student %s, exam %s: %s", student_id, exam_id, exc)
            return Response({
                'success': False,
                'message': f'Could not process your answer sheet: {exc}',
            }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        finally:
            try:
                os.unlink(sheet_tmp)
            except Exception:
                pass

        # ── 7. Grade ───────────────────────────────────────────────────────
        score, breakdown = grade_omr(
            student_answers=student_answers_dict,
            answer_key=answer_key_dict,
            marks_per_question=marks_per_q,
            negative_per_question=negative_per_q,
        )

        total_possible = len(answer_key_dict) * marks_per_q
        is_pass = score >= (exam.pass_marks or 0)

        # ── 8. Update / create MarkSheet ──────────────────────────────────
        from django.utils import timezone as tz
        ms, _ = MarkSheet.objects.get_or_create(
            exam=exam,
            student=session.student,
            defaults={'remarks': 'OMR auto-graded'},
        )
        ms.marks_obtained = score
        ms.is_pass = is_pass
        ms.checked_at = tz.now()
        ms.is_submitted = True
        ms.remarks = f'OMR auto-graded — {int(score)}/{int(total_possible)}'
        # Store per-question breakdown in question_marks JSONField
        ms.question_marks = breakdown
        ms.save(update_fields=['marks_obtained', 'is_pass', 'checked_at', 'is_submitted', 'remarks', 'question_marks'])

        # Save uploaded sheet reference to session
        session.is_submitted = True
        session.submitted_at = tz.now()
        session.save(update_fields=['uploaded_answer_sheet', 'is_submitted', 'submitted_at'])

        return Response({
            'success': True,
            'score': score,
            'total': total_possible,
            'is_pass': is_pass,
            'correct': sum(1 for b in breakdown if b['result'] == 'correct'),
            'wrong': sum(1 for b in breakdown if b['result'] == 'wrong'),
            'unanswered': sum(1 for b in breakdown if b['result'] == 'unanswered'),
            'breakdown': breakdown,
            'marksheet_id': str(ms.id),
        }, status=status.HTTP_200_OK)


class OMRBulkUploadView(APIView):
    """Bulk upload OMR sheets for offline MCQ exams.

    Accepts multipart/form-data with multiple files in `answer_sheets`.
    Each file is parsed for student identity from the sheet itself and graded
    against the exam answer key.
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, exam_id):
        # from .omr import extract_answer_key_from_file, detect_student_answers, grade_omr, parse_student_identity_from_sheet
        if getattr(django_settings,'OMR_ENGINE') == 'azure' and getattr(django_settings,'AZURE_OPENAI_KEY'):
            from .omr_azure import (
                extract_answer_key_from_file_azure as extract_answer_key_from_file,
                detect_student_answers_azure as detect_student_answers,
                parse_student_identity_from_sheet_azure as parse_student_identity_from_sheet,
            )
        else:
            from .omr import extract_answer_key_from_file, detect_student_answers, parse_student_identity_from_sheet
        from results.models import MarkSheet
        import tempfile, os

        role = _user_role(request.user)

        try:
            qs = Exam.objects.filter(is_deleted=False)
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)

        if exam.exam_mode != 'offline' or exam.exam_type != 'mcq':
            return Response({
                'success': False,
                'message': 'OMR grading is only available for offline MCQ exams.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if not exam.answer_key:
            return Response({
                'success': False,
                'message': 'No answer key uploaded for this exam. Please ask your admin to upload one.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if role not in ADMIN_ROLES and role != 'faculty':
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if role == 'admin' and not has_user_branch_access(request.user, exam.branch_id):
            return Response({'success': False, 'message': 'You do not have access to this exam branch.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            n_questions = int(request.data.get('n_questions', 0)) or exam.total_marks or 100
        except (TypeError, ValueError):
            n_questions = exam.total_marks or 100

        try:
            marks_per_q = float(request.data.get('marks_per_question', 1.0))
        except (TypeError, ValueError):
            marks_per_q = 1.0

        try:
            negative_per_q = float(request.data.get('negative_marks', 0.0))
        except (TypeError, ValueError):
            negative_per_q = 0.0

        n_options = 4

        answer_sheets = request.FILES.getlist('answer_sheets') or request.FILES.getlist('answer_sheet')
        if not answer_sheets:
            return Response({'success': False, 'message': 'Please upload at least one answer sheet in answer_sheets.'}, status=status.HTTP_400_BAD_REQUEST)

        key_suffix = os.path.splitext(exam.answer_key.name)[1] or '.jpg'
        try:
            with tempfile.NamedTemporaryFile(suffix=key_suffix, delete=False) as kf:
                for chunk in exam.answer_key.chunks():
                    kf.write(chunk)
                key_tmp = kf.name

            answer_key_dict = extract_answer_key_from_file(key_tmp, n_questions=n_questions, n_options=n_options)
        except Exception as exc:
            logger.error("OMR answer key extraction failed for exam %s: %s", exam_id, exc)
            return Response({
                'success': False,
                'message': 'Could not parse the answer key file. Ensure it is a clear OMR image or a text/PDF listing answers.',
                'detail': str(exc),
            }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        finally:
            try:
                os.unlink(key_tmp)
            except Exception:
                pass

        results = []
        for answer_sheet in answer_sheets:
            sheet_result = {'file_name': answer_sheet.name, 'status': 'error'}
            sheet_suffix = os.path.splitext(answer_sheet.name)[1] or '.jpg'
            try:
                with tempfile.NamedTemporaryFile(suffix=sheet_suffix, delete=False) as sf:
                    for chunk in answer_sheet.chunks():
                        sf.write(chunk)
                    sheet_tmp = sf.name

                sheet_metadata = parse_student_identity_from_sheet(sheet_tmp)
                if not sheet_metadata:
                    sheet_result['message'] = 'Could not extract student identity from sheet.'
                    results.append(sheet_result)
                    continue

                student = _find_student_from_sheet_metadata(sheet_metadata, exam)
                if not student:
                    sheet_result['message'] = 'Could not resolve a student from sheet metadata.'
                    results.append(sheet_result)
                    continue

                if exam.batch_id and student.batch_id != exam.batch_id:
                    sheet_result['message'] = 'Parsed student is not enrolled in this exam batch.'
                    results.append(sheet_result)
                    continue

                if exam.branch_id and student.branch_id != exam.branch_id:
                    sheet_result['message'] = 'Parsed student does not belong to this exam branch.'
                    results.append(sheet_result)
                    continue

                session, _ = ExamSession.objects.get_or_create(exam=exam, student=student)
                if session.is_submitted:
                    sheet_result['message'] = 'OMR already submitted for this student.'
                    results.append(sheet_result)
                    continue

                session.uploaded_answer_sheet.save(answer_sheet.name, answer_sheet, save=False)
                student_answers_dict = detect_student_answers(sheet_tmp, n_questions=n_questions, n_options=n_options)

                score, breakdown = grade_omr(
                    student_answers=student_answers_dict,
                    answer_key=answer_key_dict,
                    marks_per_question=marks_per_q,
                    negative_per_question=negative_per_q,
                )

                total_possible = len(answer_key_dict) * marks_per_q
                is_pass = score >= (exam.pass_marks or 0)

                ms, _ = MarkSheet.objects.get_or_create(
                    exam=exam,
                    student=student,
                    defaults={'remarks': 'OMR auto-graded'},
                )
                ms.marks_obtained = score
                ms.is_pass = is_pass
                ms.checked_at = timezone.now()
                ms.is_submitted = True
                ms.remarks = f'OMR auto-graded — {int(score)}/{int(total_possible)}'
                ms.question_marks = breakdown
                ms.save(update_fields=['marks_obtained', 'is_pass', 'checked_at', 'is_submitted', 'remarks', 'question_marks'])

                session.is_submitted = True
                session.submitted_at = timezone.now()
                session.save(update_fields=['uploaded_answer_sheet', 'is_submitted', 'submitted_at'])

                sheet_result.update({
                    'status': 'success',
                    'student_id': str(student.id),
                    'student_name': student.full_name,
                    'score': score,
                    'total': total_possible,
                    'is_pass': is_pass,
                    'correct': sum(1 for b in breakdown if b['result'] == 'correct'),
                    'wrong': sum(1 for b in breakdown if b['result'] == 'wrong'),
                    'unanswered': sum(1 for b in breakdown if b['result'] == 'unanswered'),
                    'marksheet_id': str(ms.id),
                })
            except ImportError as exc:
                sheet_result['message'] = str(exc)
            except Exception as exc:
                logger.error("Bulk OMR upload failed for exam %s file %s: %s", exam_id, answer_sheet.name, exc)
                sheet_result['message'] = str(exc)
            finally:
                try:
                    os.unlink(sheet_tmp)
                except Exception:
                    pass

            results.append(sheet_result)

        return Response({
            'success': True,
            'processed': len(results),
            'succeeded': sum(1 for r in results if r['status'] == 'success'),
            'failed': sum(1 for r in results if r['status'] != 'success'),
            'results': results,
        }, status=status.HTTP_200_OK)
