"""
chat/notifications.py

Push notification helper using Firebase Cloud Messaging (FCM) HTTP v1 API.
Uses a Service Account JSON file for authentication (no legacy server key needed).

Setup:
1. Firebase Console → Project Settings → Service accounts tab
2. Click "Generate new private key" → download the JSON file
3. Save the file as `firebase_service_account.json` inside the Insight/ project folder
   (same folder as manage.py)
4. Add to your .env:
       FIREBASE_SERVICE_ACCOUNT_PATH=/absolute/path/to/firebase_service_account.json
   OR just place it as Insight/firebase_service_account.json (auto-detected)
"""
import json
import logging
import os
import threading
from typing import Optional

import requests
from django.conf import settings
from django.db.models import Q

logger = logging.getLogger(__name__)

_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


def _get_access_token() -> Optional[str]:
    """
    Obtain a short-lived OAuth2 access token from the service account credentials.
    Uses google-auth library (pip install google-auth).
    """
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests as google_requests

        # Resolve the service account JSON path
        sa_path = getattr(settings, 'FIREBASE_SERVICE_ACCOUNT_PATH', None) or \
                  os.environ.get('FIREBASE_SERVICE_ACCOUNT_PATH', '')

        # Auto-detect: look for the file next to manage.py
        if not sa_path:
            base_dir = getattr(settings, 'BASE_DIR', None)
            if base_dir:
                auto_path = os.path.join(str(base_dir), 'insightServicesSdk.json')
                if os.path.exists(auto_path):
                    sa_path = auto_path

        if not sa_path or not os.path.exists(sa_path):
            logger.warning(
                "FCM: firebase_service_account.json not found. "
                "Set FIREBASE_SERVICE_ACCOUNT_PATH in .env or place the file next to manage.py."
            )
            return None

        credentials = service_account.Credentials.from_service_account_file(
            sa_path,
            scopes=[_FCM_SCOPE],
        )
        credentials.refresh(google_requests.Request())
        return credentials.token

    except Exception as exc:
        logger.error("FCM: Failed to obtain access token: %s", exc)
        return None


def _get_project_id() -> Optional[str]:
    """Read project_id from the service account JSON file."""
    sa_path = getattr(settings, 'FIREBASE_SERVICE_ACCOUNT_PATH', None) or \
              os.environ.get('FIREBASE_SERVICE_ACCOUNT_PATH', '')

    if not sa_path:
        base_dir = getattr(settings, 'BASE_DIR', None)
        if base_dir:
            auto_path = os.path.join(str(base_dir), 'insightServicesSdk.json')
            if os.path.exists(auto_path):
                sa_path = auto_path

    if sa_path and os.path.exists(sa_path):
        try:
            with open(sa_path) as f:
                data = json.load(f)
            return data.get('project_id')
        except Exception:
            pass
    return None


def send_fcm_notification(*, token: str, title: str, body: str, data: dict = None, user_id=None):
    """
    Send a push notification to a single FCM device token using the HTTP v1 API.
    Also saves a record in NotificationHistory.
    """
    if user_id:
        try:
            from auth_user.models import NotificationHistory
            NotificationHistory.objects.create(
                user_id=user_id,
                title=title,
                body=body,
                data=data or {}
            )
        except Exception as e:
            logger.error("FCM: Failed to save notification history: %s", e)

    if not token:
        return

    access_token = _get_access_token()
    if not access_token:
        return  # Warning already logged inside _get_access_token

    project_id = _get_project_id()
    if not project_id:
        logger.warning("FCM: Could not determine Firebase project_id.")
        return

    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

    payload = {
        "message": {
            "token": token,
            "notification": {
                "title": title,
                "body": body,
            },
            "data": {str(k): str(v) for k, v in (data or {}).items()},
            "android": {
                "priority": "high",
                "notification": {
                    "sound": "default",
                    "channel_id": "insight_default",
                    "default_vibrate_timings": True,
                    "default_light_settings": True,
                    "notification_priority": "PRIORITY_HIGH",
                },
                "direct_boot_ok": True,
            },
            "apns": {
                "headers": {
                    "apns-priority": "10",
                    "apns-push-type": "alert",
                },
                "payload": {
                    "aps": {
                        "sound": "default",
                        "content-available": 1,
                        "mutable-content": 1,
                    }
                }
            },
        }
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=5,
        )
        if response.status_code == 200:
            logger.info("FCM: Notification sent to token %s...", token[:20])
        else:
            logger.warning("FCM: Send failed (%s): %s", response.status_code, response.text[:200])
    except requests.RequestException as exc:
        logger.error("FCM: Request error: %s", exc)


