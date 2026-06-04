from django.db import models

# Create your models here.

import uuid

from django.conf import settings
from django.db import models


class ChatRoom(models.Model):
    ROOM_TYPE_CHOICES = (
        ("direct", "Direct"),
        ("group", "Group"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, blank=True, default="",help_text="Human-readable name (blank for direct rooms).",)
    room_type = models.CharField(max_length=10, choices=ROOM_TYPE_CHOICES)
    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="chat_rooms", blank=True,)
    direct_hash = models.CharField(max_length=100, blank=True, default="", unique=True,help_text="For direct rooms only: sorted user-UUID pair separated by '_'.",)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["room_type"])]

    def __str__(self) -> str:
        return self.name or f"Room {self.id}"

    @staticmethod
    def build_direct_hash(user_id_1, user_id_2) -> str:
        return "_".join(sorted([str(user_id_1), str(user_id_2)]))


class Message(models.Model):
    # Placeholder text shown to all clients when a message is soft-deleted.
    DELETED_TEXT = "This message was deleted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_messages",)
    content = models.TextField(blank=True, default="",help_text="Text body of the message (may be blank for file-only).",)
    file_url = models.URLField(max_length=1024, blank=True, null=True)
    file_name = models.CharField(max_length=255, blank=True, null=True)
    file_size = models.PositiveIntegerField(blank=True, null=True, help_text="File size in bytes.")
    # ---------------------------------------------------------------
    # Soft-delete flag
    # When True: content is replaced by DELETED_TEXT, file fields
    # are cleared, and the message is no longer editable.
    # ---------------------------------------------------------------
    is_deleted = models.BooleanField(default=False,help_text="Soft-delete flag. Content replaced by placeholder when True.",)
    # ---------------------------------------------------------------
    # created_at   → single tick  (sent)
    # delivered_at → double tick  (delivered to recipient's device)
    # read via MessageReadReceipt → filled tick (read)
    # ---------------------------------------------------------------
    delivered_at = models.DateTimeField(null=True, blank=True,help_text="Set when the recipient first connects after this message was sent.",)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["room", "-created_at"])]

    def __str__(self) -> str:
        if self.is_deleted:
            return f"Message {self.id} – [deleted]"
        preview = (self.content[:40] + "…") if len(self.content) > 40 else self.content
        return f"Message {self.id} – {preview or self.file_name or '(empty)'}"

    @property
    def tick_status(self) -> str:
        """Returns 'sent' | 'delivered' | 'read' for frontend convenience."""
        if self.read_receipts.exists():
            return "read"
        if self.delivered_at is not None:
            return "delivered"
        return "sent"


class MessageReadReceipt(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="read_receipts",)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="read_receipts",)
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user")

    def __str__(self) -> str:
        return f"Read by {self.user_id} at {self.read_at}"