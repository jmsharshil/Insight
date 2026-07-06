import logging
from django.conf import settings
from core.sender import send_email
from chat.notifications import send_system_notification

logger = logging.getLogger(__name__)

def _notify(user_id, title, body, metadata=None, email_template=None, email_context=None):
    """Stub: in-app notification replaced with real."""
    if user_id:
        send_system_notification(
            user_id=str(user_id),
            title=title,
            body=body,
            metadata=metadata,
        )


def send_checker_assignment_email(marksheet):
    """Notify paper_checker about their assignment + in-app notification."""
    checker = marksheet.paper_checker
    if not checker:
        return
    token = marksheet.tokens.filter(is_used=False).order_by('-created_at').first()
    link = f"{getattr(settings, 'FRONTEND_BASE_URL', 'http://localhost:5173')}/api/v1/checker-portal/submit/?token={token.token}" if token else 'N/A'
    deadline = token.expires_at if token else 'N/A'
    
    subject = f"Paper Assignment: {marksheet.exam.title}"
    text_content = (
        f"Dear {checker.name},\n"
        f"You have been assigned to check papers for: {marksheet.exam.title}\n"
        f"Submission link: {link}\n"
        f"Deadline: {deadline}\n"
    )

    send_email(
        to=checker.email,
        subject=subject,
        text=text_content,
        template='emails/checker_assignment.html',
        template_context={
            'checker_name': checker.name,
            'exam_title': marksheet.exam.title,
            'submission_link': link,
            'deadline': deadline,
        },
        organization=marksheet.exam.organization if hasattr(marksheet.exam, 'organization') else checker.organization,
    )

    # FRD §4.6.2: in-app notification alongside email
    _notify(
        checker.id, title="Paper Assigned",
        body=f"You have been assigned papers for {marksheet.exam.title}. Check your secure link.",
        metadata={"marksheet_id": str(marksheet.id), "exam_id": str(marksheet.exam_id)},
    )


def send_answer_key_email(checker, exam, signed_url):
    """Send answer key access link to paper_checker + in-app notification."""
    subject = f"Answer Key: {exam.title}"
    text_content = (
        f"Dear {checker.name},\n"
        f"Answer key for: {exam.title}\n"
        f"Access link (expires in 48h): {signed_url}\n"
    )

    send_email(
        to=checker.email,
        subject=subject,
        text=text_content,
        template='emails/answer_key.html',
        template_context={
            'checker_name': checker.name,
            'exam_title': exam.title,
            'access_link': signed_url,
        },
        organization=exam.organization if hasattr(exam, 'organization') else checker.organization,
    )

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
        
    subject = f"Reminder: Pending Papers for {marksheet.exam.title}"
    text_content = (
        f"Dear {checker.name},\n"
        f"Reminder: You have pending papers for {marksheet.exam.title}.\n"
        f"Please submit your marks at your earliest convenience.\n"
    )

    send_email(
        to=checker.email,
        subject=subject,
        text=text_content,
        template='emails/submission_reminder.html',
        template_context={
            'checker_name': checker.name,
            'exam_title': marksheet.exam.title,
        },
        organization=marksheet.exam.organization if hasattr(marksheet.exam, 'organization') else checker.organization,
    )


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
    organization = marksheet.exam.organization if hasattr(marksheet.exam, 'organization') else None
    
    # Needs to go to Admin Senior Executives. Here we will find one or just use default.
    from auth_user.models import User
    admin_execs = User.objects.filter(role='admin_senior_executive')
    if organization:
        admin_execs = admin_execs.filter(organization=organization)
        
    admin_email = admin_execs.first().email if admin_execs.exists() else settings.DEFAULT_FROM_EMAIL

    subject = f"Recheck Request: {exam_title}"
    text_content = (
        f"Recheck Request:\n"
        f"Student: {student_name}\n"
        f"Exam: {exam_title}\n"
        f"Reason: {recheck_request.reason or 'No reason provided'}\n"
    )

    send_email(
        to=admin_email,
        subject=subject,
        text=text_content,
        template='emails/recheck_request.html',
        template_context={
            'student_name': student_name,
            'exam_title': exam_title,
            'reason': recheck_request.reason,
        },
        organization=organization,
    )

    # In-app notification to ASE (recipient resolved by caller)
    _notify(
        None, title="Recheck Request",
        body=f"{student_name} has requested a recheck for {exam_title}",
        metadata={"recheck_request_id": str(recheck_request.id)},
    )
