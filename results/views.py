import logging
from django.utils import timezone
from django.db.models import Count, Q, Max
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny

from .models import MarkSheet, PublishedResult, RecheckRequest
from .serializers import (
    MarkSheetSerializer, PublishedResultSerializer,
    RecheckRequestSerializer, RecheckRequestCreateSerializer,
    RecheckRequestActionSerializer,
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


def _user_role(user):
    return getattr(user, 'role', None)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. GET  /api/v1/exams/{id}/papers/
# ═══════════════════════════════════════════════════════════════════════════════

class PaperView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request, exam_id):
        role = _user_role(request.user)
        if role not in PAPER_VIEW_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        qs = MarkSheet.objects.filter(exam_id=exam_id).select_related('student__user', 'paper_checker')
        if role == 'paper_checker':
            qs = qs.filter(paper_checker=request.user)

        return Response({'success': True, 'count': qs.count(), 'data': MarkSheetSerializer(qs, many=True).data})


# ═══════════════════════════════════════════════════════════════════════════════
# 2. POST  /api/v1/exams/{id}/papers/{marksheet_id}/marks/
# ═══════════════════════════════════════════════════════════════════════════════

class PaperMarksView(APIView):
    # permission_classes = [IsAuthenticated]

    def post(self, request, exam_id, marksheet_id):
        role = _user_role(request.user)
        if role not in PAPER_MARK_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            ms = MarkSheet.objects.get(id=marksheet_id, exam_id=exam_id)
        except MarkSheet.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if ms.paper_checker != request.user and role != 'super_admin':
            return Response({'success': False, 'message': 'Not assigned to you.'}, status=status.HTTP_403_FORBIDDEN)

        if ms.is_submitted:
            return Response({'success': False, 'message': 'Already submitted.'}, status=status.HTTP_400_BAD_REQUEST)

        marks = request.data.get('marks_obtained')
        if marks is None or float(marks) < 0 or float(marks) > ms.exam.total_marks:
            return Response({'success': False, 'message': 'Invalid marks.'}, status=status.HTTP_400_BAD_REQUEST)

        ms.marks_obtained = marks
        ms.remarks = request.data.get('remarks', '')
        ms.checked_at = timezone.now()
        ms.is_submitted = True
        ms.is_pass = float(marks) >= ms.exam.pass_marks
        ms.save()

        return Response({'success': True, 'message': 'Marks submitted.', 'data': {'marksheet_id': str(ms.id), 'marks_obtained': marks}})


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
            ms = MarkSheet.objects.get(id=marksheet_id, exam_id=exam_id)
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
                'pending': total - submitted, 'overdue': 0,
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
            exam = Exam.objects.get(id=exam_id)
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

    def get(self, request, exam_id):
        role = _user_role(request.user)
        qs = PublishedResult.objects.filter(exam_id=exam_id).select_related('student__user')

        if role == 'student':
            qs = qs.filter(student__user=request.user)
        elif role == 'parents':
            qs = qs.filter(student__user__linked_parents=request.user)

        return Response({'success': True, 'count': qs.count(), 'data': PublishedResultSerializer(qs, many=True).data})


# ═══════════════════════════════════════════════════════════════════════════════
# 8. POST  /api/v1/exams/{id}/results/recheck-request/   (v2 NEW — FRD §4.6.2)
#    GET   /api/v1/exams/{id}/recheck-requests/
#    PATCH /api/v1/exams/{id}/recheck-requests/{request_id}/
# ═══════════════════════════════════════════════════════════════════════════════

class StudentRecheckRequestView(APIView):
    """Student raises a recheck request (FRD §4.6.2)."""
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
        if not PublishedResult.objects.filter(exam_id=exam_id, student=student).exists():
            return Response({'success': False, 'message': 'Results not published yet. Cannot request recheck.'}, status=status.HTTP_400_BAD_REQUEST)

        # Get marksheet
        try:
            ms = MarkSheet.objects.get(exam_id=exam_id, student=student)
        except MarkSheet.DoesNotExist:
            return Response({'success': False, 'message': 'MarkSheet not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Check no pending/approved recheck already exists
        if RecheckRequest.objects.filter(marksheet=ms, status__in=['pending', 'approved']).exists():
            return Response({'success': False, 'message': 'A recheck request is already pending or approved.'}, status=status.HTTP_409_CONFLICT)

        ser = RecheckRequestCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        rr = RecheckRequest.objects.create(
            marksheet=ms,
            requested_by=student,
            reason=ser.validated_data.get('reason', ''),
            status='pending',
        )

        # Notify ASE
        send_recheck_request_notification(rr)

        return Response({
            'recheck_requested': True, 'status': 'pending',
            'message': 'Your recheck request has been submitted for review.',
        }, status=status.HTTP_201_CREATED)


class RecheckRequestListView(APIView):
    """List recheck requests for an exam (admin/ASE)."""
    # permission_classes = [IsAuthenticated]

    def get(self, request, exam_id):
        role = _user_role(request.user)
        if role not in RECHECK_REQUEST_REVIEW_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        qs = RecheckRequest.objects.filter(
            marksheet__exam_id=exam_id
        ).select_related('marksheet', 'requested_by__user', 'reviewed_by', 'new_checker')

        return Response({'success': True, 'count': qs.count(), 'data': RecheckRequestSerializer(qs, many=True).data})


class RecheckRequestActionView(APIView):
    """ASE approves/rejects a recheck request (FRD §4.6.2)."""
    # permission_classes = [IsAuthenticated]

    def patch(self, request, exam_id, request_id):
        role = _user_role(request.user)
        if role not in ['super_admin', 'admin_senior_executive']:
            return Response({'success': False, 'message': 'Only ASE can review recheck requests.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            rr = RecheckRequest.objects.select_related('marksheet').get(id=request_id, marksheet__exam_id=exam_id)
        except RecheckRequest.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if rr.status not in ['pending']:
            return Response({'success': False, 'message': f'Cannot act on a request with status "{rr.status}".'}, status=status.HTTP_400_BAD_REQUEST)

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
            logger.info(f"[NOTIFY STUB] Recheck request {rr.id} rejected for student {rr.requested_by_id}")

            return Response({'success': True, 'message': 'Recheck request rejected.'})
