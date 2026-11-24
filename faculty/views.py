from datetime import timedelta
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
from core.utils import apply_filters, get_user_branch_id, get_user_branch_ids

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
    from core.utils import get_user_role
    return get_user_role(user)


# ── Stub notification helper ──────────────────────────────────────────────────

def notify(recipient_user_id, title, body, metadata=None, email_template=None, email_context=None, email_subject=None):
    from chat.notifications import send_system_notification
    if recipient_user_id:
        send_system_notification(
            user_id=str(recipient_user_id),
            title=title,
            body=body,
            metadata=metadata,
            email_template=email_template,
            email_context=email_context,
            email_subject=email_subject,
        )
# ═══════════════════════════════════════════════════════════════════════════════
# 1. GET & POST  /api/v1/faculty/
# ═══════════════════════════════════════════════════════════════════════════════

class FacultyListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['employment_type', 'level', 'branch']
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

        try:
            qs = FacultyProfile.objects.select_related('user', 'branch').prefetch_related(
                'batch_assignments__batch', 'levels', 'levels__course'
            ).annotate(
                batch_count=Count('batch_assignments', distinct=True)
            )
            branch_ids = get_user_branch_ids(request.user)
            if role == 'branch_manager':
                if branch_ids:
                    qs = qs.filter(branch_id__in=branch_ids)
                else:
                    qs = qs.none()
            elif getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            if role not in ('super_admin', 'branch_manager'):
                if branch_ids:
                    qs = qs.filter(branch_id__in=branch_ids)

            is_active = request.GET.get('is_active')
            if is_active is not None:
                normalized_is_active = is_active.strip().lower()
                if normalized_is_active in {'true', '1', 'yes'}:
                    qs = qs.filter(is_active=True, user__is_active=True)
                elif normalized_is_active in {'false', '0', 'no'}:
                    qs = qs.filter(Q(is_active=False) | Q(user__is_active=False))
                else:
                    return Response(
                        {'success': False, 'message': 'is_active must be true or false.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            employment_type = request.GET.get('employment_type')
            if employment_type:
                qs = qs.filter(employment_type=employment_type)

            # branch_id / branch filter â available to all roles (branch_manager
            # in particular uses this to scope the list to a specific branch).
            branch_filter = request.GET.get('branch_id') or request.GET.get('branch')
            if branch_filter:
                qs = qs.filter(branch_id=branch_filter)

            level_val = request.GET.get('level_id') or request.GET.get('level')
            if level_val:
                qs = qs.filter(
                    Q(level=level_val) |
                    Q(levels__id=level_val) |
                    Q(levels__name__icontains=level_val)
                ).distinct()

            qs = apply_filters(self, request, qs)

            return paginate_queryset(qs, request, FacultyListSerializer, serializer_context={'request': request})

        except Exception as e:
            logger.error(f'FacultyListCreateView.get error (role={role}): {e}', exc_info=True)
            return Response({'success': False, 'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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

        branch_id = get_user_branch_id(request.user) or request.data.get('branch_id') or request.data.get('branch')
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
                is_active=user.is_active,
                qualification=d['qualification'], specialization=d['specialization'],
                subject_expertise=d.get('subject_expertise', ''),
                level=d.get('level', 'executive'),
                employment_type=d.get('employment_type', 'full_time'),
                joining_date=d['joining_date'],
                salary=d.get('salary', 0), hourly_rate=d.get('hourly_rate', 0),
                bank_account=d.get('bank_account', ''),
                ifsc_code=d.get('ifsc_code', ''), pan_number=d.get('pan_number', ''),
                salary_retention_percentage=user.salary_retention_percentage,
            )
            if d.get('photo'):
                fp.photo = d['photo']
                fp.save(update_fields=['photo'])
            if qr_file:
                fp.qr_code.save(qr_file.name, qr_file, save=True)

            from faculty.serializers import resolve_course_levels
            levels_input = d.get('levels') or ([d.get('level')] if d.get('level') else [])
            if levels_input:
                resolved_levels = resolve_course_levels(levels_input, organization=branch.organization)
                fp.levels.set(resolved_levels)
                user.levels.set(resolved_levels)
                first_lvl = resolved_levels.first()
                if first_lvl:
                    name_lower = first_lvl.name.lower()
                    lvl_choice = 'professional' if 'professional' in name_lower else 'executive'
                    fp.level = lvl_choice
                    fp.save(update_fields=['level'])
                    user.level = lvl_choice
                    user.save(update_fields=['level'])

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
            from django.db.models import Q
            qs = FacultyProfile.objects.select_related('user', 'branch').prefetch_related(
                'batch_assignments__batch', 'levels', 'levels__course', 'user__faculty_chapters__subject'
            ).all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            return qs.filter(Q(id=faculty_id) | Q(user_id=faculty_id)).first()
        except Exception:
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
# 5. GET /api/v1/faculty/checkout-session-report/  &  POST /api/v1/faculty/qr-checkin/
# ═══════════════════════════════════════════════════════════════════════════════

def parse_time_str(t):
    if not t:
        return None
    from datetime import time, datetime
    if isinstance(t, time):
        return t
    t_str = str(t).strip()
    for fmt in ('%H:%M:%S', '%H:%M'):
        try:
            return datetime.strptime(t_str, fmt).time()
        except ValueError:
            pass
    return None


def build_faculty_checkout_autofill_data(fp, request=None):
    from datetime import datetime, timedelta, time
    from batches.models import TimetableSlot, Chapter, BatchFaculty, Batch, Subject
    from attendance.models import EmployeeAttendanceRecord

    local_now = timezone.localtime(timezone.now())
    today = local_now.date()
    dow = today.weekday()

    # 1. Attendance check
    open_record = EmployeeAttendanceRecord.objects.filter(
        user=fp.user, date=today, checked_in_at__isnull=False, checked_out_at__isnull=True
    ).order_by('-checked_in_at').first()

    latest_record = EmployeeAttendanceRecord.objects.filter(
        user=fp.user, date=today, checked_in_at__isnull=False
    ).order_by('-checked_in_at').first()

    checkin_log = FacultyQRScanLog.objects.filter(
        faculty=fp, scan_type='check_in', scanned_at__date=today
    ).order_by('-scanned_at').first()

    if open_record and open_record.checked_in_at:
        checkin_dt = timezone.localtime(open_record.checked_in_at)
        is_checked_in = True
        att_rec_id = str(open_record.id)
    elif checkin_log and checkin_log.scanned_at:
        checkin_dt = timezone.localtime(checkin_log.scanned_at)
        is_checked_in = True
        att_rec_id = None
    elif latest_record and latest_record.checked_in_at:
        checkin_dt = timezone.localtime(latest_record.checked_in_at)
        is_checked_in = False
        att_rec_id = str(latest_record.id)
    else:
        checkin_dt = None
        is_checked_in = False
        att_rec_id = None

    check_in_time_str = checkin_dt.strftime('%H:%M:%S') if checkin_dt else None
    check_in_short_str = checkin_dt.strftime('%H:%M') if checkin_dt else None
    check_out_time_str = local_now.strftime('%H:%M:%S')
    check_out_short_str = local_now.strftime('%H:%M')

    elapsed_minutes = 0
    if checkin_dt:
        elapsed_minutes = max(0, int((local_now - checkin_dt).total_seconds() / 60))

    # 2. Existing session reports today for this faculty
    existing_reports = list(SessionReport.objects.filter(
        faculty=fp, session_date=today
    ).select_related('batch', 'subject').prefetch_related('chapters'))

    used_report_ids = set()

    # 3. Timetable slots for today
    slots_qs = TimetableSlot.objects.filter(
        Q(day_of_week=dow) | Q(session_date=today),
        faculty=fp, batch__is_active=True
    ).filter(
        Q(effective_from__isnull=True) | Q(effective_from__lte=today)
    ).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=today)
    ).select_related('batch', 'subject', 'classroom').prefetch_related('chapters').order_by('start_time')

    slots = list(slots_qs)

    # 4. Process slots & match existing reports
    today_slots_data = []
    pending_slots = []

    for slot in slots:
        matched_sr = None
        if slot.start_time:
            slot_start_dt = datetime.combine(today, slot.start_time)
            for sr in existing_reports:
                if sr.id in used_report_ids:
                    continue
                if sr.batch_id == slot.batch_id and sr.subject_id == slot.subject_id:
                    sr_start_dt = datetime.combine(today, sr.start_time)
                    diff_mins = abs((sr_start_dt - slot_start_dt).total_seconds() / 60)
                    if diff_mins <= 45:
                        matched_sr = sr
                        used_report_ids.add(sr.id)
                        break

        slot_start_str = slot.start_time.strftime('%H:%M') if slot.start_time else ''
        slot_end_str = slot.end_time.strftime('%H:%M') if slot.end_time else ''
        sched_duration = 0
        if slot.start_time and slot.end_time:
            st_dt = datetime.combine(today, slot.start_time)
            et_dt = datetime.combine(today, slot.end_time)
            if et_dt < st_dt:
                et_dt += timedelta(days=1)
            sched_duration = int((et_dt - st_dt).total_seconds() / 60)

        slot_item = {
            'timetable_slot_id': str(slot.id),
            'slot_code': slot.slot_code or '',
            'session_type': slot.session_type,
            'session_name': slot.session_name or '',
            'batch_id': str(slot.batch.id) if slot.batch else None,
            'batch_name': slot.batch.name if slot.batch else '',
            'subject_id': str(slot.subject.id) if slot.subject else None,
            'subject_name': slot.subject.name if slot.subject else '',
            'classroom_id': str(slot.classroom.id) if slot.classroom else None,
            'classroom_name': getattr(slot.classroom, 'room_number', None) or getattr(slot.classroom, 'name', '') if slot.classroom else '',
            'scheduled_start_time': slot_start_str,
            'scheduled_end_time': slot_end_str,
            'duration_minutes': sched_duration,
            'already_submitted': matched_sr is not None,
            'existing_report_id': str(matched_sr.id) if matched_sr else None,
            'existing_report': {
                'id': str(matched_sr.id),
                'chapter_covered': matched_sr.chapter_covered,
                'topics_covered': matched_sr.topics_covered,
                'status': matched_sr.status,
                'completion_percentage': matched_sr.completion_percentage,
                'start_time': matched_sr.start_time.strftime('%H:%M') if matched_sr.start_time else '',
                'end_time': matched_sr.end_time.strftime('%H:%M') if matched_sr.end_time else '',
                'duration_minutes': matched_sr.duration_minutes,
            } if matched_sr else None
        }

        today_slots_data.append(slot_item)
        if not matched_sr:
            pending_slots.append((slot, slot_item))

    # 5. Determine active / current slot to autofill
    current_slot = None
    current_slot_item = None

    if pending_slots:
        # Match closest pending slot to checkin_dt or local_now
        ref_time = checkin_dt.time() if checkin_dt else local_now.time()
        ref_dt = datetime.combine(today, ref_time)
        best_diff = None
        for s, s_item in pending_slots:
            if s.start_time:
                s_dt = datetime.combine(today, s.start_time)
                diff = abs((s_dt - ref_dt).total_seconds())
                if best_diff is None or diff < best_diff:
                    best_diff = diff
                    current_slot = s
                    current_slot_item = s_item
        if not current_slot and pending_slots:
            current_slot, current_slot_item = pending_slots[0]
    elif slots:
        # All slots already submitted, default to the last slot
        current_slot = slots[-1]
        current_slot_item = today_slots_data[-1]

    # Helper to resolve chapters & suggested topics for a given batch & subject
    def get_chapters_and_suggestion(batch, subject, slot=None):
        if not subject:
            return [], [], [], "", ""

        chapters_qs = Chapter.objects.filter(subject=subject, is_active=True).order_by('order')
        all_chapters_data = [
            {'id': str(c.id), 'name': c.name, 'order': c.order, 'description': c.description or ''}
            for c in chapters_qs
        ]

        suggested_chapters = []
        if slot and slot.chapters.exists():
            suggested_chapters = list(slot.chapters.all())
        else:
            prev_sr = SessionReport.objects.filter(
                batch=batch, subject=subject
            ).exclude(session_date=today, id__in=used_report_ids).order_by('-session_date', '-start_time').first()

            if prev_sr:
                if prev_sr.completion_percentage < 100:
                    suggested_chapters = list(prev_sr.chapters.all())
                else:
                    prev_last_ch = prev_sr.chapters.order_by('-order').first()
                    if prev_last_ch and prev_last_ch.order is not None:
                        next_ch = chapters_qs.filter(order__gt=prev_last_ch.order).order_by('order').first()
                        suggested_chapters = [next_ch] if next_ch else [prev_last_ch]
                    else:
                        first_ch = chapters_qs.first()
                        suggested_chapters = [first_ch] if first_ch else []
            else:
                first_ch = chapters_qs.first()
                suggested_chapters = [first_ch] if first_ch else []

        suggested_chapters = [c for c in suggested_chapters if c is not None]
        suggested_ids = [str(c.id) for c in suggested_chapters]
        suggested_names = [c.name for c in suggested_chapters]
        chapter_str = ", ".join(suggested_names)

        topics = ""
        if slot and slot.session_name:
            topics = slot.session_name
        elif suggested_names:
            topics = f"Covered {chapter_str}"

        return all_chapters_data, suggested_ids, suggested_names, chapter_str, topics

    # Build pre-filled session reports for all pending slots
    prefilled_reports = []
    for s, s_item in pending_slots:
        all_ch, ch_ids, ch_names, ch_str, topics = get_chapters_and_suggestion(s.batch, s.subject, slot=s)

        is_cur = bool(current_slot and s.id == current_slot.id)
        st_time = s.start_time.strftime('%H:%M') if s.start_time else (check_in_short_str or '09:00')
        et_time = s.end_time.strftime('%H:%M') if s.end_time else (check_out_short_str or '10:00')
        dur_mins = s_item['duration_minutes']

        rep_dict = {
            'timetable_slot_id': str(s.id),
            'batch_id': str(s.batch.id) if s.batch else None,
            'batch_name': s.batch.name if s.batch else '',
            'subject_id': str(s.subject.id) if s.subject else None,
            'subject_name': s.subject.name if s.subject else '',
            'classroom_id': str(s.classroom.id) if s.classroom else None,
            'classroom_name': getattr(s.classroom, 'room_number', None) or getattr(s.classroom, 'name', '') if s.classroom else '',
            'session_type': s.session_type,
            'session_name': s.session_name or '',
            'slot_code': s.slot_code or '',
            'scheduled_start_time': s_item['scheduled_start_time'],
            'scheduled_end_time': s_item['scheduled_end_time'],
            'start_time': st_time,
            'end_time': et_time,
            'duration_minutes': dur_mins,
            'session_date': today.strftime('%Y-%m-%d'),
            'chapter_ids': ch_ids,
            'chapter_names': ch_names,
            'chapter_covered': ch_str,
            'topics_covered': topics,
            'completion_percentage': 100,
            'status': 'completed',
            'notes': '',
            'already_submitted': False,
            'is_current': is_cur,
            'available_chapters': all_ch
        }
        prefilled_reports.append(rep_dict)

    # 6. Build current_session object
    current_session = None
    if current_slot:
        for pr in prefilled_reports:
            if pr['timetable_slot_id'] == str(current_slot.id):
                current_session = pr
                break
        if not current_session:
            all_ch, ch_ids, ch_names, ch_str, topics = get_chapters_and_suggestion(current_slot.batch, current_slot.subject, slot=current_slot)
            current_session = {
                'timetable_slot_id': str(current_slot.id),
                'batch_id': str(current_slot.batch.id) if current_slot.batch else None,
                'batch_name': current_slot.batch.name if current_slot.batch else '',
                'subject_id': str(current_slot.subject.id) if current_slot.subject else None,
                'subject_name': current_slot.subject.name if current_slot.subject else '',
                'classroom_id': str(current_slot.classroom.id) if current_slot.classroom else None,
                'classroom_name': getattr(current_slot.classroom, 'room_number', None) or getattr(current_slot.classroom, 'name', '') if current_slot.classroom else '',
                'session_type': current_slot.session_type,
                'session_name': current_slot.session_name or '',
                'slot_code': current_slot.slot_code or '',
                'scheduled_start_time': current_slot.start_time.strftime('%H:%M') if current_slot.start_time else '',
                'scheduled_end_time': current_slot.end_time.strftime('%H:%M') if current_slot.end_time else '',
                'start_time': current_slot.start_time.strftime('%H:%M') if current_slot.start_time else (check_in_short_str or '09:00'),
                'end_time': current_slot.end_time.strftime('%H:%M') if current_slot.end_time else (check_out_short_str or '10:00'),
                'duration_minutes': current_slot_item['duration_minutes'] if current_slot_item else 0,
                'session_date': today.strftime('%Y-%m-%d'),
                'chapter_ids': ch_ids,
                'chapter_names': ch_names,
                'chapter_covered': ch_str,
                'topics_covered': topics,
                'completion_percentage': 100,
                'status': 'completed',
                'notes': '',
                'already_submitted': current_slot_item['already_submitted'] if current_slot_item else False,
                'is_current': True,
                'available_chapters': all_ch
            }
    else:
        # Fallback: No slots today, check BatchFaculty
        bf = BatchFaculty.objects.filter(faculty=fp, batch__is_active=True).select_related('batch', 'subject').first()
        b = bf.batch if bf else None
        s = bf.subject if bf else None
        all_ch, ch_ids, ch_names, ch_str, topics = get_chapters_and_suggestion(b, s)

        st_time = check_in_short_str or '09:00'
        et_time = check_out_short_str or '10:00'
        dur_mins = elapsed_minutes if elapsed_minutes > 0 else 60

        current_session = {
            'timetable_slot_id': None,
            'batch_id': str(b.id) if b else None,
            'batch_name': b.name if b else '',
            'subject_id': str(s.id) if s else None,
            'subject_name': s.name if s else '',
            'classroom_id': None,
            'classroom_name': '',
            'session_type': 'regular',
            'session_name': '',
            'slot_code': '',
            'scheduled_start_time': None,
            'scheduled_end_time': None,
            'start_time': st_time,
            'end_time': et_time,
            'duration_minutes': dur_mins,
            'session_date': today.strftime('%Y-%m-%d'),
            'chapter_ids': ch_ids,
            'chapter_names': ch_names,
            'chapter_covered': ch_str,
            'topics_covered': topics,
            'completion_percentage': 100,
            'status': 'completed',
            'notes': '',
            'already_submitted': False,
            'is_current': True,
            'available_chapters': all_ch
        }
        if b and s:
            prefilled_reports.append(current_session)

    # 7. Build hierarchy of all assigned batches, subjects, and chapters for dropdown selection
    batches_dict = {}
    for slot in slots:
        if not slot.batch:
            continue
        b_id = str(slot.batch.id)
        if b_id not in batches_dict:
            batches_dict[b_id] = {
                'id': b_id,
                'name': slot.batch.name,
                'subjects': []
            }
        if slot.subject:
            sub_id = str(slot.subject.id)
            if not any(sb['id'] == sub_id for sb in batches_dict[b_id]['subjects']):
                chs = Chapter.objects.filter(subject=slot.subject, is_active=True).order_by('order')
                batches_dict[b_id]['subjects'].append({
                    'id': sub_id,
                    'name': slot.subject.name,
                    'chapters': [{'id': str(c.id), 'name': c.name, 'order': c.order} for c in chs]
                })

    bf_qs = BatchFaculty.objects.filter(faculty=fp, batch__is_active=True).select_related('batch', 'subject')
    for bf in bf_qs:
        if not bf.batch:
            continue
        b_id = str(bf.batch.id)
        if b_id not in batches_dict:
            batches_dict[b_id] = {
                'id': b_id,
                'name': bf.batch.name,
                'subjects': []
            }
        if bf.subject:
            sub_id = str(bf.subject.id)
            if not any(sb['id'] == sub_id for sb in batches_dict[b_id]['subjects']):
                chs = Chapter.objects.filter(subject=bf.subject, is_active=True).order_by('order')
                batches_dict[b_id]['subjects'].append({
                    'id': sub_id,
                    'name': bf.subject.name,
                    'chapters': [{'id': str(c.id), 'name': c.name, 'order': c.order} for c in chs]
                })

    # Mark `is_current` on today_slots_data
    if current_slot:
        for s_item in today_slots_data:
            s_item['is_current'] = bool(s_item['timetable_slot_id'] == str(current_slot.id))

    return {
        # Top-level legacy & direct autofill keys for immediate checkout submission
        'faculty_id': str(fp.id),
        'faculty_name': fp.user.name if fp.user else '',
        'employee_id': fp.employee_id,
        'branch_id': str(fp.branch_id) if fp.branch_id else None,
        'branch_name': fp.branch.name if fp.branch else '',
        'date': today.strftime('%d-%m-%Y'),
        'iso_date': today.strftime('%Y-%m-%d'),
        'start_time': check_in_short_str or (current_session['start_time'] if current_session else None),
        'end_time': check_out_short_str or (current_session['end_time'] if current_session else None),

        # Direct auto-filled batch & subject for checkout submission
        'batch_id': current_session['batch_id'] if current_session else None,
        'batch_name': current_session['batch_name'] if current_session else '',
        'subject_id': current_session['subject_id'] if current_session else None,
        'subject_name': current_session['subject_name'] if current_session else '',
        'timetable_slot_id': current_session['timetable_slot_id'] if current_session else None,
        'classroom_name': current_session['classroom_name'] if current_session else '',
        'chapter_ids': current_session['chapter_ids'] if current_session else [],
        'chapter_names': current_session['chapter_names'] if current_session else [],
        'chapter_covered': current_session['chapter_covered'] if current_session else '',
        'topics_covered': current_session['topics_covered'] if current_session else '',
        'completion_percentage': current_session['completion_percentage'] if current_session else 100,
        'status': current_session['status'] if current_session else 'completed',
        'available_chapters': current_session['available_chapters'] if current_session else [],

        # Attendance details
        'attendance': {
            'is_checked_in': is_checked_in,
            'check_in_time': check_in_time_str,
            'check_out_time': check_out_time_str,
            'duration_minutes': elapsed_minutes,
            'attendance_record_id': att_rec_id,
        },

        # Current session to autofill
        'current_session': current_session,

        # All pending session reports for today
        'session_reports': prefilled_reports,

        # All scheduled slots for today with submission status
        'today_slots': today_slots_data,

        # Full hierarchy for dropdown selections
        'batches': list(batches_dict.values()),
        'has_pending_reports': len(prefilled_reports) > 0
    }


class FacultyCheckoutSessionReportView(APIView):
    """
    GET /api/v1/faculty/checkout-session-report/
    GET /api/v1/faculty/session-reports/autofill/

    Auto-fills and returns session report data on checkout for faculty:
    - batch_id, batch_name, subject_id, subject_name, chapter_ids, topics_covered
    - faculty profile details
    - attendance record & check-in timing
    - current_session: pre-filled session report for the session being checked out right now
    - session_reports: array of pre-filled session reports for all pending sessions today
    - today_slots: all timetable slots for today with submission status
    - batches: available batches, subjects, and chapters for dropdown selection
    """
    def get(self, request):
        role = _user_role(request.user)
        if role not in SESSION_VIEW_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        fp = None
        qr_data = request.query_params.get('qr_data')
        if qr_data:
            fp = FacultyProfile.objects.select_related('user', 'branch').filter(employee_id=qr_data).first()

        if not fp:
            if role == 'faculty':
                try:
                    fp = FacultyProfile.objects.select_related('user', 'branch').get(user=request.user)
                except FacultyProfile.DoesNotExist:
                    return Response({'success': False, 'message': 'Faculty profile not found.'}, status=status.HTTP_404_NOT_FOUND)
            else:
                qs = FacultyProfile.objects.select_related('user', 'branch')
                if getattr(request.user, 'organization', None):
                    qs = qs.filter(branch__organization=request.user.organization)

                fac_id = request.query_params.get('faculty_id') or request.query_params.get('id')
                emp_id = request.query_params.get('employee_id')
                u_id = request.query_params.get('user_id')

                if fac_id:
                    fp = qs.filter(id=fac_id).first()
                elif emp_id:
                    fp = qs.filter(employee_id=emp_id).first()
                elif u_id:
                    fp = qs.filter(user_id=u_id).first()
                elif hasattr(request.user, 'faculty_profile'):
                    fp = request.user.faculty_profile

                if not fp:
                    return Response({'success': False, 'message': 'Faculty profile not found. Please provide faculty_id or qr_data.'}, status=status.HTTP_400_BAD_REQUEST)

        data = build_faculty_checkout_autofill_data(fp, request)
        return Response({'success': True, 'data': data})


class FacultyQRCheckinView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request):
        role = _user_role(request.user)
        qr_data = request.query_params.get('qr_data')
        fp = None
        if qr_data:
            fp = FacultyProfile.objects.select_related('user', 'branch').filter(employee_id=qr_data).first()

        if not fp:
            if role != 'faculty':
                return Response({'success': False, 'message': 'Faculty only.'}, status=status.HTTP_403_FORBIDDEN)
            try:
                fp = FacultyProfile.objects.select_related('user', 'branch').get(user=request.user)
            except FacultyProfile.DoesNotExist:
                return Response({'success': False, 'message': 'Faculty profile not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = build_faculty_checkout_autofill_data(fp, request)
        return Response({'success': True, 'data': data})

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
        is_early_checkout = False
        early_minutes = 0
        # Use local time for all comparisons with timetable slot times (which are stored in IST)
        now = timezone.localtime(timezone.now())

        from payroll.models import LateEntryPolicy
        policy = LateEntryPolicy.objects.filter(branch=fp.branch, is_active=True).first()
        grace = policy.grace_period_minutes if policy else 5

        from batches.models import TimetableSlot
        from django.db.models import Q
        from attendance.models import EmployeeAttendanceRecord
        
        # 1. Determine Timetable Slot for current time
        current_time = now.time()
        current_dow = now.weekday()
        
        from datetime import timedelta
        buffered_time = (now + timedelta(minutes=15)).time()

        # Get matching slots within the time window (15 min buffer)
        matching_slots = TimetableSlot.objects.filter(
            faculty=fp,
            day_of_week=current_dow,
            start_time__lte=buffered_time,
            end_time__gte=current_time
        ).order_by('start_time')

        # Collect already-attended slot IDs for today
        attended_slot_ids = set(
            EmployeeAttendanceRecord.objects.filter(
                user=request.user, date=now.date(), timetable_slot__isnull=False
            ).values_list('timetable_slot_id', flat=True)
        )

        # Pick the first matching slot that hasn't fully ended yet and isn't attended
        active_slot = None
        for slot in matching_slots:
            if slot.id not in attended_slot_ids:
                active_slot = slot
                break

        # Check if there's any future slot to give a good error message if they are too early
        future_slot = None
        if not active_slot:
            future_slot = TimetableSlot.objects.filter(
                faculty=fp,
                day_of_week=current_dow,
                start_time__gt=buffered_time
            ).order_by('start_time').first()

        # If no active slot found from matching slots, but there's a past matching slot that was attended,
        # we can use that to trigger the "already marked" message instead of "too early".
        if not active_slot and not future_slot and matching_slots.exists():
            active_slot = matching_slots.last()

        # 2. Check existing open record
        open_record = EmployeeAttendanceRecord.objects.filter(
            user=request.user, date=now.date(), checked_in_at__isnull=False, checked_out_at__isnull=True
        ).order_by('-checked_in_at').first()

        if scan_type == 'check_in':
            if open_record:
                return Response({'success': False, 'message': 'You are already checked in. Please check out first.'}, status=status.HTTP_400_BAD_REQUEST)
            
            if active_slot:
                if EmployeeAttendanceRecord.objects.filter(user=request.user, date=now.date(), timetable_slot=active_slot).exists():
                    return Response({'success': False, 'message': 'You have already marked attendance for this slot today.'}, status=status.HTTP_400_BAD_REQUEST)
            else:
                if future_slot:
                    formatted_time = future_slot.start_time.strftime("%I:%M %p")
                    return Response({'success': False, 'message': f'You are too early to check in. Your next session starts at {formatted_time}. Check-in is allowed 15 minutes prior.'}, status=status.HTTP_400_BAD_REQUEST)
                
                completed_today = EmployeeAttendanceRecord.objects.filter(
                    user=request.user, date=now.date(), checked_in_at__isnull=False, checked_out_at__isnull=False
                ).exists()
                if completed_today:
                    return Response({'success': False, 'message': 'You have already completed attendance for all your sessions today.'}, status=status.HTTP_400_BAD_REQUEST)

        elif scan_type == 'check_out':
            if not open_record:
                return Response({'success': False, 'message': 'Must check in first before checking out.'}, status=status.HTTP_400_BAD_REQUEST)

        # Determine late status for check_in
        if scan_type == 'check_in':
            expected_start = None
            if active_slot and active_slot.start_time:
                expected_start = active_slot.start_time
            elif future_slot and future_slot.start_time:
                expected_start = future_slot.start_time

            if expected_start:
                from datetime import datetime
                expected_dt = datetime.combine(now.date(), expected_start)
                actual_dt = datetime.combine(now.date(), now.time())
                diff = (actual_dt - expected_dt).total_seconds() / 60
                if diff > grace:
                    is_late = True
                    late_minutes = int(diff)
        
        elif scan_type == 'check_out':
            expected_end = None
            if open_record and open_record.timetable_slot and open_record.timetable_slot.end_time:
                expected_end = open_record.timetable_slot.end_time
            else:
                # Fallback to the latest slot of the day if no open record matched
                dow = now.weekday()
                slots = TimetableSlot.objects.filter(
                    Q(day_of_week=dow) | Q(session_date=now.date()),
                    faculty=fp, batch__branch=fp.branch, batch__is_active=True,
                    end_time__isnull=False
                )
                for slot in slots:
                    if expected_end is None or slot.end_time > expected_end:
                        expected_end = slot.end_time
            
            if expected_end:
                from datetime import datetime
                expected_dt = datetime.combine(now.date(), expected_end)
                actual_dt = datetime.combine(now.date(), now.time())
                diff = (expected_dt - actual_dt).total_seconds() / 60
                if diff > grace:
                    is_early_checkout = True
                    early_minutes = int(diff)

        log = FacultyQRScanLog.objects.create(
            faculty=fp, branch=fp.branch,
            latitude=ser.validated_data.get('latitude'),
            longitude=ser.validated_data.get('longitude'),
            scan_type=scan_type,
            is_late=is_late, late_minutes=late_minutes,
            is_early_checkout=is_early_checkout, early_minutes=early_minutes,
        )
        
        if scan_type == 'check_out':
            session_reports_data = ser.validated_data.get('session_reports')
            if session_reports_data:
                from batches.models import Batch, Subject, Chapter
                from batches.models import TimetableSlot as TTSlot
                from django.db.models import Q as SlotQ
                session_dow = now.weekday()
                
                for rdata in session_reports_data:
                    batch_id = rdata.get('batch_id')
                    subject_id = rdata.get('subject_id')
                    chapter_ids = rdata.get('chapter_ids', [])
                    status_val = rdata.get('status', 'completed')
                    
                    slot_id = rdata.get('timetable_slot_id') or rdata.get('slot_id')
                    session_slot = None
                    if slot_id:
                        session_slot = TTSlot.objects.filter(id=slot_id).first()
                    
                    # Auto-detect batch and subject from today's timetable slot if not provided
                    if not batch_id or not subject_id:
                        candidate_slots = TTSlot.objects.filter(
                            SlotQ(day_of_week=session_dow) | SlotQ(session_date=now.date()),
                            faculty=fp, batch__is_active=True
                        ).order_by('start_time')
                        if candidate_slots.exists():
                            session_slot = candidate_slots.first()
                            if not batch_id and session_slot.batch_id:
                                batch_id = str(session_slot.batch_id)
                            if not subject_id and session_slot.subject_id:
                                subject_id = str(session_slot.subject_id)
                            if not chapter_ids and session_slot.chapters.exists():
                                chapter_ids = list(session_slot.chapters.values_list('id', flat=True))
                    
                    if batch_id and subject_id:
                        batch = Batch.objects.filter(id=batch_id).first()
                        subject = Subject.objects.filter(id=subject_id).first()
                        
                        chapters_str = ""
                        chapters_qs = None
                        if chapter_ids:
                            chapters_qs = Chapter.objects.filter(id__in=chapter_ids)
                            chapters_str = ", ".join([c.name for c in chapters_qs])
                        chapter_covered_val = rdata.get('chapter_covered') or chapters_str or "General"
                        
                        # Match timetable slot if not yet matched
                        if not session_slot:
                            session_slot = TTSlot.objects.filter(
                                SlotQ(day_of_week=session_dow) | SlotQ(session_date=now.date()),
                                batch=batch, subject=subject, faculty=fp
                            ).first()
                        if not session_slot:
                            session_slot = TTSlot.objects.filter(
                                SlotQ(day_of_week=session_dow) | SlotQ(session_date=now.date()),
                                batch=batch, subject=subject
                            ).first()

                        # Parse or determine start_time and end_time
                        start_time = None
                        end_time = None
                        st_raw = rdata.get('start_time')
                        et_raw = rdata.get('end_time')
                        if st_raw and et_raw:
                            start_time = parse_time_str(st_raw)
                            end_time = parse_time_str(et_raw)

                        if not start_time or not end_time:
                            if session_slot and session_slot.start_time and session_slot.end_time:
                                start_time = session_slot.start_time
                                end_time = session_slot.end_time
                            else:
                                checkin_log = FacultyQRScanLog.objects.filter(
                                    faculty=fp, scan_type='check_in', scanned_at__date=now.date()
                                ).order_by('scanned_at').first()
                                if checkin_log:
                                    start_time = timezone.localtime(checkin_log.scanned_at).time()
                                else:
                                    start_time = now.time()
                                end_time = now.time()
                            
                        if batch and subject:
                            sr = SessionReport.objects.create(
                                faculty=fp, branch=fp.branch,
                                batch=batch, subject=subject,
                                session_date=now.date(),
                                chapter_covered=chapter_covered_val,
                                topics_covered=rdata.get('topics_covered', ''),
                                status=status_val,
                                start_time=start_time,
                                end_time=end_time,
                                completion_percentage=rdata.get('completion_percentage', 100),
                                notes=rdata.get('notes', ''),
                            )
                            if chapter_ids and chapters_qs:
                                sr.chapters.set(chapters_qs)

        if scan_type == 'check_in':
            EmployeeAttendanceRecord.objects.filter(
                user=request.user,
                date=now.date(),
                status='absent'
            ).delete()
            EmployeeAttendanceRecord.objects.create(
                user=request.user, date=now.date(), timetable_slot=active_slot,
                branch_id=fp.branch_id, status='checkout_pending', checked_in_at=now,
                latitude=ser.validated_data.get('latitude'),
                longitude=ser.validated_data.get('longitude'),
                location_verified=True,
                check_in_method='qr',
            )
        elif scan_type == 'check_out':
            if open_record:
                open_record.checked_out_at = now
                open_record.status = 'present'
                open_record.check_out_method = 'qr'
                checkout_lat = ser.validated_data.get('latitude')
                checkout_lng = ser.validated_data.get('longitude')
                checkout_fields = ['checked_out_at', 'status', 'check_out_method']
                if checkout_lat is not None and checkout_lng is not None:
                    open_record.checkout_latitude = checkout_lat
                    open_record.checkout_longitude = checkout_lng
                    open_record.checkout_location_verified = True
                    checkout_fields.extend(['checkout_latitude', 'checkout_longitude', 'checkout_location_verified'])
                open_record.save(update_fields=checkout_fields)

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

        # Send notification using the new helper
        try:
            from attendance.notifications import notify_faculty_checkin
            notify_faculty_checkin(request.user, scan_type, now, is_late=is_late, late_minutes=late_minutes)
        except Exception as ne:
            logger.error(f"Faculty checkin notification failed: {ne}")

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
            if role != 'super_admin':
                branch_ids = get_user_branch_ids(request.user)
                if branch_ids:
                    qs = qs.filter(branch_id__in=branch_ids)
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

# ═══════════════════════════════════════════════════════════════════════════════
# 10. GET  /api/v1/faculty/extra-hours/
# ═══════════════════════════════════════════════════════════════════════════════

class FacultyExtraHoursView(APIView):
    def get(self, request):
        role = _user_role(request.user)
        if role != 'faculty':
            return Response({'success': False, 'message': 'Only faculty can access this endpoint.'}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            fp = FacultyProfile.objects.get(user=request.user)
        except FacultyProfile.DoesNotExist:
            return Response({'success': False, 'message': 'Faculty profile not found.'}, status=status.HTTP_404_NOT_FOUND)

        from batches.models import TimetableSlot
        slots = TimetableSlot.objects.filter(faculty=fp).prefetch_related('chapters')
        
        from collections import defaultdict
        chapter_duration = defaultdict(float)
        chapter_objects = {}
        
        from datetime import datetime, date
        for slot in slots:
            if slot.start_time and slot.end_time:
                t1 = datetime.combine(date.today(), slot.start_time)
                t2 = datetime.combine(date.today(), slot.end_time)
                if t2 > t1:
                    duration = (t2 - t1).total_seconds()
                    if slot.is_recurring and slot.effective_from and slot.effective_to:
                        days = (slot.effective_to - slot.effective_from).days
                        weeks = max(1, days // 7)
                        total_seconds = duration * weeks
                    else:
                        total_seconds = duration
                        
                    for chapter in slot.chapters.all():
                        chapter_duration[chapter.id] += total_seconds
                        chapter_objects[chapter.id] = chapter
                        
        results = []
        for ch_id, total_seconds in chapter_duration.items():
            total_hours_given = total_seconds / 3600.0
            chapter = chapter_objects[ch_id]
            allocated = chapter.duration_hours
            
            if total_hours_given > allocated:
                extra_hours = total_hours_given - allocated
                results.append({
                    'chapter_id': chapter.id,
                    'chapter_name': chapter.name,
                    'subject_name': chapter.subject.name,
                    'allocated_hours': allocated,
                    'total_hours_given': round(total_hours_given, 1),
                    'extra_hours': round(extra_hours, 1),
                    'message': f"Great dedication! You have spent {round(extra_hours, 1)} extra hours ensuring students deeply understand this chapter."
                })
                
        return Response({
            'success': True,
            'data': results
        })
