import json
import logging
from uuid import UUID

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError

logger = logging.getLogger(__name__)

FACULTY_ROLE = "faculty"  # ← change if your role field uses a different value


class ChatConsumer(AsyncWebsocketConsumer):

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self):
        self.room_id = str(self.scope["url_route"]["kwargs"]["room_id"])
        self.room_group_name = f"room_{self.room_id}"
        self.user = None

        # --- JWT auth ---
        query_string = self.scope.get("query_string", b"").decode("utf-8")
        token_str = _parse_token(query_string)

        if not token_str:
            await self.close(code=4001)
            return

        user = await self._authenticate_token(token_str)
        if user is None:
            await self.close(code=4001)
            return

        self.user = user

        # --- Room membership ---
        is_participant = await self._is_room_participant(self.room_id, self.user.id)
        if not is_participant:
            await self.close(code=4003)
            return

        # --- BR-011: Faculty cannot join direct rooms ---
        user_role = getattr(self.user, "role", None)
        if user_role == FACULTY_ROLE:
            room_type = await self._get_room_type(self.room_id)
            if room_type == "direct":
                await self.close(code=4003)
                return

        # --- Join channel group ---
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        # --- ITEM-2: Mark undelivered messages as delivered on connect ---
        await self._mark_messages_delivered(self.room_id, self.user)
        delivered_msgs = await self._get_newly_delivered_messages(self.room_id, self.user)
        for msg in delivered_msgs:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat.delivered_receipt",
                    "message_id": str(msg["id"]),
                    "user_id": str(self.user.id),
                    "delivered_at": msg["delivered_at"].isoformat(),
                },
            )

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    # ------------------------------------------------------------------
    # Inbound dispatcher
    # ------------------------------------------------------------------

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data)
        except (json.JSONDecodeError, TypeError):
            await self._send_error("INVALID_JSON", "Payload is not valid JSON.")
            return

        event_type = data.get("type")
        handler_map = {
            "send_message":   self._handle_send_message,
            "typing_start":   self._handle_typing_start,
            "typing_stop":    self._handle_typing_stop,
            "mark_read":      self._handle_mark_read,
            "edit_message":   self._handle_edit_message,
            "delete_message": self._handle_delete_message,
        }

        handler = handler_map.get(event_type)
        if handler is None:
            await self._send_error("UNKNOWN_EVENT", f"Event type '{event_type}' is not recognised.")
            return

        await handler(data)

    # ------------------------------------------------------------------
    # Inbound handlers
    # ------------------------------------------------------------------

    async def _handle_send_message(self, data: dict):
        content   = data.get("content", "")
        file_url  = data.get("file_url")
        file_name = data.get("file_name")
        file_size = data.get("file_size")

        if not content and not file_url:
            await self._send_error("EMPTY_MESSAGE", "Message must contain content or a file attachment.")
            return

        try:
            message = await self._save_message(
                room_id=self.room_id,
                sender=self.user,
                content=content,
                file_url=file_url,
                file_name=file_name,
                file_size=file_size,
            )
        except Exception as exc:
            logger.exception("Failed to save message in room %s", self.room_id)
            await self._send_error("DB_ERROR", f"Could not save message: {exc}")
            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat.new_message",
                "message": {
                    "id":         str(message.id),
                    "room_id":    self.room_id,
                    "sender": {
                        "id":        str(self.user.id),
                        "full_name": getattr(self.user, "name", ""),
                        "avatar_url": getattr(self.user, "avatar_url", None) or "",
                    },
                    "content":    message.content,
                    "file_url":   message.file_url or "",
                    "file_name":  message.file_name or "",
                    "file_size":  message.file_size,
                    "created_at": message.created_at.isoformat(),
                    # tick states
                    "delivered_at": None,   # will update via delivered_receipt
                    "read_at":      None,   # will update via read_receipt
                },
            },
        )

        await self._dispatch_notification_task(
            room_id=self.room_id,
            message_id=str(message.id),
            sender_id=str(self.user.id),
        )

    async def _handle_typing_start(self, _data: dict):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type":      "chat.typing",
                "user_id":   str(self.user.id),
                "full_name": getattr(self.user, "name", ""),
                "is_typing": True,
            },
        )

    async def _handle_typing_stop(self, _data: dict):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type":      "chat.typing",
                "user_id":   str(self.user.id),
                "full_name": getattr(self.user, "name", ""),
                "is_typing": False,
            },
        )

    async def _handle_mark_read(self, data: dict):
        message_id = data.get("message_id")
        if not message_id:
            await self._send_error("MISSING_FIELD", "'message_id' is required.")
            return

        try:
            UUID(message_id)
        except (ValueError, AttributeError):
            await self._send_error("INVALID_UUID", "'message_id' is not a valid UUID.")
            return

        receipt = await self._create_read_receipt(message_id, self.user)
        if receipt is None:
            return  # already read — silently succeed

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type":       "chat.read_receipt",
                "message_id": str(message_id),
                "user_id":    str(self.user.id),
                "read_at":    receipt.read_at.isoformat(),
            },
        )

    async def _handle_edit_message(self, data: dict):
        """
        Inbound: { "type": "edit_message", "message_id": "<uuid>", "content": "new text" }
        Saves the new content to DB (sender only, not deleted).
        Broadcasts message_edited to the whole room.
        """
        message_id  = data.get("message_id")
        new_content = (data.get("content") or "").strip()

        if not message_id or not new_content:
            await self._send_error("MISSING_FIELD", "'message_id' and 'content' are required.")
            return

        result = await self._edit_message(message_id, self.user, new_content)

        if result == "not_found":
            await self._send_error("NOT_FOUND", "Message not found.")
        elif result == "forbidden":
            await self._send_error("FORBIDDEN", "You can only edit your own messages.")
        elif result == "deleted":
            await self._send_error("DELETED", "Cannot edit a deleted message.")
        else:
            # result is the updated Message instance
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type":       "chat.message_edited",
                    "message_id": str(result.id),
                    "room_id":    self.room_id,
                    "content":    result.content,
                    "updated_at": result.updated_at.isoformat(),
                    "edited_by":  str(self.user.id),
                },
            )

    async def _handle_delete_message(self, data: dict):
        """
        Inbound: { "type": "delete_message", "message_id": "<uuid>" }
        Soft-deletes the message (sender only):
          - sets is_deleted = True
          - replaces content with 'This message was deleted'
          - clears file fields
        Broadcasts message_deleted to the whole room.
        """
        message_id = data.get("message_id")
        if not message_id:
            await self._send_error("MISSING_FIELD", "'message_id' is required.")
            return

        result = await self._soft_delete_message(message_id, self.user)

        if result == "not_found":
            await self._send_error("NOT_FOUND", "Message not found.")
        elif result == "forbidden":
            await self._send_error("FORBIDDEN", "You can only delete your own messages.")
        else:
            # result is the updated Message instance
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type":       "chat.message_deleted",
                    "message_id": str(result.id),
                    "room_id":    self.room_id,
                    "content":    result.content,   # 'This message was deleted'
                    "is_deleted": True,
                    "updated_at": result.updated_at.isoformat(),
                    "deleted_by": str(self.user.id),
                },
            )

    # ------------------------------------------------------------------
    # Outbound handlers
    # ------------------------------------------------------------------

    async def chat_new_message(self, event):
        await self.send(text_data=json.dumps({
            "type":    "new_message",
            "message": event["message"],
        }))

    async def chat_typing(self, event):
        await self.send(text_data=json.dumps({
            "type":      "typing",
            "user_id":   event["user_id"],
            "full_name": event["full_name"],
            "is_typing": event["is_typing"],
        }))

    async def chat_read_receipt(self, event):
        await self.send(text_data=json.dumps({
            "type":       "read_receipt",
            "message_id": event["message_id"],
            "user_id":    event["user_id"],
            "read_at":    event["read_at"],
        }))

    # ITEM-2 — delivered_receipt outbound handler
    async def chat_delivered_receipt(self, event):
        await self.send(text_data=json.dumps({
            "type":         "delivered_receipt",
            "message_id":   event["message_id"],
            "user_id":      event["user_id"],
            "delivered_at": event["delivered_at"],
        }))

    async def chat_message_edited(self, event):
        """Relay message_edited event to the WebSocket client."""
        await self.send(text_data=json.dumps({
            "type":       "message_edited",
            "message_id": event["message_id"],
            "room_id":    event["room_id"],
            "content":    event["content"],
            "updated_at": event["updated_at"],
            "edited_by":  event["edited_by"],
        }))

    async def chat_message_deleted(self, event):
        """Relay message_deleted event to the WebSocket client."""
        await self.send(text_data=json.dumps({
            "type":       "message_deleted",
            "message_id": event["message_id"],
            "room_id":    event["room_id"],
            "content":    event["content"],    # 'This message was deleted'
            "is_deleted": True,
            "updated_at": event["updated_at"],
            "deleted_by": event["deleted_by"],
        }))

    # ------------------------------------------------------------------
    # Error helper
    # ------------------------------------------------------------------

    async def _send_error(self, code: str, detail: str):
        await self.send(text_data=json.dumps({
            "type":   "error",
            "code":   code,
            "detail": detail,
        }))

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    @database_sync_to_async
    def _authenticate_token(self, token_str: str):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            validated = AccessToken(token_str)
            return User.objects.get(id=validated["user_id"])
        except (TokenError, User.DoesNotExist, KeyError):
            return None

    @database_sync_to_async
    def _is_room_participant(self, room_id: str, user_id) -> bool:
        from .models import ChatRoom
        return ChatRoom.objects.filter(id=room_id, participants__id=user_id).exists()

    @database_sync_to_async
    def _get_room_type(self, room_id: str) -> str:
        """BR-011 helper — returns room_type string."""
        from .models import ChatRoom
        try:
            return ChatRoom.objects.values_list("room_type", flat=True).get(id=room_id)
        except ChatRoom.DoesNotExist:
            return ""

    @database_sync_to_async
    def _save_message(self, *, room_id, sender, content, file_url, file_name, file_size):
        from .models import Message
        return Message.objects.create(
            room_id=room_id,
            sender=sender,
            content=content or "",
            file_url=file_url,
            file_name=file_name,
            file_size=file_size,
        )

    @database_sync_to_async
    def _create_read_receipt(self, message_id: str, user):
        from .models import MessageReadReceipt
        receipt, created = MessageReadReceipt.objects.get_or_create(
            message_id=message_id,
            user=user,
            defaults={"read_at": timezone.now()},
        )
        return receipt if created else None

    # ITEM-2 — new delivered helpers
    @database_sync_to_async
    def _mark_messages_delivered(self, room_id: str, user):
        """
        Mark all undelivered messages in this room (not sent by this user)
        as delivered now that the user has connected.
        """
        from .models import Message
        Message.objects.filter(
            room_id=room_id,
            delivered_at__isnull=True,
        ).exclude(sender=user).update(delivered_at=timezone.now())

    @database_sync_to_async
    def _get_newly_delivered_messages(self, room_id: str, user):
        """
        Return messages that were just marked delivered (last 5 seconds)
        so we can broadcast delivered_receipt events.
        """
        from .models import Message
        from django.utils import timezone
        import datetime

        cutoff = timezone.now() - datetime.timedelta(seconds=5)
        return list(
            Message.objects.filter(
                room_id=room_id,
                delivered_at__gte=cutoff,
            ).exclude(sender=user)
            .values("id", "delivered_at")
            .order_by("-created_at")[:50]
        )

    @database_sync_to_async
    def _dispatch_notification_task(self, *, room_id, message_id, sender_id):
        """
        Run the push-notification logic synchronously (no Celery/Redis required).
        Errors are logged but never propagated so a notification failure
        cannot crash the WebSocket consumer.
        """
        from .tasks import notify_new_chat_message
        try:
            notify_new_chat_message(room_id, message_id, sender_id)
        except Exception:
            logger.exception(
                "notify_new_chat_message failed for message %s in room %s.",
                message_id, room_id,
            )

    @database_sync_to_async
    def _edit_message(self, message_id: str, user, new_content: str):
        """
        Update the content of a message.

        Returns:
            Message instance on success.
            'not_found'  if the message does not exist in this room.
            'forbidden'  if the user is not the sender.
            'deleted'    if the message has already been soft-deleted.
        """
        from .models import Message
        try:
            message = Message.objects.get(id=message_id, room_id=self.room_id)
        except Message.DoesNotExist:
            return "not_found"

        if str(message.sender_id) != str(user.id):
            return "forbidden"

        if message.is_deleted:
            return "deleted"

        message.content = new_content
        message.save(update_fields=["content", "updated_at"])
        return message

    @database_sync_to_async
    def _soft_delete_message(self, message_id: str, user):
        """
        Soft-delete a message: sets is_deleted=True, replaces content
        with the placeholder, and clears file fields.

        Returns:
            Message instance on success (already deleted counts as success).
            'not_found'  if the message does not exist in this room.
            'forbidden'  if the user is not the sender.
        """
        from .models import Message
        try:
            message = Message.objects.get(id=message_id, room_id=self.room_id)
        except Message.DoesNotExist:
            return "not_found"

        if str(message.sender_id) != str(user.id):
            return "forbidden"

        if not message.is_deleted:
            message.is_deleted = True
            message.content    = Message.DELETED_TEXT
            message.file_url   = None
            message.file_name  = None
            message.file_size  = None
            message.save(update_fields=["is_deleted", "content", "file_url", "file_name", "file_size", "updated_at"])

        return message



# ======================================================================
# Module-level helpers
# ======================================================================

def _parse_token(query_string: str) -> str | None:
    from urllib.parse import parse_qs
    params = parse_qs(query_string)
    tokens = params.get("token")
    return tokens[0] if tokens else None