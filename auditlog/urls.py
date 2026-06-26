from django.urls import path
from .views import (
    AuditLogListView,
    AuditLogDetailView,
    AuditLogFlushView,
    AuditLogByUserView,
)

app_name = "auditlog"

urlpatterns = [
    path("", AuditLogListView.as_view(), name="auditlog-list"),
    path("<uuid:pk>/", AuditLogDetailView.as_view(), name="auditlog-detail"),
    path("flush/", AuditLogFlushView.as_view(), name="auditlog-flush"),
    path("by-user/", AuditLogByUserView.as_view(), name="auditlog-by-user"),
]
