"""
fees/signals.py — Cross-module signals for Fee payment events.

Post-save hook for Payment model. When verified, calls update_student_fee_status()
to recalculate amounts, mark installments, and sync status (paid/partial/etc).
Receipt generation is handled explicitly in create_student_fee() and PaymentVerifyView.
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='fees.Payment')
def payment_status_changed(sender, instance, created, **kwargs):
    """
    Post-save handler limited to status recalculation. Receipt PDF + email is now
    called explicitly from create_student_fee() and PaymentVerifyView (with
    _receipt_generated guard on the instance to break recursion on
    payment_document.save()).
    """
    if getattr(instance, 'status', None) not in ('verified', 'approved'):
        return

    try:
        if instance.student_fee_id:
            from .utils import update_student_fee_status
            updated_fee = update_student_fee_status(instance.student_fee_id)
            logger.info(
                f"Payment {instance.receipt_number or instance.id} verified — "
                f"updated StudentFee {updated_fee.id} to status '{updated_fee.status}'"
            )
    except Exception as e:
        logger.error(f"Fee payment signal error for payment {getattr(instance, 'id', 'N/A')}: {e}")
