import logging
from django.conf import settings
from core.sender import send_email
from chat.notifications import send_system_notification, send_whatsapp_with_fallback

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

    try:
        send_whatsapp_with_fallback(
            to=checker.phone,
            template_name="admission_process",
            language_code="en",
            components=[{"type": "body", "parameters": [{"type": "text", "text": checker.name}]}],
            fallback_body=text_content,
            user_id=str(checker.id),
        )
    except Exception as e:
        print(e)

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

    try:
        send_whatsapp_with_fallback(
            to=checker.phone,
            template_name="admission_process",
            language_code="en",
            components=[{"type": "body", "parameters": [{"type": "text", "text": checker.name}]}],
            fallback_body=text_content,
            user_id=str(checker.id),
        )
    except Exception as e:
        print(e)

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

    try:
        send_whatsapp_with_fallback(
            to=checker.phone,
            template_name="admission_process",
            language_code="en",
            components=[{"type": "body", "parameters": [{"type": "text", "text": checker.name}]}],
            fallback_body=text_content,
            user_id=str(checker.id),
        )
    except Exception as e:
        print(e)


def send_material_upload_reminder_email(faculty_user, exam, missing_items):
    """
    Remind faculty to upload missing exam materials (Question Paper / Answer Key).
    Includes a direct frontend link to the exam detail/upload page.
    """
    from django.conf import settings

    frontend_base = getattr(settings, 'FRONTEND_BASE_URL', 'http://localhost:5173')
    # Deep-link to the exam upload page on the faculty portal
    exam_link = f"{frontend_base}/exams/{exam.id}/upload"

    missing_str = " and ".join(missing_items)
    subject = f"Action Required: Upload {missing_str} for '{exam.title}'"
    text_content = (
        f"Dear {faculty_user.name},\n\n"
        f"This is a reminder to upload the following material(s) for the exam "
        f"'{exam.title}' scheduled on {exam.scheduled_date.strftime('%d %b %Y')}:\n\n"
        f"  • {chr(10).join('  • ' + item for item in missing_items)}\n\n"
        f"Please submit them to the admin as soon as possible.\n\n"
        f"Thank you."
    )

    send_email(
        to=faculty_user.email,
        subject=subject,
        text=text_content,
        template='emails/material_upload_reminder.html',
        template_context={
            'faculty_name': faculty_user.name,
            'exam_title': exam.title,
            'exam_date': exam.scheduled_date.strftime('%d %b %Y'),
            'missing_items': missing_items,
        },
        organization=exam.branch.organization if hasattr(exam, 'branch') and exam.branch else None,
    )

    # Save to NotificationHistory so the reminder appears in the in-app notification feed
    # (Email path bypasses send_fcm_notification, so we record it explicitly here)
    try:
        from auth_user.models import NotificationHistory
        missing_str = " and ".join(missing_items)
        NotificationHistory.objects.create(
            user=faculty_user,
            title='Reminder: Submit Exam Materials',
            body=f"Please submit the {missing_str} to the admin for '{exam.title}' scheduled on {exam.scheduled_date.strftime('%d %b %Y')}.",
            data={'exam_id': str(exam.id), 'missing_items': missing_items, 'channel': 'email'},
        )
    except Exception as e:
        logger.warning(f"Failed to save NotificationHistory for faculty {faculty_user.id}: {e}")

    try:
        if getattr(faculty_user, 'phone', None):
            send_whatsapp_with_fallback(
                to=faculty_user.phone,
                template_name="admission_process",
                language_code="en",
                components=[{"type": "body", "parameters": [{"type": "text", "text": faculty_user.name}]}],
                fallback_body=text_content,
                user_id=str(faculty_user.id),
            )
    except Exception as e:
        logger.warning(f"WhatsApp reminder failed for faculty {faculty_user.id}: {e}")


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
    admin_phone = admin_execs.first().phone if admin_execs.exists() else None
    admin_id = admin_execs.first().id if admin_execs.exists() else None

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
    
    try:
        if admin_phone:
            send_whatsapp_with_fallback(
                to=admin_phone,
                template_name="admission_process",
                language_code="en",
                components=[{"type": "body", "parameters": [{"type": "text", "text": student_name}]}],
                fallback_body=text_content,
                user_id=str(admin_id),
            )
    except Exception as e:
        print(e)

    # In-app notification to ASE (recipient resolved by caller)
    _notify(
        None, title="Recheck Request",
        body=f"{student_name} has requested a recheck for {exam_title}",
        metadata={"recheck_request_id": str(recheck_request.id)},
    )