def notify_new_message(*, room_id: str, message_id: str, sender_name: str, content: str, participant_ids: list, target_user_ids: list = None, sender_id: str = None):
    """
    Send push notifications to relevant users. If target_user_ids are provided
    (multiple targets supported via m2m), only notify the targets + any super_admin
    (excluding the sender to avoid self-notifications). Otherwise notify all
    participants (except sender). Runs in background thread.
    Called from consumers.py and views.py after a message is saved.
    """
    def _send():
        from django.contrib.auth import get_user_model
        User = get_user_model()

        if target_user_ids and len([tid for tid in target_user_ids if tid]) > 0:
            # Targeted message: only notify the specific targets (exclude sender)
            target_ids = [tid for tid in target_user_ids if tid]
            q = Q(id__in=target_ids)
            if sender_id:
                q &= ~Q(id=sender_id)
            recipients = User.objects.filter(q).exclude(fcm_token='').values('id', 'name', 'fcm_token')
        else:
            # Normal group message: notify all participants (except sender)
            qs = User.objects.filter(id__in=participant_ids)
            if sender_id:
                qs = qs.exclude(id=sender_id)
            recipients = qs.exclude(fcm_token='').values('id', 'name', 'fcm_token')

        # Truncate long message previews
        preview = content[:100] + '...' if len(content) > 100 else content

        for user in recipients:
            send_fcm_notification(
                token=user['fcm_token'],
                title=sender_name,
                body=preview,
                data={
                    "type": "new_message",
                    "room_id": str(room_id),
                    "message_id": str(message_id),
                    "is_targeted": bool(target_user_ids),
                    "route": f"/chat/{str(room_id)}",
                },
                user_id=user['id']
            )

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()

#whatapp notifiation 
from core.utils import queue_whatsapp_media, queue_whatsapp_template, queue_whatsapp_text 

def send_whatsapp_text(*, to: str, body: str, delay_seconds: int = 0, user_id=None) -> Optional[str]:
    """Schedule a plain text WhatsApp message. Returns the ScheduledTask id
    (as a string) or None if `to` is empty. Mirrors send_fcm_notification's
    signature style."""
    if not to:
        return None
 
    task = queue_whatsapp_text(to=to, body=body, delay_seconds=delay_seconds)
    task_id = str(task.id) if task else None
 
    if user_id and task_id:
        _record_history(user_id=user_id, title="WhatsApp", body=body, task_id=task_id)
 
    return task_id
 
 
def send_whatsapp_template(*, to: str, template_name: str, language_code: str = "en_US",
                            components: list = None, delay_seconds: int = 0,
                            user_id=None) -> Optional[str]:
    """Schedule a template WhatsApp message (works outside the 24h session
    window, unlike send_whatsapp_text)."""
    if not to:
        return None
 
    task = queue_whatsapp_template(
        to=to, template_name=template_name, language_code=language_code,
        components=components, delay_seconds=delay_seconds,
    )
    task_id = str(task.id) if task else None
 
    if user_id and task_id:
        _record_history(
            user_id=user_id, title="WhatsApp template", body=template_name, task_id=task_id
        )
 
    return task_id
 
 
def send_whatsapp_media(*, to: str, media_type: str, link: str = None, media_id: str = None,
                         caption: str = None, filename: str = None,
                         delay_seconds: int = 0, user_id=None) -> Optional[str]:
    if not to:
        return None
 
    task = queue_whatsapp_media(
        to=to, media_type=media_type, link=link, media_id=media_id,
        caption=caption, filename=filename, delay_seconds=delay_seconds,
    )
    task_id = str(task.id) if task else None
 
    if user_id and task_id:
        _record_history(user_id=user_id, title="WhatsApp media", body=media_type, task_id=task_id)
 
    return task_id
 
 
