"""
Email stubs for exam module.
Replace print() with actual send_mail() when email service is configured.
FRD §4.6.2: all email stubs also call in-app notification stub.
"""
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def _notify(user_id, title, body, metadata=None):
    """Stub: in-app notification."""
    logger.info(f"NOTIFY [{user_id}] {title}: {body}")


def send_checker_assignment_email(marksheet):
    """Notify paper_checker about their assignment + in-app notification."""
    checker = marksheet.paper_checker
    if not checker:
        return
    token = marksheet.tokens.filter(is_used=False).order_by('-created_at').first()
    link = f"{getattr(settings, 'BASE_URL', 'http://localhost:8000')}/api/v1/checker-portal/submit/?token={token.token}" if token else 'N/A'

    msg = (
        f"Dear {checker.name},\n"
        f"You have been assigned to check papers for: {marksheet.exam.title}\n"
        f"Submission link: {link}\n"
        f"Deadline: {token.expires_at if token else 'N/A'}\n"
    )
    logger.info(f"[EMAIL STUB] Checker assignment → {checker.email}: {msg}")
    print(f"[EMAIL STUB] send_checker_assignment_email → {checker.email}")

    # FRD §4.6.2: in-app notification alongside email
    _notify(
        checker.id, title="Paper Assigned",
        body=f"You have been assigned papers for {marksheet.exam.title}. Check your secure link.",
        metadata={"marksheet_id": str(marksheet.id), "exam_id": str(marksheet.exam_id)},
    )


def send_answer_key_email(checker, exam, signed_url):
    """Send answer key access link to paper_checker + in-app notification."""
    msg = (
        f"Dear {checker.name},\n"
        f"Answer key for: {exam.title}\n"
        f"Access link (expires in 48h): {signed_url}\n"
    )
    logger.info(f"[EMAIL STUB] Answer key → {checker.email}: {msg}")
    print(f"[EMAIL STUB] send_answer_key_email → {checker.email}")

    # FRD §4.6.2: in-app notification
    _notify(
        checker.id, title="Answer Key Available",
        body=f"Answer key for {exam.title} is ready. Link expires in 48 hours.",
        metadata={"exam_id": str(exam.id), "signed_url": signed_url},
    )


def send_submission_reminder_email(marksheet):
    """Remind paper_checker about overdue marksheet."""
    checker = marksheet.paper_checker
    if not checker:
        return
    msg = (
        f"Dear {checker.name},\n"
        f"Reminder: You have pending papers for {marksheet.exam.title}.\n"
        f"Please submit your marks at your earliest convenience.\n"
    )
    logger.info(f"[EMAIL STUB] Submission reminder → {checker.email}: {msg}")
    print(f"[EMAIL STUB] send_submission_reminder_email → {checker.email}")


def send_recheck_request_notification(recheck_request):
    """
    FRD §4.6.2: notify Admin Senior Executive when student raises recheck.
    """
    marksheet = recheck_request.marksheet
    student_name = ''
    try:
        student_name = recheck_request.requested_by.user.name
    except Exception:
        student_name = str(recheck_request.requested_by_id)

    exam_title = marksheet.exam.title

    msg = (
        f"Recheck Request:\n"
        f"Student: {student_name}\n"
        f"Exam: {exam_title}\n"
        f"Reason: {recheck_request.reason or 'No reason provided'}\n"
    )
    logger.info(f"[EMAIL STUB] Recheck request notification: {msg}")
    print(f"[EMAIL STUB] send_recheck_request_notification for {exam_title}")

    # In-app notification to ASE (recipient resolved by caller)
    _notify(
        None, title="Recheck Request",
        body=f"{student_name} has requested a recheck for {exam_title}",
        metadata={"recheck_request_id": str(recheck_request.id)},
    )
