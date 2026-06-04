"""
Full endpoint map:
  POST   chat/rooms/direct/                              → DirectRoomView
  POST   chat/rooms/group/                               → GroupRoomView
  GET    chat/rooms/                                     → RoomListView
  DELETE chat/rooms/<room_id>/                           → GroupRoomDeleteView
  GET    chat/rooms/<room_id>/messages/                  → MessageListCreateView
  POST   chat/rooms/<room_id>/messages/                  → MessageListCreateView
  PATCH  chat/rooms/<room_id>/messages/<message_id>/     → MessageDetailView (edit)
  DELETE chat/rooms/<room_id>/messages/<message_id>/     → MessageDetailView (delete)
  GET    chat/rooms/<room_id>/members/                   → GroupMemberView (list)
  POST   chat/rooms/<room_id>/members/                   → GroupMemberView (add)
  DELETE chat/rooms/<room_id>/members/<user_id>/         → GroupMemberRemoveView
  POST   chat/upload/                                    → FileUploadView
"""

from django.urls import path

from .views import (DirectRoomView,FileUploadView,GroupMemberRemoveView,GroupMemberView,GroupRoomDeleteView,GroupRoomView,MessageDetailView,MessageListCreateView,RemoveMemberView,RoomListView,)

urlpatterns = [
    path("chat/rooms/direct/",DirectRoomView.as_view(),name="chat-room-direct"),
    path("chat/rooms/group/",GroupRoomView.as_view(),name="chat-room-group"),
    path("chat/rooms/",RoomListView.as_view(),name="chat-room-list"),
    path("chat/rooms/<uuid:room_id>/",GroupRoomDeleteView.as_view(),name="chat-room-delete",),
    path("chat/rooms/<uuid:room_id>/messages/",MessageListCreateView.as_view(),name="chat-messages",),
    path("chat/rooms/<uuid:room_id>/messages/<uuid:message_id>/",MessageDetailView.as_view(),name="chat-message-detail",),
    path("chat/rooms/<uuid:room_id>/members/",GroupMemberView.as_view(),name="chat-group-members",),
    path("chat/rooms/<uuid:room_id>/members/<uuid:user_id>/",GroupMemberRemoveView.as_view(),name="chat-group-member-remove",),
    path("chat/rooms/<uuid:room_id>/remove-member/",RemoveMemberView.as_view(),name="chat-group-remove-member",),
    path(
        "chat/rooms/<uuid:room_id>/upload/",
        FileUploadView.as_view(),
        name="chat-upload",
    ),
]