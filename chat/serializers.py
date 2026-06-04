from rest_framework import serializers
from .models import ChatRoom, Message, MessageReadReceipt


class UserMiniSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    full_name = serializers.CharField(source="name", read_only=True)
    avatar_url = serializers.SerializerMethodField()

    def get_avatar_url(self, obj) -> str:
        return getattr(obj, "avatar_url", None) or ""


class ReadReceiptSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    read_at = serializers.DateTimeField(format="iso-8601", read_only=True)

    class Meta:
        model = MessageReadReceipt
        fields = ("user_id", "read_at")


class MessageSerializer(serializers.ModelSerializer):
    sender = UserMiniSerializer(read_only=True)
    read_receipts = ReadReceiptSerializer(many=True, read_only=True)
    created_at = serializers.DateTimeField(format="iso-8601", read_only=True)
    updated_at = serializers.DateTimeField(format="iso-8601", read_only=True)
    delivered_at = serializers.DateTimeField(format="iso-8601", read_only=True, allow_null=True)
    tick_status = serializers.SerializerMethodField()
    # File fields are masked to null when the message is soft-deleted
    file_url = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()
    file_size = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ("id","room","sender","content","is_deleted","file_url","file_name","file_size","created_at","updated_at","delivered_at","tick_status","read_receipts",)
        read_only_fields = ("id", "room", "sender", "created_at", "updated_at")

    def get_tick_status(self, obj) -> str:
        if obj.read_receipts.all():
            return "read"
        if obj.delivered_at is not None:
            return "delivered"
        return "sent"

    def get_file_url(self, obj):
        return None if obj.is_deleted else obj.file_url

    def get_file_name(self, obj):
        return None if obj.is_deleted else obj.file_name

    def get_file_size(self, obj):
        return None if obj.is_deleted else obj.file_size


class LastMessageSerializer(serializers.Serializer):
    sender_name = serializers.CharField()
    content     = serializers.CharField(allow_blank=True)
    file_name   = serializers.CharField(allow_blank=True, allow_null=True)
    created_at  = serializers.DateTimeField(format="iso-8601")


class ChatRoomSerializer(serializers.ModelSerializer):
    participants  = UserMiniSerializer(many=True, read_only=True)
    last_message  = serializers.SerializerMethodField()
    unread_count  = serializers.IntegerField(read_only=True, default=0)
    created_at    = serializers.DateTimeField(format="iso-8601", read_only=True)

    class Meta:
        model = ChatRoom
        fields = ("id","name","room_type","participants","created_at","last_message","unread_count",)

    def get_last_message(self, obj) -> dict | None:
        messages = obj.messages.order_by("-created_at")[:1]
        msg = messages[0] if messages else None
        if msg is None:
            return None
        return {
            "sender_name": getattr(msg.sender, "name", ""),
            "content":     msg.content,
            "file_name":   msg.file_name or "",
            "created_at":  msg.created_at.isoformat(),
            "tick_status": msg.tick_status,   # ITEM-2
        }