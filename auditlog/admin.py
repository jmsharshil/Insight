from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = [
        "timestamp", "user", "organization", "action", "method",
        "path", "status_code", "flushed_to_blob",
    ]
    list_filter = ["action", "method", "flushed_to_blob", "timestamp"]
    search_fields = ["path", "user__email", "user__name", "ip_address"]
    readonly_fields = [
        "id", "user", "organization", "action", "method", "path",
        "endpoint_name", "status_code", "query_params", "request_body",
        "response_summary", "ip_address", "user_agent", "target_model",
        "target_id", "timestamp", "flushed_to_blob",
    ]
    date_hierarchy = "timestamp"
    list_per_page = 50
