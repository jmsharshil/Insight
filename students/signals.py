"""
students/signals.py
Post-save signal for Student (E1).

Fires auto_assign_batch() and create_student_fee() whenever a new Student
is created (i.e., admission → enrolled). Errors are caught and logged so
a single failing step never prevents enrollment from completing.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from students.models import Student

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Student)
def on_student_created(sender, instance, created, **kwargs):
    """Trigger batch assignment and fee creation on first student creation."""
    if not created:
        return

    from batches.services import auto_assign_batch
    from fees.services import create_student_fee

    for fn, label in [
        (auto_assign_batch, 'auto_assign_batch'),
        (create_student_fee, 'create_student_fee'),
    ]:
        try:
            fn(instance)
        except Exception as e:
            logger.error(
                f"{label} failed for student {instance.pk}: {e}",
                exc_info=True,
            )
