import logging
from core.pagination import paginate_queryset
from decimal import Decimal
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .models import PayrollRun, PaySlip, LateEntryPolicy
from .serializers import (
    PayrollRunListSerializer, PayrollRunDetailSerializer, PaySlipSerializer,
    PayrollGenerateSerializer, LateEntryPolicySerializer, LateEntryPolicyInputSerializer,
)
from .utils import compute_payslip_for_faculty

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

    def get(self, request):
        role = _user_role(request.user)
        if role not in PAYROLL_VIEW_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        qs = PayrollRun.objects.select_related('branch').all()
        bid = _user_branch_id(request.user)
        if role != 'super_admin' and bid:
            qs = qs.filter(branch_id=bid)

        for param, field in [('year', 'year'), ('month', 'month'), ('status', 'status')]:
            val = request.GET.get(param)
            if val:
                qs = qs.filter(**{field: val})

        return paginate_queryset(qs, request, PayrollRunListSerializer)

    def post(self, request):
        role = _user_role(request.user)
        if role not in PAYROLL_GENERATE_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        ser = PayrollGenerateSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        d = ser.validated_data
        if PayrollRun.objects.filter(branch_id=d['branch_id'], month=d['month'], year=d['year']).exists():
            return Response({'success': False, 'message': 'Payroll already exists for this month.'}, status=status.HTTP_409_CONFLICT)

        from faculty.models import FacultyProfile
        payroll_run = PayrollRun.objects.create(
            branch_id=d['branch_id'], month=d['month'], year=d['year'],
            generated_by=request.user,
        )

        faculty_list = FacultyProfile.objects.filter(branch_id=d['branch_id'], is_active=True)
        total = Decimal(0)
        for fp in faculty_list:
            ps = compute_payslip_for_faculty(fp, d['month'], d['year'], payroll_run)
            total += ps.net_salary

        payroll_run.total_amount = total
        payroll_run.save(update_fields=['total_amount'])

        return Response({
            'success': True, 'message': 'Payroll generated.',
            'data': {
                'payroll_run_id': str(payroll_run.id), 'status': payroll_run.status,
                'total_amount': str(payroll_run.total_amount),
                'faculty_count': faculty_list.count(), 'generated_at': payroll_run.generated_at,
            },
        }, status=status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. GET  /api/v1/payroll/{id}/
# ═══════════════════════════════════════════════════════════════════════════════

class PayrollDetailView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request, payroll_id):
        role = _user_role(request.user)
        if role not in PAYROLL_VIEW_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            pr = PayrollRun.objects.get(id=payroll_id)
        except PayrollRun.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': PayrollRunDetailSerializer(pr).data})


# ═══════════════════════════════════════════════════════════════════════════════
# 3. GET  /api/v1/payroll/{id}/payslips/
# ═══════════════════════════════════════════════════════════════════════════════

class PayrollPayslipsView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request, payroll_id):
        role = _user_role(request.user)
        if role not in PAYROLL_VIEW_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        slips = PaySlip.objects.filter(payroll_run_id=payroll_id).select_related('faculty', 'faculty_profile').prefetch_related('late_logs')
        return Response({'success': True, 'count': slips.count(), 'data': PaySlipSerializer(slips, many=True).data})


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
            pr = PayrollRun.objects.get(id=payroll_id)
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
            pr = PayrollRun.objects.get(id=payroll_id)
        except PayrollRun.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if pr.status != 'approved':
            return Response({'success': False, 'message': 'Payroll must be approved first.'}, status=status.HTTP_400_BAD_REQUEST)

        payslips = pr.payslips.select_related('faculty')
        payslips.update(is_disbursed=True)
        pr.status = 'disbursed'
        pr.disbursed_at = timezone.now()
        pr.save()

        # FRD §4.8.4: send IN-APP notification to each faculty with payslip data
        for ps in payslips:
            notify(
                recipient_user_id=str(ps.faculty.id),
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

    def get(self, request, faculty_id):
        role = _user_role(request.user)
        from faculty.models import FacultyProfile
        try:
            fp = FacultyProfile.objects.get(id=faculty_id)
        except FacultyProfile.DoesNotExist:
            return Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if role == 'faculty' and fp.user != request.user:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if role not in ['faculty', 'accountant', 'branch_manager', 'super_admin']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        qs = PaySlip.objects.filter(faculty_profile=fp).select_related('payroll_run').prefetch_related('late_logs')
        year = request.GET.get('year')
        month = request.GET.get('month')
        if year:
            qs = qs.filter(payroll_run__year=year)
        if month:
            qs = qs.filter(payroll_run__month=month)

        return Response({'success': True, 'count': qs.count(), 'data': PaySlipSerializer(qs, many=True).data})


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
        qs = LateEntryPolicy.objects.all()
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
