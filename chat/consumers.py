import json
import logging
from uuid import UUID

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError
from typing import Optional
from urllib.parse import parse_qs
from .notifications import notify_new_message


logger = logging.getLogger(__name__)

FACULTY_ROLE = "faculty"


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

        # await self._set_user_online(self.room_id, str(self.user.id))
        # # --- Broadcast presence: user is online ---
        # await self.channel_layer.group_send(
        #     self.room_group_name,
        #     {
        #         "type":      "chat.presence",
        #         "user_id":   str(self.user.id),
        #         "full_name": getattr(self.user, "name", ""),
        #         "is_online": True,
        #     },
        # )

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

        # Mark all messages as read when user joins/opens the chat room.
        # This removes them from the unread count (see ChatRoom.get_unread_count).
        await self._mark_all_messages_read(self.room_id, self.user)
        new_count = await self._get_unread_count(self.room_id, self.user)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type":         "chat.all_read",
                "user_id":      str(self.user.id),
                "room_id":      self.room_id,
                "unread_count": new_count,
            },
        )

        # Also broadcast unread_update so sidebar/room-list can refresh badge immediately
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type":        "chat.unread_update",
                "room_id":     self.room_id,
                "user_id":     str(self.user.id),
                "unread_count": new_count,
            },
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    # async def disconnect(self, close_code):
    #     if self.user:
    #         await self._set_user_offline(self.room_id, str(self.user.id))
    #         await self.channel_layer.group_send(
    #             self.room_group_name,
    #             {
    #                 "type":      "chat.presence",
    #                 "user_id":   str(self.user.id),
    #                 "full_name": getattr(self.user, "name", ""),
    #                 "is_online": False,
    #             },
    #         )
    #     await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

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
            "ping":           self._handle_ping,
            "send_message":   self._handle_send_message,
            "typing_start":   self._handle_typing_start,
            "typing_stop":    self._handle_typing_stop,
            "mark_read":      self._handle_mark_read,
            "mark_all_read":  self._handle_mark_all_read,
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

    async def _handle_ping(self, data: dict):
        await self.send(text_data=json.dumps({"type": "pong"}))

    async def _handle_send_message(self, data: dict):
        content   = data.get("content", "")
        file_url  = data.get("file_url")
        file_name = data.get("file_name")
        file_size = data.get("file_size")
        target_user_ids = data.get("target_user_ids") or data.get("target_user_id")
        # If the REST API already created the message, the frontend can pass
        # the message_id to avoid a duplicate DB insert.
        existing_message_id = data.get("message_id")

        if not content and not file_url:
            await self._send_error("EMPTY_MESSAGE", "Message must contain content or a file attachment.")
            return

        # Normalize target_user_ids to list for many-to-many support
        if isinstance(target_user_ids, str):
            if "," in target_user_ids:
                target_user_ids = [x.strip() for x in target_user_ids.split(",") if x.strip()]
            else:
                target_user_ids = [target_user_ids]
        if not isinstance(target_user_ids, list):
            target_user_ids = [target_user_ids] if target_user_ids else []
        target_user_ids = [str(tid).strip() for tid in target_user_ids if str(tid).strip()]

        if existing_message_id:
            # Message was already saved via REST POST — just broadcast, don't save again.
            # (e.g. after using the /upload/ + messages POST flow)
            targets_data = []
            for tid in target_user_ids:
                targets_data.append({
                    "id": str(tid),
                    "full_name": data.get("target_name", ""),
                    "role": data.get("target_role", ""),
                })
            message_data = {
                "id":         str(existing_message_id),
                "room_id":    self.room_id,
                "sender": {
                    "id":        str(self.user.id),
                    "full_name": getattr(self.user, "name", ""),
                    "avatar_url": getattr(self.user, "avatar_url", None) or "",
                },
                "targets":    targets_data,
                "content":    content,
                "file_url":   file_url or "",
                "file_name":  file_name or "",
                "file_size":  file_size,
                "created_at": data.get("created_at", timezone.now().isoformat()),
                "delivered_at": None,
                "read_at":      None,
            }
        else:
            # No existing message — save to DB first, then broadcast.
            try:
                message = await self._save_message(
                    room_id=self.room_id,
                    sender=self.user,
                    content=content,
                    file_url=file_url,
                    file_name=file_name,
                    file_size=file_size,
                    target_user_ids=target_user_ids,
                )
            except Exception as exc:
                logger.exception("Failed to save message in room %s", self.room_id)
                await self._send_error("DB_ERROR", f"Could not save message: {exc}")
                return

            # Rebuild targets_data from saved message safely using async helper
            targets_data = await self._get_message_targets_data(message)
            message_data = {
                "id":         str(message.id),
                "room_id":    self.room_id,
                "sender": {
                    "id":        str(self.user.id),
                    "full_name": getattr(self.user, "name", ""),
                    "avatar_url": getattr(self.user, "avatar_url", None) or "",
                },
                "targets":    targets_data,
                "content":    message.content,
                "file_url":   message.file_url or "",
                "file_name":  message.file_name or "",
                "file_size":  message.file_size,
                "created_at": message.created_at.isoformat(),
                "delivered_at": None,
                "read_at":      None,
            }

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat.new_message",
                "message": message_data,
            },
        )

        # Fire push notifications — now filtered for targeted messages (see notifications.py)
        room_participant_ids = await self._get_room_participant_ids(self.room_id)
        recipient_ids = [uid for uid in room_participant_ids if str(uid) != str(self.user.id)]
        notify_new_message(
            room_id=self.room_id,
            message_id=message_data["id"],
            sender_name=getattr(self.user, "name", "Someone"),
            content=content or "📎 Attachment",
            participant_ids=recipient_ids,
            target_user_ids=target_user_ids,
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

        # Compute new unread count so frontend can update badges immediately
        new_count = await self._get_unread_count(self.room_id, self.user)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type":         "chat.read_receipt",
                "message_id":   str(message_id),
                "user_id":      str(self.user.id),
                "read_at":      receipt.read_at.isoformat(),
                "unread_count": new_count,          # update on mark_read
            },
        )

        # Also send dedicated unread_update for room-list components
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type":        "chat.unread_update",
                "room_id":     self.room_id,
                "user_id":     str(self.user.id),
                "unread_count": new_count,
            },
        )

    async def _handle_mark_all_read(self, data: dict):
        """Handle explicit request from frontend to mark all messages in room as read."""
        await self._mark_all_messages_read(self.room_id, self.user)
        new_count = await self._get_unread_count(self.room_id, self.user)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type":         "chat.all_read",
                "user_id":      str(self.user.id),
                "room_id":      self.room_id,
                "unread_count": new_count,
            },
        )

        # Also broadcast a dedicated unread_update so room-list components
        # can react uniformly (whether single or bulk read).
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type":        "chat.unread_update",
                "room_id":     self.room_id,
                "user_id":     str(self.user.id),
                "unread_count": new_count,
            },
        )


    async def _handle_edit_message(self, data: dict):
        message_id = data.get("message_id")
        new_content = data.get("content", "").strip()

        if not message_id:
            await self._send_error("MISSING_FIELD", "'message_id' is required.")
            return
        if not new_content:
            await self._send_error("MISSING_FIELD", "'content' is required.")
            return

        try:
            UUID(message_id)
        except (ValueError, AttributeError):
            await self._send_error("INVALID_UUID", "'message_id' is not a valid UUID.")
            return

        updated = await self._update_message(message_id, self.user, new_content)
        if not updated:
            await self._send_error("FORBIDDEN", "Message not found or you are not the sender.")
            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type":       "chat.message_updated",
                "message_id": message_id,
                "content":    new_content,
            },
        )


    async def _handle_delete_message(self, data: dict):
        message_id = data.get("message_id")

        if not message_id:
            await self._send_error("MISSING_FIELD", "'message_id' is required.")
            return

        try:
            UUID(message_id)
        except (ValueError, AttributeError):
            await self._send_error("INVALID_UUID", "'message_id' is not a valid UUID.")
            return

        deleted = await self._delete_message(message_id, self.user)
        if not deleted:
            await self._send_error("FORBIDDEN", "Message not found or you are not the sender.")
            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type":       "chat.message_deleted",
                "message_id": message_id,
                "content":    "This message was deleted", 
                "is_deleted": True,   
            },
        )

        

    # ------------------------------------------------------------------
    # Outbound handlers
    # ------------------------------------------------------------------

    async def chat_new_message(self, event):
        # Skip echoing the message back to the sender to prevent duplicates
        # on the frontend (the sender already adds the message locally).
        msg = event["message"]
        if self.user and str(self.user.id) == msg.get("sender", {}).get("id"):
            return

        # Privacy filter for targeted messages (now supports *multiple* targets via m2m).
        # Only sender, any listed target, and super_admin receive the WS event.
        targets = msg.get("targets", [])
        if targets:
            user_role = getattr(self.user, 'role', None)
            user_id_str = str(self.user.id)
            sender_id = msg.get("sender", {}).get("id")
            target_ids = {
                str(t.get("id")) for t in targets
                if isinstance(t, dict) and t.get("id")
            }
            if user_role != 'super_admin' and user_id_str != sender_id and user_id_str not in target_ids:
                return  # do not deliver to other group members

        await self.send(text_data=json.dumps({
            "type":    "new_message",
            "message": msg,
        }))

    async def chat_typing(self, event):
        await self.send(text_data=json.dumps({
            "type":      "typing",
            "user_id":   event["user_id"],
            "full_name": event["full_name"],
            "is_typing": event["is_typing"],
        }))

    async def chat_read_receipt(self, event):
        """Send read receipt + updated unread count (so frontend can update badges on mark_read)."""
        await self.send(text_data=json.dumps({
            "type":         "read_receipt",
            "message_id":   event["message_id"],
            "user_id":      event["user_id"],
            "read_at":      event["read_at"],
            "unread_count": event.get("unread_count", 0),
        }))

    async def chat_all_read(self, event):
        """Broadcast that a user has marked all messages in this room as read.
        Frontend can use this to clear unread badge/count for the room.
        """
        await self.send(text_data=json.dumps({
            "type":         "all_messages_read",
            "user_id":      event["user_id"],
            "room_id":      event.get("room_id"),
            "unread_count": event.get("unread_count", 0),
        }))

    async def chat_unread_update(self, event):
        """Send real-time update of unread count for this room (used by room list/sidebar)."""
        await self.send(text_data=json.dumps({
            "type":         "unread_update",
            "room_id":      event["room_id"],
            "user_id":      event["user_id"],
            "unread_count": event["unread_count"],
        }))

    # ITEM-2 — new outbound handler
    async def chat_delivered_receipt(self, event):
        await self.send(text_data=json.dumps({
            "type":         "delivered_receipt",
            "message_id":   event["message_id"],
            "user_id":      event["user_id"],
            "delivered_at": event["delivered_at"],
        }))

    async def chat_message_updated(self, event):
        await self.send(text_data=json.dumps({
            "type":       "message_updated",
            "message_id": event["message_id"],
            "content":    event["content"],
        }))

    async def chat_message_deleted(self, event):
        await self.send(text_data=json.dumps({
            "type":       "message_deleted",
            "message_id": event["message_id"],
            "content":    event["content"],   
            "is_deleted": event["is_deleted"],   
        }))

    # async def chat_presence(self, event):
    #     await self.send(text_data=json.dumps({
    #         "type":      "presence",
    #         "user_id":   event["user_id"],
    #         "full_name": event["full_name"],
    #         "is_online": event["is_online"],
    #     }))

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
    # Take this synchronous database query and safely run it in a background thread so it doesn't freeze the main asynchronous WebSocket loop
    @database_sync_to_async
    def _get_message_targets_data(self, message) -> list:
        targets_data = []
        if hasattr(message, "targets") and message.targets.exists():
            for tgt in message.targets.all():
                targets_data.append({
                    "id": str(tgt.id),
                    "full_name": getattr(tgt, "name", ""),
                    "role": getattr(tgt, "role", ""),
                })
        return targets_data

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
    def _get_room_participant_ids(self, room_id: str) -> list:
        """Return list of participant user IDs (as strings) in the room."""
        from .models import ChatRoom
        try:
            room = ChatRoom.objects.prefetch_related('participants').get(id=room_id)
            return [str(u.id) for u in room.participants.all()]
        except ChatRoom.DoesNotExist:
            return []

    @database_sync_to_async
    def _save_message(self, *, room_id, sender, content, file_url, file_name, file_size, target_user_ids=None):
        from .models import Message, ChatRoom
        from django.contrib.auth import get_user_model
        User = get_user_model()
        targets = []
        if target_user_ids:
            try:
                target_user_ids = [tid for tid in target_user_ids if tid]
                targets = list(User.objects.filter(id__in=target_user_ids))
                # Verify all are participants (basic check)
                room = ChatRoom.objects.get(id=room_id)
                participant_ids = set(str(p.id) for p in room.participants.all())
                if not all(str(t.id) in participant_ids for t in targets):
                    targets = []  # fallback to no targets if any invalid
            except (User.DoesNotExist, ChatRoom.DoesNotExist, ValueError, TypeError):
                targets = []

        message = Message.objects.create(
            room_id=room_id,
            sender=sender,
            content=content or "",
            file_url=file_url,
            file_name=file_name,
            file_size=file_size,
        )
        if targets:
            message.targets.set(targets)
        return message

    @database_sync_to_async
    def _create_read_receipt(self, message_id: str, user):
        from .models import MessageReadReceipt
        receipt, created = MessageReadReceipt.objects.get_or_create(
            message_id=message_id,
            user=user,
            defaults={"read_at": timezone.now()},
        )
        return receipt if created else None

    @database_sync_to_async
    def _mark_all_messages_read(self, room_id: str, user):
        """
        Bulk mark all *visible* unread messages in the room as read for this user.
        Called automatically on WebSocket connect() — opening a chat clears its
        unread count (see ChatRoom.get_unread_count() and get_visible_messages_qs()).
        Uses bulk_create for performance with many unread messages.
        """
        from .models import ChatRoom, MessageReadReceipt
        from django.utils import timezone
        from django.db.models import Q

        try:
            room = ChatRoom.objects.get(id=room_id, is_active=True)
        except ChatRoom.DoesNotExist:
            return 0

        # Reuse the model's visibility logic (respects targeted messages, soft deletes, etc.)
        visible_qs = room.get_visible_messages_qs(user)
        unread_ids = list(visible_qs.filter(
            ~Q(read_receipts__user=user),
            ~Q(sender=user),
        ).values_list("id", flat=True))

        if not unread_ids:
            return 0

        now = timezone.now()
        receipts = [
            MessageReadReceipt(
                message_id=msg_id,
                user=user,
                read_at=now,
            )
            for msg_id in unread_ids
        ]
        # ignore_conflicts=True prevents errors if receipt created concurrently by another connection
        MessageReadReceipt.objects.bulk_create(receipts, ignore_conflicts=True)
        return len(unread_ids)  # number of messages we marked read

    @database_sync_to_async
    def _get_unread_count(self, room_id: str, user):
        """Return current unread count for this user in the room (uses model logic)."""
        from .models import ChatRoom
        try:
            room = ChatRoom.objects.get(id=room_id, is_active=True)
            return room.get_unread_count(user)
        except ChatRoom.DoesNotExist:
            return 0

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
    def _update_message(self, message_id: str, user, new_content: str) -> bool:
        from .models import Message
        updated = Message.objects.filter(
            id=message_id,
            sender=user,        # only sender can edit
        ).update(content=new_content, updated_at=timezone.now())
        return updated > 0


    @database_sync_to_async
    def _delete_message(self, message_id: str, user) -> bool:
        from .models import Message
        updated = Message.objects.filter(
            id=message_id,
            sender=user,
        ).update(is_deleted=True, updated_at=timezone.now())
        return updated > 0
    
    # @database_sync_to_async
    # def _set_user_online(self, room_id: str, user_id: str):
    #     from django.core.cache import cache
    #     key = f"online_{room_id}_{user_id}"
    #     cache.set(key, True, timeout=None)

    # @database_sync_to_async
    # def _set_user_offline(self, room_id: str, user_id: str):
    #     from django.core.cache import cache
    #     key = f"online_{room_id}_{user_id}"
    #     cache.delete(key)
    # @database_sync_to_async
    # def _dispatch_notification_task(self, *, room_id, message_id, sender_id):
    #     from .tasks import notify_new_chat_message
    #     notify_new_chat_message.delay(room_id, message_id, sender_id)


# ======================================================================
# Module-level helpers
# ======================================================================

def _parse_token(query_string: str) -> Optional[str]:
    params = parse_qs(query_string)
    tokens = params.get("token")
    return tokens[0] if tokens else None