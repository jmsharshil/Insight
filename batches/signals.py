# ═══════════════════════════════════════════════════════════════════════════════
#  Signals for auto-updating Subject.total_hours based on Chapter.duration_hours
# ═══════════════════════════════════════════════════════════════════════════════
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Chapter, Subject
@receiver(post_save, sender=Chapter)
def update_subject_total_hours(sender, instance, created=False, **kwargs):
    """Update subject's total_hours whenever a chapter is saved (created/updated)."""
    if instance.subject:
        instance.subject.update_total_hours()


@receiver(post_delete, sender=Chapter)
def update_subject_total_hours_on_delete(sender, instance, **kwargs):
    """Update subject's total_hours when a chapter is deleted."""
    if instance.subject and instance.subject.pk:
        # Refresh the subject instance from DB in case it was deleted (though unlikely)
        try:
            subject = Subject.objects.get(pk=instance.subject.pk)
            subject.update_total_hours()
        except Subject.DoesNotExist:
            pass
