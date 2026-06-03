"""
chat/urls.py

REST URL patterns for the chat module.

These are included in the project's ``urls.py`` under the
``api/chat/`` prefix (or ``api/v1/chat/`` depending on project config).
"""

from django.urls import path

from .views import (
    DirectRoomView,
    FileUploadView,
    GroupAddMembersView,
    GroupRemoveMemberView,
    GroupRoomView,
    MessageListCreateView,
    MessageDetailAPIView,
    RoomListView,GroupMembersView,GroupDeleteView
)

urlpatterns = [
    path("chat/rooms/direct/", DirectRoomView.as_view(), name="chat-room-direct"),
    path("chat/rooms/group/", GroupRoomView.as_view(), name="chat-room-group"),
    path("chat/rooms/", RoomListView.as_view(), name="chat-room-list"),
    path("chat/rooms/<uuid:room_id>/members/", GroupMembersView.as_view(), name="group-members"),
    path("chat/rooms/<uuid:room_id>/delete/", GroupDeleteView.as_view(), name="delete-group"),
    path("chat/rooms/<uuid:room_id>/messages/", MessageListCreateView.as_view(), name="chat-messages"),
    path("chat/rooms/<uuid:room_id>/add-members/", GroupAddMembersView.as_view(), name="chat-group-add-members"),
    path("chat/rooms/<uuid:room_id>/remove-member/", GroupRemoveMemberView.as_view(), name="chat-group-remove-member"),
    path("chat/messages/<uuid:message_id>/", MessageDetailAPIView.as_view(), name="chat-message-detail"),
    path("chat/upload/", FileUploadView.as_view(), name="chat-upload"),
]