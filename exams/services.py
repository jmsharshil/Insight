import logging
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from django.core.mail import EmailMessage
from exams.models import Exam
from chat.notifications import send_system_notification
from batches.models import BatchStudent

logger = logging.getLogger(__name__)

def _get_parent_email(student):
    # Some profiles might have parent_email
    if hasattr(student, 'parent_email') and student.parent_email:
        return student.parent_email
    return None

def notify_exam_scheduled(exam):
    """
    Called when an exam is created/scheduled.
    Notifies students (system), parents (email), and examiners (system).
    """
    if exam.status not in ['scheduled', 'ongoing']:
        return

    # Notify students and parents
    if exam.batch:
        student_profiles = BatchStudent.objects.filter(batch=exam.batch).select_related('student__user')
        for bs in student_profiles:
            student = bs.student
            if student and student.user:
                # Notify student via system notification
                send_system_notification(
                    user_id=str(student.user.id),
                    title='New Exam Scheduled',
                    body=f"An exam '{exam.title}' has been scheduled for {exam.scheduled_date.strftime('%d %b %Y')} at {exam.start_time.strftime('%I:%M %p')}.",
                    metadata={'exam_id': str(exam.id)}
                )
                
            # Notify parent via email
            parent_email = _get_parent_email(student)
            if parent_email:
                subject = f"Exam Scheduled: {exam.title}"
                body = f"Dear Parent,\n\nAn exam '{exam.title}' has been scheduled for your child {student.first_name} {student.surname}.\n\nDate: {exam.scheduled_date.strftime('%d %b %Y')}\nTime: {exam.start_time.strftime('%I:%M %p')}\n\nInsight Institute"
                email = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [parent_email])
                try:
                    email.send(fail_silently=True)
                except Exception as e:
                    logger.error(f"Failed to send exam schedule email to parent {parent_email}: {e}")

    # Notify examiners (paper checkers and supervisors)
    examiners = set()
    for checker in exam.paper_checkers.all():
        examiners.add(checker)
    for supervisor in exam.supervisors.all():
        examiners.add(supervisor)
        
    for examiner in examiners:
        send_system_notification(
            user_id=str(examiner.id),
            title='Assigned to Exam',
            body=f"You have been assigned to the exam '{exam.title}' on {exam.scheduled_date.strftime('%d %b %Y')} at {exam.start_time.strftime('%I:%M %p')}.",
            metadata={'exam_id': str(exam.id)}
        )

def exam_reminders_task(*args, **kwargs):
    """
    Background task to send 1-day and 1-hour reminders for scheduled exams.
    Runs every 15 minutes.
    """
    now = timezone.now()
    one_day_from_now = now + timedelta(days=1)
    one_hour_from_now = now + timedelta(hours=1)
    
    # 1-DAY REMINDERS
    upcoming_1d = Exam.objects.filter(
        status='scheduled',
        is_deleted=False,
        reminder_1d_sent=False,
        scheduled_date=one_day_from_now.date()
    )
    
    for exam in upcoming_1d:
        dt_start = timezone.make_aware(timezone.datetime.combine(exam.scheduled_date, exam.start_time))
        if dt_start <= one_day_from_now and dt_start > now:
            _send_exam_reminder(exam, "1 Day", dt_start)
            exam.reminder_1d_sent = True
            exam.save(update_fields=['reminder_1d_sent'])

    # 1-HOUR REMINDERS
    # For 1-hour, check exact time difference
    upcoming_1h = Exam.objects.filter(
        status='scheduled',
        is_deleted=False,
        reminder_1h_sent=False,
        scheduled_date=one_hour_from_now.date()  # Might be today or tomorrow depending on timezone crossover
    )
    
    for exam in upcoming_1h:
        dt_start = timezone.make_aware(timezone.datetime.combine(exam.scheduled_date, exam.start_time))
        if dt_start <= one_hour_from_now and dt_start > now:
            _send_exam_reminder(exam, "1 Hour", dt_start)
            exam.reminder_1h_sent = True
            exam.save(update_fields=['reminder_1h_sent'])
            

def _send_exam_reminder(exam, timeframe, dt_start):
    time_str = dt_start.strftime('%I:%M %p on %d %b %Y')
    
    if exam.batch:
        student_profiles = BatchStudent.objects.filter(batch=exam.batch).select_related('student__user')
        for bs in student_profiles:
            student = bs.student
            if student and student.user:
                send_system_notification(
                    user_id=str(student.user.id),
                    title=f'Exam Reminder: In {timeframe}',
                    body=f"Reminder: Your exam '{exam.title}' starts in {timeframe} at {time_str}.",
                    metadata={'exam_id': str(exam.id)}
                )
            
            parent_email = _get_parent_email(student)
            if parent_email:
                subject = f"Exam Reminder: {exam.title} in {timeframe}"
                body = f"Dear Parent,\n\nReminder: Your child's exam '{exam.title}' starts in {timeframe} at {time_str}.\n\nInsight Institute"
                email = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [parent_email])
                try:
                    email.send(fail_silently=True)
                except Exception:
                    pass

    examiners = set()
    for checker in exam.paper_checkers.all():
        examiners.add(checker)
    for supervisor in exam.supervisors.all():
        examiners.add(supervisor)
        
    for examiner in examiners:
        send_system_notification(
            user_id=str(examiner.id),
            title=f'Exam Duty Reminder: In {timeframe}',
            body=f"Reminder: You are assigned to the exam '{exam.title}' which starts in {timeframe} at {time_str}.",
            metadata={'exam_id': str(exam.id)}
        )
