from django.db import transaction
from django.db.models import Q, Sum
from .models import StudentFee, Payment, InstallmentItem, Refund, InstallmentPlan, BankAccount
from decimal import Decimal
import logging
import random
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


def get_installment_plan_status(level_or_course, num_installments):
    """
    Determine initial status for an InstallmentPlan based on level name
    (CSEET, CSExecutive, CS Professional) instead of the deprecated course_type
    on CourseLevel. Also supports legacy course_type strings for backward compat.
    
    Rules:
    - CSEET: pending_approval if >2 installments
    - CSExecutive / CS Professional: pending_approval if >4 installments
    - Otherwise: approved (no approval needed)
    """
    if not level_or_course:
        return 'approved'
    
    val = str(level_or_course).strip().lower().replace(' ', '').replace('_', '').replace('-', '')
    is_cseet = any(x in val for x in ['cseet', 'cse et'])
    
    if is_cseet:
        return 'pending_approval' if num_installments > 2 else 'approved'
    return 'pending_approval' if num_installments > 4 else 'approved'


def select_bank_accounts_for_payment(amount, limit=None):
    """Return a shuffled list of active BankAccount objects whose max_payment_amount
    is either unset (None) or greater than or equal to the total payments received
    in the current financial year plus the given amount.

    Args:
        amount (Decimal): The payment amount to compare against thresholds.
        limit (int, optional): Maximum number of accounts to return. If None, returns all.
    Returns:
        list[BankAccount]: Shuffled list of eligible bank accounts.
    """
    bank_accounts = BankAccount.objects.filter(is_active=True)
    eligible_accounts = [acc for acc in bank_accounts if acc.is_under_threshold(amount)]
    random.shuffle(eligible_accounts)
    if limit is not None:
        return eligible_accounts[:limit]
    return eligible_accounts


