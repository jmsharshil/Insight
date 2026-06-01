"""Celery tasks for exam module. Graceful fallback if Celery not installed."""
import logging
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)

try:
    from celery import shared_task
except ImportError:
    def shared_task(func=None, **kwargs):
        if func is None:
            return lambda f: f
        return func


@shared_task
def update_exam_statuses():
    """
    Every minute: automatically transition exam statuses.
    - scheduled -> ongoing (if current time >= start_time)
    - ongoing -> completed (if current time > end_time)
    """
    from .models import Exam
    
    now = timezone.localtime(timezone.now())
    current_date = now.date()
    current_time = now.time()

    # Scheduled -> Ongoing
    to_ongoing = Exam.objects.filter(
        status='scheduled',
        scheduled_date__lte=current_date,
    )
    count_ongoing = 0
    for exam in to_ongoing:
        if exam.scheduled_date < current_date or (exam.scheduled_date == current_date and exam.start_time <= current_time):
            exam.status = 'ongoing'
            exam.save(update_fields=['status'])
            count_ongoing += 1

    # Ongoing -> Completed
    to_completed = Exam.objects.filter(
        status='ongoing',
        scheduled_date__lte=current_date,
    )
    count_completed = 0
    for exam in to_completed:
        if exam.scheduled_date < current_date or (exam.scheduled_date == current_date and exam.end_time < current_time):
            exam.status = 'completed'
            exam.save(update_fields=['status'])
            count_completed += 1

    if count_ongoing > 0 or count_completed > 0:
        logger.info(f"Exam Status Update: {count_ongoing} -> ongoing, {count_completed} -> completed.")
    return f"{count_ongoing} ongoing, {count_completed} completed"


@shared_task
def send_pending_submission_reminders():
    """Daily: remind checkers about overdue marksheets."""
    from results.models import MarkSheet, SubmissionReminderLog
    from .emails import send_submission_reminder_email

    cutoff = timezone.now().date() - timedelta(days=1)
    pending = MarkSheet.objects.filter(is_submitted=False, exam__scheduled_date__lt=cutoff)

    count = 0
    for ms in pending:
        log, created = SubmissionReminderLog.objects.get_or_create(marksheet=ms)
        if not created:
            log.reminder_count += 1
            log.save(update_fields=['reminder_count'])
        send_submission_reminder_email(ms)
        count += 1

    logger.info(f"Sent {count} submission reminders")
    return f"{count} reminders sent"


@shared_task
def auto_expire_exam_sessions():
    """Every minute: auto-submit expired sessions."""
    from .models import ExamSession
    from .utils import auto_submit_session

    now = timezone.now()
    expired = ExamSession.objects.filter(is_submitted=False).select_related('exam')

    count = 0
    for session in expired:
        deadline = session.started_at + timedelta(minutes=session.exam.duration_minutes)
        if now > deadline:
            auto_submit_session(session)
            count += 1

    logger.info(f"Auto-submitted {count} expired sessions")
    return f"{count} sessions auto-submitted"
