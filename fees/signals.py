"""
fees/signals.py — Cross-module signals for Fee payment events.

Fires when a fee payment is verified, updating the student's
fee status and triggering receipt generation.
"""

import logging
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='fees.Payment')
def payment_status_changed(sender, instance, created, **kwargs):
    """
    When a Payment's status is set to 'verified' / 'approved',
    update the associated StudentFee status and log the event.
    """
    if not hasattr(instance, 'status'):
        return

    if instance.status not in ('verified', 'approved'):
        return

    try:
        # Update the parent StudentFee record if it exists
        student_fee = getattr(instance, 'student_fee', None)
        if student_fee:
            # Check if all installments are paid
            from fees.models import Payment
            total_paid = Payment.objects.filter(
                student_fee=student_fee,
                status__in=['verified', 'approved'],
            ).aggregate(total=models.Sum('amount'))['total'] or 0

            if total_paid >= student_fee.total_amount:
                student_fee.status = 'paid'
                student_fee.save(update_fields=['status'])
                logger.info(f"StudentFee {student_fee.id} marked as fully paid")
            else:
                if student_fee.status == 'unpaid':
                    student_fee.status = 'partial'
                    student_fee.save(update_fields=['status'])

    except Exception as e:
        logger.error(f"Fee payment signal error: {e}")
