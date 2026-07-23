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
    GroupUpdateView,
    GroupRoomView,
    MessageListCreateView,
    MessageDetailAPIView,
    RoomListView,RoomDetailView,GroupMembersView,GroupDeleteView
)
from .webhook import WhatsAppWebhookView

urlpatterns = [
    path("chat/rooms/direct/", DirectRoomView.as_view(), name="chat-room-direct"),
    path("chat/rooms/group/", GroupRoomView.as_view(), name="chat-room-group"),
    path("chat/rooms/", RoomListView.as_view(), name="chat-room-list"),
    path("chat/rooms/<uuid:room_id>/", RoomDetailView.as_view(), name="chat-room-detail"),
    path("chat/rooms/<uuid:room_id>/members/", GroupMembersView.as_view(), name="group-members"),
    path("chat/rooms/<uuid:room_id>/delete/", GroupDeleteView.as_view(), name="delete-group"),
    path("chat/rooms/<uuid:room_id>/messages/", MessageListCreateView.as_view(), name="chat-messages"),
    path("chat/rooms/<uuid:room_id>/update-group/", GroupUpdateView.as_view(), name="chat-group-update"),
    path("chat/messages/<uuid:message_id>/", MessageDetailAPIView.as_view(), name="chat-message-detail"),
    path("chat/upload/", FileUploadView.as_view(), name="chat-upload"),
    # WhatsApp Cloud API Webhook (Meta)
    path("whatsapp/webhook/", WhatsAppWebhookView.as_view(), name="whatsapp-webhook"),
]