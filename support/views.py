from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import get_user_model
from .models import SupportQuery, SupportQueryMessage
from .serializers import SupportQuerySerializer, SupportQueryMessageSerializer
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
            
        from django.db.models import Q
        return SupportQuery.objects.filter(Q(user=user) | Q(assigned_to=user))

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

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        query = self.get_object()
        
        # Only super admins or the assigned user can resolve
        if request.user.role != 'super_admin' and request.user != query.assigned_to:
            return Response({"detail": "Not authorized to resolve queries."}, status=status.HTTP_403_FORBIDDEN)
            
        message_text = request.data.get('message')
        if not message_text:
            return Response({"detail": "Message is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        attachment = request.data.get('attachment')
        
        msg = SupportQueryMessage.objects.create(
            query=query,
            sender=request.user,
            message=message_text,
            attachment=attachment,
            is_resolution=True
        )
        
        query.status = 'resolved'
        query.save()
        
        # Notify the original user
        try:
            send_system_notification(
                user_id=str(query.user.id),
                title=f"Support Query Resolved: {query.title}",
                body=f"Your query was resolved by {request.user.email}.",
                metadata={
                    "type": "support_query_resolved",
                    "query_id": str(query.id)
                },
                route=f"/queries/{query.id}"
            )
        except Exception as e:
            logger.error(f"Error sending resolve notification: {e}")
            
        return Response(SupportQuerySerializer(query).data)

    @action(detail=True, methods=['post'])
    def reply(self, request, pk=None):
        query = self.get_object()
        
        message_text = request.data.get('message')
        if not message_text:
            return Response({"detail": "Message is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        attachment = request.data.get('attachment')
        
        msg = SupportQueryMessage.objects.create(
            query=query,
            sender=request.user,
            message=message_text,
            attachment=attachment,
            is_resolution=False
        )
        
        # If user replies to a resolved query, reopen it
        if request.user == query.user and query.status == 'resolved':
            query.status = 'reopened'
            query.save()
            
        # Notify appropriately
        try:
            if request.user == query.user:
                # User replied, notify admins
                org = query.organization
                super_admins = User.objects.filter(role='super_admin', is_active=True)
                if org:
                    super_admins = super_admins.filter(organization=org)
                for admin in super_admins:
                    send_system_notification(
                        user_id=str(admin.id),
                        title=f"New Reply to Support Query: {query.title}",
                        body=f"{request.user.email} replied to the query.",
                        metadata={"type": "support_query_reply", "query_id": str(query.id)},
                        route=f"/queries/{query.id}"
                    )
            else:
                # Admin replied, notify user
                send_system_notification(
                    user_id=str(query.user.id),
                    title=f"New Reply to Support Query: {query.title}",
                    body=f"{request.user.email} replied to your query.",
                    metadata={"type": "support_query_reply", "query_id": str(query.id)},
                    route=f"/queries/{query.id}"
                )
        except Exception as e:
            logger.error(f"Error sending reply notification: {e}")
            
        return Response(SupportQuerySerializer(query).data)

    @action(detail=True, methods=['post'])
    def forward(self, request, pk=None):
        query = self.get_object()
        
        # Only super_admin or current assignee can forward
        if request.user.role != 'super_admin' and request.user != query.assigned_to:
            return Response({"detail": "Not authorized to forward this query."}, status=status.HTTP_403_FORBIDDEN)
            
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({"detail": "user_id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
            
        query.assigned_to = target_user
        query.save()
        
        # Notify the assigned user
        try:
            send_system_notification(
                user_id=str(target_user.id),
                title=f"Support Query Forwarded: {query.title}",
                body=f"A query from {query.user.email} has been forwarded to you.",
                metadata={"type": "support_query_forwarded", "query_id": str(query.id)},
                route=f"/queries/{query.id}"
            )
        except Exception as e:
            logger.error(f"Error sending forward notification: {e}")
            
        return Response(SupportQuerySerializer(query).data)
