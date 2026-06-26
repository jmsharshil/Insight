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
from .serializers import AuditLogSerializer
from .tasks import flush_logs_to_blob
from .blob_service import download_log_file


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
    filterset_fields = {
        "user": ["exact"],
        "user_id": ["exact"],
        "organization": ["exact"],
        "organization_id": ["exact"],
        "action": ["exact"],
        "method": ["exact"],
        "path": ["icontains"],
        "status_code": ["exact"],
        "flushed_to_blob": ["exact"],
        "timestamp": ["gte", "lte", "exact"],
    }
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
    Manually trigger a flush of un-synced logs to blob storage.
    Admin-only.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        flush_logs_to_blob()
        return Response(
            {"detail": "Flush triggered successfully."},
            status=status.HTTP_200_OK,
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
