"""
fees/services.py
Fee auto-creation logic on admission approval (replaces deprecated course_type mapping).
"""
import logging
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction

from .utils import get_installment_plan_status, update_student_fee_status
from .models import (
    StudentFee, InstallmentPlan, InstallmentItem,
    Payment, FeeStructure,
)

logger = logging.getLogger(__name__)


@transaction.atomic
def create_student_fee(student, acting_user=None):
    """
    Called from StudentService.create_from_admission().
    Creates StudentFee, InstallmentPlan + Item(s), and a verified Payment
    if admission had payment data. Uses level.name for status rules.
    """
    if not hasattr(student, 'admission') or not student.admission:
        raise ValidationError("Student must be linked to an Admission.")

    admission = student.admission
    fs = admission.fee_structure

    # Fallback to latest active FeeStructure matching student's course via level name
    if fs is None:
        level_name_map = {
            'cseet': 'CSEET',
            'cs_executive': 'CS Executive',
            'cs_professional': 'CS Professional',
        }
        target_level_name = level_name_map.get(admission.course, admission.course)
        fs = FeeStructure.objects.filter(
            level__name__icontains=target_level_name,
            is_active=True,
        ).order_by('-created_at').first()

        if not fs:
            fs = FeeStructure.objects.filter(
                course__name__icontains=target_level_name,
                is_active=True,
            ).order_by('-created_at').first()

    if fs is None:
        raise ValidationError(
            f"No active FeeStructure found for course '{admission.course}'. "
            "Please create one before enrolling students."
        )

    # Create or get StudentFee
    student_fee, created = StudentFee.objects.get_or_create(
        student=student,
        fee_structure=fs,
        defaults={
            'total_amount': fs.total_amount,
            'discount': Decimal('0'),
            'amount_paid': Decimal('0'),
            'status': 'approval_pending',
            'due_date': timezone.now().date() + timezone.timedelta(days=30),
        },
    )

    if not created:
        logger.warning(f"StudentFee already existed for student {student.admission_number}")
        return student_fee

    # Create InstallmentPlan + default 1 item (lumpsum)
    level_name = getattr(fs.level, 'name', '') or getattr(fs.course, 'name', '') or admission.course
    num_items = 1
    plan_status = get_installment_plan_status(level_name, num_items)
    plan = InstallmentPlan.objects.create(
        student_fee=student_fee,
        created_by=acting_user,
        status=plan_status,
    )

    item = InstallmentItem.objects.create(
        plan=plan,
        amount=student_fee.total_amount - admission.payment_amount,
        due_date=student_fee.due_date or (timezone.now().date() + timezone.timedelta(days=30)),
        is_paid=False,
    )

    # Create verified Payment if admission has payment info (as in approval flow)
    payment_amount = getattr(admission, 'payment_amount', Decimal('0')) or Decimal('0')
    if payment_amount > 0 or admission.payment_screenshot or admission.transaction_id:
        payment = Payment.objects.create(
            student=student,
            student_fee=student_fee,
            installment_item=item,
            amount=payment_amount or student_fee.total_amount,
            payment_mode='online',
            transaction_ref=admission.transaction_id or f'AUTO-ADM-{admission.id}',
            payment_proof=admission.payment_screenshot,
            status='verified',
            recorded_by=acting_user,
            verified_by=acting_user,
            verified_at=timezone.now(),
            payment_date=timezone.now().date(),
            note=f'Auto-verified from admission #{admission.id}. Tx: {admission.transaction_id or "N/A"}',
        )
        # Hook will trigger update_student_fee_status + mark_installment_paid
        logger.info(f"Auto-created verified Payment {payment.receipt_number} for admission {admission.id}")

        # Auto-approve plan if it was pending
        if plan.status == 'pending_approval':
            plan.status = 'approved'
            plan.approved_by = acting_user
            plan.approved_at = timezone.now()
            plan.save(update_fields=['status', 'approved_by', 'approved_at'])

    logger.info(
        f"StudentFee (with InstallmentPlan) created for {student.admission_number} "
        f"from admission {admission.id} using FeeStructure {fs.name}"
    )
    return student_fee


def payment_approval_reminders_task(*args, **kwargs):
    """
    Background task to notify branch managers and super admins about payments
    that are pending approval for more than 2 hours.
    Scheduled to run every 2 hours globally.
    """
    from django.utils import timezone
    from datetime import timedelta
    from .models import Payment
    from core.utils import notify_users_by_role

    two_hours_ago = timezone.now() - timedelta(hours=2)

    # Get payments that are approval_pending and created older than 2 hours
    pending_payments = Payment.objects.filter(
        status='approval_pending',
        created_at__lte=two_hours_ago
    ).select_related('student__branch')

    if not pending_payments.exists():
        return

    # Group by branch
    branch_map = {}
    for payment in pending_payments:
        branch_id = payment.student.branch_id if payment.student.branch else None
        if branch_id not in branch_map:
            branch_map[branch_id] = {
                'branch': payment.student.branch,
                'count': 0,
                'total_amount': 0
            }
        branch_map[branch_id]['count'] += 1
        branch_map[branch_id]['total_amount'] += payment.amount

    # Send notifications per branch to branch managers + super admins
    for branch_id, data in branch_map.items():
        count = data['count']
        total = data['total_amount']
        branch = data['branch']
        branch_name = branch.name if branch else "Global"

        notify_users_by_role(
            roles=['super_admin', 'branch_manager'],
            title=f'Pending Payment Approvals ({branch_name})',
            body=f"There are {count} payments totaling ₹{total} pending approval for over 2 hours.",
            organization=branch.organization if branch else None,
            branch=branch,
            email_subject=f"Action Required: {count} Payments Pending Approval"
        )