def update_student_fee_status(student_fee_id):
    """
    Recalculates amount_paid and status for a StudentFee
    based on all verified payments and completed refunds.
    """
    try:
        student_fee = StudentFee.objects.select_related('fee_structure').get(id=student_fee_id)
    except StudentFee.DoesNotExist:
        logger.warning(f"StudentFee {student_fee_id} not found during status update.")
        return None

    # Sum of verified payments (note: only 'verified' count toward paid)
    paid_sum = Payment.objects.filter(
        student_fee=student_fee,
        status='verified',
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    # Subtract completed refunds
    refund_sum = Refund.objects.filter(
        payment__student_fee=student_fee,
        status='completed',
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    net_paid = paid_sum - refund_sum
    student_fee.amount_paid = net_paid

    # Sync every installment item (per-item payment sums drive is_paid flags).
    # This replaces the previous remaining_payment sequential logic (which had
    # bugs with multiple plans and didn't respect payment.installment_item FK).
    for item in InstallmentItem.objects.filter(
        plan__student_fee=student_fee
    ).select_related('plan').order_by('due_date', 'id'):
        mark_installment_paid(item.id)

    # Determine StudentFee status (matches summary: paid/partial/overdue/approval_pending)
    amount_due = student_fee.total_amount - student_fee.discount - net_paid
    if amount_due <= 0:
        student_fee.status = 'paid'
    elif net_paid > 0:
        student_fee.status = 'partial'
    else:
        if (student_fee.due_date and student_fee.due_date < timezone.now().date()):
            student_fee.status = 'overdue'
        else:
            student_fee.status = 'approval_pending'

    student_fee.save(update_fields=['amount_paid', 'status', 'updated_at'])
    logger.info(
        f"Updated StudentFee {student_fee.id} (status={student_fee.status}, "
        f"paid={net_paid}, due={amount_due})"
    )
    return student_fee


@transaction.atomic
def mark_installment_paid(installment_item_id):
    """Sync an InstallmentItem's is_paid status based on sum of its verified
    linked Payments. Marks paid (and updates plan to completed if all items paid)
    or unmarks if underpaid (reverts plan from completed). This is called from
    update_student_fee_status(), Payment create/verify flows, and signals.
    """
    item = InstallmentItem.objects.select_related('plan').get(id=installment_item_id)
    paid_sum = Payment.objects.filter(
        installment_item=item,
        status='verified',
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    # Ensure Decimal (handles both None/0 from aggregate and SQLite quirks)
    paid = Decimal(str(paid_sum))

    plan = item.plan
    if paid >= item.amount:
        if not item.is_paid:
            item.is_paid = True
            item.paid_at = timezone.now()
            item.save(update_fields=['is_paid', 'paid_at'])
            logger.debug(f"Marked InstallmentItem {item.id} as paid (₹{paid}/{item.amount})")

        # If all items in plan are now paid, complete the plan
        if not plan.items.filter(is_paid=False).exists():
            if plan.status != 'completed':
                plan.status = 'completed'
                plan.save(update_fields=['status'])
                logger.info(f"Completed InstallmentPlan {plan.id} for StudentFee {plan.student_fee_id}")
    else:
        if item.is_paid:
            item.is_paid = False
            item.paid_at = None
            item.save(update_fields=['is_paid', 'paid_at'])
            logger.debug(f"Unmarked InstallmentItem {item.id} (paid ₹{paid} < ₹{item.amount})")

        # If plan was completed but now not, revert status
        if plan.status == 'completed':
            plan.status = 'approved'
            plan.save(update_fields=['status'])
            logger.info(f"Reverted InstallmentPlan {plan.id} to approved (due to partial payment/refund)")

    return item


def has_overdue_installment(student_id):
    """
    Returns True if the student has any unpaid InstallmentItem that is
    more than 15 days past its due_date (the 'expiry date of installment').
    This is used to block attendance QR check-in.
    """
    today = timezone.now().date()
    # due_date < (today - 15 days) = overdue by more than 15 days
    threshold = today - timedelta(days=15)

    return InstallmentItem.objects.filter(
        plan__student_fee__student_id=student_id,
        is_paid=False,
        due_date__lt=threshold,
        plan__status__in=['approved', 'active'],
    ).exists()


def get_refund_policy(payment, requested_amount=None):
    """Return refund eligibility and the capped amount based on payment age and issued inventory."""
    payment_date = getattr(payment, 'payment_date', None) or getattr(payment, 'created_at', None)
    if payment_date is None:
        return {
            'eligible': False,
            'reason': 'Payment date is unavailable.',
            'max_refundable_amount': Decimal('0'),
            'deduction_percent': Decimal('100'),
        }

    if hasattr(payment_date, 'date'):
        payment_date_val = payment_date.date()
    else:
        payment_date_val = payment_date
        
    age_days = (timezone.now().date() - payment_date_val).days
    cap = Decimal('0')
    deduction_percent = Decimal('100')

    if age_days > 7:
        return {
            'eligible': False,
            'reason': 'Refund not allowed after 7 days from payment date.',
            'max_refundable_amount': cap,
            'deduction_percent': deduction_percent,
        }

    if age_days <= 7:
        deduction_percent = Decimal('10')
        payment_amount = Decimal(str(getattr(payment, 'amount', 0)))
        inventory_cost = Decimal('0')

        try:
            from inventory.models import ItemAllocation
            student_id = getattr(payment, 'student_id', None)
            if student_id:
                allocations = ItemAllocation.objects.filter(student_id=student_id, status='issued')
                for allocation in allocations.select_related('item'):
                    unit_price = getattr(allocation.item, 'unit_price', 0) or 0
                    inventory_cost += Decimal(str(unit_price)) * Decimal(str(getattr(allocation, 'quantity', 0) or 0))
        except Exception:
            inventory_cost = Decimal('0')

        adjusted_payment_amount = max(payment_amount - inventory_cost, Decimal('0'))
        cap = (adjusted_payment_amount * (Decimal('100') - deduction_percent)) / Decimal('100')

    requested = Decimal(str(requested_amount if requested_amount is not None else getattr(payment, 'amount', 0)))
    max_refundable = min(requested, cap)

    return {
        'eligible': True,
        'reason': 'Refund allowed with 10% deduction within 7 days.',
        'max_refundable_amount': max_refundable,
        'deduction_percent': deduction_percent,
    }


def get_recipient_emails(student):
    """
    Returns deduplicated list of email addresses for a student (self, parent, user fallback).
    Used for receipt and rejection notifications.
    """
    emails = set()
    if getattr(student, 'email', None):
        emails.add(student.email)
    if getattr(student, 'email_parent', None):
        emails.add(student.email_parent)
    if not emails and getattr(student, 'user', None) and getattr(student.user, 'email', None):
        emails.add(student.user.email)
    return list(emails)


def log_pdf_fallback_usage(payment, used_fallback=False, method='weasyprint', size_bytes=0):
    """
    Helper for fallback detection and logging. Called from send_payment_receipt() or
    pdf_services to track WeasyPrint vs Playwright usage (for monitoring complex CSS cases).
    """
    if used_fallback:
        logger.warning(
            f"Playwright fallback USED for payment {getattr(payment, 'id', 'N/A')} "
            f"receipt PDF (size: {size_bytes} bytes)"
        )
    else:
        logger.info(
            f"Receipt PDF generated with {method} for payment {getattr(payment, 'id', 'N/A')} "
            f"(size: {size_bytes} bytes)"
        )
