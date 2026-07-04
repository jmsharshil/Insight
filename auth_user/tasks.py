import logging
from datetime import timedelta

from django.utils import timezone

from .models import NotificationHistory

logger = logging.getLogger(__name__)


def cleanup_old_notifications(retention_days=21):
    """Delete notification history entries older than the retention window."""
    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted, _ = NotificationHistory.objects.filter(created_at__lt=cutoff).delete()
    logger.info("[NOTIFICATION RETENTION] Deleted %d notifications older than %d days.", deleted, retention_days)
    return deleted


def schedule_notification_retention():
    from scheduler.services import TaskScheduler

    TaskScheduler.schedule(
        task_type="cleanup_old_notifications",
        delay_seconds=3600,
        is_recurring=True,
        interval_seconds=86400,
        max_retries=3,
    )
    logger.info("[NOTIFICATION RETENTION] Scheduler task created.")
