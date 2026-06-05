"""
chat/tasks.py

Celery tasks for the chat module.

Currently contains the ``notify_new_chat_message`` task that sends push
notifications to room participants who are offline

"""

import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    acks_late=True,
    name="chat.notify_new_chat_message",
)
def notify_new_chat_message(self, room_id: str, message_id: str, sender_id: str):
    """
    Send push notifications to participants who are NOT currently
    online in the chat room.

    Steps:
      1. Fetch room participants excluding the sender.
      2. For every participant, delegate to
         ``NotificationService.send()`` if available, otherwise log.

    Parameters
    ----------
    room_id : str
        UUID of the chat room.
    message_id : str
        UUID of the newly created message.
    sender_id : str
        UUID of the user who sent the message.
    """
    from chat.models import ChatRoom, Message
    from django.contrib.auth import get_user_model

    User = get_user_model()

    try:
        room = ChatRoom.objects.get(id=room_id)
    except ChatRoom.DoesNotExist:
        logger.error("notify_new_chat_message: room %s not found", room_id)
        return

    try:
        message = Message.objects.select_related("sender").get(id=message_id)
    except Message.DoesNotExist:
        logger.error("notify_new_chat_message: message %s not found", message_id)
        return

    # Participants minus the sender
    participants = room.participants.exclude(id=sender_id)

    if not participants.exists():
        return

    # Since we are running without Redis online-status tracking,
    # we consider all other participants as targets for push notifications.
    offline_participants = list(participants)

    # Attempt to use NotificationService if it exists
    notification_service = _get_notification_service()

    sender_name = getattr(message.sender, "name", "Someone")
    preview = message.content[:100] if message.content else (message.file_name or "sent a file")

    for participant in offline_participants:
        try:
            if notification_service is not None:
                notification_service.send(
                    user=participant,
                    title=f"New message from {sender_name}",
                    body=preview,
                    data={
                        "type": "chat_message",
                        "room_id": str(room_id),
                        "message_id": str(message_id),
                    },
                )
            else:
                logger.info(
                    "[CHAT PUSH PLACEHOLDER] Notify user %s (%s): "
                    "New message from %s in room %s -- '%s'",
                    participant.id,
                    getattr(participant, "name", ""),
                    sender_name,
                    room_id,
                    preview,
                )
        except Exception:
            logger.exception(
                "Failed to notify user %s for message %s",
                participant.id,
                message_id,
            )


def _get_notification_service():
    """
    Try to import ``NotificationService`` from the notifications module.
    Returns the class if available, else ``None``.
    """
    try:
        from notifications.service import NotificationService
        return NotificationService
    except ImportError:
        return None
