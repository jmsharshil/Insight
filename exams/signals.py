from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
import logging

from .models import Exam, Question

logger = logging.getLogger(__name__)


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


@receiver(post_save, sender=Exam)
def ensure_paper_checkers_on_exam_create(sender, instance, created=False, **kwargs):
    """Automatically ensure Exam.paper_checkers M2M is populated on creation
    (or first save if empty). Uses branch-scoped fallback for paper_checker
    role users. This guarantees the M2M exists for visibility in paper_checker
    queryset (Q(paper_checkers=user)). MarkSheet FK assignment remains delayed
    until exam completion + auto_mark_absent (in tasks.py).
    """
    if created or not instance.paper_checkers.exists():
        try:
            instance.ensure_paper_checkers()
            if created:
                logger.info(f"Auto-ensured paper_checkers M2M for new exam {instance.id} ({instance.title})")
            else:
                logger.debug(f"Ensured paper_checkers for existing exam {instance.id}")
        except Exception as e:
            logger.warning(f"Failed to ensure paper checkers for exam {instance.id}: {e}")
