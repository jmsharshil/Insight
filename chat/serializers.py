from rest_framework import serializers
from .models import ChatRoom, Message, MessageReadReceipt


class UserMiniSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    full_name = serializers.CharField(source="name", read_only=True)
    role = serializers.CharField(read_only=True)
    avatar_url = serializers.SerializerMethodField()

    def get_avatar_url(self, obj) -> str:
        """Return avatar URL or empty string if the user has no avatar."""
        if hasattr(obj, 'profile_pic') and obj.profile_pic:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_pic.url)
            return obj.profile_pic.url
        return getattr(obj, "avatar_url", None) or ""


class ReadReceiptSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    read_at = serializers.DateTimeField(format="iso-8601", read_only=True)

    class Meta:
        model = MessageReadReceipt
        fields = ("user_id", "read_at")


class MessageSerializer(serializers.ModelSerializer):
    sender = UserMiniSerializer(read_only=True)
    targets = UserMiniSerializer(many=True, read_only=True)
    read_receipts = ReadReceiptSerializer(many=True, read_only=True)
    created_at = serializers.DateTimeField(format="iso-8601", read_only=True)
    updated_at = serializers.DateTimeField(format="iso-8601", read_only=True)
    delivered_at  = serializers.DateTimeField(format="iso-8601", read_only=True, allow_null=True)
    tick_status   = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ("id","room","sender","targets","content","file_url","file_name","file_size","is_deleted","created_at","updated_at","delivered_at","tick_status", "read_receipts",)
        read_only_fields = ("id", "room", "sender", "targets", "created_at", "updated_at", "is_deleted")

    def get_tick_status(self, obj) -> str:
        if obj.read_receipts.all():
            return "read"
        if obj.delivered_at is not None:
            return "delivered"
        return "sent"

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if data.get('is_deleted'):
            data['content'] = "This message was deleted"
            data['file_url'] = None
            data['file_name'] = None
            data['file_size'] = None
        return data

class LastMessageSerializer(serializers.Serializer):
    sender_name = serializers.CharField()
    content = serializers.CharField(allow_blank=True)
    file_name = serializers.CharField(allow_blank=True, allow_null=True)
    created_at = serializers.DateTimeField(format="iso-8601")


class ChatRoomListSerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.IntegerField(read_only=True, default=0)
    created_at = serializers.DateTimeField(format="iso-8601", read_only=True)
    room_type_display = serializers.CharField(source="get_room_type_display", read_only=True)
    avatar_url = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = ("id", "name", "avatar_url", "room_type", "created_at", "last_message", "unread_count", 'room_type_display')

    def get_name(self, obj):
        if obj.room_type == 'group':
            return obj.name
        
        request = self.context.get("request")
        if request and request.user:
            participants = obj.participants.all()
            other_user = next((u for u in participants if u.id != request.user.id), None)
            if other_user:
                return getattr(other_user, 'name', "") or ""
        return obj.name

    def get_avatar_url(self, obj):
        if obj.room_type == 'group':
            if obj.avatar:
                request = self.context.get('request')
                if request:
                    return request.build_absolute_uri(obj.avatar.url)
                return obj.avatar.url
            return ""
        
        request = self.context.get("request")
        if request and request.user:
            participants = obj.participants.all()
            other_user = next((u for u in participants if u.id != request.user.id), None)
            if other_user and hasattr(other_user, 'profile_pic') and other_user.profile_pic:
                return request.build_absolute_uri(other_user.profile_pic.url) if request else other_user.profile_pic.url
        return ""

    def get_last_message(self, obj):
        messages = obj.messages.order_by("-created_at")[:1]
        msg = messages[0] if messages else None
        if msg is None:
            return None
        return {
            "sender_name": getattr(msg.sender, "name", ""),
            "content": msg.content,
            "file_name": msg.file_name or "",
            "created_at": msg.created_at.isoformat(),
            "tick_status": msg.tick_status,
        }


class ChatRoomSerializer(serializers.ModelSerializer):
    participants = UserMiniSerializer(many=True, read_only=True)
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.IntegerField(read_only=True, default=0)
    created_at = serializers.DateTimeField(format="iso-8601", read_only=True)
    room_type_display = serializers.CharField(source="get_room_type_display", read_only=True)
    avatar_url = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = ("id","name", "avatar_url", "room_type","participants","created_at","last_message","unread_count", 'room_type_display')

    def get_name(self, obj):
        if obj.room_type == 'group':
            return obj.name
        
        request = self.context.get("request")
        if request and request.user:
            participants = obj.participants.all()
            other_user = next((u for u in participants if u.id != request.user.id), None)
            if other_user:
                return getattr(other_user, 'name', "") or ""
        return obj.name

    def get_avatar_url(self, obj):
        if obj.room_type == 'group':
            if obj.avatar:
                request = self.context.get('request')
                if request:
                    return request.build_absolute_uri(obj.avatar.url)
                return obj.avatar.url
            return ""
        
        request = self.context.get("request")
        if request and request.user:
            participants = obj.participants.all()
            other_user = next((u for u in participants if u.id != request.user.id), None)
            if other_user and hasattr(other_user, 'profile_pic') and other_user.profile_pic:
                return request.build_absolute_uri(other_user.profile_pic.url) if request else other_user.profile_pic.url
        return ""

    def get_last_message(self, obj):
        # If messages were prefetched, use the cached set
        messages = obj.messages.order_by("-created_at")[:1]
        msg = messages[0] if messages else None

        if msg is None:
            return None

        return {
            "sender_name": getattr(msg.sender, "name", ""),
            "content": msg.content,
            "file_name": msg.file_name or "",
            "created_at": msg.created_at.isoformat(),
            "tick_status": msg.tick_status,
        }