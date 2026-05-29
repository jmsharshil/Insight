from django.db import transaction
from .models import StudentFee, Payment, InstallmentItem


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
            student_fee.status = 'pending'

    student_fee.save(update_fields=['amount_paid', 'status', 'updated_at'])
    return student_fee


@transaction.atomic
def mark_installment_paid(installment_item_id):
    """Mark an installment item as paid if its linked payment is verified."""
    from django.db.models import Sum
    item = InstallmentItem.objects.get(id=installment_item_id)
    paid = Payment.objects.filter(
        installment_item=item,
        status='verified',
    ).aggregate(total=Sum('amount'))['total'] or 0

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
