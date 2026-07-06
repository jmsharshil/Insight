from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter

from .services import get_role_dashboard, clear_dashboard_cache


class DashboardRateThrottle(UserRateThrottle):
    """Custom throttle for dashboard to prevent abuse while allowing high throughput."""
    rate = '60/minute'  # High limit since cached


class DashboardAPIView(APIView):
    """
    Role-specific Dashboard API - optimized for lowest possible response time.
    
    Features:
    - Per-user Redis caching (5 min TTL)
    - Role-based data scoping and widgets
    - Heavily optimized ORM queries (aggregates, select_related, values())
    - Custom throttling
    - Vary on auth headers for cache correctness
    - Supports all roles defined in auth_user.models.User.ROLE_CHOICES
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [DashboardRateThrottle]

    @method_decorator(cache_page(60 * 5))  # 5 min cache to match reports/
    @method_decorator(vary_on_headers('Authorization'))
    @extend_schema(
        tags=['Dashboard'],
        parameters=[
            OpenApiParameter(name='refresh', type=bool, location=OpenApiParameter.QUERY,
                           description='Force cache refresh (bypass cache)'),
        ],
        responses={200: {'type': 'object', 'properties': {
            'success': {'type': 'boolean'},
            'role': {'type': 'string'},
            'data': {'type': 'object'},
        }}}
    )
    def get(self, request):
        """Return optimized, role-specific dashboard data."""
        refresh = request.query_params.get('refresh') == 'true'
        user = request.user

        if refresh:
            # Clear both page cache and service cache for this user
            clear_dashboard_cache(user)

        data = get_role_dashboard(user)
        
        return Response({
            'success': True,
            'role': user.role,
            'data': data,
            'timestamp': timezone.now().isoformat(),
        })
