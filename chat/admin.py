from django.contrib import admin
from django.utils.html import format_html

from .models import ChatRoom, Message, MessageReadReceipt

@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    """Admin view for ChatRoom."""

    list_display  = ("id", "name", "room_type", "is_active", "participant_count", "created_at")
    list_filter   = ("room_type", "is_active", "created_at")
    search_fields = ("id", "name", "direct_hash")
    readonly_fields = ("id", "direct_hash", "created_at")
    filter_horizontal = ("participants",)
    ordering = ("-created_at",)

    @admin.display(description="Participants")
    def participant_count(self, obj):
        count = obj.participants.count()
        return format_html("<b>{}</b>", count)

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """Admin view for Message."""

    list_display  = (
        "id", "room", "sender", "short_content",
        "has_file", "tick_status", "created_at",
    )
    list_filter   = ("created_at", "room__room_type")
    search_fields = ("id", "content", "sender__username", "sender__name", "room__name")
    readonly_fields = (
        "id", "room", "sender", "created_at", "updated_at",
        "delivered_at", "tick_status",
    )
    ordering = ("-created_at",)

    @admin.display(description="Content preview")
    def short_content(self, obj):
        if obj.content:
            return obj.content[:60] + ("…" if len(obj.content) > 60 else "")
        return format_html("<em style='color:#999'>—</em>")

    @admin.display(description="File?", boolean=True)
    def has_file(self, obj):
        return bool(obj.file_url)

    @admin.display(description="Tick status")
    def tick_status(self, obj):
        icons = {
            "read":      "✅ Read",
            "delivered": "✔✔ Delivered",
            "sent":      "✔ Sent",
        }
        return icons.get(obj.tick_status, obj.tick_status)

@admin.register(MessageReadReceipt)
class MessageReadReceiptAdmin(admin.ModelAdmin):
    """Admin view for MessageReadReceipt."""

    list_display  = ("id", "message", "user", "read_at")
    list_filter   = ("read_at",)
    search_fields = ("message__id", "user__username", "user__name")
    readonly_fields = ("message", "user", "read_at")
    ordering = ("-read_at",)

    def has_add_permission(self, request):
        return False
