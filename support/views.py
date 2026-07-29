from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import get_user_model
from .models import SupportQuery
from .serializers import SupportQuerySerializer
from chat.notifications import send_system_notification
import logging

logger = logging.getLogger(__name__)
User = get_user_model()

class SupportQueryViewSet(viewsets.ModelViewSet):
    """
    A viewset for viewing and creating support queries.
    Users can view their own queries. Super admins can view all queries.
    """
    serializer_class = SupportQuerySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        org = getattr(user, 'organization', None)
        
        if user.role == 'super_admin':
            return SupportQuery.objects.filter(organization=org) if org else SupportQuery.objects.all()
        return SupportQuery.objects.filter(user=user)

    def perform_create(self, serializer):
        # Save the query
        query = serializer.save()

        # Notify super admins in the same organization
        try:
            org = query.organization
            super_admins = User.objects.filter(role='super_admin', is_active=True)
            if org:
                super_admins = super_admins.filter(organization=org)
                
            for admin in super_admins:
                send_system_notification(
                    user_id=str(admin.id),
                    title=f"New Support Query: {query.title}",
                    body=f"Query from {query.user.email}: {query.description}",
                    metadata={
                        "type": "support_query_created",
                        "query_id": str(query.id)
                    },
                    route="/queries"  # Example route, adjust if there's a specific frontend path
                )
        except Exception as e:
            logger.error(f"Error sending notifications for Support Query {query.id}: {e}")
