"""
schofee_finance/signals.py
──────────────────────────
Signal receiver for Admission lifecycle.
Automatically initializes a FinanceApplication in INITIATED status
when an admission is created or updated with payment_type == 'finance'.
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .services.pipeline import handle_admission_finance_hook

logger = logging.getLogger(__name__)


@receiver(post_save, sender="onboarding.Admission")
def on_admission_saved(sender, instance, **kwargs):
    if str(getattr(instance, "payment_type", "")).lower() == "finance":
        try:
            finance_app = handle_admission_finance_hook(instance)
            if finance_app:
                logger.info(
                    "Finance hook initialized FinanceApplication #%s for admission #%s",
                    finance_app.id,
                    instance.id,
                )
        except Exception as exc:
            logger.error("Error running finance hook for admission #%s: %s", instance.id, exc, exc_info=True)
