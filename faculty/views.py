import logging
from core.pagination import paginate_queryset
from django.utils import timezone
from django.db.models import Q, Count, Sum, Avg
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from core.utils import apply_filters

from .models import FacultyProfile, FacultyQRScanLog, SessionReport, SubjectHourlyRate
from .serializers import (
    FacultyListSerializer, FacultyDetailSerializer, FacultyCreateSerializer,
    FacultyUpdateSerializer, FacultyQRCheckinSerializer, FacultyQRScanLogSerializer,
    SessionReportSerializer, SessionReportCreateSerializer, SessionReportUpdateSerializer,
    SubjectHourlyRateSerializer, SubjectHourlyRateCreateSerializer,
)
from .utils import generate_employee_id, generate_faculty_qr_code

logger = logging.getLogger(__name__)

FACULTY_VIEW_ROLES = ['super_admin', 'branch_manager', 'admin_senior_executive']
FACULTY_CREATE_ROLES = ['super_admin', 'branch_manager']
FACULTY_EDIT_ROLES = ['super_admin', 'branch_manager', 'admin_senior_executive']
SESSION_VIEW_ROLES = ['super_admin', 'branch_manager', 'admin_senior_executive', 'faculty']
SUBJECT_RATE_VIEW_ROLES = ['accountant', 'branch_manager', 'admin_senior_executive', 'super_admin']
SUBJECT_RATE_EDIT_ROLES = ['branch_manager', 'admin_senior_executive', 'super_admin']


def _user_role(user):
    return getattr(user, 'role', None)


def _user_branch_id(user):
    if hasattr(user, 'branch_id') and user.branch_id:
        return user.branch_id
    if hasattr(user, 'profile') and hasattr(user.profile, 'branch_id'):
        return user.profile.branch_id
    # Fallback: check FacultyProfile
    try:
        from .models import FacultyProfile
        fp = FacultyProfile.objects.get(user=user)
        return fp.branch_id
    except Exception:
        pass
    return None


# ── Stub notification helper ──────────────────────────────────────────────────

def notify(recipient_user_id, title, body, metadata=None):
    """Stub: push/in-app notification. Replace with real implementation."""
    logger.info(f"NOTIFY [{recipient_user_id}] {title}: {body} | meta={metadata}")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. GET & POST  /api/v1/faculty/
# ═══════════════════════════════════════════════════════════════════════════════

