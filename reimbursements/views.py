import logging
from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum, Q
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from core.utils import get_user_role
from chat.notifications import send_system_notification
from .models import Reimbursement
from .serializers import (
    ReimbursementSerializer,
    ReimbursementCreateSerializer,
    ReimbursementUpdateSerializer,
    ReimbursementRejectSerializer,
)

logger = logging.getLogger(__name__)

APPROVER_ROLES = {'super_admin', 'admin', 'center_in_charge'}


def _is_approver(user):
    user_role = get_user_role(user)
    return any(user_role == r for r in APPROVER_ROLES)


class ReimbursementListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        user = request.user
        role = get_user_role(user)
        is_appr = _is_approver(user)

        # Base queryset
        qs = Reimbursement.objects.select_related('user', 'branch', 'approved_by', 'rejected_by', 'payroll_run')

        # If not an approver or requested my claims specifically:
        my_only = request.query_params.get('my', '').lower() in ('true', '1')
        if not is_appr or my_only:
            qs = qs.filter(user=user)
        elif role == 'center_in_charge':
            # Center in-charge sees claims from their branch
            if user.branch:
                qs = qs.filter(Q(branch=user.branch) | Q(user=user))
            else:
                qs = qs.filter(user=user)

        # Filters
        status_param = request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        user_id = request.query_params.get('user_id')
        if user_id and is_appr and not my_only:
            qs = qs.filter(user_id=user_id)

        branch_id = request.query_params.get('branch_id')
        if branch_id and (role in ['super_admin', 'admin']):
            qs = qs.filter(branch_id=branch_id)

        from_date = request.query_params.get('from_date')
        if from_date:
            qs = qs.filter(expense_date__gte=from_date)

        to_date = request.query_params.get('to_date')
        if to_date:
            qs = qs.filter(expense_date__lte=to_date)

        month = request.query_params.get('month')
        year = request.query_params.get('year')
        if month:
            qs = qs.filter(expense_date__month=month)
        if year:
            qs = qs.filter(expense_date__year=year)

        serializer = ReimbursementSerializer(qs, many=True)
        return Response({
            'success': True,
            'count': qs.count(),
            'data': serializer.data
        })

    def post(self, request):
        serializer = ReimbursementCreateSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response({
                'success': False,
                'message': 'Validation failed',
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        reimbursement = serializer.save()

        # Notify admins / approvers
        try:
            from core.utils import notify_users_by_role
            applicant_name = request.user.name or request.user.email
            notify_users_by_role(
                roles=['super_admin', 'admin'],
                title='New Reimbursement Claim',
                body=f"{applicant_name} submitted a reimbursement claim '{reimbursement.title}' for ₹{reimbursement.amount}.",
                metadata={'reimbursement_id': str(reimbursement.id)}
            )
        except Exception as e:
            logger.error(f"Failed to send notification for reimbursement {reimbursement.id}: {e}")

        return Response({
            'success': True,
            'message': 'Reimbursement claim submitted successfully.',
            'data': ReimbursementSerializer(reimbursement).data
        }, status=status.HTTP_201_CREATED)


class ReimbursementDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_object(self, request, pk):
        user = request.user
        role = get_user_role(user)
        try:
            reimb = Reimbursement.objects.select_related('user', 'branch', 'approved_by', 'rejected_by', 'payroll_run').get(pk=pk)
        except Reimbursement.DoesNotExist:
            return None

        if reimb.user == user or role in ['super_admin', 'admin'] or (role == 'center_in_charge' and reimb.branch == user.branch):
            return reimb
        return None

    def get(self, request, pk):
        reimb = self._get_object(request, pk)
        if not reimb:
            return Response({'success': False, 'message': 'Reimbursement not found or access denied.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': ReimbursementSerializer(reimb).data})

    def patch(self, request, pk):
        reimb = self._get_object(request, pk)
        if not reimb:
            return Response({'success': False, 'message': 'Reimbursement not found or access denied.'}, status=status.HTTP_404_NOT_FOUND)

        if reimb.user != request.user and not _is_approver(request.user):
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if reimb.status != 'pending':
            return Response({'success': False, 'message': f'Cannot edit claim with status {reimb.status}.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ReimbursementUpdateSerializer(reimb, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        serializer.save()
        return Response({'success': True, 'message': 'Reimbursement updated.', 'data': ReimbursementSerializer(reimb).data})

    def delete(self, request, pk):
        reimb = self._get_object(request, pk)
        if not reimb:
            return Response({'success': False, 'message': 'Reimbursement not found or access denied.'}, status=status.HTTP_404_NOT_FOUND)

        if reimb.user != request.user and get_user_role(request.user) not in ['super_admin', 'admin']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if reimb.status != 'pending':
            return Response({'success': False, 'message': f'Cannot delete claim with status {reimb.status}.'}, status=status.HTTP_400_BAD_REQUEST)

        reimb.delete()
        return Response({'success': True, 'message': 'Reimbursement deleted.'})


class ReimbursementApproveAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _is_approver(request.user):
            return Response({'success': False, 'message': 'Permission denied. Only admins or center in-charges can approve.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            reimb = Reimbursement.objects.select_related('user', 'branch').get(pk=pk)
        except Reimbursement.DoesNotExist:
            return Response({'success': False, 'message': 'Reimbursement not found.'}, status=status.HTTP_404_NOT_FOUND)

        if reimb.status == 'approved':
            return Response({'success': False, 'message': 'Claim is already approved.'}, status=status.HTTP_400_BAD_REQUEST)

        if reimb.is_paid:
            return Response({'success': False, 'message': 'Claim has already been paid.'}, status=status.HTTP_400_BAD_REQUEST)

        reimb.status = 'approved'
        reimb.approved_by = request.user
        reimb.approved_at = timezone.now()
        reimb.rejected_by = None
        reimb.rejected_at = None
        reimb.rejection_reason = ''
        reimb.save()

        # Send in-app notification to applicant
        try:
            send_system_notification(
                user_id=str(reimb.user.id),
                title='Reimbursement Approved',
                body=f"Your reimbursement claim '{reimb.title}' for ₹{reimb.amount} has been approved and will be added to your monthly pay.",
                metadata={'reimbursement_id': str(reimb.id)}
            )
        except Exception as e:
            logger.error(f"Failed to notify user for approved reimbursement {reimb.id}: {e}")

        return Response({
            'success': True,
            'message': f"Reimbursement '{reimb.title}' approved successfully. Amount will be added to monthly pay.",
            'data': ReimbursementSerializer(reimb).data
        })


class ReimbursementRejectAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _is_approver(request.user):
            return Response({'success': False, 'message': 'Permission denied. Only admins or center in-charges can reject.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            reimb = Reimbursement.objects.select_related('user', 'branch').get(pk=pk)
        except Reimbursement.DoesNotExist:
            return Response({'success': False, 'message': 'Reimbursement not found.'}, status=status.HTTP_404_NOT_FOUND)

        if reimb.is_paid:
            return Response({'success': False, 'message': 'Cannot reject a claim that has already been paid.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ReimbursementRejectSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        reimb.status = 'rejected'
        reimb.rejected_by = request.user
        reimb.rejected_at = timezone.now()
        reimb.rejection_reason = serializer.validated_data['rejection_reason']
        reimb.approved_by = None
        reimb.approved_at = None
        reimb.save()

        # Send in-app notification to applicant
        try:
            send_system_notification(
                user_id=str(reimb.user.id),
                title='Reimbursement Rejected',
                body=f"Your reimbursement claim '{reimb.title}' for ₹{reimb.amount} was rejected. Reason: {reimb.rejection_reason}",
                metadata={'reimbursement_id': str(reimb.id)}
            )
        except Exception as e:
            logger.error(f"Failed to notify user for rejected reimbursement {reimb.id}: {e}")

        return Response({
            'success': True,
            'message': f"Reimbursement '{reimb.title}' rejected.",
            'data': ReimbursementSerializer(reimb).data
        })


class ReimbursementSummaryAPIView(APIView):
    """Provides summary breakdown of reimbursements (total claimed, pending, approved, paid)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        role = get_user_role(user)
        is_appr = _is_approver(user)
        my_only = request.query_params.get('my', '').lower() in ('true', '1')

        qs = Reimbursement.objects.all()
        if not is_appr or my_only:
            qs = qs.filter(user=user)
        elif role == 'center_in_charge' and user.branch:
            qs = qs.filter(Q(branch=user.branch) | Q(user=user))

        branch_id = request.query_params.get('branch_id')
        if branch_id and role in ['super_admin', 'admin']:
            qs = qs.filter(branch_id=branch_id)

        pending_qs = qs.filter(status='pending')
        approved_qs = qs.filter(status='approved')
        rejected_qs = qs.filter(status='rejected')
        paid_qs = qs.filter(is_paid=True)

        return Response({
            'success': True,
            'summary': {
                'total_claims': qs.count(),
                'total_amount': qs.aggregate(total=Sum('amount'))['total'] or Decimal('0'),
                'pending_count': pending_qs.count(),
                'pending_amount': pending_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0'),
                'approved_count': approved_qs.count(),
                'approved_amount': approved_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0'),
                'rejected_count': rejected_qs.count(),
                'rejected_amount': rejected_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0'),
                'paid_count': paid_qs.count(),
                'paid_amount': paid_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0'),
            }
        })
