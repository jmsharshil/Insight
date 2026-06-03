"""
ASGI config for insight project.

Supports both HTTP and WebSocket protocols.

HTTP requests are handled by Django's standard ASGI application.
WebSocket requests (``/ws/...``) are routed through Django Channels
to the chat consumer.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "insight.settings")

# Initialize Django ASGI application early to ensure apps are loaded
# before importing any Channels routing.
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

import chat.routing  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(
            URLRouter(chat.routing.websocket_urlpatterns)
        ),
    }
)
