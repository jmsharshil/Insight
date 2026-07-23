import uuid

from django.conf import settings
from django.db import models
from django.db.models import Count, Q


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

    def get_visible_messages_qs(self, user):
        """Return queryset of non-deleted messages visible to this user (respects M2M `targets`)."""
        qs = self.messages.filter(is_deleted=False).select_related("sender")
        role = getattr(user, "role", None)
        if role != "super_admin":
            qs = qs.annotate(num_targets=Count("targets")).filter(
                # Normal messages or ones where user is sender or a target
                Q(num_targets=0) | Q(sender=user) | Q(targets=user)
            )
        return qs

    def get_last_visible_message(self, user):
        """Return the most recent message visible to the given user (for room list last_message)."""
        return self.get_visible_messages_qs(user).order_by("-created_at").first()

    def get_unread_count(self, user):
        """Count unread visible messages for this user (no read receipt + not sent by self)."""
        qs = self.get_visible_messages_qs(user)
        user_id = user.id
        return (
            qs.filter(
                ~Q(read_receipts__user_id=user_id),
                ~Q(sender_id=user_id),
            )
            .distinct()
            .count()
        )


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

class WhatsAppMessage(models.Model):
    """
    Persists inbound (and optionally outbound) WhatsApp messages
    received via the Meta Cloud API webhook.
    """

    DIRECTION_CHOICES = [
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wa_message_id = models.CharField(
        max_length=255, unique=True, db_index=True,
        help_text="Meta's wamid (WhatsApp message ID).",
    )
    sender_wa_id = models.CharField(
        max_length=20,
        help_text="Sender's WhatsApp ID (phone number without +).",
    )
    sender_name = models.CharField(max_length=255, blank=True, default='')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='whatsapp_messages',
        help_text="Matched system user (if phone is recognized).",
    )
    message_type = models.CharField(
        max_length=20, default='text',
        help_text="text, image, document, video, audio, location, interactive, button, reaction",
    )
    content = models.TextField(blank=True, default='')
    extra_data = models.JSONField(default=dict, blank=True, help_text="Media IDs, reply metadata, etc.")
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES, default='inbound')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'whatsapp_messages'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.direction}] {self.sender_wa_id} ({self.message_type}) @ {self.created_at}"
