from django.db import transaction
from .models import StudentFee, Payment, InstallmentItem
import random
from django.db.models import Q
from django.utils import timezone


def get_installment_plan_status(course_type, num_installments):
    """
    Determine initial status for an InstallmentPlan based on course_type of the level
    and number of installment items.
    
    Rules:
    - If course_type is 'cseet' and >2 items → 'pending_approval'
    - For other course_types if >4 items → 'pending_approval'
    - Otherwise → 'approved' (no approval needed)
    """
    if course_type == 'cseet':
        return 'pending_approval' if num_installments > 2 else 'approved'
    return 'pending_approval' if num_installments > 4 else 'approved'

def select_bank_accounts_for_payment(amount, limit=None):
    """Return a shuffled list of active BankAccount objects whose max_payment_amount
    is either unset (None) or greater than or equal to the given amount.

    Args:
        amount (Decimal): The payment amount to compare against thresholds.
        limit (int, optional): Maximum number of accounts to return. If None, returns all.
    Returns:
        list[BankAccount]: Shuffled list of eligible bank accounts.
    """
    from .models import BankAccount
    eligible_qs = BankAccount.objects.filter(is_active=True).filter(
        Q(max_payment_amount__isnull=True) | Q(max_payment_amount__gte=amount)
    )
    accounts = list(eligible_qs)
    random.shuffle(accounts)
    if limit is not None:
        return accounts[:limit]
    return accounts


def update_student_fee_status(student_fee_id):
    """
    Recalculates amount_paid and status for a StudentFee
    based on all verified payments and completed refunds.
    """
    student_fee = StudentFee.objects.get(id=student_fee_id)

    # Sum of verified payments
    from django.db.models import Sum
    paid_sum = Payment.objects.filter(
        student_fee=student_fee,
        status='verified',
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Subtract completed refunds
    from .models import Refund
    refund_sum = Refund.objects.filter(
        payment__student_fee=student_fee,
        status='completed',
    ).aggregate(total=Sum('amount'))['total'] or 0

    net_paid = paid_sum - refund_sum
    student_fee.amount_paid = net_paid

    # Auto-resolve installments based on net_paid
    from .models import InstallmentPlan
    for plan in InstallmentPlan.objects.filter(student_fee=student_fee, status__in=['approved', 'completed']):
        remaining_payment = net_paid
        for item in plan.items.all().order_by('due_date', 'id'):
            if remaining_payment >= item.amount:
                if not item.is_paid:
                    item.is_paid = True
                    from django.utils import timezone
                    item.paid_at = timezone.now()
                    item.save(update_fields=['is_paid', 'paid_at'])
                remaining_payment -= item.amount
            else:
                if item.is_paid:
                    item.is_paid = False
                    item.paid_at = None
                    item.save(update_fields=['is_paid', 'paid_at'])
                # Consume remaining payment so we don't apply it further
                remaining_payment = 0
                
        if not plan.items.filter(is_paid=False).exists():
            plan.status = 'completed'
            plan.save(update_fields=['status'])
        else:
            plan.status = 'approved'
            plan.save(update_fields=['status'])

    # Determine status
    amount_due = student_fee.total_amount - student_fee.discount - net_paid
    if amount_due <= 0:
        student_fee.status = 'paid'
    elif net_paid > 0:
        student_fee.status = 'partial'
    else:
        from django.utils import timezone
        if student_fee.due_date and student_fee.due_date < timezone.now().date():
            student_fee.status = 'overdue'
        else:
            student_fee.status = 'approval_pending'

    student_fee.save(update_fields=['amount_paid', 'status', 'updated_at'])
    return student_fee


@transaction.atomic
def mark_installment_paid(installment_item_id):
    """Mark an installment item as paid if its linked payment is verified."""
    from django.db.models import Sum
    from decimal import Decimal
    item = InstallmentItem.objects.get(id=installment_item_id)
    paid = Payment.objects.filter(
        installment_item=item,
        status='verified',
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Ensure paid is a Decimal to avoid TypeError in SQLite
    paid = Decimal(str(paid))

    if paid >= item.amount:
        item.is_paid = True
        from django.utils import timezone
        item.paid_at = timezone.now()
        item.save(update_fields=['is_paid', 'paid_at'])

        # Check if all items in the plan are paid
        plan = item.plan
        if not plan.items.filter(is_paid=False).exists():
            plan.status = 'completed'
            plan.save(update_fields=['status'])

    return item
