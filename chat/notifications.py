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
                "notification": {"sound": "default"},
            },
            "apns": {
                "payload": {
                    "aps": {"sound": "default"}
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
            # Targeted message: only notify the specific targets + super_admins (exclude sender)
            target_ids = [tid for tid in target_user_ids if tid]
            q = Q(id__in=target_ids) | Q(role='super_admin')
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
                },
                user_id=user['id']
            )

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()
