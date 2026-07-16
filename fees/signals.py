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
    When a Payment is saved with verified status, trigger full status recalc
    via utils (updates amount_paid, marks installments paid, sets fee status
    to paid/partial/overdue/approval_pending). Also logs.
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

        # Auto-generate and save receipt PDF to payment.payment_document (and email)
        # when payment is verified. Uses _receipt_generated flag on instance to
        # prevent recursion from the document.save() inside send_payment_receipt().
        if (
            getattr(instance, 'status', None) == 'verified'
            and not getattr(instance, '_receipt_generated', False)
        ):
            instance._receipt_generated = True
            from .services import send_payment_receipt
            send_payment_receipt(instance)
    except Exception as e:
        logger.error(f"Fee payment signal error for payment {getattr(instance, 'id', 'N/A')}: {e}")
