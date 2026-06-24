import logging
from core.pagination import paginate_queryset
from decimal import Decimal
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from core.utils import apply_filters

from .models import PayrollRun, PaySlip, LateEntryPolicy
from .serializers import (
    PayrollRunListSerializer, PayrollRunDetailSerializer, PaySlipSerializer,
    PayrollGenerateSerializer, LateEntryPolicySerializer, LateEntryPolicyInputSerializer,
    PaySlipAdjustSerializer,
)
from .utils import compute_payslip_for_faculty, compute_payslip_for_user, EMPLOYEE_ROLES

logger = logging.getLogger(__name__)

PAYROLL_GENERATE_ROLES = ['accountant', 'super_admin']
PAYROLL_VIEW_ROLES = ['accountant', 'super_admin', 'branch_manager']
PAYROLL_APPROVE_ROLES = ['branch_manager', 'super_admin']
PAYROLL_DISBURSE_ROLES = ['super_admin', 'accountant']
LATE_POLICY_VIEW_ROLES = ['super_admin', 'branch_manager', 'accountant']
LATE_POLICY_EDIT_ROLES = ['super_admin', 'branch_manager']


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
# 1. GET & POST  /api/v1/payroll/
# ═══════════════════════════════════════════════════════════════════════════════

class PayrollListCreateView(APIView):
    # permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['year', 'month', 'status']
    search_fields = ['branch__name']
    ordering_fields = '__all__'

    def get(self, request):
        role = _user_role(request.user)
        if role not in PAYROLL_VIEW_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        # ── Default to current month/year if not provided ──
        now = timezone.now()
        year = request.GET.get('year', str(now.year))
        month = request.GET.get('month', str(now.month))
        req_branch_id = request.GET.get('branch_id')
        bid = _user_branch_id(request.user)

        target_branch_id = bid if (role != 'super_admin' and bid) else req_branch_id

        # ── Auto-generate payroll on GET ──
        try:
            y_int = int(year)
            m_int = int(month)
            from faculty.models import FacultyProfile
            from django.contrib.auth import get_user_model
            User = get_user_model()

            # Determine which branches to auto-generate for
            if target_branch_id:
                branch_ids = [target_branch_id]
            else:
                # super_admin with no branch filter → auto-generate for all branches that have active employees
                fp_qs = FacultyProfile.objects.filter(is_active=True)
                staff_qs = User.objects.filter(role__in=EMPLOYEE_ROLES, is_active=True)
                if getattr(request.user, 'organization', None):
                    fp_qs = fp_qs.filter(branch__organization=request.user.organization)
                    staff_qs = staff_qs.filter(organization=request.user.organization)
                faculty_branch_ids = set(fp_qs.values_list('branch_id', flat=True).distinct())
                staff_branch_ids = set(staff_qs.exclude(branch_id__isnull=True).values_list('branch_id', flat=True).distinct())
                branch_ids = list(faculty_branch_ids | staff_branch_ids)

            for br_id in branch_ids:
                faculty_list = FacultyProfile.objects.filter(branch_id=br_id, is_active=True)
                # Non-faculty staff employees in this branch (exclude users who already have FacultyProfile)
                faculty_user_ids = set(FacultyProfile.objects.filter(branch_id=br_id, is_active=True).values_list('user_id', flat=True))
                staff_users = User.objects.filter(
                    branch_id=br_id, role__in=EMPLOYEE_ROLES, is_active=True
                ).exclude(id__in=faculty_user_ids)

                if not faculty_list.exists() and not staff_users.exists():
                    continue

                pr, created = PayrollRun.objects.get_or_create(
                    branch_id=br_id, month=m_int, year=y_int,
                    defaults={'generated_by': request.user}
                )

                if created:
                    # First time → generate all payslips
                    total = Decimal(0)
                    for fp in faculty_list:
                        ps = compute_payslip_for_faculty(fp, m_int, y_int, pr)
                        total += ps.net_salary
                    for u in staff_users:
                        ps = compute_payslip_for_user(u, m_int, y_int, pr)
                        total += ps.net_salary
                    pr.total_amount = total
                    pr.save(update_fields=['total_amount'])

                elif pr.status == 'draft':
                    # Already exists as draft → regenerate payslips so edited salary/rate is reflected
                    pr.payslips.all().delete()
                    total = Decimal(0)
                    for fp in faculty_list:
                        ps = compute_payslip_for_faculty(fp, m_int, y_int, pr)
                        total += ps.net_salary
                    for u in staff_users:
                        ps = compute_payslip_for_user(u, m_int, y_int, pr)
                        total += ps.net_salary
                    pr.total_amount = total
                    pr.save(update_fields=['total_amount'])
                
                else:
                    # It's approved or disbursed. Generate for missing faculties/staff only.
                    existing_faculty_ids = set(pr.payslips.filter(faculty__isnull=False).values_list('faculty_id', flat=True))
                    existing_user_ids = set(pr.payslips.filter(user__isnull=False).values_list('user_id', flat=True))
                    missing_faculties = faculty_list.exclude(id__in=existing_faculty_ids)
                    missing_staff = staff_users.exclude(id__in=existing_user_ids)
                    if missing_faculties.exists() or missing_staff.exists():
                        added_total = Decimal(0)
                        for fp in missing_faculties:
                            ps = compute_payslip_for_faculty(fp, m_int, y_int, pr)
                            added_total += ps.net_salary
                        for u in missing_staff:
                            ps = compute_payslip_for_user(u, m_int, y_int, pr)
                            added_total += ps.net_salary
                        pr.total_amount += added_total
                        pr.status = 'pending_approval'
                        pr.save(update_fields=['total_amount', 'status'])

        except (ValueError, TypeError):
            pass

        # ── Return payroll list ──
        qs = PayrollRun.objects.select_related('branch').all()
        if getattr(request.user, 'organization', None):
            qs = qs.filter(branch__organization=request.user.organization)
        if target_branch_id:
            qs = qs.filter(branch_id=target_branch_id)

        for param, field in [('year', 'year'), ('month', 'month'), ('status', 'status')]:
            val = request.GET.get(param)
            if val:
                qs = qs.filter(**{field: val})

        qs = apply_filters(self, request, qs)

        return paginate_queryset(qs, request, PayrollRunListSerializer)

    def post(self, request):
        role = _user_role(request.user)
        if role not in PAYROLL_GENERATE_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        ser = PayrollGenerateSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        d = ser.validated_data
        from faculty.models import FacultyProfile
        from django.contrib.auth import get_user_model
        User = get_user_model()

        # Non-faculty staff for this branch
        faculty_user_ids = set(FacultyProfile.objects.filter(branch=d['branch_id'], is_active=True).values_list('user_id', flat=True))
        staff_users = User.objects.filter(
            branch=d['branch_id'], role__in=EMPLOYEE_ROLES, is_active=True
        ).exclude(id__in=faculty_user_ids)

        existing_run = PayrollRun.objects.filter(branch=d['branch_id'], month=d['month'], year=d['year']).first()
        if existing_run:
            if existing_run.status == 'draft':
                # Regenerate payslips for draft
                existing_run.payslips.all().delete()
                faculty_list = FacultyProfile.objects.filter(branch=d['branch_id'], is_active=True)
                total = Decimal(0)
                for fp in faculty_list:
                    ps = compute_payslip_for_faculty(fp, d['month'], d['year'], existing_run)
                    total += ps.net_salary
                for u in staff_users:
                    ps = compute_payslip_for_user(u, d['month'], d['year'], existing_run)
                    total += ps.net_salary
                existing_run.total_amount = total
                existing_run.save(update_fields=['total_amount'])
                message = 'Payroll regenerated.'
            else:
                # It's approved or disbursed. Just generate for missing employees.
                existing_faculty_ids = set(existing_run.payslips.filter(faculty__isnull=False).values_list('faculty_id', flat=True))
                existing_user_ids = set(existing_run.payslips.filter(user__isnull=False).values_list('user_id', flat=True))
                faculty_list = FacultyProfile.objects.filter(branch=d['branch_id'], is_active=True).exclude(id__in=existing_faculty_ids)
                missing_staff = staff_users.exclude(id__in=existing_user_ids)
                if not faculty_list.exists() and not missing_staff.exists():
                    return Response({'success': False, 'message': f'Payroll already {existing_run.status}. All active employees already have payslips.'}, status=status.HTTP_409_CONFLICT)
                
                added_total = Decimal(0)
                for fp in faculty_list:
                    ps = compute_payslip_for_faculty(fp, d['month'], d['year'], existing_run)
                    added_total += ps.net_salary
                for u in missing_staff:
                    ps = compute_payslip_for_user(u, d['month'], d['year'], existing_run)
                    added_total += ps.net_salary
                
                existing_run.total_amount += added_total
                existing_run.status = 'pending_approval'
                existing_run.save(update_fields=['total_amount', 'status'])
                message = f'Added missing payslips and changed status to pending_approval.'
            
            return Response({
                'success': True, 'message': message,
                'data': {
                    'payroll_run_id': str(existing_run.id), 'status': existing_run.status,
                    'total_amount': str(existing_run.total_amount),
                    'employee_count': existing_run.payslips.count(), 'generated_at': existing_run.generated_at,
                },
            }, status=status.HTTP_200_OK)

        payroll_run = PayrollRun.objects.create(
            branch=d['branch_id'], month=d['month'], year=d['year'],
            generated_by=request.user,
        )

        faculty_list = FacultyProfile.objects.filter(branch=d['branch_id'], is_active=True)
        total = Decimal(0)
        for fp in faculty_list:
            ps = compute_payslip_for_faculty(fp, d['month'], d['year'], payroll_run)
            total += ps.net_salary
        for u in staff_users:
            ps = compute_payslip_for_user(u, d['month'], d['year'], payroll_run)
            total += ps.net_salary

        payroll_run.total_amount = total
        payroll_run.save(update_fields=['total_amount'])

        return Response({
            'success': True, 'message': 'Payroll generated.',
            'data': {
                'payroll_run_id': str(payroll_run.id), 'status': payroll_run.status,
                'total_amount': str(payroll_run.total_amount),
                'employee_count': faculty_list.count() + staff_users.count(), 'generated_at': payroll_run.generated_at,
            },
        }, status=status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. GET  /api/v1/payroll/{id}/
# ═══════════════════════════════════════════════════════════════════════════════

class PayrollDetailView(APIView):
    # permission_classes = [IsAuthenticated]

    def _get_payroll(self, request, payroll_id):
        role = _user_role(request.user)
        if role not in PAYROLL_VIEW_ROLES:
            return None, Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = PayrollRun.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            return qs.get(id=payroll_id), None
        except PayrollRun.DoesNotExist:
            return None, Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    def get(self, request, payroll_id):
        pr, err = self._get_payroll(request, payroll_id)
        if err:
            return err
        return Response({'success': True, 'data': PayrollRunDetailSerializer(pr).data})

    def patch(self, request, payroll_id):
        """PATCH /api/v1/payroll/{id}/ — update payroll notes or status."""
        pr, err = self._get_payroll(request, payroll_id)
        if err:
            return err
        role = _user_role(request.user)
        if role not in PAYROLL_GENERATE_ROLES + PAYROLL_APPROVE_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if 'notes' in request.data:
            pr.notes = request.data['notes']
        if 'status' in request.data and role in PAYROLL_APPROVE_ROLES:
            allowed_transitions = {
                'draft': ['pending_approval'],
                'pending_approval': ['draft'],
            }
            new_status = request.data['status']
            if new_status in allowed_transitions.get(pr.status, []):
                pr.status = new_status
            else:
                return Response({'success': False, 'message': f'Cannot transition from {pr.status} to {new_status}.'}, status=status.HTTP_400_BAD_REQUEST)
        pr.save()
        return Response({'success': True, 'message': 'Payroll updated.', 'data': PayrollRunDetailSerializer(pr).data})

    def delete(self, request, payroll_id):
        """DELETE /api/v1/payroll/{id}/ — delete a draft payroll run."""
        pr, err = self._get_payroll(request, payroll_id)
        if err:
            return err
        role = _user_role(request.user)
        if role not in ['super_admin', 'accountant']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if pr.status not in ('draft', 'pending_approval'):
            return Response({'success': False, 'message': 'Can only delete draft or pending payrolls.'}, status=status.HTTP_400_BAD_REQUEST)
        pr.payslips.all().delete()
        pr.delete()
        return Response({'success': True, 'message': 'Payroll deleted.'}, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. GET  /api/v1/payroll/{id}/payslips/
# ═══════════════════════════════════════════════════════════════════════════════

class PayrollPayslipsView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request, payroll_id):
        role = _user_role(request.user)
        if role not in PAYROLL_VIEW_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        slips = PaySlip.objects.filter(payroll_run_id=payroll_id).select_related('faculty__user').prefetch_related('late_logs')
        if getattr(request.user, 'organization', None):
            slips = slips.filter(payroll_run__branch__organization=request.user.organization)
        return Response({'success': True, 'count': slips.count(), 'data': PaySlipSerializer(slips, many=True).data})


class PayslipAdjustView(APIView):
    """PATCH, DELETE /api/v1/payroll/{payroll_id}/payslips/{slip_id}/"""
    # permission_classes = [IsAuthenticated]

    def patch(self, request, payroll_id, slip_id):
        """Adjust payslip amounts (bonus, deductions, etc.)."""
        role = _user_role(request.user)
        if role not in ['accountant', 'super_admin']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = PaySlip.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(payroll_run__branch__organization=request.user.organization)
            ps = qs.get(id=slip_id, payroll_run_id=payroll_id)
        except PaySlip.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if ps.is_disbursed:
            return Response({'success': False, 'message': 'Cannot adjust disbursed payslip.'}, status=status.HTTP_400_BAD_REQUEST)

        ser = PaySlipAdjustSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        d = ser.validated_data
        for field in ['bonus', 'other_deductions', 'deduction_note', 'leave_deductions']:
            if field in d:
                setattr(ps, field, d[field])

        # Recompute net salary
        ps.net_salary = (
            ps.basic_salary + ps.hour_based_amount + ps.bonus
            - ps.late_penalty - ps.absence_deductions - ps.leave_deductions - ps.other_deductions
        )
        ps.save()

        # Update payroll run total
        pr = ps.payroll_run
        pr.total_amount = sum(s.net_salary for s in pr.payslips.all())
        pr.save(update_fields=['total_amount'])

        return Response({'success': True, 'message': 'Payslip adjusted.', 'data': PaySlipSerializer(ps).data})

    def delete(self, request, payroll_id, slip_id):
        """Remove a payslip from a payroll run."""
        role = _user_role(request.user)
        if role not in ['super_admin']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = PaySlip.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(payroll_run__branch__organization=request.user.organization)
            ps = qs.get(id=slip_id, payroll_run_id=payroll_id)
        except PaySlip.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if ps.is_disbursed:
            return Response({'success': False, 'message': 'Cannot delete disbursed payslip.'}, status=status.HTTP_400_BAD_REQUEST)

        pr = ps.payroll_run
        ps.delete()

        # Update payroll run total
        pr.total_amount = sum(s.net_salary for s in pr.payslips.all())
        pr.save(update_fields=['total_amount'])

        return Response({'success': True, 'message': 'Payslip deleted.'}, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. POST  /api/v1/payroll/{id}/approve/
# ═══════════════════════════════════════════════════════════════════════════════

class PayrollApproveView(APIView):
    # permission_classes = [IsAuthenticated]

    def post(self, request, payroll_id):
        role = _user_role(request.user)
        if role not in PAYROLL_APPROVE_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = PayrollRun.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            pr = qs.get(id=payroll_id)
        except PayrollRun.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if pr.status not in ('draft', 'pending_approval'):
            return Response({'success': False, 'message': f'Cannot approve payroll in status: {pr.status}.'}, status=status.HTTP_400_BAD_REQUEST)

        pr.status = 'approved'
        pr.approved_by = request.user
        pr.approved_at = timezone.now()
        pr.save()

        # Notify accountant
        if pr.generated_by:
            notify(
                str(pr.generated_by.id),
                title="Payroll Approved",
                body=f"Payroll for {pr.month}/{pr.year} has been approved.",
                metadata={"payroll_run_id": str(pr.id), "status": "approved"},
            )

        return Response({
            'success': True, 'message': 'Payroll approved.',
            'data': {
                'payroll_run_id': str(pr.id), 'status': pr.status,
                'approved_by': str(request.user.id), 'approved_at': pr.approved_at,
            },
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 5. POST  /api/v1/payroll/{id}/disburse/
# ═══════════════════════════════════════════════════════════════════════════════

class PayrollDisburseView(APIView):
    # permission_classes = [IsAuthenticated]

    def post(self, request, payroll_id):
        role = _user_role(request.user)
        if role not in PAYROLL_DISBURSE_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = PayrollRun.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            pr = qs.get(id=payroll_id)
        except PayrollRun.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if pr.status != 'approved':
            return Response({'success': False, 'message': 'Payroll must be approved first.'}, status=status.HTTP_400_BAD_REQUEST)

        payslips = pr.payslips.select_related('faculty__user', 'user')
        payslips.update(is_disbursed=True)
        pr.status = 'disbursed'
        pr.disbursed_at = timezone.now()
        pr.save()

        # Send IN-APP notification to each employee with payslip data
        for ps in payslips:
            recipient_user = ps.faculty.user if ps.faculty else ps.user
            if not recipient_user:
                continue
            notify(
                recipient_user_id=str(recipient_user.id),
                title=f"Your payslip for {pr.month}/{pr.year} is ready",
                body=f"Net salary: {ps.net_salary}. Sessions: {ps.sessions_conducted}.",
                metadata={
                    "payslip_id": str(ps.id),
                    "payroll_run_id": str(pr.id),
                    "net_salary": str(ps.net_salary),
                    "month": pr.month,
                    "year": pr.year,
                },
            )

        return Response({
            'success': True, 'message': 'Payroll disbursed.',
            'data': {
                'disbursed': True,
                'faculty_count': payslips.count(),
                'total_amount': str(pr.total_amount),
            },
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 6. GET  /api/v1/faculty/{id}/payslips/
# ═══════════════════════════════════════════════════════════════════════════════

class FacultyPayslipsView(APIView):
    # permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['payroll_run__year', 'payroll_run__month']
    search_fields = ['faculty__user__name']
    ordering_fields = '__all__'

    def get(self, request, faculty_id):
        role = _user_role(request.user)
        from faculty.models import FacultyProfile
        try:
            fp_qs = FacultyProfile.objects.all()
            if getattr(request.user, 'organization', None):
                fp_qs = fp_qs.filter(branch__organization=request.user.organization)
            fp = fp_qs.get(id=faculty_id)
        except FacultyProfile.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if role == 'faculty' and fp.user != request.user:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if role not in ['faculty', 'accountant', 'branch_manager', 'super_admin']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        qs = PaySlip.objects.filter(faculty=fp).select_related('payroll_run').prefetch_related('late_logs')
        year = request.GET.get('year')
        month = request.GET.get('month')
        if year:
            qs = qs.filter(payroll_run__year=year)
        if month:
            qs = qs.filter(payroll_run__month=month)

        qs = apply_filters(self, request, qs)

        return Response({'success': True, 'count': qs.count(), 'data': PaySlipSerializer(qs, many=True).data})


class FacultySalaryPreviewView(APIView):
    """GET /api/v1/faculty/{id}/salary-preview/?month=X&year=Y"""
    # permission_classes = [IsAuthenticated]

    def get(self, request, faculty_id):
        role = _user_role(request.user)
        from faculty.models import FacultyProfile
        try:
            fp_qs = FacultyProfile.objects.all()
            if getattr(request.user, 'organization', None):
                fp_qs = fp_qs.filter(branch__organization=request.user.organization)
            fp = fp_qs.get(id=faculty_id)
        except FacultyProfile.DoesNotExist:
            return Response({'success': False, 'message': 'Faculty not found.'}, status=status.HTTP_404_NOT_FOUND)

        if role == 'faculty' and fp.user != request.user:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if role not in ['faculty', 'accountant', 'branch_manager', 'super_admin']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        month_str = request.GET.get('month')
        year_str = request.GET.get('year')

        if not month_str or not year_str:
            from django.utils import timezone
            now = timezone.now()
            month = now.month
            year = now.year
        else:
            try:
                month = int(month_str)
                year = int(year_str)
            except ValueError:
                return Response({'success': False, 'message': 'Invalid month or year.'}, status=status.HTTP_400_BAD_REQUEST)

        from .utils import preview_payslip_for_faculty
        preview_data = preview_payslip_for_faculty(fp, month, year)
        
        return Response({
            'success': True,
            'message': 'Salary preview calculated successfully.',
            'data': {
                'faculty_id': faculty_id,
                'month': month,
                'year': year,
                'payslip_preview': preview_data
            }
        })



# ═══════════════════════════════════════════════════════════════════════════════
# 7. GET & POST  /api/v1/payroll/late-policy/
# ═══════════════════════════════════════════════════════════════════════════════

class LatePolicyView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request):
        role = _user_role(request.user)
        if role not in LATE_POLICY_VIEW_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        bid = _user_branch_id(request.user)
        qs = LateEntryPolicy.objects.select_related('branch').all()
        if getattr(request.user, 'organization', None):
            qs = qs.filter(branch__organization=request.user.organization)
        if role != 'super_admin' and bid:
            qs = qs.filter(branch_id=bid)
        return Response({'success': True, 'data': LateEntryPolicySerializer(qs, many=True).data})

    def post(self, request):
        role = _user_role(request.user)
        if role not in LATE_POLICY_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        ser = LateEntryPolicyInputSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        bid = _user_branch_id(request.user) or request.data.get('branch_id')
        if not bid:
            return Response({'success': False, 'message': 'Branch required.'}, status=status.HTTP_400_BAD_REQUEST)

        policy, created = LateEntryPolicy.objects.update_or_create(
            branch_id=bid,
            defaults={**ser.validated_data, 'created_by': request.user},
        )
        return Response({
            'success': True,
            'message': 'Late policy created.' if created else 'Late policy updated.',
            'data': LateEntryPolicySerializer(policy).data,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class LatePolicyDetailView(APIView):
    """PATCH, DELETE /api/v1/payroll/late-policy/{policy_id}/"""
    # permission_classes = [IsAuthenticated]

    def patch(self, request, policy_id):
        role = _user_role(request.user)
        if role not in LATE_POLICY_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = LateEntryPolicy.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            policy = qs.get(id=policy_id)
        except LateEntryPolicy.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        for field in ['grace_period_minutes', 'deduction_per_minute', 'max_deduction_per_session',
                       'absence_deduction_per_day', 'late_entry_threshold', 'auto_halfday_deduction', 'is_active']:
            if field in request.data:
                setattr(policy, field, request.data[field])
        policy.save()
        return Response({'success': True, 'message': 'Policy updated.', 'data': LateEntryPolicySerializer(policy).data})

    def delete(self, request, policy_id):
        role = _user_role(request.user)
        if role not in LATE_POLICY_EDIT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            qs = LateEntryPolicy.objects.all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            policy = qs.get(id=policy_id)
        except LateEntryPolicy.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        policy.delete()
        return Response({'success': True, 'message': 'Late policy deleted.'}, status=status.HTTP_200_OK)

# ═══════════════════════════════════════════════════════════════════════════════
# 8. GET & PATCH  /api/v1/payroll/extra-hours/
# ═══════════════════════════════════════════════════════════════════════════════

class ExtraHoursApprovalListView(APIView):
    # permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['payroll_month', 'payroll_year', 'status']
    search_fields = ['faculty__user__name', 'chapter__name']
    ordering_fields = '__all__'

    def get(self, request):
        role = _user_role(request.user)
        if role not in PAYROLL_VIEW_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        
        from .models import ExtraHoursApproval
        from .serializers import ExtraHoursApprovalSerializer
        
        qs = ExtraHoursApproval.objects.select_related('faculty__user', 'chapter__subject', 'approved_by').all()
        
        bid = _user_branch_id(request.user)
        if role != 'super_admin' and bid:
            qs = qs.filter(faculty__branch_id=bid)
            
        qs = apply_filters(self, request, qs)
        return paginate_queryset(qs, request, ExtraHoursApprovalSerializer)

class ExtraHoursApprovalUpdateView(APIView):
    # permission_classes = [IsAuthenticated]

    def patch(self, request, approval_id):
        role = _user_role(request.user)
        if role not in ['super_admin']:
            return Response({'success': False, 'message': 'Permission denied. Super Admin only.'}, status=status.HTTP_403_FORBIDDEN)
            
        from .models import ExtraHoursApproval
        from .serializers import ExtraHoursApprovalSerializer, ExtraHoursApprovalUpdateSerializer
        
        try:
            approval = ExtraHoursApproval.objects.get(id=approval_id)
        except ExtraHoursApproval.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
            
        ser = ExtraHoursApprovalUpdateSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        status_val = ser.validated_data['status']
        approval.status = status_val
        if status_val == 'approved':
            approval.approved_by = request.user
            
        approval.save()
        
        # We need to recalculate the payslip for that month if the payroll is still draft
        pr = PayrollRun.objects.filter(
            branch=approval.faculty.branch,
            month=approval.payroll_month,
            year=approval.payroll_year
        ).first()
        
        if pr and pr.status == 'draft':
            from .utils import compute_payslip_for_faculty
            ps = compute_payslip_for_faculty(approval.faculty, pr.month, pr.year, pr)
            # Recompute total
            pr.total_amount = sum(s.net_salary for s in pr.payslips.all())
            pr.save(update_fields=['total_amount'])
            
        return Response({
            'success': True,
            'message': f'Extra hours request {status_val}.',
            'data': ExtraHoursApprovalSerializer(approval).data
        })


# ═══════════════════════════════════════════════════════════════════════════════
# My Payroll — GET /api/v1/payroll/my/
# Returns all payroll runs that include a payslip for the logged-in employee.
# Each entry contains the full payroll run metadata + the user's payslip detail.
# Works for faculty (via FacultyProfile) AND non-faculty staff (via User).
# ═══════════════════════════════════════════════════════════════════════════════

class MyPayrollView(APIView):
    """
    Personal payroll history for the currently authenticated employee.

    GET /api/v1/payroll/my/
      → list of all payroll runs that include this employee's payslip,
        each with full payslip breakdown.

    GET /api/v1/payroll/my/?year=2026
      → filter by year

    GET /api/v1/payroll/my/?month=6&year=2026
      → filter by month + year
    """

    def get(self, request):
        from .serializers import MyPaySlipSerializer
        from django.db.models import Q

        user = request.user

        # Try to find faculty profile (may not exist for non-faculty staff)
        faculty = None
        try:
            from faculty.models import FacultyProfile
            faculty = FacultyProfile.objects.get(user=user)
        except Exception:
            pass

        # Build payslip queryset — faculty-based OR user-based
        if faculty:
            qs = PaySlip.objects.filter(
                Q(faculty=faculty) | Q(user=user)
            )
        else:
            qs = PaySlip.objects.filter(user=user)

        if not qs.exists():
            return Response(
                {'success': False, 'message': 'No payslips found for this user.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        qs = qs.select_related(
            'payroll_run', 'payroll_run__branch', 'faculty',
        ).prefetch_related('late_logs').order_by('-payroll_run__year', '-payroll_run__month')

        # Optional filters
        year = request.GET.get('year')
        month = request.GET.get('month')
        run_status = request.GET.get('status')

        if year:
            qs = qs.filter(payroll_run__year=year)
        if month:
            qs = qs.filter(payroll_run__month=month)
        if run_status:
            qs = qs.filter(payroll_run__status=run_status)

        payslips = MyPaySlipSerializer(qs, many=True, context={'request': request}).data

        # Summary totals
        total_net = sum((Decimal(str(p['net_salary'])) for p in payslips), Decimal('0'))
        total_disbursed = sum(
            (Decimal(str(p['net_salary'])) for p in payslips if p.get('is_disbursed')), Decimal('0')
        )

        employee_id = faculty.employee_id if faculty else (user.employee_id or '')

        return Response({
            'success': True,
            'employee': {
                'id': str(faculty.id) if faculty else str(user.id),
                'employee_id': employee_id,
                'name': user.name,
                'email': user.email,
                'role': user.role,
            },
            'summary': {
                'total_payslips': len(payslips),
                'total_net_earned': total_net,
                'total_disbursed': total_disbursed,
            },
            'payslips': payslips,
        })

