"""
WebSocket URL patterns for the chat module.
"""

from django.urls import path

from .consumers import ChatConsumer

websocket_urlpatterns = [
    path("ws/chat/<uuid:room_id>/", ChatConsumer.as_asgi()),
]