"""
leads/signals.py — Cross-module signals for CRM → Admissions pipeline.

Fires when a Lead's status is updated to 'converted', triggering
automatic Admission record creation in the onboarding app.
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='leads.Lead')
def lead_status_changed(sender, instance, created, **kwargs):
    """
    When a Lead's status changes to 'converted', auto-create an
    Admission record in the onboarding app if one doesn't already exist.
    """
    if created:
        return  # Only trigger on updates, not creation

    if instance.current_stage != 'converted':
        return

    try:
        from onboarding.models import Admission

        # Avoid duplicate admission
        if Admission.objects.filter(lead=instance).exists():
            logger.info(f"Admission already exists for Lead {instance.id}")
            return

        admission = Admission.objects.create(
            lead=instance,
            branch=instance.branch,
            student_name=instance.student_name,
            student_email=instance.email,
            student_phone=instance.phone,
            course=instance.course,
            status='pending',
        )
        logger.info(f"Auto-created Admission {admission.id} from Lead {instance.id}")

    except Exception as e:
        logger.error(f"Failed to auto-create Admission from Lead {instance.id}: {e}")
