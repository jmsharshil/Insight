from django.contrib import admin

from .models import ChatRoom, Message, MessageReadReceipt


@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "room_type", "created_at")
    list_filter = ("room_type",)
    search_fields = ("name", "id")
    readonly_fields = ("id", "direct_hash", "created_at")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "room", "sender", "short_content", "created_at")
    list_filter = ("created_at",)
    search_fields = ("content", "id")
    readonly_fields = ("id", "created_at", "updated_at")

    @admin.display(description="Content")
    def short_content(self, obj):
        if obj.content:
            return obj.content[:80]
        return obj.file_name or "(empty)"


@admin.register(MessageReadReceipt)
class MessageReadReceiptAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "user", "read_at")
    readonly_fields = ("read_at",)