def notify_new_message_whatsapp(*, room_id: str, sender_name: str, content: str,
                                 recipient_phone: str, recipient_user_id=None):
    """
    WhatsApp equivalent of notify_new_message() in notifications.py — call this
    alongside the FCM one, e.g. as a fallback channel for users without an
    fcm_token, or for users opted into WhatsApp alerts.
    """
    if not recipient_phone:
        return
 
    preview = content[:100] + "..." if len(content) > 100 else content
    send_whatsapp_text(
        to=recipient_phone,
        body=f"{sender_name}: {preview}",
        user_id=recipient_user_id,
    )
 
 
def _record_history(*, user_id, title: str, body: str, task_id: str):
    """Optional: log queued WhatsApp sends the same way NotificationHistory does
    for FCM, so you have one place to look up what was sent/attempted."""
    try:
        from auth_user.models import NotificationHistory
        NotificationHistory.objects.create(
            user_id=user_id,
            title=title,
            body=body,
            data={"channel": "whatsapp", "scheduled_task_id": task_id},
        )
    except Exception as e:
        logger.error("WhatsApp: failed to save notification history: %s", e)

def send_system_notification(
    user_id: str,
    title: str,
    body: str,
    metadata: dict = None,
    email_template: str = None,
    email_context: dict = None,
    email_subject: str = None,
    whatsapp_template: str = None,
    whatsapp_context: dict = None,
    whatsapp_template_lang_code: str = "en_US",
    delay_seconds: int = 0,
    whatsapp_media: dict = None
):
    """
    Centralized helper to send a push notification (FCM) and/or an email.
    If email_template is provided, it will send an email.
    If the user has an FCM token, it will send a push notification.
    """
    def _send_task():
        from django.contrib.auth import get_user_model
        from core.sender import send_email
        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            logger.warning("Notification failed: User %s not found.", user_id)
            return

        # 1. Send FCM Push Notification
        if getattr(user, 'fcm_token', None):
            send_fcm_notification(
                token=user.fcm_token,
                title=title,
                body=body,
                data=metadata or {},
                user_id=str(user.id)
            )

        # 2. Send Email Notification
        if email_template and getattr(user, 'email', None):
            subject = email_subject or title
            ctx = email_context or {}
            # Fallbacks for some basic context if not provided
            if 'user_name' not in ctx:
                ctx['user_name'] = user.name
                
            org = getattr(user, 'organization', None)
            
            try:
                send_email(
                    to=user.email,
                    subject=subject,
                    text=body,
                    template=email_template,
                    template_context=ctx,
                    organization=org,
                )
            except Exception as e:
                logger.error("Failed to send system email to %s: %s", user.email, e)


            try:
                if whatsapp_template and getattr(user, 'phone', None):
                    send_whatsapp_template(
                        to=user.phone,
                        template_name=whatsapp_template,
                        language_code= whatsapp_template_lang_code or 'en_US',
                        components=[{"type": "body", "parameters": [{"type": "text", "text": str(whatsapp_context.get(k, ''))} for k in whatsapp_context]}] if whatsapp_context else [],
                        user_id=str(user.id),
                        delay_seconds=delay_seconds or 0
                    )
                elif whatsapp_media and getattr(user, 'phone', None):
                    send_whatsapp_media(
                        to=user.phone,
                        media_type=whatsapp_media.get('media_type'),
                        link=whatsapp_media.get('link'),
                        media_id=whatsapp_media.get('media_id'),
                        caption=whatsapp_media.get('caption'),
                        filename=whatsapp_media.get('filename'),
                        user_id=str(user.id),
                        delay_seconds=delay_seconds or 0
                    )
                elif getattr(user, 'phone', None):
                    # Fallback: send plain text WhatsApp if no template is specified
                    send_whatsapp_text(to=user.phone, body=body, user_id=str(user.id))
            except Exception as e:
                logger.error("Failed to send WhatsApp notification to %s: %s", user.id, e)

    thread = threading.Thread(target=_send_task, daemon=True)
    thread.start()