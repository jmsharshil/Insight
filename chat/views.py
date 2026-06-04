from django.shortcuts import render 
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

logger = logging.getLogger(__name__)
User = get_user_model()

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
    permission_classes = [IsAuthenticated]

    def post(self, request):
        other_user_id = request.data.get("other_user_id")
        if not other_user_id:
            return Response(
                {"detail": "'other_user_id' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            other_user = User.objects.get(id=other_user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        if str(other_user.id) == str(request.user.id):
            return Response(
                {"detail": "Cannot create a direct room with yourself."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        direct_hash = ChatRoom.build_direct_hash(request.user.id, other_user.id)
        room = ChatRoom.objects.filter(room_type="direct", direct_hash=direct_hash).first()

        if room is None:
            with transaction.atomic():
                room = ChatRoom.objects.create(
                    room_type="direct", direct_hash=direct_hash, is_active=True,
                )
                room.participants.set([request.user, other_user])

        serializer = ChatRoomSerializer(room, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class GroupRoomView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        name = request.data.get("name", "").strip()
        participant_ids = request.data.get("participant_ids", [])

        if not name:
            return Response(
                {"detail": "'name' is required for group rooms."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        participants = list(User.objects.filter(id__in=participant_ids))
        if request.user not in participants:
            participants.append(request.user)

        with transaction.atomic():
            room = ChatRoom.objects.create(
                name=name, room_type="group", direct_hash="", is_active=True,
            )
            room.participants.set(participants)

        serializer = ChatRoomSerializer(room, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# ======================================================================
# Room listing
# ======================================================================

class RoomListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        rooms = (
            ChatRoom.objects
            .filter(participants=user)
            .prefetch_related("participants", "messages__sender")
            .annotate(
                unread_count=Count(
                    "messages",
                    filter=(
                        ~Q(messages__read_receipts__user=user)
                        & ~Q(messages__sender=user)
                    ),
                ),
            )
            .order_by("-created_at")
        )
        serializer = ChatRoomSerializer(rooms, many=True, context={"request": request})
        return Response(serializer.data)


# ======================================================================
# Messages
# ======================================================================

class MessageListCreateView(APIView):
    """
    GET  /api/chat/rooms/<room_id>/messages/
         Query params:
           before  — UUID cursor for pagination
           limit   — page size (default 50, max 100)
           search  — keyword search in message content  ← NEW (ITEM-3)

    POST /api/chat/rooms/<room_id>/messages/
         REST fallback for sending a message.
    """

    # We want to accept JSON for text-only messages, and multipart for file uploads
    # If parser_classes isn't defined, DRF handles JSON and Form data by default.
    # We will explicitly add them to ensure multipart is handled.
    from rest_framework.parsers import JSONParser
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        if not self._is_participant(room_id, request.user):
            return Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        before = request.query_params.get("before")
        limit  = min(int(request.query_params.get("limit", 50)), 100)
        search = request.query_params.get("search", "").strip()   # ITEM-3

        qs = (
            Message.objects
            .filter(room_id=room_id)
            .select_related("sender")
            .prefetch_related("read_receipts__user")
            .order_by("-created_at")
        )

        # ---- ITEM-3: keyword search ----
        if search:
            qs = qs.filter(content__icontains=search)

        if before:
            try:
                cursor_msg = Message.objects.get(id=before)
                qs = qs.filter(created_at__lt=cursor_msg.created_at)
            except Message.DoesNotExist:
                pass

        messages = qs[:limit]
        serializer = MessageSerializer(messages, many=True)

        return Response({
            "results":     serializer.data,
            "next_cursor": (
                str(messages[len(messages) - 1].id) if len(messages) == limit else None
            ),
            "search": search or None,   # echo back so frontend knows it was filtered
        })

    def post(self, request, room_id):
        if not self._is_participant(room_id, request.user):
            return Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        content = request.data.get("content", "")
        uploaded_file = request.FILES.get("file")
        
        file_url = request.data.get("file_url")
        file_name = request.data.get("file_name")
        file_size = request.data.get("file_size")

        # If a file is directly uploaded in this request, process and save it
        if uploaded_file:
            if uploaded_file.content_type not in ALLOWED_CONTENT_TYPES:
                return Response(
                    {"detail": (
                        f"Unsupported file type '{uploaded_file.content_type}'. "
                        f"Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}."
                    )},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if uploaded_file.size > MAX_UPLOAD_SIZE:
                return Response(
                    {"detail": (
                        f"File size {uploaded_file.size} bytes exceeds "
                        f"the maximum of {MAX_UPLOAD_SIZE} bytes (10 MB)."
                    )},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            from django.core.files.storage import default_storage
            path       = f"chat/attachments/{uploaded_file.name}"
            saved_path = default_storage.save(path, uploaded_file)
            file_url   = default_storage.url(saved_path)
            file_name  = uploaded_file.name
            file_size  = uploaded_file.size

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

        from .tasks import notify_new_chat_message
        try:
            notify_new_chat_message(str(room_id), str(message.id), str(request.user.id))
        except Exception:
            logger.exception(
                "notify_new_chat_message failed for message %s in room %s.",
                message.id, room_id,
            )

        serializer = MessageSerializer(message)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _is_participant(room_id, user) -> bool:
        return ChatRoom.objects.filter(id=room_id, participants=user).exists()


# ======================================================================
# File upload
# ======================================================================

class FileUploadView(APIView):
    """
    POST /api/v1/chat/rooms/<room_id>/upload/
        Upload a file to be sent in a specific chat room.
        Must be sent as multipart/form-data with a 'file' field.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, room_id):
        if not ChatRoom.objects.filter(id=room_id, participants=request.user).exists():
            return Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response({"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        if uploaded_file.content_type not in ALLOWED_CONTENT_TYPES:
            return Response(
                {"detail": (
                    f"Unsupported file type '{uploaded_file.content_type}'. "
                    f"Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}."
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if uploaded_file.size > MAX_UPLOAD_SIZE:
            return Response(
                {"detail": (
                    f"File size {uploaded_file.size} bytes exceeds "
                    f"the maximum of {MAX_UPLOAD_SIZE} bytes (10 MB)."
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.core.files.storage import default_storage
        path       = f"chat/attachments/{uploaded_file.name}"
        saved_path = default_storage.save(path, uploaded_file)
        file_url   = default_storage.url(saved_path)

        return Response(
            {"file_url": file_url, "file_name": uploaded_file.name, "file_size": uploaded_file.size},
            status=status.HTTP_201_CREATED,
        )


# ======================================================================
# Message detail — edit & delete
# ======================================================================

class MessageDetailView(APIView):
    """
    PATCH  /api/v1/chat/rooms/<room_id>/messages/<message_id>/
        Edit the content of a message. Only the original sender can edit.
        Request body: { "content": "updated text" }

    DELETE /api/v1/chat/rooms/<room_id>/messages/<message_id>/
        Hard-delete a message. Only the original sender can delete.
    """

    permission_classes = [IsAuthenticated]

    def _get_message(self, room_id, message_id, user):
        """
        Fetch the message and validate room membership + ownership.
        Returns (message, error_response) — one of them is always None.
        """
        if not ChatRoom.objects.filter(id=room_id, participants=user).exists():
            return None, Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            message = Message.objects.get(id=message_id, room_id=room_id)
        except Message.DoesNotExist:
            return None, Response(
                {"detail": "Message not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if str(message.sender_id) != str(user.id):
            return None, Response(
                {"detail": "You can only edit or delete your own messages."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return message, None

    def patch(self, request, room_id, message_id):
        """Edit the text content of a message (sender only, cannot edit deleted messages)."""
        message, err = self._get_message(room_id, message_id, request.user)
        if err:
            return err

        if message.is_deleted:
            return Response(
                {"detail": "Cannot edit a deleted message."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_content = request.data.get("content", "").strip()
        if not new_content:
            return Response(
                {"detail": "'content' is required and cannot be blank."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        message.content = new_content
        message.save(update_fields=["content", "updated_at"])

        serializer = MessageSerializer(message)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, room_id, message_id):
        """
        Soft-delete a message (sender only).
        Content is replaced with the placeholder text and file fields are cleared.
        The message row is kept so read receipts and ordering are preserved.
        """
        message, err = self._get_message(room_id, message_id, request.user)
        if err:
            return err

        if message.is_deleted:
            # Already deleted — return current state without doing anything.
            serializer = MessageSerializer(message)
            return Response(serializer.data, status=status.HTTP_200_OK)

        message.is_deleted = True
        message.content   = Message.DELETED_TEXT
        message.file_url  = None
        message.file_name = None
        message.file_size = None
        message.save(update_fields=["is_deleted", "content", "file_url", "file_name", "file_size", "updated_at"])

        serializer = MessageSerializer(message)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ======================================================================
# Group room management
# ======================================================================

class GroupMemberView(APIView):
    """
    GET  /api/v1/chat/rooms/<room_id>/members/
        List all participants of a group room.

    POST /api/v1/chat/rooms/<room_id>/members/
        Add one or more users to a group room.
        Request body: { "user_ids": [1, 2, 3] }
    """

    permission_classes = [IsAuthenticated]

    def _get_group_room(self, room_id, user):
        """
        Fetch the room and confirm it is a group room that the user belongs to.
        Returns (room, error_response).
        """
        try:
            room = ChatRoom.objects.get(id=room_id, room_type="group")
        except ChatRoom.DoesNotExist:
            return None, Response(
                {"detail": "Group room not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not room.participants.filter(id=user.id).exists():
            return None, Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return room, None

    def get(self, request, room_id):
        """Return the full participant list of a group room."""
        room, err = self._get_group_room(room_id, request.user)
        if err:
            return err

        members = room.participants.all().values(
            "id", "name", "email", "role",
        )
        return Response({"room_id": str(room_id), "members": list(members)})

    def post(self, request, room_id):
        """Add users to an existing group room."""
        room, err = self._get_group_room(room_id, request.user)
        if err:
            return err

        user_ids = request.data.get("user_ids", [])
        if not user_ids:
            return Response(
                {"detail": "'user_ids' list is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        users_to_add = User.objects.filter(id__in=user_ids)
        if not users_to_add.exists():
            return Response(
                {"detail": "No valid users found for the provided ids."},
                status=status.HTTP_404_NOT_FOUND,
            )

        room.participants.add(*users_to_add)

        added = list(users_to_add.values("id", "name", "email"))
        return Response(
            {"detail": f"{len(added)} member(s) added.", "added": added},
            status=status.HTTP_200_OK,
        )


class GroupMemberRemoveView(APIView):
    """
    DELETE /api/v1/chat/rooms/<room_id>/members/<user_id>/
        Remove a specific user from a group room.
        Any existing participant can remove another participant
        (or remove themselves to leave the group).
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, room_id, user_id):
        """Remove a participant from a group room."""
        try:
            room = ChatRoom.objects.get(id=room_id, room_type="group")
        except ChatRoom.DoesNotExist:
            return Response(
                {"detail": "Group room not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not room.participants.filter(id=request.user.id).exists():
            return Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not room.participants.filter(id=target_user.id).exists():
            return Response(
                {"detail": "That user is not a member of this room."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        room.participants.remove(target_user)

        # If the room is left with fewer than 2 members, deactivate it.
        if room.participants.count() < 2:
            room.is_active = False
            room.save(update_fields=["is_active"])

        return Response(
            {"detail": f"User {target_user.name} removed from the group."},
            status=status.HTTP_200_OK,
        )


class RemoveMemberView(APIView):
    """
    POST /api/v1/chat/rooms/<room_id>/remove-member/
        Remove a user from a group room by passing user_id in the request body.

        Request body:
            { "user_id": "<uuid>" }

        Any current participant can remove another participant,
        or remove themselves to leave the group.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, room_id):
        """Remove a participant using user_id from the request body."""
        # --- validate room ---
        try:
            room = ChatRoom.objects.get(id=room_id, room_type="group")
        except ChatRoom.DoesNotExist:
            return Response(
                {"detail": "Group room not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # --- requester must be a member ---
        if not room.participants.filter(id=request.user.id).exists():
            return Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # --- get target user_id from body ---
        user_id = request.data.get("user_id")
        if not user_id:
            return Response(
                {"detail": "'user_id' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not room.participants.filter(id=target_user.id).exists():
            return Response(
                {"detail": "That user is not a member of this room."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        room.participants.remove(target_user)

        # Deactivate room if fewer than 2 members remain.
        if room.participants.count() < 2:
            room.is_active = False
            room.save(update_fields=["is_active"])

        return Response(
            {"detail": f"User {target_user.name} removed from the group."},
            status=status.HTTP_200_OK,
        )


class GroupRoomDeleteView(APIView):
    """
    DELETE /api/v1/chat/rooms/<room_id>/
        Permanently delete a group room and all its messages.
        Any current participant can delete the group.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, room_id):
        """Delete a group chat room entirely."""
        try:
            room = ChatRoom.objects.get(id=room_id, room_type="group")
        except ChatRoom.DoesNotExist:
            return Response(
                {"detail": "Group room not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not room.participants.filter(id=request.user.id).exists():
            return Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        room.delete()   # cascades to Message and MessageReadReceipt
        return Response(
            {"detail": "Group deleted successfully."},
            status=status.HTTP_200_OK,
        )
