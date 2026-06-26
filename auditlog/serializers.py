from rest_framework import serializers
from django_filters import rest_framework as filters
from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    """Read-only serializer for AuditLog entries."""

    user_email = serializers.CharField(source="user.email", read_only=True, default=None)
    user_name = serializers.CharField(source="user.name", read_only=True, default=None)
    user_role = serializers.CharField(source="user.role", read_only=True, default=None)
    organization_name = serializers.CharField(source="organization.name", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "user",
            "user_email",
            "user_name",
            "user_role",
            "organization",
            "organization_name",
            "action",
            "method",
            "path",
            "endpoint_name",
            "status_code",
            "query_params",
            "request_body",
            "response_summary",
            "ip_address",
            "user_agent",
            "target_model",
            "target_id",
            "timestamp",
            "flushed_to_blob",
        ]
        read_only_fields = fields


class AuditLogFilterSerializer(serializers.Serializer):
    """Query params for filtering audit logs."""

    user_id = serializers.UUIDField(required=False)
    organization_id = serializers.UUIDField(required=False)
    action = serializers.ChoiceField(
        choices=AuditLog.ACTION_CHOICES, required=False
    )
    method = serializers.CharField(required=False)
    path = serializers.CharField(required=False)
    date_from = serializers.DateTimeField(required=False)
    date_to = serializers.DateTimeField(required=False)
    flushed_to_blob = serializers.BooleanField(required=False)


class AuditLogFilter(filters.FilterSet):
    """Django FilterSet with support for date range aliases and organization scoping."""

    date_from = filters.DateTimeFilter(field_name="timestamp", lookup_expr="gte")
    date_to = filters.DateTimeFilter(field_name="timestamp", lookup_expr="lte")
    user_id = filters.UUIDFilter(field_name="user_id")
    organization_id = filters.UUIDFilter(field_name="organization_id")
    path = filters.CharFilter(field_name="path", lookup_expr="icontains")

    class Meta:
        model = AuditLog
        fields = {
            "action": ["exact"],
            "method": ["exact"],
            "status_code": ["exact"],
            "flushed_to_blob": ["exact"],
        }
