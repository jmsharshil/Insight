"""
chat/routing.py

WebSocket URL patterns for the chat module.

Registered in insight/asgi.py under the 'websocket' protocol router.
"""

from django.urls import path

from .consumers import ChatConsumer

websocket_urlpatterns = [
    # ws://host/ws/chat/<room_id>/?token=<jwt>
    path("ws/chat/<uuid:room_id>/", ChatConsumer.as_asgi()),
]
