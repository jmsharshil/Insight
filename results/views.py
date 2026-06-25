import logging
from django.utils import timezone
from django.db.models import Count, Q, Max
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from core.utils import apply_filters

from .models import MarkSheet, PublishedResult, RecheckRequest, CheckerQuery
from .serializers import (
    MarkSheetSerializer, PublishedResultSerializer,
    RecheckRequestSerializer, RecheckRequestCreateSerializer,
    RecheckRequestActionSerializer, CheckerQuerySerializer,
    CheckerQueryCreateSerializer,
)
from exams.models import Exam, CheckerToken
from exams.utils import calculate_ranks, generate_checker_token
from exams.emails import send_checker_assignment_email, send_recheck_request_notification

logger = logging.getLogger(__name__)

# ── Role constants ────────────────────────────────────────────────────────────
PAPER_VIEW_ROLES = ['super_admin', 'paper_checker', 'admin_senior_executive']
PAPER_MARK_ROLES = ['super_admin', 'paper_checker']
RECHECK_ROLES = ['super_admin', 'paper_checker', 'admin_senior_executive']
CHECKER_STATUS_ROLES = ['super_admin', 'admin_senior_executive', 'branch_manager']
PUBLISH_ROLES = ['super_admin', 'admin_senior_executive', 'branch_manager']
RECHECK_REQUEST_REVIEW_ROLES = ['super_admin', 'admin_senior_executive', 'branch_manager']
QUERY_ROLES = ['super_admin', 'paper_checker', 'admin_senior_executive']


def _user_role(user):
    return getattr(user, 'role', None)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. GET  /api/v1/exams/{id}/papers/
# ═══════════════════════════════════════════════════════════════════════════════

class PaperView(APIView):
    # permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_submitted', 'is_pass', 'is_rechecked']
    search_fields = ['student__user__name', 'paper_checker__name']
    ordering_fields = '__all__'

    def get(self, request, exam_id):
        role = _user_role(request.user)
        if role not in PAPER_VIEW_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        qs = MarkSheet.objects.filter(exam_id=exam_id).select_related('student__user', 'paper_checker', 'exam__batch', 'exam__subject').prefetch_related('queries')
        if getattr(request.user, 'organization', None):
            qs = qs.filter(exam__branch__organization=request.user.organization)
        if role == 'paper_checker':
            qs = qs.filter(paper_checker=request.user)

        qs = apply_filters(self, request, qs)

        return Response({'success': True, 'count': qs.count(), 'data': MarkSheetSerializer(qs, many=True).data})


# ═══════════════════════════════════════════════════════════════════════════════
# 2. POST  /api/v1/exams/{id}/papers/{marksheet_id}/marks/
# ═══════════════════════════════════════════════════════════════════════════════

