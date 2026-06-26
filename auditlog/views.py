"""
API views for the auditlog app.

Endpoints:
  GET /api/audit-logs/              – List audit logs (with filters)
  GET /api/audit-logs/<id>/         – Retrieve a single log entry
  POST /api/audit-logs/flush/       – Manually trigger blob flush (admin only)
  GET /api/audit-logs/by-user/      – Get logs for a specific user + date from blob
"""

from datetime import date

from rest_framework import generics, status, filters
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.http import HttpResponse
from django_filters.rest_framework import DjangoFilterBackend

from .models import AuditLog
from .serializers import AuditLogSerializer, AuditLogFilter
from .tasks import flush_logs_to_blob
from .blob_service import download_log_file
from core.task_queue import TASK_QUEUE


# ── List & Retrieve views ─────────────────────────────────────────

class AuditLogListView(generics.ListAPIView):
    """
    List audit log entries with filtering.

    Query params:
      - user_id: filter by user UUID
      - organization_id: filter by organization UUID
      - action: CREATE / READ / UPDATE / DELETE / LOGIN / LOGOUT / OTHER
      - method: GET / POST / PUT / PATCH / DELETE
      - path: substring match on request path
      - date_from / date_to: timestamp range
      - flushed_to_blob: true / false
    """

    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = AuditLogFilter
    ordering_fields = ["timestamp", "action", "method"]
    ordering = ["-timestamp"]

    def get_queryset(self):
        qs = AuditLog.objects.select_related("user", "organization").all()
        # Non-admin users can only see their own organization's logs
        if self.request.user.role != "admin":
            qs = qs.filter(organization=self.request.user.organization)
        return qs


class AuditLogDetailView(generics.RetrieveAPIView):
    """Retrieve a single audit log entry by ID."""

    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = AuditLog.objects.select_related("user", "organization").all()
        if self.request.user.role != "admin":
            qs = qs.filter(organization=self.request.user.organization)
        return qs


# ── Manual flush trigger ──────────────────────────────────────────

class AuditLogFlushView(APIView):
    """
    Manually trigger a background flush of un-synced logs to blob storage
    (via the task scheduler/queue). Admin-only.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != "admin":
            return Response(
                {"detail": "Admin access required to trigger flush."},
                status=status.HTTP_403_FORBIDDEN,
            )

        TASK_QUEUE.enqueue(flush_logs_to_blob)
        return Response(
            {"detail": "Flush scheduled successfully in background."},
            status=status.HTTP_202_ACCEPTED,
        )


# ── Blob download view ────────────────────────────────────────────

class AuditLogByUserView(APIView):
    """
    Download audit logs for a specific user and date from blob storage.

    Query params:
      - user_name: Name of the user (required)
      - date: YYYY-MM-DD (required)
      - organization_name: Name of the organization (optional, defaults to requester's organization)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_name = request.query_params.get("user_name")
        date_str = request.query_params.get("date")

        if not user_name or not date_str:
            return Response(
                {"detail": "user_name and date query parameters are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            log_date = date.fromisoformat(date_str)
        except ValueError:
            return Response(
                {"detail": "Invalid date format. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        organization_name = request.query_params.get("organization_name") or str(
            request.user.organization.name if request.user.organization else "Unknown_organization"
        )

        # Non-admins can only access their own organization's logs
        if request.user.role != "admin":
            user_org_name = str(
                request.user.organization.name
                if request.user.organization
                else "Unknown_organization"
            )
            if organization_name != user_org_name:
                return Response(
                    {"detail": "You can only access logs for your own organization."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        content = download_log_file(organization_name, user_name, log_date)

        if content is None:
            return Response(
                {"detail": "No log file found for the given parameters."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Return as plain text file download
        response = HttpResponse(content, content_type="text/plain")
        response["Content-Disposition"] = f'attachment; filename="audit_{user_name}_{date_str}.log"'
        return response
