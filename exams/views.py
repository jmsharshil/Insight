import logging
from core.pagination import paginate_queryset
import uuid
import hashlib
from django.utils import timezone
from django.db import transaction
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny

from .models import (
    Exam, Question, Choice, ExamSession, StudentAnswer,
    SeatArrangement, MalpracticeReport, ScreenEvent,
    AnswerKeyDistributionLog, CheckerToken,
)
from .serializers import (
    ExamListSerializer, ExamCreateSerializer, QuestionSerializer,
    QuestionStudentSerializer, QuestionInputSerializer, ExamStartSerializer,
    ExamSubmitSerializer, AutosaveSerializer, ScreenEventSerializer,
    SeatInputSerializer, SeatArrangementSerializer, MalpracticeInputSerializer,
    MalpracticeSerializer, MarksInputSerializer, GeoCheckSerializer,
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
    if hasattr(user, 'branch_id'):
        return user.branch_id
    if hasattr(user, 'profile') and hasattr(user.profile, 'branch_id'):
        return user.profile.branch_id
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 1. GET & POST  /api/v1/exams/
# ═══════════════════════════════════════════════════════════════════════════════

class ExamListCreateView(APIView):
    # permission_classes = [IsAuthenticated]

    def _get_queryset(self, request):
        user = request.user
        role = _user_role(user)
        qs = Exam.objects.filter(is_deleted=False).select_related('batch', 'subject', 'branch', 'created_by')
        if getattr(request.user, 'organization', None):
            qs = qs.filter(branch__organization=request.user.organization)

        if role == 'student':
            try:
                from students.models import Student
                sp = Student.objects.get(user=user)
                qs = qs.filter(batch_id=sp.batch_id, status__in=['scheduled', 'ongoing'])
            except Exception:
                qs = qs.none()
        elif role == 'faculty':
            qs = qs.filter(created_by=user)
        elif role == 'exam_supervisor':
            bid = _user_branch_id(user)
            if bid:
                qs = qs.filter(branch_id=bid)
        elif role == 'paper_checker':
            qs = qs.filter(marksheets__paper_checker=user).distinct()
        elif role not in ['super_admin']:
            bid = _user_branch_id(user)
            if bid:
                qs = qs.filter(branch_id=bid)

        for param, field in [('exam_type', 'exam_type'), ('status', 'status'), ('batch_id', 'batch_id'), ('scheduled_date', 'scheduled_date')]:
            val = request.GET.get(param)
            if val:
                qs = qs.filter(**{field: val})

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
                if not ExamSession.objects.filter(exam=exam, student=sp).exists() or exam.status != 'ongoing':
                    return Response({'success': False, 'message': 'Exam session not active'}, status=status.HTTP_403_FORBIDDEN)
                return Response(QuestionStudentSerializer(questions, many=True).data)
            except:
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

        if role not in ['super_admin', 'admin_senior_executive'] and not (role == 'faculty' and exam.created_by == request.user):
            return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        serializer = QuestionInputSerializer(data=request.data, many=True)
        if not serializer.is_valid():
            return Response({'success': False, 'message': 'Validation failed'}, status=status.HTTP_400_BAD_REQUEST)

        total_new_marks = sum(item['marks'] for item in serializer.validated_data)
        current_marks = sum(q.marks for q in Question.objects.filter(exam=exam))
        if current_marks + total_new_marks > exam.total_marks:
            pass # warn, but spec says "Warn if sum... > total_marks", we will just accept it for now or return a warning in response.

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
        
        return Response({'success': True, 'message': 'Questions added', 'details': {}}, status=status.HTTP_201_CREATED)


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


class ExamStartView(APIView):
    # permission_classes = [IsAuthenticated]


    def post(self, request, exam_id):
        if _user_role(request.user) != 'student':
            return Response({'success': False, 'message': 'Only students can start exams.'}, status=status.HTTP_403_FORBIDDEN)
        
        fingerprint = request.headers.get('X-Device-Fingerprint', '')
        if not fingerprint:
            logger.warning(f"Exam start without device fingerprint — user={request.user.email}")

        try:
            from students.models import Student
            student = Student.objects.get(user=request.user)
        except Exception:
            return Response({'success': False, 'message': 'Student profile not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            qs = Exam.objects.filter(is_deleted=False)
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)

        if student.batch_id != exam.batch_id:
            return Response({'success': False, 'message': 'Not enrolled in this exam batch'}, status=status.HTTP_403_FORBIDDEN)
        # if exam.status != 'scheduled':
        if exam.status not in ['scheduled', 'ongoing']:
            return Response({'success': False, 'message': 'Exam is not scheduled'}, status=status.HTTP_403_FORBIDDEN)
        
        now = timezone.now()
        dt_start = timezone.make_aware(timezone.datetime.combine(exam.scheduled_date, exam.start_time))
        dt_end = timezone.make_aware(timezone.datetime.combine(exam.scheduled_date, exam.end_time))
        
        if not (dt_start <= now <= dt_end):
            return Response({'success': False, 'message': 'Exam is not currently active'}, status=status.HTTP_403_FORBIDDEN)
        
        if ExamSession.objects.filter(exam=exam, student=student).exists():
            return Response({'success': False, 'message': 'Session already exists'}, status=status.HTTP_409_CONFLICT)

        if exam.geo_radius_meters > 0:
            ser = ExamStartSerializer(data=request.data)
            if not ser.is_valid():
                return Response({'success': False, 'message': 'Location required'}, status=status.HTTP_400_BAD_REQUEST)
            lat, lon = ser.validated_data.get('student_lat'), ser.validated_data.get('student_lon')
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
            exam=exam, student=student, device_fingerprint=fingerprint,
            student_lat=request.data.get('student_lat'), student_lon=request.data.get('student_lon'),
            last_geo_check_at=timezone.now() if exam.geo_radius_meters > 0 else None,
        )
        
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
            MarkSheet.objects.get_or_create(exam=session.exam, student=session.student)
            return Response({'submitted': True, 'message': 'Answers submitted. Results pending review.'})


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