class FacultyListCreateView(APIView):
    # permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_active', 'employment_type', 'level']
    search_fields = ['user__name', 'employee_id', 'specialization']
    ordering_fields = '__all__'

    def get(self, request):
        role = _user_role(request.user)
        if role == 'faculty':
            try:
                fp = FacultyProfile.objects.get(user=request.user)
                return Response({'success': True, 'data': FacultyDetailSerializer(fp, context={'request': request}).data})
            except FacultyProfile.DoesNotExist:
                return Response({'success': False, 'message': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        if role not in FACULTY_VIEW_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        qs = FacultyProfile.objects.select_related('user', 'branch').prefetch_related('batch_assignments__batch').annotate(
            batch_count=Count('batch_assignments', distinct=True)
        )
        if getattr(request.user, 'organization', None):
            qs = qs.filter(branch__organization=request.user.organization)
        bid = _user_branch_id(request.user)
        if role not in ('super_admin', 'branch_manager') and bid:
            qs = qs.filter(branch_id=bid)

        for param, field in [('is_active', 'is_active'), ('employment_type', 'employment_type'), ('level', 'level')]:
            val = request.GET.get(param)
            if val:
                if param == 'is_active':
                    qs = qs.filter(is_active=val.lower() == 'true')
                else:
                    qs = qs.filter(**{field: val})

        qs = apply_filters(self, request, qs)

        return paginate_queryset(qs, request, FacultyListSerializer, serializer_context={'request': request})

    def post(self, request):
        role = _user_role(request.user)
        if role not in FACULTY_CREATE_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        ser = FacultyCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        d = ser.validated_data
        from django.contrib.auth import get_user_model
        User = get_user_model()

        if User.objects.filter(email=d['email']).exists():
            return Response({'success': False, 'message': 'Email already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        branch_id = _user_branch_id(request.user) or request.data.get('branch_id') or request.data.get('branch')
        if not branch_id:
            return Response({'success': False, 'message': 'Branch is required.'}, status=status.HTTP_400_BAD_REQUEST)

        from branch.models import Branch
        try:
            branch = Branch.objects.get(id=branch_id)
        except Branch.DoesNotExist:
            return Response({'success': False, 'message': 'Branch not found.'}, status=status.HTTP_404_NOT_FOUND)

        base_username = d['email'].split('@')[0][:90]
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        try:
            user = User.objects.create_user(
                username=username,
                email=d['email'],
                password='changeme123',
                name=d['full_name'],
                phone=d.get('phone', ''),
                role='faculty',
            )
            # Link the user to the correct organization and branch
            if hasattr(user, 'organization'):
                user.organization = branch.organization
            if hasattr(user, 'branch_id'):
                user.branch_id = branch.id
            user.save()
            
            emp_id = generate_employee_id(branch)
            qr_file = generate_faculty_qr_code(emp_id)

            fp = FacultyProfile.objects.create(
                user=user, branch=branch, employee_id=emp_id,
                qualification=d['qualification'], specialization=d['specialization'],
                subject_expertise=d.get('subject_expertise', ''),
                level=d.get('level', 'executive'),
                employment_type=d.get('employment_type', 'full_time'),
                joining_date=d['joining_date'],
                salary=d.get('salary', 0), hourly_rate=d.get('hourly_rate', 0),
                bank_account=d.get('bank_account', ''),
                ifsc_code=d.get('ifsc_code', ''), pan_number=d.get('pan_number', ''),
            )
            if d.get('photo'):
                fp.photo = d['photo']
                fp.save(update_fields=['photo'])
            if qr_file:
                fp.qr_code.save(qr_file.name, qr_file, save=True)

        except Exception as e:
            logger.error(f"Faculty creation error: {e}")
            return Response({'success': False, 'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        data = FacultyDetailSerializer(fp, context={'request': request}).data
        return Response({
            'success': True, 'message': 'Faculty created.',
            'data': {
                'faculty_id': str(fp.id), 'employee_id': emp_id,
                'user_id': str(user.id),
                'photo_url': data.get('photo_url'),
                'qr_code_url': data.get('qr_code_url'),
            },
        }, status=status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. GET, PATCH  /api/v1/faculty/{id}/
# ═══════════════════════════════════════════════════════════════════════════════

class FacultyDetailView(APIView):
    # permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_faculty(self, request, faculty_id):
        try:
            qs = FacultyProfile.objects.select_related('user', 'branch').prefetch_related('batch_assignments__batch').all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            return qs.get(id=faculty_id)
        except FacultyProfile.DoesNotExist:
            return None

    def get(self, request, faculty_id):
        role = _user_role(request.user)
        fp = self._get_faculty(request, faculty_id)
        if fp is None:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if role == 'faculty' and fp.user != request.user:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if role not in FACULTY_VIEW_ROLES + ['faculty']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        return Response({'success': True, 'data': FacultyDetailSerializer(fp, context={'request': request}).data})

    def patch(self, request, faculty_id):
        role = _user_role(request.user)
        if role not in FACULTY_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        fp = self._get_faculty(request, faculty_id)
        if fp is None:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        ser = FacultyUpdateSerializer(fp, data=request.data, partial=True)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)
        ser.save()
        return Response({'success': True, 'message': 'Faculty updated.', 'data': FacultyDetailSerializer(fp, context={'request': request}).data})

    def delete(self, request, faculty_id):
        """DELETE /api/v1/faculty/{id}/ — soft-delete (deactivate) a faculty profile."""
        role = _user_role(request.user)
        if role not in FACULTY_CREATE_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        fp = self._get_faculty(request, faculty_id)
        if fp is None:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        fp.is_active = False
        fp.save(update_fields=['is_active'])
        # Also deactivate the user account
        fp.user.is_active = False
        fp.user.save(update_fields=['is_active'])
        return Response({'success': True, 'message': 'Faculty deactivated.'}, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. GET  /api/v1/faculty/{id}/qr-id/
# ═══════════════════════════════════════════════════════════════════════════════

class FacultyQRIDView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request, faculty_id):
        role = _user_role(request.user)
        try:
            qs = FacultyProfile.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            fp = qs.get(id=faculty_id)
        except FacultyProfile.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if role == 'faculty' and fp.user != request.user:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if role not in FACULTY_VIEW_ROLES + ['faculty']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if not fp.qr_code:
            qr_file = generate_faculty_qr_code(fp.employee_id)
            if qr_file:
                fp.qr_code.save(qr_file.name, qr_file, save=True)

        qr_url = None
        if fp.qr_code and hasattr(fp.qr_code, 'url'):
            qr_url = request.build_absolute_uri(fp.qr_code.url)
        return Response({'success': True, 'data': {'qr_code_url': qr_url}})


# ═══════════════════════════════════════════════════════════════════════════════
# 4. GET & POST  /api/v1/faculty/{id}/subject-rates/
# ═══════════════════════════════════════════════════════════════════════════════

class SubjectHourlyRateView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request, faculty_id):
        role = _user_role(request.user)
        if role not in SUBJECT_RATE_VIEW_ROLES and not (role == 'faculty'):
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            qs = FacultyProfile.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            fp = qs.get(id=faculty_id)
        except FacultyProfile.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if role == 'faculty' and fp.user != request.user:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        rates = SubjectHourlyRate.objects.filter(faculty=fp).select_related('subject')
        return Response({'success': True, 'data': SubjectHourlyRateSerializer(rates, many=True).data})

    def post(self, request, faculty_id):
        role = _user_role(request.user)
        if role not in SUBJECT_RATE_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            qs = FacultyProfile.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            fp = qs.get(id=faculty_id)
        except FacultyProfile.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        ser = SubjectHourlyRateCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        d = ser.validated_data
        if SubjectHourlyRate.objects.filter(
            faculty=fp, subject_id=d['subject_id'], effective_from=d['effective_from']
        ).exists():
            return Response({'success': False, 'message': 'Duplicate rate for this subject and date.'}, status=status.HTTP_409_CONFLICT)

        rate = SubjectHourlyRate.objects.create(
            faculty=fp, subject_id=d['subject_id'],
            hourly_rate=d['hourly_rate'], effective_from=d['effective_from'],
            created_by=request.user,
        )
        return Response({
            'success': True, 'message': 'Subject rate created.',
            'data': SubjectHourlyRateSerializer(rate).data,
        }, status=status.HTTP_201_CREATED)


class SubjectRateDetailView(APIView):
    """PATCH, DELETE /api/v1/faculty/{faculty_id}/subject-rates/{rate_id}/"""
    # permission_classes = [IsAuthenticated]

    def _get_rate(self, request, faculty_id, rate_id):
        role = _user_role(request.user)
        if role not in SUBJECT_RATE_EDIT_ROLES:
            return None, Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = SubjectHourlyRate.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(faculty__branch__organization=request.user.organization)
            rate = qs.get(id=rate_id, faculty_id=faculty_id)
        except SubjectHourlyRate.DoesNotExist:
            return None, Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return rate, None

    def patch(self, request, faculty_id, rate_id):
        rate, err = self._get_rate(request, faculty_id, rate_id)
        if err:
            return err
        if 'hourly_rate' in request.data:
            rate.hourly_rate = request.data['hourly_rate']
        if 'effective_from' in request.data:
            rate.effective_from = request.data['effective_from']
        rate.save()
        return Response({'success': True, 'message': 'Rate updated.', 'data': SubjectHourlyRateSerializer(rate).data})

    def delete(self, request, faculty_id, rate_id):
        rate, err = self._get_rate(request, faculty_id, rate_id)
        if err:
            return err
        rate.delete()
        return Response({'success': True, 'message': 'Rate deleted.'}, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. POST  /api/v1/faculty/qr-checkin/
# ═══════════════════════════════════════════════════════════════════════════════

class FacultyQRCheckinView(APIView):
    # permission_classes = [IsAuthenticated]

    def post(self, request):
        role = _user_role(request.user)
        if role != 'faculty':
            return Response({'success': False, 'message': 'Faculty only.'}, status=status.HTTP_403_FORBIDDEN)

        ser = FacultyQRCheckinSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        try:
            qs = FacultyProfile.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            fp = qs.get(user=request.user)
        except FacultyProfile.DoesNotExist:
            return Response({'success': False, 'message': 'Faculty profile not found.'}, status=status.HTTP_404_NOT_FOUND)

        if ser.validated_data['qr_data'] != fp.employee_id:
            return Response({'success': False, 'message': 'QR does not match your profile.'}, status=status.HTTP_400_BAD_REQUEST)

        scan_type = ser.validated_data['scan_type']
        is_late = False
        late_minutes = 0
        now = timezone.now()

        # Determine late status for check_in
        if scan_type == 'check_in':
            from payroll.models import LateEntryPolicy
            policy = LateEntryPolicy.objects.filter(branch=fp.branch, is_active=True).first()
            grace = policy.grace_period_minutes if policy else 5

            # Try to find today's expected start from batch timetable
            from batches.models import TimetableSlot
            dow = now.weekday()
            slots = TimetableSlot.objects.filter(
                faculty=fp, batch__branch=fp.branch, batch__is_active=True,
                day_of_week=dow, start_time__isnull=False
            )
            expected_start = None
            for slot in slots:
                if expected_start is None or slot.start_time < expected_start:
                    expected_start = slot.start_time

            if expected_start:
                from datetime import datetime, timedelta
                expected_dt = datetime.combine(now.date(), expected_start)
                actual_dt = datetime.combine(now.date(), now.time())
                diff = (actual_dt - expected_dt).total_seconds() / 60
                if diff > grace:
                    is_late = True
                    late_minutes = int(diff - grace)

        log = FacultyQRScanLog.objects.create(
            faculty=fp, branch=fp.branch,
            latitude=ser.validated_data.get('latitude'),
            longitude=ser.validated_data.get('longitude'),
            scan_type=scan_type,
            is_late=is_late, late_minutes=late_minutes,
        )

        if is_late:
            from leave.models import LateEntryRecord
            LateEntryRecord.objects.create(
                user=request.user, branch=fp.branch, date=now.date(),
                expected_time=expected_start or now.time(),
                actual_time=now.time(),
                late_minutes=late_minutes, recorded_by=None,
                is_penalized=True, penalty_type='salary_deduction',
            )
            # Check late entry threshold for auto half-day deduction
            from leave.utils import check_late_entry_threshold
            check_late_entry_threshold(request.user, now.month, now.year)

        message = 'Check-out recorded.' if scan_type == 'check_out' else (
            'Late check-in recorded.' if is_late else 'Check-in recorded.'
        )

        return Response({
            'success': True,
            'data': {
                'faculty_name': fp.user.name, 'employee_id': fp.employee_id,
                'scan_time': log.scanned_at, 'scan_type': log.scan_type,
                'is_late': is_late, 'late_minutes': late_minutes,
            },
            'message': message,
        }, status=status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. GET & POST  /api/v1/faculty/sessions/
# ═══════════════════════════════════════════════════════════════════════════════

class SessionListCreateView(APIView):
    # permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['batch_id', 'subject_id', 'status']
    search_fields = ['chapter_covered', 'topics_covered', 'notes']
    ordering_fields = '__all__'

    def get(self, request):
        role = _user_role(request.user)
        faculty_id = request.GET.get('faculty_id')

        if role == 'faculty':
            try:
                fp = FacultyProfile.objects.get(user=request.user)
            except FacultyProfile.DoesNotExist:
                return Response({'success': False, 'message': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)
            qs = SessionReport.objects.filter(faculty=fp)
        elif role in SESSION_VIEW_ROLES and faculty_id:
            qs = SessionReport.objects.filter(faculty_id=faculty_id)
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
        elif role in SESSION_VIEW_ROLES:
            qs = SessionReport.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            bid = _user_branch_id(request.user)
            if role != 'super_admin' and bid:
                qs = qs.filter(branch_id=bid)
        else:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        for param, field in [('batch_id', 'batch_id'), ('subject_id', 'subject_id'), ('status', 'status')]:
            val = request.GET.get(param)
            if val:
                qs = qs.filter(**{field: val})

        month = request.GET.get('month')
        if month:
            try:
                y, m = map(int, month.split('-'))
                qs = qs.filter(session_date__year=y, session_date__month=m)
            except (ValueError, AttributeError):
                pass

        qs = apply_filters(self, request, qs)

        return paginate_queryset(qs, request, SessionReportSerializer)

    def post(self, request):
        role = _user_role(request.user)
        if role not in SESSION_VIEW_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        ser = SessionReportCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        d = ser.validated_data
        try:
            qs = FacultyProfile.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            
            if role == 'faculty':
                fp = qs.get(user=request.user)
            else:
                fac_id = d.get('faculty_id')
                if not fac_id:
                    return Response({'success': False, 'message': 'faculty_id is required for admins.'}, status=status.HTTP_400_BAD_REQUEST)
                fp = qs.get(id=fac_id)
        except FacultyProfile.DoesNotExist:
            return Response({'success': False, 'message': 'Faculty profile not found.'}, status=status.HTTP_404_NOT_FOUND)

        d = ser.validated_data
        sr = SessionReport.objects.create(
            faculty=fp, branch=fp.branch,
            batch_id=d['batch_id'], subject_id=d['subject_id'],
            session_date=d['session_date'], chapter_covered=d['chapter_covered'],
            topics_covered=d['topics_covered'],
            completion_percentage=d.get('completion_percentage', 100),
            status=d['status'],
            start_time=d['start_time'], end_time=d['end_time'], notes=d.get('notes', ''),
        )

        return Response({
            'success': True, 'message': 'Session report created.',
            'data': SessionReportSerializer(sr).data,
        }, status=status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. GET, PATCH  /api/v1/faculty/sessions/{id}/
# ═══════════════════════════════════════════════════════════════════════════════

class SessionDetailView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        try:
            qs = SessionReport.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            sr = qs.get(id=session_id)
        except SessionReport.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': SessionReportSerializer(sr).data})

    def patch(self, request, session_id):
        role = _user_role(request.user)
        try:
            qs = SessionReport.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            sr = qs.get(id=session_id)
        except SessionReport.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if role == 'faculty' and sr.faculty.user != request.user:
            return Response({'success': False, 'message': 'Not your session.'}, status=status.HTTP_403_FORBIDDEN)
        if role not in ['faculty', 'admin_senior_executive', 'super_admin']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if (timezone.now().date() - sr.session_date).days > 7:
            return Response({'success': False, 'message': 'Cannot edit sessions older than 7 days.'}, status=status.HTTP_400_BAD_REQUEST)

        s = SessionReportUpdateSerializer(sr, data=request.data, partial=True)
        if not s.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': s.errors}, status=status.HTTP_400_BAD_REQUEST)
        s.save()
        return Response({'success': True, 'message': 'Session updated.', 'data': SessionReportSerializer(sr).data})

    def delete(self, request, session_id):
        """DELETE /api/v1/faculty/sessions/{id}/ — delete a session report."""
        role = _user_role(request.user)
        try:
            qs = SessionReport.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            sr = qs.get(id=session_id)
        except SessionReport.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if role == 'faculty' and sr.faculty.user != request.user:
            return Response({'success': False, 'message': 'Not your session.'}, status=status.HTTP_403_FORBIDDEN)
        if role not in ['faculty', 'admin_senior_executive', 'super_admin']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if (timezone.now().date() - sr.session_date).days > 7:
            return Response({'success': False, 'message': 'Cannot delete sessions older than 7 days.'}, status=status.HTTP_400_BAD_REQUEST)

        sr.delete()
        return Response({'success': True, 'message': 'Session deleted.'}, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. GET  /api/v1/faculty/sessions/summary/
# ═══════════════════════════════════════════════════════════════════════════════

class SessionSummaryView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request):
        role = _user_role(request.user)
        faculty_id = request.GET.get('faculty_id')
        month = request.GET.get('month')

        if role == 'faculty':
            try:
                fp = FacultyProfile.objects.get(user=request.user)
            except FacultyProfile.DoesNotExist:
                return Response({'success': False, 'message': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)
            qs = SessionReport.objects.filter(faculty=fp)
        elif role in SESSION_VIEW_ROLES and faculty_id:
            qs = SessionReport.objects.filter(faculty_id=faculty_id)
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
        else:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if month:
            try:
                y, m = map(int, month.split('-'))
                qs = qs.filter(session_date__year=y, session_date__month=m)
            except (ValueError, AttributeError):
                pass

        total = qs.count()
        completed = qs.filter(status='completed').count()
        in_progress = qs.filter(status='in_progress').count()
        total_minutes = sum(s.duration_minutes for s in qs)
        avg_completion = qs.aggregate(avg=Avg('completion_percentage'))['avg'] or 0

        by_subject = list(qs.values('subject__name').annotate(
            sessions=Count('id'), minutes=Sum('duration_minutes'),
            avg_completion=Avg('completion_percentage'),
        ))
        by_batch = list(qs.values('batch__name').annotate(sessions=Count('id')))

        return Response({
            'success': True,
            'data': {
                'total_sessions': total,
                'completed_sessions': completed,
                'in_progress_sessions': in_progress,
                'total_hours': round(total_minutes / 60, 2),
                'avg_completion_percentage': round(avg_completion, 1),
                'by_subject': [{
                    'subject_name': s['subject__name'],
                    'sessions': s['sessions'],
                    'hours': round((s['minutes'] or 0) / 60, 2),
                    'avg_completion': round(s['avg_completion'] or 0, 1),
                } for s in by_subject],
                'by_batch': [{'batch_name': b['batch__name'], 'sessions': b['sessions']} for b in by_batch],
            },
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 9. GET  /api/v1/faculty/{id}/sessions/  (faculty-specific sessions)
# ═══════════════════════════════════════════════════════════════════════════════

class FacultySessionsView(APIView):
    # permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['batch_id', 'subject_id', 'status']
    search_fields = ['chapter_covered', 'topics_covered']
    ordering_fields = '__all__'

    def get(self, request, faculty_id):
        role = _user_role(request.user)
        try:
            qs = FacultyProfile.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            fp = qs.get(id=faculty_id)
        except FacultyProfile.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if role == 'faculty' and fp.user != request.user:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if role not in SESSION_VIEW_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        qs = SessionReport.objects.filter(faculty=fp)

        for param, field in [('batch_id', 'batch_id'), ('subject_id', 'subject_id'), ('status', 'status')]:
            val = request.GET.get(param)
            if val:
                qs = qs.filter(**{field: val})

        month = request.GET.get('month')
        if month:
            try:
                y, m = map(int, month.split('-'))
                qs = qs.filter(session_date__year=y, session_date__month=m)
            except (ValueError, AttributeError):
                pass

        qs = apply_filters(self, request, qs)

        return paginate_queryset(qs, request, SessionReportSerializer)
