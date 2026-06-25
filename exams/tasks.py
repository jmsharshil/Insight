"""Celery tasks for exam module. Graceful fallback if Celery not installed."""
import logging
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)




def update_exam_statuses():
    """
    Every minute: automatically transition exam statuses.
    - scheduled -> ongoing (if current time >= start_time)
    - ongoing -> completed (if current time > end_time)
      → Also auto-marks absent students when transitioning to completed.
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
            # Auto-mark absent students for this exam
            try:
                absent_count = auto_mark_absent_after_exam(exam)
                if absent_count > 0:
                    logger.info(f"Auto-marked {absent_count} students absent for exam {exam.title} ({exam.id})")
            except Exception as e:
                logger.error(f"Error auto-marking absent for exam {exam.id}: {e}")

            # NEW: Auto-assign papers (marksheets) to available paper checkers
            # Uses exam.paper_checkers filtered by time slot availability (work hours overlap)
            try:
                from .utils import assign_papers_to_checker
                assigned_count = assign_papers_to_checker(exam.id)
                if assigned_count > 0:
                    logger.info(f"Auto-assigned {assigned_count} papers to checkers for exam {exam.title} ({exam.id})")
            except Exception as e:
                logger.error(f"Error auto-assigning papers for exam {exam.id}: {e}")

    if count_ongoing > 0 or count_completed > 0:
        logger.info(f"Exam Status Update: {count_ongoing} -> ongoing, {count_completed} -> completed.")
    return f"{count_ongoing} ongoing, {count_completed} completed"


def auto_mark_absent_after_exam(exam):
    """
    Auto-mark all students in the exam's batch who did NOT attend as absent.
    Creates MarkSheet records for students who don't have one yet.
    Called automatically when an exam transitions to 'completed'.
    """
    from results.models import MarkSheet
    from .models import ExamSession
    from students.models import Student
    from batches.models import BatchStudent

    if not exam.batch:
        logger.warning(f"Exam {exam.id} has no batch — skipping auto-absent.")
        return 0

    # Collect all students in this batch (direct FK + BatchStudent M2M)
    batch_student_ids = set(
        Student.objects.filter(batch=exam.batch, status='active')
        .values_list('id', flat=True)
    )
    batch_student_ids.update(
        BatchStudent.objects.filter(batch=exam.batch)
        .values_list('student_id', flat=True)
    )

    if not batch_student_ids:
        return 0

    # Students who attended (have a submitted ExamSession)
    attended_student_ids = set(
        ExamSession.objects.filter(exam=exam, is_submitted=True)
        .values_list('student_id', flat=True)
    )

    # Students who did NOT attend
    absent_student_ids = batch_student_ids - attended_student_ids

    absent_count = 0
    now = timezone.now()

    for student_id in absent_student_ids:
        ms, created = MarkSheet.objects.get_or_create(
            exam=exam,
            student_id=student_id,
            defaults={
                'is_absent': True,
                'marks_obtained': 0,
                'is_pass': False,
                'is_submitted': True,
                'remarks': 'Absent',
                'checked_at': now,
            }
        )
        if not created and not ms.is_submitted:
            # MarkSheet exists but was not submitted — mark as absent
            ms.is_absent = True
            ms.marks_obtained = 0
            ms.is_pass = False
            ms.is_submitted = True
            ms.remarks = 'Absent'
            ms.checked_at = now
            ms.save()
            absent_count += 1
        elif created:
            absent_count += 1

    return absent_count


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
