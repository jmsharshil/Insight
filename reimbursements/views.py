import logging
from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum, Q
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from core.utils import get_user_role, has_user_branch_access, get_user_branch_ids
from chat.notifications import send_system_notification
from .models import Reimbursement
from .serializers import (
    ReimbursementSerializer,
    ReimbursementCreateSerializer,
    ReimbursementUpdateSerializer,
    ReimbursementRejectSerializer,
)

logger = logging.getLogger(__name__)

from .utils import is_super_admin_user, is_accountant_user

# Roles allowed to review (approve / reject) reimbursement claims strictly limited to super_admin and accountant
GLOBAL_ADMIN_ROLES = {'super_admin', 'accountant'}

# Branch approver roles (empty since only super admin and accountant are authorized)
BRANCH_APPROVER_ROLES = set()

# All roles authorized to review (approve/reject) claims
APPROVER_ROLES = GLOBAL_ADMIN_ROLES

# Non-staff roles that cannot submit reimbursement claims (strictly from User.ROLE_CHOICES)
NON_STAFF_ROLES = {'student', 'parents', 'printers'}


def _is_approver(user):
    return is_super_admin_user(user) or is_accountant_user(user)



class ReimbursementListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        user = request.user
        role = get_user_role(user)
        is_appr = _is_approver(user)

        # Base queryset
        qs = Reimbursement.objects.select_related('user', 'branch', 'accountant_approved_by', 'approved_by', 'rejected_by', 'payroll_run')

        # If not an approver or requested my claims specifically:
        my_only = request.query_params.get('my', '').lower() in ('true', '1')
        if not is_appr or my_only:
            qs = qs.filter(user=user)
        elif role in BRANCH_APPROVER_ROLES and role not in GLOBAL_ADMIN_ROLES:
            # Branch manager sees claims from their branch
            branch_ids = get_user_branch_ids(user) or []
            if getattr(user, 'branch_id', None) and user.branch_id not in branch_ids:
                branch_ids.append(user.branch_id)
            if branch_ids:
                qs = qs.filter(Q(branch_id__in=branch_ids) | Q(user=user))
            else:
                qs = qs.filter(user=user)

        # Filters
        status_param = request.query_params.get('status')
        if status_param:
            if ',' in status_param:
                statuses = [s.strip() for s in status_param.split(',') if s.strip()]
                qs = qs.filter(status__in=statuses)
            else:
                qs = qs.filter(status=status_param)

        user_id = request.query_params.get('user_id')
        if user_id and is_appr and not my_only:
            qs = qs.filter(user_id=user_id)

        branch_id = request.query_params.get('branch_id')
        if branch_id and role in GLOBAL_ADMIN_ROLES:
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
        role = get_user_role(request.user)
        if role in NON_STAFF_ROLES:
            return Response({
                'success': False,
                'message': 'Only staff members can apply for expense reimbursements.'
            }, status=status.HTTP_403_FORBIDDEN)

        serializer = ReimbursementCreateSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response({
                'success': False,
                'message': 'Validation failed',
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        reimbursement = serializer.save()

        # Notify approvers (strictly Super Admin and Accountant)
        try:
            from django.contrib.auth import get_user_model
            from chat.notifications import send_system_notification
            from core.utils import get_role_filter_q
            from .utils import send_reimbursement_whatsapp_notification, get_reimbursement_proof_url
            User = get_user_model()

            applicant_name = request.user.name or request.user.email
            proof_url = get_reimbursement_proof_url(reimbursement)
            notif_body = f"{applicant_name} submitted a reimbursement claim '{reimbursement.title}' for ₹{reimbursement.amount}."
            notif_meta = {
                'reimbursement_id': str(reimbursement.id),
                'type': 'reimbursement_claim',
                'route': f"/reimbursements/{reimbursement.id}",
                'proof_url': proof_url,
                'skip_whatsapp': True,
            }

            # Only super_admin and accountant receive approval notifications
            target_users_qs = User.objects.filter(
                get_role_filter_q(['super_admin', 'accountant']),
                is_active=True
            )

            # If reimbursement has a branch, also include branch-assigned accountants
            if reimbursement.branch:
                branch_accountants = User.objects.filter(
                    get_role_filter_q(['accountant']),
                    is_active=True
                ).filter(
                    Q(branch=reimbursement.branch) | Q(branches=reimbursement.branch)
                )
                target_users_qs = target_users_qs | branch_accountants

            # Exclude claimant if other approvers exist; keep if testing with single admin account
            all_approvers = list(target_users_qs.distinct())
            other_approvers = [u for u in all_approvers if u.id != request.user.id]
            target_users = other_approvers if other_approvers else all_approvers

            logger.info("[Reimbursement] Found %d target approvers for claim %s", len(target_users), reimbursement.id)

            for u in target_users:
                # In-app push / email notification
                send_system_notification(
                    user_id=str(u.id),
                    title='New Reimbursement Claim',
                    body=notif_body,
                    metadata=notif_meta,
                    notification_type='payroll',
                )
                # WhatsApp: reimbursement_claim_ template with [Approve] & [Reject] buttons
                try:
                    send_reimbursement_whatsapp_notification(reimbursement, u)
                except Exception as wa_err:
                    logger.error(f"[Reimbursement Claim] WhatsApp to approver {u.id} failed: {wa_err}")
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
            reimb = Reimbursement.objects.select_related('user', 'branch', 'accountant_approved_by', 'approved_by', 'rejected_by', 'payroll_run').get(pk=pk)
        except Reimbursement.DoesNotExist:
            return None

        if reimb.user == user or role in GLOBAL_ADMIN_ROLES:
            return reimb
        if role in BRANCH_APPROVER_ROLES:
            if reimb.branch_id and has_user_branch_access(user, reimb.branch_id):
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

        role = get_user_role(request.user)
        if reimb.user != request.user and role not in GLOBAL_ADMIN_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if reimb.status != 'pending':
            return Response({'success': False, 'message': f'Cannot delete claim with status {reimb.status}.'}, status=status.HTTP_400_BAD_REQUEST)

        reimb.delete()
        return Response({'success': True, 'message': 'Reimbursement deleted.'})


class ReimbursementApproveAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _is_approver(request.user):
            return Response({'success': False, 'message': 'Permission denied. Only Super Admin and Accountant can approve reimbursement claims.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            reimb = Reimbursement.objects.select_related('user', 'branch', 'accountant_approved_by').get(pk=pk)
        except Reimbursement.DoesNotExist:
            return Response({'success': False, 'message': 'Reimbursement not found.'}, status=status.HTTP_404_NOT_FOUND)

        if reimb.user == request.user:
            return Response({'success': False, 'message': 'You cannot approve your own reimbursement claim.'}, status=status.HTTP_400_BAD_REQUEST)

        if reimb.status == 'approved':
            return Response({'success': False, 'message': 'Claim is already approved.'}, status=status.HTTP_400_BAD_REQUEST)

        if reimb.status == 'rejected':
            return Response({'success': False, 'message': 'Claim has already been rejected.'}, status=status.HTTP_400_BAD_REQUEST)

        if reimb.is_paid:
            return Response({'success': False, 'message': 'Claim has already been paid.'}, status=status.HTTP_400_BAD_REQUEST)

        user_is_sa = is_super_admin_user(request.user)
        user_is_acc = is_accountant_user(request.user)

        now = timezone.now()
        applicant_name = getattr(reimb.user, 'name', None) or getattr(reimb.user, 'email', 'Employee')
        reviewer_name = request.user.name or request.user.email or 'Admin'

        if user_is_sa:
            # Super Admin approves directly from 'pending' OR completes Level 2 from 'approved_by_accountant'
            reimb.status = 'approved'
            reimb.approved_by = request.user
            reimb.approved_at = now
            reimb.rejected_by = None
            reimb.rejected_at = None
            reimb.rejection_reason = ''
            reimb.save()

            # Send in-app notification to applicant
            try:
                send_system_notification(
                    user_id=str(reimb.user.id),
                    title='Reimbursement Approved',
                    body=f"Your reimbursement claim '{reimb.title}' for ₹{reimb.amount} has been approved by {reviewer_name} and will be added to your monthly pay.",
                    metadata={
                        'reimbursement_id': str(reimb.id),
                        'type': 'reimbursement_approved',
                        'status': 'approved',
                        'route': f"/reimbursements/{reimb.id}",
                        'skip_whatsapp': True,
                    },
                    notification_type='payroll',
                )
            except Exception as e:
                logger.error(f"Failed to notify user for approved reimbursement {reimb.id}: {e}")

            # Send WhatsApp message to claimer
            try:
                from .utils import send_reimbursement_status_whatsapp_to_applicant
                send_reimbursement_status_whatsapp_to_applicant(reimb, 'approved', reviewer_name=reviewer_name)
            except Exception as e:
                logger.error(f"Failed to send approval WhatsApp to claimer {reimb.user_id}: {e}")

            return Response({
                'success': True,
                'message': f"Reimbursement '{reimb.title}' approved successfully by Super Admin. Amount will be added to monthly pay.",
                'data': ReimbursementSerializer(reimb).data
            })

        elif user_is_acc:
            # Accountant approving
            if reimb.status == 'approved_by_accountant':
                return Response({
                    'success': False,
                    'message': 'Claim has already been approved by Accountant and is awaiting final approval from Super Admin.'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Move to 'approved_by_accountant'
            reimb.status = 'approved_by_accountant'
            reimb.accountant_approved_by = request.user
            reimb.accountant_approved_at = now
            reimb.rejected_by = None
            reimb.rejected_at = None
            reimb.rejection_reason = ''
            reimb.save()

            # In-app notification to applicant
            try:
                send_system_notification(
                    user_id=str(reimb.user.id),
                    title='Reimbursement Claim Verified by Accountant',
                    body=f"Your reimbursement claim '{reimb.title}' for ₹{reimb.amount} has been approved by Accountant ({reviewer_name}) and is pending final approval from Super Admin.",
                    metadata={
                        'reimbursement_id': str(reimb.id),
                        'type': 'reimbursement_accountant_approved',
                        'status': 'approved_by_accountant',
                        'route': f"/reimbursements/{reimb.id}",
                        'skip_whatsapp': True,
                    },
                    notification_type='payroll',
                )
            except Exception as e:
                logger.error(f"Failed to notify applicant of accountant approval {reimb.id}: {e}")

            # Notify Super Admins
            try:
                from django.contrib.auth import get_user_model
                from core.utils import get_role_filter_q
                from .utils import send_reimbursement_whatsapp_notification, get_reimbursement_proof_url
                User = get_user_model()
                super_admins = list(User.objects.filter(get_role_filter_q(['super_admin']), is_active=True).distinct())
                for sa in super_admins:
                    if sa.id == reimb.user_id:
                        continue
                    send_system_notification(
                        user_id=str(sa.id),
                        title='Reimbursement Pending Final Approval',
                        body=f"Reimbursement claim '{reimb.title}' for ₹{reimb.amount} ({applicant_name}) was approved by Accountant ({reviewer_name}) and requires your final approval.",
                        metadata={
                            'reimbursement_id': str(reimb.id),
                            'type': 'reimbursement_claim',
                            'status': 'approved_by_accountant',
                            'route': f"/reimbursements/{reimb.id}",
                            'proof_url': get_reimbursement_proof_url(reimb),
                            'skip_whatsapp': True,
                        },
                        notification_type='payroll',
                    )
                    try:
                        send_reimbursement_whatsapp_notification(
                            reimb,
                            sa,
                            note_prefix=f"[Verified by Accountant: {reviewer_name}]"
                        )
                    except Exception as wa_err:
                        logger.error(f"Failed to send WhatsApp to super admin {sa.id}: {wa_err}")
            except Exception as e:
                logger.error(f"Failed to notify super admins of accountant approval {reimb.id}: {e}")

            return Response({
                'success': True,
                'message': f"Reimbursement '{reimb.title}' approved by Accountant. Pending final approval from Super Admin.",
                'data': ReimbursementSerializer(reimb).data
            })


class ReimbursementRejectAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _is_approver(request.user):
            return Response({'success': False, 'message': 'Permission denied. Only Super Admin and Accountant can reject reimbursement claims.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            reimb = Reimbursement.objects.select_related('user', 'branch').get(pk=pk)
        except Reimbursement.DoesNotExist:
            return Response({'success': False, 'message': 'Reimbursement not found.'}, status=status.HTTP_404_NOT_FOUND)

        if reimb.user == request.user:
            return Response({'success': False, 'message': 'You cannot reject your own reimbursement claim.'}, status=status.HTTP_400_BAD_REQUEST)

        if reimb.status == 'approved':
            return Response({'success': False, 'message': 'Cannot reject a claim that has already been approved.'}, status=status.HTTP_400_BAD_REQUEST)

        if reimb.status == 'rejected':
            return Response({'success': False, 'message': 'Claim has already been rejected.'}, status=status.HTTP_400_BAD_REQUEST)

        if reimb.is_paid:
            return Response({'success': False, 'message': 'Cannot reject a claim that has already been paid.'}, status=status.HTTP_400_BAD_REQUEST)

        user_is_sa = is_super_admin_user(request.user)

        # If already approved by accountant, only Super Admin can reject
        if reimb.status == 'approved_by_accountant' and not user_is_sa:
            return Response({
                'success': False,
                'message': 'Claim has already been approved by Accountant and is awaiting Super Admin final approval. Only Super Admin can reject it.'
            }, status=status.HTTP_403_FORBIDDEN)

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
                metadata={
                    'reimbursement_id': str(reimb.id),
                    'type': 'reimbursement_rejected',
                    'status': 'rejected',
                    'route': f"/reimbursements/{reimb.id}",
                    'skip_whatsapp': True,
                },
                notification_type='payroll',
            )
        except Exception as e:
            logger.error(f"Failed to notify user for rejected reimbursement {reimb.id}: {e}")

        # Send WhatsApp message to claimer
        try:
            from .utils import send_reimbursement_status_whatsapp_to_applicant
            reviewer_name = request.user.name or 'Admin'
            send_reimbursement_status_whatsapp_to_applicant(reimb, 'rejected', reviewer_name=reviewer_name)
        except Exception as e:
            logger.error(f"Failed to send rejection WhatsApp to claimer {reimb.user_id}: {e}")

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
        elif role in BRANCH_APPROVER_ROLES and role not in GLOBAL_ADMIN_ROLES:
            branch_ids = get_user_branch_ids(user) or []
            if getattr(user, 'branch_id', None) and user.branch_id not in branch_ids:
                branch_ids.append(user.branch_id)
            if branch_ids:
                qs = qs.filter(Q(branch_id__in=branch_ids) | Q(user=user))
            else:
                qs = qs.filter(user=user)

        branch_id = request.query_params.get('branch_id')
        if branch_id and role in GLOBAL_ADMIN_ROLES:
            qs = qs.filter(branch_id=branch_id)

        pending_qs = qs.filter(status='pending')
        approved_by_accountant_qs = qs.filter(status='approved_by_accountant')
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
                'approved_by_accountant_count': approved_by_accountant_qs.count(),
                'approved_by_accountant_amount': approved_by_accountant_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0'),
                'approved_count': approved_qs.count(),
                'approved_amount': approved_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0'),
                'rejected_count': rejected_qs.count(),
                'rejected_amount': rejected_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0'),
                'paid_count': paid_qs.count(),
                'paid_amount': paid_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0'),
            }
        })
