"""
core/utils.py — Shared helper functions used across all apps.

Centralises the repeated _user_role / _user_branch_id helpers that were
previously copy-pasted in attendance, exams, leave, and payroll views.
"""

import logging

logger = logging.getLogger(__name__)


def get_user_role(user):
    """Return the role string of the authenticated user."""
    return getattr(user, 'role', None)


def get_user_branch_id(user):
    """
    Resolve the branch_id for the given user.

    Priority:
      1. user.branch_id   (User model FK)
      2. user.faculty_profile.branch_id  (FacultyProfile)
    """
    # Direct FK on User model
    branch_id = getattr(user, 'branch_id', None)
    if branch_id:
        return branch_id

    # Fallback: FacultyProfile
    try:
        from faculty.models import FacultyProfile
        fp = FacultyProfile.objects.only('branch_id').get(user=user)
        return fp.branch_id
    except Exception:
        pass

    return None


def get_student_profile(user):
    """
    Return the Student/StudentProfile for a user with role='student'.
    Returns None if not found.
    """
    try:
        from students.models import Student
        return Student.objects.select_related('branch', 'batch').get(user=user)
    except Exception:
        return None


def apply_filters(view_instance, request, queryset):
    """
    Helper to apply DRF filter backends manually to an APIView.
    Uses view_instance.filter_backends to determine which filters to apply.
    """
    backends = getattr(view_instance, 'filter_backends', [])
    for backend_class in backends:
        backend = backend_class()
        queryset = backend.filter_queryset(request, queryset, view_instance)
    return queryset


def notify_users_by_role(
    roles,
    title,
    body,
    organization=None,
    branch=None,
    metadata=None,
    email_template=None,
    email_context=None,
    email_subject=None,
):
    """
    Find users with the given roles (optionally scoped by organization or branch)
    and send them a system notification.
    """
    from django.contrib.auth import get_user_model
    from chat.notifications import send_system_notification

    User = get_user_model()
    qs = User.objects.filter(role__in=roles, is_active=True)

    if branch:
        qs = qs.filter(branch=branch)
    elif organization:
        qs = qs.filter(organization=organization)

    for user in qs:
        send_system_notification(
            user_id=str(user.id),
            title=title,
            body=body,
            metadata=metadata,
            email_template=email_template,
            email_context=email_context,
            email_subject=email_subject,
        )

#whatsapp task
"""
Wires WhatsApp sending into your existing scheduler.services.TaskScheduler
instead of a separate worker process. TaskScheduler already gives you DB
persistence, exponential backoff, retry, and reconciliation after restart —
this file just registers "whatsapp_send" as a task_type it knows how to run.

Nothing new to deploy: whatever process already calls TaskScheduler.reconcile()
/ reschedule_future_pending() on startup (and whatever already drains
core.task_queue.TASK_QUEUE) now also drains WhatsApp sends. No dedicated
run_whatsapp_worker process, no second sqlite file.

Setup:
    1. Import this module somewhere that runs at process startup, before
       TaskScheduler.reconcile() is called — e.g. your AppConfig.ready(),
       right next to wherever you already call TaskScheduler.register(...)
       for your other task types (interview_feedback_reminder, bgv_status_poll).

           # apps.py
           def ready(self):
               from chat import whatsapp_tasks  # noqa: registers "whatsapp_send"
               ...

    2. Call queue_whatsapp_text / queue_whatsapp_template / queue_whatsapp_media
       from views.py / consumers.py instead of touching TaskScheduler directly.
"""
from typing import Any, Dict, List, Optional

from django.conf import settings
from typing import Optional

from scheduler.services import TaskScheduler

from .sender import WhatsAppAPIError, WhatsAppConfig, WhatsAppSender

# Same list as before: Meta error codes that will never succeed on retry.
# https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes
PERMANENT_ERROR_CODES = {
    100,     # invalid object ID / no permission / unsupported operation (e.g. wrong phone_number_id)
    131026,  # undeliverable / invalid number
    131047,  # outside 24h window, needs a template
    131051,  # unsupported message type
    132000,  # template param count mismatch
    132001,  # template missing / not approved
    132005,  # template param format mismatch
    131009,  # invalid parameter value
    133010,  # phone_number_id wrong / not registered
    190,     # bad/expired access token
}

_sender_instance: Optional[WhatsAppSender] = None


def _get_sender() -> WhatsAppSender:
    """One pooled WhatsAppSender per process, reused across every task run —
    same reasoning as before, just without a dedicated worker process to own it."""
    global _sender_instance
    if _sender_instance is None:
        config = WhatsAppConfig(
            phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID,
            access_token=settings.WHATSAPP_ACCESS_TOKEN,
        )
        _sender_instance = WhatsAppSender(config)
    return _sender_instance


