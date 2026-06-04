import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "insight.settings")

# Initialise Django before importing anything that touches ORM / settings.
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack          # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from chat.routing import websocket_urlpatterns          # noqa: E402

application = ProtocolTypeRouter(
    {
        # Standard Django HTTP requests
        "http": django_asgi_app,

        # WebSocket connections.
        # AllowedHostsOriginValidator is intentionally omitted:
        #   - It rejects clients that omit or send a non-matching Origin header
        #     (common in testing tools and mobile apps).
        #   - Security is handled by JWT token validation inside ChatConsumer
        #     (invalid/missing token → close 4001, non-participant → close 4003).
        "websocket": AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        ),
    }
)
