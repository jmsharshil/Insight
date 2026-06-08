import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ChatRoom, Message, MessageReadReceipt
from .serializers import ChatRoomSerializer, MessageSerializer

from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from core.utils import apply_filters

logger = logging.getLogger(__name__)
User = get_user_model()

# Upload constraints
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "application/pdf",
}


# ======================================================================
# Room creation
# ======================================================================


class DirectRoomView(APIView):
    """
    POST /api/chat/rooms/direct/

    Get-or-create a direct (1:1) chat room between the requesting user
    and ``other_user_id``.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        other_user_id = request.data.get("other_user_id")
        if not other_user_id:
            return Response(
                {"detail": "'other_user_id' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            if getattr(request.user, 'organization', None):
                other_user = User.objects.get(id=other_user_id, organization=request.user.organization)
            else:
                other_user = User.objects.get(id=other_user_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if str(other_user.id) == str(request.user.id):
            return Response(
                {"detail": "Cannot create a direct room with yourself."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        direct_hash = ChatRoom.build_direct_hash(request.user.id, other_user.id)

        # --- get or create ---
        room = ChatRoom.objects.filter(
            room_type="direct",
            direct_hash=direct_hash,
            is_active=True,  # Only retrieve active rooms, skip soft-deleted ones
        ).first()

        if room is None:
            with transaction.atomic():
                room = ChatRoom.objects.create(
                    room_type="direct",
                    direct_hash=direct_hash,
                    is_active=True,
                )
                room.participants.set([request.user, other_user])

        serializer = ChatRoomSerializer(
            room,
            context={"request": request},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class GroupRoomView(APIView):
    """
    POST /api/chat/rooms/group/

    Create a new group chat room with the given name and participants.
    The requesting user is always added as a participant.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        name = request.data.get("name", "").strip()
        participant_ids = request.data.get("participant_ids", [])

        if not name:
            return Response(
                {"detail": "'name' is required for group rooms."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Resolve participant user objects
        if getattr(request.user, 'organization', None):
            participants = list(User.objects.filter(id__in=participant_ids, organization=request.user.organization))
        else:
            participants = list(User.objects.filter(id__in=participant_ids))
        # Always include the requesting user
        if request.user not in participants:
            participants.append(request.user)

        with transaction.atomic():
            room = ChatRoom.objects.create(
                name=name,
                room_type="group",
                direct_hash="",  # Not used for group rooms
                is_active=True,
            )
            room.participants.set(participants)

        serializer = ChatRoomSerializer(
            room,
            context={"request": request},
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# ======================================================================
# Room listing
# ======================================================================


class RoomListView(APIView):
    """
    GET /api/chat/rooms/

    Return every room in which the requesting user is a participant.
    Each room includes ``last_message`` and ``unread_count``.
    """

    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['room_type']
    search_fields = ['name']
    ordering_fields = '__all__'

    def get(self, request):
        user = request.user

        rooms = (
            ChatRoom.objects
            .filter(participants=user, is_active=True)  # Exclude deleted rooms
            .prefetch_related("participants", "messages__sender")
            .annotate(
                unread_count=Count(
                    "messages",
                    filter=~Q(
                        messages__read_receipts__user=user,
                    ) & ~Q(messages__sender=user),
                ),
            )
            .order_by("-created_at")
        )

        rooms = apply_filters(self, request, rooms)

        serializer = ChatRoomSerializer(
            rooms,
            many=True,
            context={"request": request},
        )
        return Response(serializer.data)


# ======================================================================
# Messages
# ======================================================================


class MessageListCreateView(APIView):
    """
    GET  /api/chat/rooms/<room_id>/messages/  — paginated message history
    POST /api/chat/rooms/<room_id>/messages/  — REST fallback for sending
    """

    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['sender']
    search_fields = ['content', 'file_name']
    ordering_fields = '__all__'

    def get(self, request, room_id):
        """
        Return messages in the room, newest first, paginated with
        cursor-based pagination (using ``before`` query param for the
        cursor and ``limit`` for page size, default 50).
        """
        if not self._is_participant(room_id, request.user):
            return Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        before = request.query_params.get("before")  # message UUID cursor
        limit = min(int(request.query_params.get("limit", 50)), 100)
        search = request.query_params.get("search", "").strip()
        qs = (
            Message.objects
            .filter(room_id=room_id)
            .select_related("sender")
            .prefetch_related("read_receipts__user")
            .order_by("-created_at")
        )

        qs = apply_filters(self, request, qs)

        if before:
            try:
                cursor_msg = Message.objects.get(id=before)
                qs = qs.filter(created_at__lt=cursor_msg.created_at)
            except Message.DoesNotExist:
                pass

        messages = qs[:limit]
        serializer = MessageSerializer(messages, many=True)

        response_data = {
            "results": serializer.data,
            "next_cursor": str(messages[len(messages) - 1].id) if len(messages) == limit else None,
            "search": search or None,
        }
        return Response(response_data)
    

    def post(self, request, room_id):
        """
        REST fallback for sending a message (same semantics as the
        WebSocket ``send_message`` event).
        """
        if not self._is_participant(room_id, request.user):
            return Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        content = request.data.get("content", "")
        file_url = request.data.get("file_url")
        file_name = request.data.get("file_name")
        file_size = request.data.get("file_size")

        if not content and not file_url:
            return Response(
                {"detail": "Message must contain content or a file attachment."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        message = Message.objects.create(
            room_id=room_id,
            sender=request.user,
            content=content or "",
            file_url=file_url,
            file_name=file_name,
            file_size=file_size,
        )

        # Fire Celery task for push notifications
        from .tasks import notify_new_chat_message

        notify_new_chat_message.delay(
            str(room_id),
            str(message.id),
            str(request.user.id),
        )

        serializer = MessageSerializer(message)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    # ------------------------------------------------------------------

    @staticmethod
    def _is_participant(room_id, user) -> bool:
        return ChatRoom.objects.filter(
            id=room_id,
            participants=user,
            is_active=True,  # Only allow access to active rooms
        ).exists()


# ======================================================================
# File upload
# ======================================================================

class MessageDetailAPIView(APIView):
    """
    PATCH  /api/chat/messages/<message_id>/ — Update a message
    DELETE /api/chat/messages/<message_id>/ — Soft delete a message
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, message_id):
        try:
            message = Message.objects.get(id=message_id)
        except Message.DoesNotExist:
            return Response({"detail": "Message not found."}, status=status.HTTP_404_NOT_FOUND)

        if str(message.sender.id) != str(request.user.id):
            return Response({"detail": "You can only update your own messages."}, status=status.HTTP_403_FORBIDDEN)
        
        if message.is_deleted:
            return Response({"detail": "Cannot update a deleted message."}, status=status.HTTP_400_BAD_REQUEST)

        content = request.data.get("content")
        if not content:
            return Response({"detail": "'content' is required to update a message."}, status=status.HTTP_400_BAD_REQUEST)

        message.content = content
        message.save(update_fields=['content', 'updated_at'])

        # Broadcast update to room via Channels
        self._broadcast_event(message.room_id, {
            "type": "chat.message_updated",
            "message_id": str(message.id),
            "content": message.content,
        })

        serializer = MessageSerializer(message)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, message_id):
        try:
            message = Message.objects.get(id=message_id)
        except Message.DoesNotExist:
            return Response({"detail": "Message not found."}, status=status.HTTP_404_NOT_FOUND)

        if str(message.sender.id) != str(request.user.id):
            return Response({"detail": "You can only delete your own messages."}, status=status.HTTP_403_FORBIDDEN)

        if message.is_deleted:
            return Response({"detail": "Message is already deleted."}, status=status.HTTP_400_BAD_REQUEST)

        message.is_deleted = True
        message.save(update_fields=['is_deleted', 'updated_at'])

        # Broadcast delete to room via Channels
        self._broadcast_event(message.room_id, {
            "type": "chat.message_deleted",
            "message_id": str(message.id),
        })

        return Response({"detail": "Message deleted."}, status=status.HTTP_204_NO_CONTENT)

    def _broadcast_event(self, room_id, event):
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"room_{room_id}",
                event
            )

# ======================================================================
# File upload
# ======================================================================


class FileUploadView(APIView):
    """
    POST /api/chat/upload/

    Accept a multipart file upload, validate size/type, store to the
    configured default storage (S3-compatible), and return the URL.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response(
                {"detail": "No file provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- Validate content type ---
        if uploaded_file.content_type not in ALLOWED_CONTENT_TYPES:
            return Response(
                {
                    "detail": (
                        f"Unsupported file type '{uploaded_file.content_type}'. "
                        f"Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- Validate size ---
        if uploaded_file.size > MAX_UPLOAD_SIZE:
            return Response(
                {
                    "detail": (
                        f"File size {uploaded_file.size} bytes exceeds the "
                        f"maximum of {MAX_UPLOAD_SIZE} bytes (10 MB)."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- Store ---
        from django.core.files.storage import default_storage

        path = f"chat/attachments/{uploaded_file.name}"
        saved_path = default_storage.save(path, uploaded_file)
        file_url = default_storage.url(saved_path)

        return Response(
            {
                "file_url": file_url,
                "file_name": uploaded_file.name,
                "file_size": uploaded_file.size,
            },
            status=status.HTTP_201_CREATED,
        )


# ======================================================================
# Group membership management
# ======================================================================


class GroupAddMembersView(APIView):
    """
    POST /api/chat/rooms/<room_id>/add-members/

    Add one or more users to a group chat room.

    Request body::

        {
            "user_ids": ["<uuid>", "<uuid>", ...]
        }

    Rules:
    * Only works on ``group`` rooms (returns 400 for direct rooms).
    * The requesting user must already be a participant.
    * Users who are already participants are silently skipped.

    Response::

        {
            "added": ["<uuid>", ...],
            "already_in_room": ["<uuid>", ...],
            "not_found": ["<uuid>", ...]
        }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, room_id):
        # Fetch room
        try:
            room = ChatRoom.objects.get(id=room_id, is_active=True)  # Prevent operations on deleted rooms
        except ChatRoom.DoesNotExist:
            return Response(
                {"detail": "Room not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Must be a group room
        if room.room_type != "group":
            return Response(
                {"detail": "Cannot add members to a direct room."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Caller must be a participant
        if not room.participants.filter(id=request.user.id).exists():
            return Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        user_ids = request.data.get("user_ids", [])
        if not user_ids or not isinstance(user_ids, list):
            return Response(
                {"detail": "'user_ids' must be a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Resolve users
        if getattr(request.user, 'organization', None):
            users_to_add = list(User.objects.filter(id__in=user_ids, organization=request.user.organization))
        else:
            users_to_add = list(User.objects.filter(id__in=user_ids))
        found_ids = {str(u.id) for u in users_to_add}
        not_found = [uid for uid in user_ids if str(uid) not in found_ids]

        # Check who is already a participant
        existing_ids = set(
            room.participants.filter(id__in=[u.id for u in users_to_add])
            .values_list("id", flat=True)
        )
        existing_ids = {str(eid) for eid in existing_ids}

        new_users = [u for u in users_to_add if str(u.id) not in existing_ids]

        # Add new participants
        if new_users:
            room.participants.add(*new_users)

        return Response(
            {
                "added": [str(u.id) for u in new_users],
                "already_in_room": list(existing_ids),
                "not_found": not_found,
            },
            status=status.HTTP_200_OK,
        )


class GroupRemoveMemberView(APIView):
    """
    POST /api/chat/rooms/<room_id>/remove-member/

    Remove a user from a group chat room.

    Request body::

        {
            "user_id": "<uuid>"
        }

    Rules:
    * Only works on ``group`` rooms (returns 400 for direct rooms).
    * The requesting user must be a participant of the room.
    * A user can remove themselves (leave the group).
    * The target user must currently be a participant.

    Response::

        {
            "removed": "<uuid>",
            "room_id": "<uuid>"
        }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, room_id):
        # Fetch room
        try:
            room = ChatRoom.objects.get(id=room_id, is_active=True)  # Prevent operations on deleted rooms
        except ChatRoom.DoesNotExist:
            return Response(
                {"detail": "Room not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Must be a group room
        if room.room_type != "group":
            return Response(
                {"detail": "Cannot remove members from a direct room."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Caller must be a participant
        if not room.participants.filter(id=request.user.id).exists():
            return Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        user_id = request.data.get("user_id")
        if not user_id:
            return Response(
                {"detail": "'user_id' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check target user is in the room
        if not room.participants.filter(id=user_id).exists():
            return Response(
                {"detail": "User is not a participant of this room."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Remove the participant
        room.participants.remove(user_id)

        return Response(
            {
                "removed": str(user_id),
                "room_id": str(room_id),
            },
            status=status.HTTP_200_OK,
        )


class GroupMembersView(APIView):
    """
    GET /api/chat/rooms/<room_id>/members/

    List all participants of a group chat room.

    Response::

        {
            "room_id": "<uuid>",
            "room_name": "...",
            "members": [
                {"id": "<uuid>", "full_name": "...", "avatar_url": "..."},
                ...
            ],
            "count": <int>
        }
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            room = ChatRoom.objects.filter(is_active=True).prefetch_related("participants").get(id=room_id)  # Exclude deleted rooms
        except ChatRoom.DoesNotExist:
            return Response(
                {"detail": "Room not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if room.room_type != "group":
            return Response(
                {"detail": "This endpoint is only for group rooms."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not room.participants.filter(id=request.user.id).exists():
            return Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        from .serializers import UserMiniSerializer

        members = room.participants.all()
        serializer = UserMiniSerializer(members, many=True)

        return Response(
            {
                "room_id": str(room.id),
                "room_name": room.name,
                "members": serializer.data,
                "count": len(serializer.data),
            },
            status=status.HTTP_200_OK,
        )


class GroupDeleteView(APIView):
    """
    DELETE /api/chat/rooms/<room_id>/delete/

    Delete (deactivate) a group chat room.

    Rules:
    * Only works on ``group`` rooms.
    * The requesting user must be a participant.
    * Sets ``is_active=False`` (soft delete) — messages are preserved.

    Response: 204 No Content
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, room_id):
        try:
            room = ChatRoom.objects.get(id=room_id, is_active=True)  # Only allow deleting active rooms
        except ChatRoom.DoesNotExist:
            return Response(
                {"detail": "Room not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if room.room_type != "group":
            return Response(
                {"detail": "Cannot delete a direct room."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not room.participants.filter(id=request.user.id).exists():
            return Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not room.is_active:
            return Response(
                {"detail": "Room is already deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        room.is_active = False
        room.save(update_fields=["is_active"])

        return Response(status=status.HTTP_204_NO_CONTENT)