def _run_whatsapp_send(*, method: str, **send_kwargs):
    """
    The task_type callable registered with TaskScheduler. Signature matches
    how _execute calls it: ``fn(**task.task_kwargs)``.

    Transient errors (network, 429, 5xx) -> re-raise, so TaskScheduler's own
    retry_count/backoff/max_retries logic in _execute handles it exactly like
    any other task type.

    Permanent errors (bad number, template not approved, expired token, etc.)
    -> logged and swallowed (not re-raised), because retrying can't fix them
    and TaskScheduler has no separate "don't retry this" signal — raising
    would just burn retries for nothing. See note at the bottom of this file
    if you want these to show as status="failed" instead of "completed".
    """
    sender = _get_sender()
    fn = getattr(sender, method, None)
    if fn is None:
        # Programmer/config error, not a transient API issue - don't retry silently,
        # surface it loudly.
        raise ValueError(f"WhatsAppSender has no method '{method}'")

    try:
        return fn(**send_kwargs)
    except WhatsAppAPIError as exc:
        if exc.error_code in PERMANENT_ERROR_CODES:
            logger.error(
                "[WHATSAPP] Permanent failure (code=%s), not retrying: %s",
                exc.error_code, exc,
            )
            return  # swallow -> TaskScheduler marks the task 'completed'
        logger.warning("[WHATSAPP] Transient failure (code=%s): %s", exc.error_code, exc)
        raise  # let TaskScheduler's retry/backoff handle it


TaskScheduler.register("whatsapp_send", _run_whatsapp_send)


# ---------------- convenience wrappers for call sites ----------------

def queue_whatsapp_text(*, to: str, body: str, delay_seconds: int = 0, max_retries: int = 3):
    return TaskScheduler.schedule(
        task_type="whatsapp_send",
        task_kwargs={"method": "send_text", "to": to, "body": body},
        delay_seconds=delay_seconds,
        max_retries=max_retries,
    )


def queue_whatsapp_template(*, to: str, template_name: str, language_code: str = "en_US",
                             components: Optional[List[Dict[str, Any]]] = None,
                             delay_seconds: int = 0, max_retries: int = 3):
    return TaskScheduler.schedule(
        task_type="whatsapp_send",
        task_kwargs={
            "method": "send_template",
            "to": to,
            "template_name": template_name,
            "language_code": language_code,
            "components": components or [],
        },
        delay_seconds=delay_seconds,
        max_retries=max_retries,
    )


def queue_whatsapp_media(*, to: str, media_type: str, link: Optional[str] = None,
                          media_id: Optional[str] = None, caption: Optional[str] = None,
                          filename: Optional[str] = None,
                          delay_seconds: int = 0, max_retries: int = 3):
    kwargs = {"method": "send_media", "to": to, "media_type": media_type}
    if link:
        kwargs["link"] = link
    if media_id:
        kwargs["media_id"] = media_id
    if caption:
        kwargs["caption"] = caption
    if filename:
        kwargs["filename"] = filename
    return TaskScheduler.schedule(
        task_type="whatsapp_send",
        task_kwargs=kwargs,
        delay_seconds=delay_seconds,
        max_retries=max_retries,
    )


# ---------------- optional: accurate "failed" status for permanent errors ----------------
#
# As written, a permanent WhatsApp error results in the ScheduledTask row ending up
# status="completed" (since _run_whatsapp_send returns normally instead of raising).
# That's a deliberate simplification to avoid touching your TaskScheduler class. If you
# want permanent failures to actually show status="failed" in the DB (e.g. for an admin
# dashboard), the smallest change is: pass the task_id through to the task function and
# update the row directly on permanent failure. That needs a one-line change in
# TaskScheduler.schedule() to inject the task's own id into task_kwargs after creation:
#
#     task = ScheduledTask.objects.create(...)
#     if task_type == "whatsapp_send":
#         task.task_kwargs = {**task.task_kwargs, "_task_id": str(task.id)}
#         task.save(update_fields=["task_kwargs"])
#
# and then in _run_whatsapp_send, pop `_task_id` out of send_kwargs before calling fn(),
# and on permanent failure do:
#     ScheduledTask.objects.filter(id=_task_id).update(
#         status="failed", error_message=str(exc), updated_at=timezone.now()
#     )
# Skip this unless you actually need the dashboard-visible distinction — the logger.error
# call already gives you a searchable record either way.