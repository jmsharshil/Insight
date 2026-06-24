from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Question


@receiver(post_save, sender=Question)
def update_total_marks_on_save(sender, instance, created=False, **kwargs):
    """Recalculate Exam.total_marks on Question create or update (e.g. marks change).
    Uses the recalculate_total_marks() method on the parent Exam.
    """
    if instance.exam_id:
        instance.exam.recalculate_total_marks()


@receiver(post_delete, sender=Question)
def update_total_marks_on_delete(sender, instance, **kwargs):
    """Recalculate Exam.total_marks on Question delete."""
    if hasattr(instance, 'exam') and instance.exam_id:
        try:
            instance.exam.recalculate_total_marks()
        except Exception:  # Exam may be deleted in cascade
            pass
