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
from .serializers import ChatRoomSerializer, ChatRoomListSerializer, MessageSerializer
from .notifications import notify_new_message

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
    "image/webp",
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "video/mp4",
    "video/webm",
    "video/mpeg",
    "video/ogg",
    "video/quicktime",
    "audio/mpeg",
    "audio/wav",
    "audio/webm",
    "audio/ogg",
    "application/octet-stream",
    "application/zip",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",

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
        avatar = request.FILES.get("avatar") or request.FILES.get("avatar_url")
        
        if hasattr(request.data, "getlist"):
            participant_ids = request.data.getlist("participant_ids")
            if len(participant_ids) == 1 and ',' in participant_ids[0]:
                participant_ids = [x.strip() for x in participant_ids[0].split(',') if x.strip()]
        else:
            participant_ids = request.data.get("participant_ids", [])
            if not isinstance(participant_ids, list):
                participant_ids = [participant_ids]
        
        participant_ids = [str(pid).strip().strip('"').strip("'") for pid in participant_ids if str(pid).strip().strip('"').strip("'")]

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
                avatar=avatar,
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
# Room listing & detail
# ======================================================================

class RoomDetailView(APIView):
    """
    GET /api/chat/rooms/<room_id>/

    Return details for a single chat room including participants.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            room = ChatRoom.objects.prefetch_related("participants").get(id=room_id, is_active=True)
        except ChatRoom.DoesNotExist:
            return Response({"detail": "Room not found."}, status=status.HTTP_404_NOT_FOUND)

        if not room.participants.filter(id=request.user.id).exists():
            return Response({"detail": "You are not a participant of this room."}, status=status.HTTP_403_FORBIDDEN)

        serializer = ChatRoomSerializer(room, context={"request": request})
        return Response(serializer.data)


class RoomListView(APIView):
    """
    GET /api/chat/rooms/

    Return every room in which the requesting user is a participant.
    Each room includes ``last_message`` and ``unread_count``.
    """

    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['room_type']
    search_fields = ['name', 'participants__name']
    ordering_fields = '__all__'

    def get(self, request):
        user = request.user

        rooms = (
            ChatRoom.objects
            .filter(participants=user, is_active=True)  # Exclude deleted rooms
            .prefetch_related("participants")
            .order_by("-created_at")
        )

        rooms = apply_filters(self, request, rooms)

        serializer = ChatRoomListSerializer(
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

    The POST endpoint accepts **multipart/form-data** (for file + text in one
    request) as well as plain JSON (for text-only or pre-uploaded file URL).

    Multipart fields:
      - ``content``  (str, optional)  — text body
      - ``file``     (file, optional) — binary attachment (max 10 MB)
      - ``file_url`` (str, optional)  — pre-uploaded URL (ignored when ``file`` is sent)
      - ``file_name``(str, optional)  — override file name (for pre-uploaded URL flow)
      - ``file_size``(int, optional)  — override file size (for pre-uploaded URL flow)
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]  # supports both multipart and JSON
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['sender']
    search_fields = ['content', 'file_name']
    ordering_fields = '__all__'

    def get(self, request, room_id):
        """
        Return messages in the room, newest first, paginated with
        cursor-based pagination (using ``before`` query param for the
        cursor and ``limit`` for page size, default 50).

        Targeted messages (targets m2m is populated) are only visible to:
        - the sender
        - any of the target users (e.g. specific faculty)
        - super_admin users
        Normal messages (no targets) are visible to all participants.
        """
        if not self._is_participant(room_id, request.user):
            return Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        before = request.query_params.get("before")  # message UUID cursor
        limit = min(int(request.query_params.get("limit", 50)), 100)
        search = request.query_params.get("search", "").strip()

        # Base queryset
        qs = (
            Message.objects
            .filter(room_id=room_id, is_deleted=False)
            .select_related("sender")
            .prefetch_related("targets", "read_receipts__user")
            .order_by("-created_at")
        )

        # Visibility filter for targeted (private-to-faculty) messages.
        # Now supports *multiple* targets via ManyToMany.
        role = getattr(request.user, 'role', None)
        if role != 'super_admin':
            qs = qs.annotate(num_targets=Count("targets")).filter(
                # Normal group messages (no targets) OR messages involving current user
                Q(num_targets=0) |
                Q(sender=request.user) |
                Q(targets=request.user)
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

        Accepts multipart/form-data so a file can be sent in the same
        request as the message text.  Also still accepts plain JSON with
        a pre-uploaded ``file_url``.

        New: ``target_user_ids`` (optional list) - for group chats, send a
        targeted message visible *only* to sender, the listed targets (multiple
        faculty allowed), and super_admin. Normal messages (empty list or omitted)
        are visible to the whole group.
        """
        if not self._is_participant(room_id, request.user):
            return Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        content = request.data.get("content", "")
        uploaded_file = request.FILES.get("file")  # multipart upload
        file_url = request.data.get("file_url")     # pre-uploaded URL fallback
        file_name = request.data.get("file_name")
        file_size = request.data.get("file_size")
        target_user_ids = request.data.get("target_user_ids") or request.data.get("target_user_id")

        # Normalize to list
        if isinstance(target_user_ids, str):
            if ',' in target_user_ids:
                target_user_ids = [x.strip() for x in target_user_ids.split(',') if x.strip()]
            else:
                target_user_ids = [target_user_ids]
        if not isinstance(target_user_ids, list):
            target_user_ids = [target_user_ids] if target_user_ids else []

        target_user_ids = [str(tid).strip() for tid in target_user_ids if str(tid).strip()]

        # ── Resolve multiple targets if provided (student -> specific faculty) ───────
        targets = []
        if target_user_ids:
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                if getattr(request.user, 'organization', None):
                    targets = list(User.objects.filter(
                        id__in=target_user_ids,
                        organization=request.user.organization
                    ))
                else:
                    targets = list(User.objects.filter(id__in=target_user_ids))

                if len(targets) != len(target_user_ids):
                    return Response(
                        {"detail": "One or more target users not found or not in organization."},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                # Must be participants of the same group
                room = ChatRoom.objects.get(id=room_id, is_active=True)
                target_ids = {str(t.id) for t in targets}
                if not all(room.participants.filter(id=tid).exists() for tid in target_ids):
                    return Response(
                        {"detail": "All target users must be participants of this room."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Optional business rule: students typically target faculty
                student_role = getattr(request.user, 'role', None) == 'student'
                if student_role:
                    for tgt in targets:
                        tgt_role = getattr(tgt, 'role', None)
                        if tgt_role not in ['faculty', 'paper_checker', 'admin_senior_executive']:
                            logger.warning(f"Student {request.user.id} targeting non-faculty {tgt.id}")
            except ChatRoom.DoesNotExist:
                return Response(
                    {"detail": "Room not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        # ── Handle direct file upload ─────────────────────────────────────
        if uploaded_file:
            # Validate content type
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

            # Validate size
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

            # Save to storage
            from django.core.files.storage import default_storage
            import uuid as _uuid
            ext = uploaded_file.name.rsplit(".", 1)[-1] if "." in uploaded_file.name else ""
            unique_name = f"{_uuid.uuid4().hex}.{ext}" if ext else _uuid.uuid4().hex
            path = f"chat/attachments/{unique_name}"
            saved_path = default_storage.save(path, uploaded_file)
            file_url = default_storage.url(saved_path)
            file_name = uploaded_file.name
            file_size = uploaded_file.size

        # ── Must have at least text or an attachment ───────────────────────
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
            file_size=int(file_size) if file_size else None,
        )
        if targets:
            message.targets.set(targets)

        # ── Broadcast to WebSocket so other participants see it in real-time ──
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        channel_layer = get_channel_layer()
        if channel_layer:
            avatar_url = ""
            if hasattr(request.user, "profile_pic") and request.user.profile_pic:
                try:
                    avatar_url = request.user.profile_pic.url
                except Exception:
                    avatar_url = ""

            # Prepare list of targets for WS payload (supports multiple)
            targets_data = []
            for tgt in message.targets.all():
                targets_data.append({
                    "id": str(tgt.id),
                    "full_name": getattr(tgt, "name", ""),
                    "role": getattr(tgt, "role", ""),
                })

            async_to_sync(channel_layer.group_send)(
                f"room_{room_id}",
                {
                    "type": "chat.new_message",
                    "message": {
                        "id":         str(message.id),
                        "room_id":    str(room_id),
                        "sender": {
                            "id":        str(request.user.id),
                            "full_name": getattr(request.user, "name", ""),
                            "avatar_url": avatar_url,
                        },
                        "targets":    targets_data,
                        "content":    message.content,
                        "file_url":   message.file_url or "",
                        "file_name":  message.file_name or "",
                        "file_size":  message.file_size,
                        "created_at": message.created_at.isoformat(),
                        "delivered_at": None,
                        "read_at":      None,
                    },
                },
            )

        # Send push notifications (filtered by targets for privacy; excludes sender)
        try:
            participant_ids = list(
                ChatRoom.objects.filter(id=room_id, is_active=True)
                .values_list("participants__id", flat=True)
                .distinct()
            )
            target_ids = [str(t.id) for t in targets]
            notify_new_message(
                room_id=room_id,
                message_id=str(message.id),
                sender_name=getattr(request.user, "name", "Someone"),
                content=content or (message.file_name or "📎 Attachment"),
                participant_ids=participant_ids,
                target_user_ids=target_ids,
                sender_id=str(request.user.id),
            )
        except Exception as exc:
            logger.warning("Push notification failed for message %s: %s", message.id, exc)

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
            "content": "This message was deleted", 
            "is_deleted": True,
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


class GroupUpdateView(APIView):
    """
    PATCH /api/chat/rooms/<room_id>/update-group/

    Update group name, add members, or remove members in a single API call.

    Request body::

        {
            "name": "New Group Name",
            "add_user_ids": ["<uuid>", ...],
            "remove_user_ids": ["<uuid>", ...]
        }

    Rules:
    * Only works on ``group`` rooms (returns 400 for direct rooms).
    * The requesting user must be a participant.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, room_id):
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
                {"detail": "Cannot update a direct room."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Caller must be a participant
        if not room.participants.filter(id=request.user.id).exists():
            return Response(
                {"detail": "You are not a participant of this room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        name = request.data.get("name")
        avatar = request.FILES.get("avatar") or request.FILES.get("avatar_url")

        if hasattr(request.data, "getlist"):
            add_user_ids = request.data.getlist("add_user_ids")
            if len(add_user_ids) == 1 and ',' in add_user_ids[0]:
                add_user_ids = [x.strip() for x in add_user_ids[0].split(',') if x.strip()]
            
            remove_user_ids = request.data.getlist("remove_user_ids")
            if len(remove_user_ids) == 1 and ',' in remove_user_ids[0]:
                remove_user_ids = [x.strip() for x in remove_user_ids[0].split(',') if x.strip()]
        else:
            add_user_ids = request.data.get("add_user_ids", [])
            remove_user_ids = request.data.get("remove_user_ids", [])
            if not isinstance(add_user_ids, list):
                add_user_ids = [add_user_ids]
            if not isinstance(remove_user_ids, list):
                remove_user_ids = [remove_user_ids]
                
        add_user_ids = [str(pid).strip().strip('"').strip("'") for pid in add_user_ids if str(pid).strip().strip('"').strip("'")]
        remove_user_ids = [str(pid).strip().strip('"').strip("'") for pid in remove_user_ids if str(pid).strip().strip('"').strip("'")]

        if not isinstance(add_user_ids, list) or not isinstance(remove_user_ids, list):
            return Response(
                {"detail": "'add_user_ids' and 'remove_user_ids' must be lists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Update name
        if name and isinstance(name, str) and name.strip():
            room.name = name.strip()
            room.save(update_fields=['name'])

        # Update avatar
        if avatar:
            room.avatar = avatar
            room.save(update_fields=['avatar'])

        # Add users
        added_ids = []
        not_found = []
        if add_user_ids:
            if getattr(request.user, 'organization', None):
                users_to_add = list(User.objects.filter(id__in=add_user_ids, organization=request.user.organization))
            else:
                users_to_add = list(User.objects.filter(id__in=add_user_ids))
            
            found_ids = {str(u.id) for u in users_to_add}
            not_found = [uid for uid in add_user_ids if str(uid) not in found_ids]
            
            existing_ids = set(room.participants.filter(id__in=[u.id for u in users_to_add]).values_list("id", flat=True))
            new_users = [u for u in users_to_add if u.id not in existing_ids]
            
            if new_users:
                room.participants.add(*new_users)
                added_ids = [str(u.id) for u in new_users]

        # Remove users
        removed_ids = []
        if remove_user_ids:
            users_to_remove = room.participants.filter(id__in=remove_user_ids)
            removed_ids = [str(u.id) for u in users_to_remove]
            if users_to_remove:
                room.participants.remove(*users_to_remove)

        return Response(
            {
                "room_id": str(room_id),
                "name": room.name,
                "added": added_ids,
                "removed": removed_ids,
                "not_found": not_found
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
        room.save(update_fields=['is_active', 'updated_at'])

        return Response(status=status.HTTP_204_NO_CONTENT)
