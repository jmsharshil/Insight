"""
Push-notification helper for the chat module.

Runs synchronously (no Celery/Redis required).

"""

import logging

logger = logging.getLogger(__name__)


def notify_new_chat_message(room_id: str, message_id: str, sender_id: str):
    """
    Send push notifications to room participants excluding the sender.

    Runs as a plain function — no Celery worker or Redis broker required.
    Called directly from views.py and consumers.py after a message is saved.
    """
    from chat.models import ChatRoom, Message

    # --- Fetch room ---
    try:
        room = ChatRoom.objects.get(id=room_id)
    except ChatRoom.DoesNotExist:
        logger.error("notify_new_chat_message: room %s not found", room_id)
        return

    # --- Fetch message ---
    try:
        message = Message.objects.select_related("sender").get(id=message_id)
    except Message.DoesNotExist:
        logger.error("notify_new_chat_message: message %s not found", message_id)
        return

    # --- Participants excluding sender ---
    participants = room.participants.exclude(id=sender_id)
    if not participants.exists():
        return

    sender_name = getattr(message.sender, "name", "Someone")
    preview = (
        message.content[:100] if message.content
        else (message.file_name or "sent a file")
    )

    payload = {
        "title": f"New message from {sender_name}",
        "body":  preview,
        "data": {
            "type":       "chat_message",
            "room_id":    str(room_id),
            "message_id": str(message_id),
        },
    }

    for participant in participants:
        try:
            _send_push(participant, payload)
        except Exception:
            logger.exception(
                "Failed to notify user %s for message %s",
                participant.id,
                message_id,
            )


def _send_push(user, payload: dict):
    """
    Central push dispatcher with 3 fallback layers.

    Layer 1 — NotificationService (if notifications app installed)
    Layer 2 — Firebase Admin SDK  (uncomment when ready)
    Layer 3 — Placeholder log     (current active fallback)
    """

    # ------------------------------------------------------------------
    # Layer 1: NotificationService
    # ------------------------------------------------------------------
    try:
        from notifications.services import NotificationService
        NotificationService.send(
            user=user,
            title=payload["title"],
            body=payload["body"],
            data=payload["data"],
        )
        logger.debug("Push sent via NotificationService → user %s", user.id)
        return
    except ImportError:
        pass

    # ------------------------------------------------------------------
    # Layer 2: Firebase Admin SDK
    # Uncomment this block when you're ready to connect real FCM.
    #
    # Setup steps:
    #   pip install firebase-admin
    #   Add to settings.py:
    #     FIREBASE_CREDENTIALS = BASE_DIR / "serviceAccountKey.json"
    #   Add to your User model:
    #     fcm_token = models.CharField(max_length=255, blank=True, default="")
    #   Call firebase_admin.initialize_app() in apps.py ready() method
    # ------------------------------------------------------------------
    #
    # import firebase_admin.messaging as fcm
    # from django.conf import settings
    #
    # device_token = getattr(user, "fcm_token", None)
    # if device_token:
    #     try:
    #         fcm_message = fcm.Message(
    #             notification=fcm.Notification(
    #                 title=payload["title"],
    #                 body=payload["body"],
    #             ),
    #             data={k: str(v) for k, v in payload["data"].items()},
    #             token=device_token,
    #         )
    #         response = fcm.send(fcm_message)
    #         logger.debug("FCM push sent → user %s | response: %s", user.id, response)
    #         return
    #     except fcm.UnregisteredError:
    #         logger.warning("FCM token invalid for user %s — clearing token", user.id)
    #         type(user).objects.filter(pk=user.pk).update(fcm_token="")
    #     except Exception as exc:
    #         logger.exception("FCM send failed for user %s: %s", user.id, exc)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Layer 3: Placeholder log (active until Firebase is connected)
    # ------------------------------------------------------------------
    logger.info(
        "[PUSH PLACEHOLDER] → user_id=%s | title=%s | body=%s | data=%s",
        getattr(user, "id", "?"),
        payload["title"],
        payload["body"],
        payload["data"],
    )