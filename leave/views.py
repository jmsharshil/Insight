import logging
from core.pagination import paginate_queryset
from decimal import Decimal
from datetime import datetime
from django.db import models
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from .models import LeavePolicy, LeaveBalance, LeaveApplication, LateEntryRecord, PublicHoliday
from .serializers import (
    LeavePolicySerializer, LeavePolicyInputSerializer,
    LeaveBalanceSerializer, LeaveApplicationListSerializer,
    LeaveApplicationDetailSerializer, LeaveApplicationCreateSerializer,
    LateEntryRecordSerializer, LateEntryCreateSerializer,
    PublicHolidaySerializer, PublicHolidayCreateSerializer,
)
from .utils import calculate_leave_days, check_leave_overlap, check_late_entry_threshold

logger = logging.getLogger(__name__)

ADMIN_ROLES = ['super_admin', 'branch_manager', 'admin_senior_executive']
LEAVE_APPLY_EXCLUDE = ['student', 'parents', 'accountant']
LEAVE_APPROVE_ROLES = ['branch_manager', 'admin_senior_executive']
POLICY_EDIT_ROLES = ['super_admin', 'branch_manager']
LATE_ENTRY_ADMIN = ['branch_manager', 'admin_senior_executive']
HOLIDAY_EDIT_ROLES = ['branch_manager', 'super_admin']


def _user_role(user):
    return getattr(user, 'role', None)


def _user_branch_id(user):
    if hasattr(user, 'branch_id') and user.branch_id:
        return user.branch_id
    if hasattr(user, 'profile') and hasattr(user.profile, 'branch_id'):
        return user.profile.branch_id
    # Fallback: check FacultyProfile
    try:
        from faculty.models import FacultyProfile
        fp = FacultyProfile.objects.get(user=user)
        return fp.branch_id
    except Exception:
        pass
    return None


def notify(recipient_user_id, title, body, metadata=None):
    """Stub: push/in-app notification. Replace with real implementation."""
    logger.info(f"NOTIFY [{recipient_user_id}] {title}: {body} | meta={metadata}")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. GET & POST  /api/v1/leave/
# ═══════════════════════════════════════════════════════════════════════════════

