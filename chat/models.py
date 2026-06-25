import uuid

from django.conf import settings
from django.db import models


class ChatRoom(models.Model):
    """
    A conversation container. Two flavours:

    * **direct** – a private 1-on-1 chat between exactly two users.
    * **group** – a named channel with an arbitrary number of members.
    """

    ROOM_TYPE_CHOICES = (
        ("direct", "Direct"),
        ("group", "Group"),
    )

    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False,)
    name = models.CharField(max_length=255,blank=True,default="",help_text="Human-readable name (blank for direct rooms).",)
    avatar = models.ImageField(upload_to="chat/group_avatars/", blank=True, null=True, help_text="Group avatar image.")
    room_type = models.CharField(max_length=10,choices=ROOM_TYPE_CHOICES,)
    participants = models.ManyToManyField(settings.AUTH_USER_MODEL,related_name="chat_rooms",blank=True,)
    direct_hash = models.CharField(max_length=100,blank=True,default="",help_text=("For direct rooms only: sorted user-UUID pair ""separated by '_' to guarantee uniqueness."),)
    is_active = models.BooleanField(default=True)
    # IMPORTANT: Soft delete flag. When a room is deleted, is_active is set to False instead of deleting the record.
    # This preserves message history and audit trails. All views MUST filter by is_active=True to exclude
    # deleted rooms from listings and operations.
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["room_type"]),
        ]

    def __str__(self) -> str:
        return self.name or f"Room {self.id}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def build_direct_hash(user_id_1, user_id_2) -> str:
        """Return a deterministic slug for a two-user direct room."""
        return "_".join(sorted([str(user_id_1), str(user_id_2)]))


class Message(models.Model):
    """
    A single chat message. A message may contain text, an attached file,
    or both. At least one of ``content`` or ``file_url`` must be present
    (enforced at the application layer, not the DB layer).
    """

    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False,)
    room = models.ForeignKey(ChatRoom,on_delete=models.CASCADE,related_name="messages",)
    sender = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="sent_messages",)
    targets = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="targeted_messages",
        help_text="If set in a group room, this message is visible ONLY to: sender, any of the listed targets (e.g. specific faculty members), and super_admin. Normal group messages have no targets.",
    )
    content = models.TextField(blank=True,default="",help_text="Text body of the message (may be blank for file-only).",)
    file_url = models.URLField(max_length=1024,blank=True,null=True,help_text="URL of the uploaded attachment on S3.",)
    file_name = models.CharField(max_length=255,blank=True,null=True,)
    file_size = models.PositiveIntegerField(blank=True,null=True,help_text="File size in bytes.",)
    is_deleted = models.BooleanField(default=False, help_text="Soft delete flag.")
    delivered_at = models.DateTimeField(null=True, blank=True,help_text="Set when the recipient first connects after this message was sent.",)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["room", "-created_at"]),
        ]

    def __str__(self) -> str:
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
    """
    Tracks when a specific user read a specific message.
    The (message, user) pair is unique.
    """

    message = models.ForeignKey(Message,on_delete=models.CASCADE,related_name="read_receipts",)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="read_receipts",)
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user")

    def __str__(self) -> str:
        return f"Read by {self.user_id} at {self.read_at}"