class PaperMarksView(APIView):
    # permission_classes = [IsAuthenticated]

    def _get_marksheet(self, request, exam_id, marksheet_id):
        role = _user_role(request.user)
        if role not in PAPER_MARK_ROLES:
            return None, Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = MarkSheet.objects.prefetch_related('queries')
            if getattr(request.user, 'organization', None):
                qs = qs.filter(exam__branch__organization=request.user.organization)
            ms = qs.get(id=marksheet_id, exam_id=exam_id)
        except MarkSheet.DoesNotExist:
            return None, Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if ms.paper_checker != request.user and role != 'super_admin':
            return None, Response({'success': False, 'message': 'Not assigned to you.'}, status=status.HTTP_403_FORBIDDEN)
        # Respect open checker queries for permissions (prevents modification while payroll-excluded)
        if any(q.status == 'open' for q in ms.queries.all()) and role not in ['super_admin', 'admin_senior_executive']:
            return None, Response({
                'success': False,
                'message': 'This marksheet has an open query. Please resolve the query first.',
                'has_open_query': True
            }, status=status.HTTP_403_FORBIDDEN)
        return ms, None

    def post(self, request, exam_id, marksheet_id):
        """POST — submit or update marks on a marksheet. Delegates to PUT for unified logic."""
        return self.put(request, exam_id, marksheet_id)

    def put(self, request, exam_id, marksheet_id):
        """PUT — re-submit / update marks on a marksheet (e.g. after recheck).
        If part of recheck flow, updates RecheckRequest to 'completed', saves checker_notes,
        ensuring the paper is added back to the (new) checker's payroll count.
        """
        ms, err = self._get_marksheet(request, exam_id, marksheet_id)
        if err:
            return err

        marks = request.data.get('marks_obtained')
        if marks is None or float(marks) < 0 or float(marks) > ms.exam.total_marks:
            return Response({'success': False, 'message': 'Invalid marks.'}, status=status.HTTP_400_BAD_REQUEST)

        ms.marks_obtained = marks
        ms.remarks = request.data.get('remarks', '')
        ms.checked_at = timezone.now()
        ms.is_submitted = True
        ms.is_pass = float(marks) >= ms.exam.pass_marks
        ms.save()

        # Handle recheck flow: mark as completed, save notes (fulfills "checker updates ... add notes and resubmits")
        rechecks = RecheckRequest.objects.filter(
            marksheet=ms,
            status__in=['approval_pending', 'approved']
        )
        if rechecks.exists():
            rr = rechecks.latest('created_at')
            rr.status = 'completed'
            rr.checker_notes = request.data.get('notes') or request.data.get('remarks', '')
            rr.save()
            ms.is_rechecked = True
            ms.save(update_fields=['is_rechecked'])

        # Update published result if exists
        try:
            pr = PublishedResult.objects.get(exam_id=exam_id, student=ms.student)
            pr.marks_obtained = marks
            pr.percentage = round((float(marks) / ms.exam.total_marks) * 100, 2) if ms.exam.total_marks else 0
            pr.is_pass = ms.is_pass
            pr.save(update_fields=['marks_obtained', 'percentage', 'is_pass'])
        except PublishedResult.DoesNotExist:
            pass

        return Response({
            'success': True, 
            'message': 'Marks updated. Recheck completed if applicable.',
            'data': MarkSheetSerializer(ms).data
        })

    def delete(self, request, exam_id, marksheet_id):
        """DELETE — remove a marksheet."""
        role = _user_role(request.user)
        if role not in ['super_admin', 'admin_senior_executive']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = MarkSheet.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(exam__branch__organization=request.user.organization)
            ms = qs.get(id=marksheet_id, exam_id=exam_id)
        except MarkSheet.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        ms.delete()
        return Response({'success': True, 'message': 'Marksheet deleted.'}, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. POST  /api/v1/exams/{id}/papers/{marksheet_id}/recheck/
# ═══════════════════════════════════════════════════════════════════════════════

class PaperRecheckView(APIView):
    # permission_classes = [IsAuthenticated]

    def post(self, request, exam_id, marksheet_id):
        role = _user_role(request.user)
        if role not in RECHECK_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            qs = MarkSheet.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(exam__branch__organization=request.user.organization)
            ms = qs.get(id=marksheet_id, exam_id=exam_id)
        except MarkSheet.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        new_cid = request.data.get('new_checker_id')
        if not new_cid:
            return Response({'success': False, 'message': 'new_checker_id required.'}, status=status.HTTP_400_BAD_REQUEST)

        ms.is_rechecked = True
        ms.recheck_request_at = timezone.now()
        ms.paper_checker_id = new_cid
        ms.is_submitted = False
        ms.save()

        generate_checker_token(ms)
        send_checker_assignment_email(ms)

        return Response({'success': True, 'message': 'Recheck requested and reassigned.'})


# ═══════════════════════════════════════════════════════════════════════════════
# 4. GET  /api/v1/exams/{id}/checker-status/
# ═══════════════════════════════════════════════════════════════════════════════

class CheckerStatusView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request, exam_id):
        role = _user_role(request.user)
        if role not in CHECKER_STATUS_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        sheets = MarkSheet.objects.filter(exam_id=exam_id).select_related('paper_checker')
        if getattr(request.user, 'organization', None):
            sheets = sheets.filter(exam__branch__organization=request.user.organization)
        total = sheets.count()
        submitted = sheets.filter(is_submitted=True).count()

        checkers = sheets.values('paper_checker__id', 'paper_checker__name').annotate(
            assigned_count=Count('id'),
            submitted_count=Count('id', filter=Q(is_submitted=True)),
            pending_count=Count('id', filter=Q(is_submitted=False)),
            last_activity=Max('checked_at'),
        )

        res_checkers = [{
            'checker_id': c['paper_checker__id'],
            'checker_name': c['paper_checker__name'],
            'assigned_count': c['assigned_count'],
            'submitted_count': c['submitted_count'],
            'pending_count': c['pending_count'],
            'last_activity': c['last_activity'],
        } for c in checkers if c['paper_checker__id']]

        return Response({
            'success': True,
            'data': {
                'total_papers': total, 'submitted': submitted,
                'approval_pending': total - submitted, 'overdue': 0,
                'checkers': res_checkers,
            },
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 5. POST  /api/v1/checker-portal/submit/  (EXEMPT from auth)
# ═══════════════════════════════════════════════════════════════════════════════

class CheckerPortalSubmitView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token_str = request.query_params.get('token')
        if not token_str:
            return Response({'success': False, 'message': 'Token required.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            token = CheckerToken.objects.get(token=token_str)
        except CheckerToken.DoesNotExist:
            return Response({'success': False, 'message': 'Invalid token.'}, status=status.HTTP_403_FORBIDDEN)

        if token.is_used or timezone.now() > token.expires_at:
            return Response({'success': False, 'message': 'Token expired or used.'}, status=status.HTTP_403_FORBIDDEN)

        ms = token.marksheet
        marks = request.data.get('marks_obtained')
        if marks is None or float(marks) < 0 or float(marks) > ms.exam.total_marks:
            return Response({'success': False, 'message': 'Invalid marks.'}, status=status.HTTP_400_BAD_REQUEST)

        ms.marks_obtained = marks
        ms.remarks = request.data.get('remarks', '')
        ms.checked_at = timezone.now()
        ms.is_submitted = True
        ms.is_pass = float(marks) >= ms.exam.pass_marks
        ms.save()

        token.is_used = True
        token.save()

        return Response({'success': True, 'message': 'Marks submitted successfully.'})


# ═══════════════════════════════════════════════════════════════════════════════
# 6. POST  /api/v1/exams/{id}/results/publish/
# ═══════════════════════════════════════════════════════════════════════════════

class PublishResultView(APIView):
    # permission_classes = [IsAuthenticated]

    def post(self, request, exam_id):
        role = _user_role(request.user)
        if role not in PUBLISH_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            qs = Exam.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)

        if exam.status == 'results_published':
            return Response({'success': False, 'message': 'Already published.'}, status=status.HTTP_400_BAD_REQUEST)

        if MarkSheet.objects.filter(exam=exam, is_submitted=False).exists():
            return Response({'success': False, 'message': 'Not all marksheets submitted.'}, status=status.HTTP_400_BAD_REQUEST)

        sheets = MarkSheet.objects.filter(exam=exam)
        pubs = []
        for ms in sheets:
            if not PublishedResult.objects.filter(exam=exam, student=ms.student).exists():
                pct = round((float(ms.marks_obtained) / exam.total_marks) * 100, 2) if exam.total_marks else 0
                pubs.append(PublishedResult(
                    exam=exam, student=ms.student, marks_obtained=ms.marks_obtained,
                    total_marks=exam.total_marks, percentage=pct, is_pass=ms.is_pass,
                    published_by=request.user,
                ))
        if pubs:
            PublishedResult.objects.bulk_create(pubs)

        calculate_ranks(exam_id)

        exam.status = 'results_published'
        exam.save()

        top = PublishedResult.objects.filter(exam=exam, rank=1).first()
        top_name = ''
        if top:
            try:
                top_name = top.student.user.name
            except Exception:
                pass

        return Response({
            'success': True, 'message': 'Results published.',
            'data': {'student_count': sheets.count(), 'top_scorer': top_name},
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 7. GET  /api/v1/exams/{id}/results/
# ═══════════════════════════════════════════════════════════════════════════════

class ResultView(APIView):
    # permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_pass']
    search_fields = ['student__user__name']
    ordering_fields = '__all__'

    def get(self, request, exam_id):
        role = _user_role(request.user)
        qs = PublishedResult.objects.filter(exam_id=exam_id).select_related('student__user')
        if getattr(request.user, 'organization', None):
            qs = qs.filter(exam__branch__organization=request.user.organization)

        if role == 'student':
            qs = qs.filter(student__user=request.user)
        elif role == 'parents':
            qs = qs.filter(student__user__linked_parents=request.user)

        qs = apply_filters(self, request, qs)

        return Response({'success': True, 'count': qs.count(), 'data': PublishedResultSerializer(qs, many=True).data})


class ResultDeleteView(APIView):
    """DELETE /api/v1/exams/{exam_id}/results/{result_id}/ — unpublish a result."""
    # permission_classes = [IsAuthenticated]

    def delete(self, request, exam_id, result_id):
        role = _user_role(request.user)
        if role not in PUBLISH_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = PublishedResult.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(exam__branch__organization=request.user.organization)
            pr = qs.get(id=result_id, exam_id=exam_id)
        except PublishedResult.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        pr.delete()
        return Response({'success': True, 'message': 'Result deleted.'}, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. POST  /api/v1/exams/{id}/results/recheck-request/   (v2 NEW — FRD §4.6.2)
#    GET   /api/v1/exams/{id}/recheck-requests/
#    PATCH /api/v1/exams/{id}/recheck-requests/{request_id}/
# ═══════════════════════════════════════════════════════════════════════════════

class StudentRecheckRequestView(APIView):
    """Student raises a recheck request with reason + optional marksheet upload (per user query).
    Requires Exam.answer_key to be uploaded first. Supports bulk via separate endpoint.
    """
    # permission_classes = [IsAuthenticated]

    def post(self, request, exam_id):
        if _user_role(request.user) != 'student':
            return Response({'success': False, 'message': 'Only students can request recheck.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            from students.models import Student
            student = Student.objects.get(user=request.user)
        except Exception:
            return Response({'success': False, 'message': 'Student profile not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Must have PublishedResult
        pr_qs = PublishedResult.objects.filter(exam_id=exam_id, student=student)
        if getattr(request.user, 'organization', None):
            pr_qs = pr_qs.filter(exam__branch__organization=request.user.organization)
        if not pr_qs.exists():
            return Response({'success': False, 'message': 'Results not published yet. Cannot request recheck.'}, status=status.HTTP_400_BAD_REQUEST)

        # NEW: Answer key must be uploaded
        try:
            exam = Exam.objects.get(id=exam_id)
            if not exam.answer_key:
                return Response({'success': False, 'message': 'Answer key has not been uploaded yet. Recheck not allowed.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Get marksheet
        try:
            qs = MarkSheet.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(exam__branch__organization=request.user.organization)
            ms = qs.get(exam_id=exam_id, student=student)
        except MarkSheet.DoesNotExist:
            return Response({'success': False, 'message': 'MarkSheet not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Check no pending/approved recheck already exists
        if RecheckRequest.objects.filter(marksheet=ms, status__in=['approval_pending', 'approved']).exists():
            return Response({'success': False, 'message': 'A recheck request is already pending or approved.'}, status=status.HTTP_409_CONFLICT)

        # Support file upload (multipart/form-data)
        serializer_data = request.data.copy()
        uploaded_file = request.FILES.get('uploaded_marksheet')
        if uploaded_file:
            serializer_data['uploaded_marksheet'] = uploaded_file

        ser = RecheckRequestCreateSerializer(data=serializer_data)
        if not ser.is_valid():
            return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        rr = RecheckRequest.objects.create(
            marksheet=ms,
            requested_by=student,
            reason=ser.validated_data.get('reason', ''),
            uploaded_marksheet=ser.validated_data.get('uploaded_marksheet'),
            status='approval_pending',
        )

        # Notify ASE
        send_recheck_request_notification(rr)

        return Response({
            'recheck_requested': True, 'status': 'approval_pending',
            'message': 'Your recheck request has been submitted for review.',
            'upload_provided': bool(rr.uploaded_marksheet),
        }, status=status.HTTP_201_CREATED)


        ser = RecheckRequestActionSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        action = ser.validated_data['action']
        ms = rr.marksheet

        if action == 'approve':
            new_checker_id = ser.validated_data['new_checker_id']
            rr.status = 'approved'
            rr.reviewed_by = request.user
            rr.reviewed_at = timezone.now()
            rr.new_checker_id = new_checker_id
            rr.save()

            ms.is_rechecked = True
            ms.recheck_request_at = timezone.now()
            ms.paper_checker_id = new_checker_id
            ms.is_submitted = False
            ms.save()

            generate_checker_token(ms)
            send_checker_assignment_email(ms)

            return Response({'success': True, 'message': 'Recheck approved and reassigned to new checker.'})

        else:  # reject
            rr.status = 'rejected'
            rr.reviewed_by = request.user
            rr.reviewed_at = timezone.now()
            rr.save()

            # Stub: notify student of rejection
            ms = qs.get(id=marksheet_id, exam_id=exam_id)
        except MarkSheet.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if ms.is_submitted:
            return Response({'success': False, 'message': 'Marks already submitted; cannot mark as absent.'}, status=status.HTTP_400_BAD_REQUEST)

        ms.is_absent = True
        ms.marks_obtained = 0
        ms.is_pass = False
        ms.is_submitted = True
        ms.remarks = 'Absent'
        ms.checked_at = timezone.now()
        ms.save()

        return Response({'success': True, 'message': 'Student marked as absent.'}, status=status.HTTP_200_OK)


class MarkAllAbsentView(APIView):
    """
    Automatically marks all students who have NO ExamSession record for an exam as absent.
    Should be called after the exam ends.
    """
    # permission_classes = [IsAuthenticated]
    ALLOWED_ROLES = ['super_admin', 'admin_senior_executive', 'branch_manager']

    def post(self, request, exam_id):
        role = _user_role(request.user)
        if role not in self.ALLOWED_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            qs = Exam.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            exam = qs.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)

        from exams.models import ExamSession

        # Get all students who started an exam session
        attended_student_ids = set(
            ExamSession.objects.filter(exam=exam, is_submitted=True)
            .values_list('student_id', flat=True)
        )

        # Mark absent all marksheets for students without a completed session
        marksheets = MarkSheet.objects.filter(exam=exam, is_submitted=False)
        absent_count = 0
        for ms in marksheets:
            if ms.student_id not in attended_student_ids:
                ms.is_absent = True
                ms.marks_obtained = 0
                ms.is_pass = False
                ms.is_submitted = True
                ms.remarks = 'Absent'
                ms.checked_at = timezone.now()
                ms.save()
                absent_count += 1

        return Response({
            'success': True,
            'message': f'{absent_count} students marked as absent.',
            'absent_count': absent_count,
        }, status=status.HTTP_200_OK)


class BulkRecheckRequestView(APIView):
    """
    NEW: Bulk recheck option for a batch (per user query).
    Creates recheck requests for all students in the exam's batch (if results published).
    Requires answer_key to be uploaded on the Exam first.
    Only ASE/super_admin.
    """
    # permission_classes = [IsAuthenticated]

    def post(self, request, exam_id):
        role = _user_role(request.user)
        if role not in ['super_admin', 'admin_senior_executive']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            exam = Exam.objects.get(id=exam_id)
            if not getattr(exam, 'answer_key', None):
                return Response({'success': False, 'message': 'Answer key must be uploaded first for rechecks.'}, status=status.HTTP_400_BAD_REQUEST)
            if not exam.batch:
                return Response({'success': False, 'message': 'Exam has no associated batch for bulk operation.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exam.DoesNotExist:
            return Response({'success': False, 'message': 'Exam not found.'}, status=status.HTTP_404_NOT_FOUND)

        reason = request.data.get('reason', 'Bulk recheck requested for entire batch.')
        from students.models import Student
        # Assume Batch has related students; adjust if Student has batch FK
        students = Student.objects.filter(
            batch=exam.batch,
            user__organization=exam.branch.organization if hasattr(exam.branch, 'organization') else None
        ) if hasattr(Student, 'batch') else []

        created_count = 0
        for student in students:
            try:
                ms = MarkSheet.objects.get(exam=exam, student=student)
                if not RecheckRequest.objects.filter(
                    marksheet=ms, status__in=['approval_pending', 'approved']
                ).exists() and PublishedResult.objects.filter(exam=exam, student=student).exists():
                    RecheckRequest.objects.create(
                        marksheet=ms,
                        requested_by=student,
                        reason=reason,
                        status='approval_pending',
                    )
                    created_count += 1
            except (MarkSheet.DoesNotExist, AttributeError):
                continue

        # Notify ASE about bulk
        logger.info(f'Bulk recheck created {created_count} requests for exam {exam_id}')

        return Response({
            'success': True,
            'message': f'Bulk recheck initiated for batch. {created_count} requests created.',
            'count': created_count,
        }, status=status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Paper Checker Query Option (NEW FRD)
# POST  /api/v1/exams/{exam_id}/papers/{marksheet_id}/query/   — raise query (paper_checker)
# PATCH /api/v1/exams/{exam_id}/queries/{query_id}/resolve/     — resolve query (admin/ASE)
# If query raised after recheck (ms.is_rechecked=True), payroll excludes the paper
# from count until query.status == 'resolved'. See CheckerQuery model + updated
# compute_payslip_for_user().
# ═══════════════════════════════════════════════════════════════════════════════

class PaperCheckerQueryView(APIView):
    """Handles raising and resolving paper checker queries.
    Queries prevent payroll payment until completed/resolved.
    """
    # permission_classes = [IsAuthenticated]

    def post(self, request, exam_id, marksheet_id=None):
        """Paper checker raises a query on a marksheet (e.g. answer key missing).
        URL: /exams/{exam_id}/papers/{marksheet_id}/query/
        """
        role = _user_role(request.user)
        if role not in QUERY_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        marksheet_id = marksheet_id or request.data.get('marksheet_id')
        try:
            qs = MarkSheet.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(exam__branch__organization=request.user.organization)
            ms = qs.get(id=marksheet_id, exam_id=exam_id)
        except MarkSheet.DoesNotExist:
            return Response({'success': False, 'message': 'MarkSheet not found.'}, status=status.HTTP_404_NOT_FOUND)

        if ms.paper_checker != request.user and role != 'super_admin':
            return Response({'success': False, 'message': 'Not assigned to you.'}, status=status.HTTP_403_FORBIDDEN)

        # Enforce after recheck start per requirement
        if not getattr(ms, 'is_rechecked', False) and role == 'paper_checker':
            return Response({
                'success': False,
                'message': 'Queries typically raised after recheck starts. Use marks submission instead.'
            }, status=status.HTTP_400_BAD_REQUEST)

        ser = CheckerQueryCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        query = CheckerQuery.objects.create(
            marksheet=ms,
            raised_by=request.user,
            query_type=ser.validated_data['query_type'],
            description=ser.validated_data.get('description', ''),
            status='open',
        )

        # Mark as not submitted until resolved (affects payroll immediately)
        if not ms.is_submitted:
            ms.is_submitted = False
            ms.save(update_fields=['is_submitted'])

        logger.info(f"Checker query raised by {request.user} on marksheet {marksheet_id}: {query.query_type}")

        return Response({
            'success': True,
            'message': 'Query raised. This paper will not count toward payment until resolved.',
            'data': CheckerQuerySerializer(query).data
        }, status=status.HTTP_201_CREATED)

    def patch(self, request, exam_id, query_id=None):
        """Admin/ASE resolves a query. 
        URL: /exams/{exam_id}/queries/{query_id}/resolve/
        Sets status=resolved; payment cut only lifted when completed.
        """
        role = _user_role(request.user)
        if role not in ['super_admin', 'admin_senior_executive']:
            return Response({'success': False, 'message': 'Only admins can resolve queries.'}, status=status.HTTP_403_FORBIDDEN)

        query_id = query_id or request.data.get('query_id')
        try:
            q_qs = CheckerQuery.objects.select_related('marksheet').all()
            if getattr(request.user, 'organization', None):
                q_qs = q_qs.filter(marksheet__exam__branch__organization=request.user.organization)
            query_obj = q_qs.get(id=query_id, marksheet__exam_id=exam_id)
        except (CheckerQuery.DoesNotExist, ValueError):
            return Response({'success': False, 'message': 'Query not found.'}, status=status.HTTP_404_NOT_FOUND)

        if query_obj.status != 'open':
            return Response({'success': False, 'message': 'Query already resolved.'}, status=status.HTTP_400_BAD_REQUEST)

        query_obj.status = 'resolved'
        query_obj.resolved_by = request.user
        query_obj.resolved_at = timezone.now()
        query_obj.save()

        # Optionally allow marks update on resolve (triggers submission for payroll)
        ms = query_obj.marksheet
        if 'marks_obtained' in request.data:
            marks = request.data.get('marks_obtained')
            if marks is not None:
                ms.marks_obtained = marks
                ms.remarks = request.data.get('remarks', ms.remarks or 'Query resolved with marks')
                ms.checked_at = timezone.now()
                ms.is_submitted = True
                ms.is_pass = float(marks) >= (ms.exam.total_marks or 0)
                ms.save()

        logger.info(f"Query {query_obj.id} resolved by {request.user}")

        return Response({
            'success': True,
            'message': 'Query resolved. Paper now eligible for payment on next payroll run (if submitted).',
            'data': CheckerQuerySerializer(query_obj).data
        })