class LeaveListCreateView(APIView):
    # permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        role = _user_role(request.user)
        if role in ADMIN_ROLES:
            qs = LeaveApplication.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            bid = _user_branch_id(request.user)
            if role != 'super_admin' and bid:
                qs = qs.filter(branch_id=bid)
        else:
            qs = LeaveApplication.objects.filter(applied_by=request.user)

        for param, field in [('status', 'status'), ('leave_type', 'leave_type'), ('applied_by', 'applied_by_id')]:
            val = request.GET.get(param)
            if val:
                qs = qs.filter(**{field: val})

        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')
        if from_date:
            qs = qs.filter(from_date__gte=from_date)
        if to_date:
            qs = qs.filter(to_date__lte=to_date)

        return paginate_queryset(qs, request, LeaveApplicationListSerializer, serializer_context={'request': request})

    def post(self, request):
        role = _user_role(request.user)
        if role in LEAVE_APPLY_EXCLUDE:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        ser = LeaveApplicationCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        d = ser.validated_data
        today = timezone.now().date()

        # Past date check (except sick leave)
        if d['leave_type'] != 'sick' and d['from_date'] < today:
            return Response({'success': False, 'message': 'Leave date cannot be in the past.'}, status=status.HTTP_400_BAD_REQUEST)

        # Get policy
        bid = _user_branch_id(request.user)
        policy = LeavePolicy.objects.filter(branch_id=bid, leave_type=d['leave_type'], is_active=True).first()

        # Advance notice check (except sick leave)
        if policy and d['leave_type'] != 'sick':
            advance = (d['from_date'] - today).days
            if advance < policy.min_advance_days:
                return Response({
                    'success': False,
                    'message': f"Leave must be requested at least {policy.min_advance_days} days in advance.",
                }, status=status.HTTP_400_BAD_REQUEST)

        # Calculate total days
        sandwich = policy.sandwich_rule if policy else False
        from branch.models import Branch
        branch_obj = Branch.objects.filter(id=bid).first() if bid else None
        total_days = calculate_leave_days(d['from_date'], d['to_date'], d['is_half_day'], sandwich, branch=branch_obj)

        # Sick leave > 2 days: require supporting_document (FRD §4.9.1)
        if d['leave_type'] == 'sick' and total_days > 2 and not d.get('supporting_document'):
            return Response({
                'success': False,
                'message': "Doctor's certificate required for sick leave > 2 days.",
            }, status=status.HTTP_400_BAD_REQUEST)

        # Club leave cap
        if d['leave_type'] == 'club' and policy:
            used_club = LeaveApplication.objects.filter(
                applied_by=request.user, leave_type='club', status='approved',
                from_date__year=today.year,
            ).aggregate(total=models.Sum('total_days'))['total'] or Decimal(0)
            if used_club + total_days > policy.max_club_days:
                return Response({'success': False, 'message': f"Club leave cap exceeded (max {policy.max_club_days} days/year)."}, status=status.HTTP_400_BAD_REQUEST)

        # Balance check
        balance = LeaveBalance.objects.filter(
            user=request.user, leave_type=d['leave_type'], year=today.year,
        ).first()
        if balance and balance.remaining_days < total_days:
            return Response({'success': False, 'message': f"Insufficient balance. Remaining: {balance.remaining_days} days."}, status=status.HTTP_400_BAD_REQUEST)

        # Overlap check
        has_overlap, conflict = check_leave_overlap(request.user, d['from_date'], d['to_date'])
        if has_overlap:
            return Response({'success': False, 'message': 'Overlapping leave exists.'}, status=status.HTTP_409_CONFLICT)

        app = LeaveApplication.objects.create(
            applied_by=request.user, branch_id=bid,
            leave_type=d['leave_type'], from_date=d['from_date'], to_date=d['to_date'],
            is_half_day=d['is_half_day'], half_day_session=d.get('half_day_session', ''),
            total_days=total_days, reason=d['reason'],
            supporting_document=d.get('supporting_document'),
        )

        # FRD §4.9.2: Push notification to ASE (Step 1 approver)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        ase_users = User.objects.filter(role='admin_senior_executive', is_active=True)
        if bid:
            ase_users_branch = ase_users  # filter by branch if branch field exists on User
        for ase in ase_users:
            notify(
                str(ase.id),
                title="Leave request pending approval",
                body=f"{request.user.name} has applied for {d['leave_type']} leave from {d['from_date']} to {d['to_date']}",
                metadata={"leave_id": str(app.id), "approval_step": 1},
            )

        return Response({
            'success': True, 'message': 'Leave application submitted.',
            'data': LeaveApplicationDetailSerializer(app, context={'request': request}).data,
        }, status=status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. GET, PATCH, DELETE  /api/v1/leave/{id}/
# ═══════════════════════════════════════════════════════════════════════════════

class LeaveDetailView(APIView):
    # permission_classes = [IsAuthenticated]

    def _get_leave(self, request, leave_id):
        try:
            qs = LeaveApplication.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            return qs.get(id=leave_id)
        except LeaveApplication.DoesNotExist:
            return None

    def get(self, request, leave_id):
        app = self._get_leave(request, leave_id)
        if app is None:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        role = _user_role(request.user)
        if role not in ADMIN_ROLES and app.applied_by != request.user:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        return Response({'success': True, 'data': LeaveApplicationDetailSerializer(app, context={'request': request}).data})

    def patch(self, request, leave_id):
        app = self._get_leave(request, leave_id)
        if app is None:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if app.applied_by != request.user:
            return Response({'success': False, 'message': 'Only the applicant can edit.'}, status=status.HTTP_403_FORBIDDEN)
        if app.status != 'pending':
            return Response({'success': False, 'message': 'Can only edit pending applications.'}, status=status.HTTP_400_BAD_REQUEST)

        allowed_fields = ['from_date', 'to_date', 'is_half_day', 'half_day_session', 'reason']
        for key, val in request.data.items():
            if key in allowed_fields:
                setattr(app, key, val)
        app.save()
        return Response({'success': True, 'message': 'Leave updated.', 'data': LeaveApplicationDetailSerializer(app, context={'request': request}).data})

    def delete(self, request, leave_id):
        app = self._get_leave(request, leave_id)
        if app is None:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if app.applied_by != request.user:
            return Response({'success': False, 'message': 'Only the applicant can cancel.'}, status=status.HTTP_403_FORBIDDEN)
        if app.status != 'pending':
            return Response({'success': False, 'message': 'Can only cancel pending applications.'}, status=status.HTTP_400_BAD_REQUEST)

        app.status = 'cancelled'
        app.save(update_fields=['status'])
        return Response({'success': True, 'message': 'Leave cancelled.'})


# ═══════════════════════════════════════════════════════════════════════════════
# 3. POST  /api/v1/leave/{id}/approve/
# ═══════════════════════════════════════════════════════════════════════════════

class LeaveApproveView(APIView):
    # permission_classes = [IsAuthenticated]

    def post(self, request, leave_id):
        role = _user_role(request.user)
        if role not in LEAVE_APPROVE_ROLES + ['super_admin']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            qs = LeaveApplication.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            app = qs.get(id=leave_id)
        except LeaveApplication.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if app.applied_by == request.user:
            return Response({'success': False, 'message': 'Cannot approve your own leave.'}, status=status.HTTP_403_FORBIDDEN)

        if app.status != 'pending':
            return Response({'success': False, 'message': 'Only pending leaves can be approved.'}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()

        # Step 1: admin_senior_executive first approval
        if role == 'admin_senior_executive':
            if app.first_approver:
                return Response({'success': False, 'message': 'First approval already done.'}, status=status.HTTP_400_BAD_REQUEST)
            app.first_approver = request.user
            app.first_approved_at = now
            app.save(update_fields=['first_approver', 'first_approved_at'])

            # FRD §4.9.2: Push notification to branch_manager (Step 2)
            from django.contrib.auth import get_user_model
            User = get_user_model()
            bm_users = User.objects.filter(role='branch_manager', is_active=True)
            for bm in bm_users:
                notify(
                    str(bm.id),
                    title="Leave awaiting your approval",
                    body=f"{app.applied_by.name} leave approved by ASE. Your approval needed.",
                    metadata={"leave_id": str(app.id), "approval_step": 2},
                )

            return Response({'success': True, 'message': 'First approval done. Awaiting branch manager.'})

        # Step 2: branch_manager second approval
        if role == 'branch_manager':
            if not app.first_approver:
                return Response({'success': False, 'message': 'First approval by admin_senior_executive is required.'}, status=status.HTTP_400_BAD_REQUEST)
            app.second_approver = request.user
            app.second_approved_at = now
            app.status = 'approved'
            app.reviewed_by = request.user
            app.reviewed_at = now
            app.save()

            # Deduct balance
            balance = LeaveBalance.objects.filter(
                user=app.applied_by, leave_type=app.leave_type, year=app.from_date.year,
            ).first()
            if balance:
                balance.used_days += app.total_days
                balance.save(update_fields=['used_days'])

            # FRD §4.9.2: Push notification to applicant
            notify(
                str(app.applied_by.id),
                title="Leave Approved",
                body=f"Your {app.leave_type} leave from {app.from_date} to {app.to_date} has been approved.",
                metadata={"leave_id": str(app.id), "status": "approved"},
            )

            return Response({'success': True, 'message': 'Leave approved.'})

        # super_admin can do both steps at once
        if role == 'super_admin':
            app.first_approver = app.first_approver or request.user
            app.first_approved_at = app.first_approved_at or now
            app.second_approver = request.user
            app.second_approved_at = now
            app.status = 'approved'
            app.reviewed_by = request.user
            app.reviewed_at = now
            app.save()

            balance = LeaveBalance.objects.filter(
                user=app.applied_by, leave_type=app.leave_type, year=app.from_date.year,
            ).first()
            if balance:
                balance.used_days += app.total_days
                balance.save(update_fields=['used_days'])

            notify(
                str(app.applied_by.id),
                title="Leave Approved",
                body=f"Your {app.leave_type} leave from {app.from_date} to {app.to_date} has been approved.",
                metadata={"leave_id": str(app.id), "status": "approved"},
            )

            return Response({'success': True, 'message': 'Leave approved (super_admin).'})

        return Response({'success': False, 'message': 'Invalid role for approval.'}, status=status.HTTP_403_FORBIDDEN)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. POST  /api/v1/leave/{id}/reject/
# ═══════════════════════════════════════════════════════════════════════════════

class LeaveRejectView(APIView):
    # permission_classes = [IsAuthenticated]

    def post(self, request, leave_id):
        role = _user_role(request.user)
        if role not in LEAVE_APPROVE_ROLES + ['super_admin']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            qs = LeaveApplication.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            app = qs.get(id=leave_id)
        except LeaveApplication.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        reason = request.data.get('reason', '')
        app.status = 'rejected'
        app.rejection_reason = reason
        app.reviewed_by = request.user
        app.reviewed_at = timezone.now()
        app.save()

        # FRD §4.9.2: Push notification to applicant WITH reason
        notify(
            str(app.applied_by.id),
            title="Leave Rejected",
            body=f"Your leave request was rejected. Reason: {reason}",
            metadata={
                "leave_id": str(app.id),
                "status": "rejected",
                "rejection_reason": reason,
            },
        )

        return Response({'success': True, 'message': 'Leave rejected.'})


# ═══════════════════════════════════════════════════════════════════════════════
# 5. GET & POST  /api/v1/leave/policy/
# ═══════════════════════════════════════════════════════════════════════════════

class LeavePolicyView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request):
        bid = _user_branch_id(request.user)
        qs = LeavePolicy.objects.filter(is_active=True)
        if getattr(request.user, 'organization', None):
            qs = qs.filter(branch__organization=request.user.organization)
        if bid:
            qs = qs.filter(branch_id=bid)
        return Response({'success': True, 'data': LeavePolicySerializer(qs, many=True).data})

    def post(self, request):
        role = _user_role(request.user)
        if role not in POLICY_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        ser = LeavePolicyInputSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        bid = _user_branch_id(request.user) or request.data.get('branch_id')
        if not bid:
            return Response({'success': False, 'message': 'Branch required.'}, status=status.HTTP_400_BAD_REQUEST)

        policy, created = LeavePolicy.objects.update_or_create(
            branch_id=bid, leave_type=ser.validated_data['leave_type'],
            defaults=ser.validated_data,
        )
        return Response({
            'success': True,
            'message': 'Policy created.' if created else 'Policy updated.',
            'data': LeavePolicySerializer(policy).data,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class LeavePolicyDetailView(APIView):
    # permission_classes = [IsAuthenticated]

    def patch(self, request, policy_id):
        role = _user_role(request.user)
        if role not in POLICY_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = LeavePolicy.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            policy = qs.get(id=policy_id)
        except LeavePolicy.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        allowed = ['annual_quota', 'max_club_days', 'min_advance_days', 'allow_half_day', 'sandwich_rule', 'carry_forward', 'max_carry_days']
        for k, v in request.data.items():
            if k in allowed:
                setattr(policy, k, v)
        policy.save()
        return Response({'success': True, 'message': 'Policy updated.', 'data': LeavePolicySerializer(policy).data})

    def delete(self, request, policy_id):
        """DELETE /api/v1/leave/policy/{id}/ — deactivate a leave policy."""
        role = _user_role(request.user)
        if role not in POLICY_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = LeavePolicy.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            policy = qs.get(id=policy_id)
        except LeavePolicy.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        policy.is_active = False
        policy.save(update_fields=['is_active'])
        return Response({'success': True, 'message': 'Leave policy deactivated.'})


# ═══════════════════════════════════════════════════════════════════════════════
# 6. GET  /api/v1/leave/balance/
# ═══════════════════════════════════════════════════════════════════════════════

class LeaveBalanceView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request):
        year = timezone.now().year
        balances = LeaveBalance.objects.filter(user=request.user, year=year)
        return Response({'success': True, 'data': LeaveBalanceSerializer(balances, many=True).data})


class LeaveBalanceUserView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        role = _user_role(request.user)
        if role not in ADMIN_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        year = request.GET.get('year', timezone.now().year)
        qs = LeaveBalance.objects.filter(user_id=user_id, year=year)
        if getattr(request.user, 'organization', None):
            qs = qs.filter(user__organization=request.user.organization)
        return Response({'success': True, 'data': LeaveBalanceSerializer(qs, many=True).data})


# ═══════════════════════════════════════════════════════════════════════════════
# 7. GET & POST  /api/v1/leave/late-entries/
# ═══════════════════════════════════════════════════════════════════════════════

class LateEntryListCreateView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request):
        role = _user_role(request.user)
        if role in LATE_ENTRY_ADMIN + ['super_admin']:
            qs = LateEntryRecord.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            bid = _user_branch_id(request.user)
            if role != 'super_admin' and bid:
                qs = qs.filter(branch_id=bid)
        else:
            qs = LateEntryRecord.objects.filter(user=request.user)

        user_id = request.GET.get('user_id')
        if user_id and role in LATE_ENTRY_ADMIN + ['super_admin']:
            qs = qs.filter(user_id=user_id)

        is_penalized = request.GET.get('is_penalized')
        if is_penalized is not None:
            qs = qs.filter(is_penalized=is_penalized.lower() == 'true')

        # Date range filters
        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')
        if from_date:
            qs = qs.filter(date__gte=from_date)
        if to_date:
            qs = qs.filter(date__lte=to_date)

        return paginate_queryset(qs, request, LateEntryRecordSerializer)

    def post(self, request):
        role = _user_role(request.user)
        if role not in LATE_ENTRY_ADMIN + ['super_admin']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        ser = LateEntryCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        d = ser.validated_data
        start_dt = datetime.combine(d['date'], d['actual_time'])
        expected_dt = datetime.combine(d['date'], d['expected_time'])
        late_min = max(0, int((start_dt - expected_dt).total_seconds() / 60))

        bid = _user_branch_id(request.user) or request.data.get('branch_id')

        # Get grace from policy
        from payroll.models import LateEntryPolicy
        policy = LateEntryPolicy.objects.filter(branch_id=bid, is_active=True).first()
        grace = policy.grace_period_minutes if policy else 10

        record = LateEntryRecord.objects.create(
            user_id=d['user_id'], branch_id=bid, date=d['date'],
            expected_time=d['expected_time'], actual_time=d['actual_time'],
            late_minutes=late_min, grace_minutes=grace,
            is_penalized=late_min > grace,
            penalty_type=d.get('penalty_type', '') if late_min > grace else '',
            notes=d.get('notes', ''), recorded_by=request.user,
        )

        # Check late entry threshold
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            target_user = User.objects.get(id=d['user_id'])
            check_late_entry_threshold(target_user, d['date'].month, d['date'].year)
        except User.DoesNotExist:
            pass

        return Response({
            'success': True, 'message': 'Late entry recorded.',
            'data': LateEntryRecordSerializer(record).data,
        }, status=status.HTTP_201_CREATED)


class LateEntryDetailView(APIView):
    """PATCH, DELETE /api/v1/leave/late-entries/{entry_id}/"""
    # permission_classes = [IsAuthenticated]

    def _get_entry(self, request, entry_id):
        role = _user_role(request.user)
        if role not in LATE_ENTRY_ADMIN + ['super_admin']:
            return None, Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = LateEntryRecord.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            return qs.get(id=entry_id), None
        except LateEntryRecord.DoesNotExist:
            return None, Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    def patch(self, request, entry_id):
        record, err = self._get_entry(request, entry_id)
        if err:
            return err
        for field in ['is_penalized', 'penalty_type', 'notes']:
            if field in request.data:
                setattr(record, field, request.data[field])
        record.save()
        return Response({'success': True, 'message': 'Late entry updated.', 'data': LateEntryRecordSerializer(record).data})

    def delete(self, request, entry_id):
        record, err = self._get_entry(request, entry_id)
        if err:
            return err
        record.delete()
        return Response({'success': True, 'message': 'Late entry deleted.'}, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. GET, POST, DELETE  /api/v1/leave/public-holidays/
# ═══════════════════════════════════════════════════════════════════════════════

class PublicHolidayListCreateView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request):
        bid = _user_branch_id(request.user)
        qs = PublicHoliday.objects.all()
        if getattr(request.user, 'organization', None):
            qs = qs.filter(branch__organization=request.user.organization)
        if bid:
            qs = qs.filter(branch_id=bid)

        year = request.GET.get('year')
        if year:
            qs = qs.filter(year=year)

        return Response({'success': True, 'data': PublicHolidaySerializer(qs, many=True).data})

    def post(self, request):
        role = _user_role(request.user)
        if role not in HOLIDAY_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        ser = PublicHolidayCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        bid = _user_branch_id(request.user) or request.data.get('branch_id')
        if not bid:
            return Response({'success': False, 'message': 'Branch required.'}, status=status.HTTP_400_BAD_REQUEST)

        d = ser.validated_data
        if PublicHoliday.objects.filter(branch_id=bid, date=d['date']).exists():
            return Response({'success': False, 'message': 'Holiday already exists for this date.'}, status=status.HTTP_409_CONFLICT)

        holiday = PublicHoliday.objects.create(
            branch_id=bid,
            date=d['date'],
            name=d['name'],
            year=d['date'].year,
            created_by=request.user,
        )
        return Response({
            'success': True, 'message': 'Public holiday created.',
            'data': PublicHolidaySerializer(holiday).data,
        }, status=status.HTTP_201_CREATED)


class PublicHolidayDetailView(APIView):
    # permission_classes = [IsAuthenticated]

    def patch(self, request, holiday_id):
        """PATCH /api/v1/leave/public-holidays/{id}/ — update a public holiday."""
        role = _user_role(request.user)
        if role not in HOLIDAY_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            qs = PublicHoliday.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            holiday = qs.get(id=holiday_id)
        except PublicHoliday.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if 'name' in request.data:
            holiday.name = request.data['name']
        if 'date' in request.data:
            from datetime import date as _date
            holiday.date = request.data['date']
            if isinstance(holiday.date, str):
                holiday.date = _date.fromisoformat(holiday.date)
            holiday.year = holiday.date.year
        holiday.save()
        return Response({'success': True, 'message': 'Holiday updated.', 'data': PublicHolidaySerializer(holiday).data})

    def delete(self, request, holiday_id):
        role = _user_role(request.user)
        if role not in HOLIDAY_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            qs = PublicHoliday.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            holiday = qs.get(id=holiday_id)
        except PublicHoliday.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        holiday.delete()
        return Response({'success': True, 'message': 'Public holiday deleted.'})
