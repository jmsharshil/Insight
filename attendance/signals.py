"""
attendance/signals.py — Cross-module signals for attendance events.

Handles post-attendance actions like violation threshold checks
and low-attendance alerting.
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='attendance.ViolationRecord')
def violation_created_or_updated(sender, instance, created, **kwargs):
    """
    When a ViolationRecord is created or resolved,
    trigger the threshold check to potentially block/unblock QR.
    """
    try:
        from attendance.tasks import check_violation_threshold
        check_violation_threshold.delay(str(instance.student_id))
    except Exception as e:
        # Graceful fallback if Celery is not running
        logger.warning(f"Could not dispatch violation threshold check: {e}")
        try:
            from attendance.utils import should_block_qr
            from students.models import Student
            if should_block_qr(instance.student_id):
                Student.objects.filter(id=instance.student_id).update(qr_blocked=True)
            else:
                Student.objects.filter(id=instance.student_id).update(qr_blocked=False)
        except Exception as inner_e:
            logger.error(f"Fallback violation check failed: {inner_e}")
