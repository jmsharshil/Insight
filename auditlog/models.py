import uuid
from django.db import models
from django.utils import timezone
from auth_user.models import User, Organization


class AuditLog(models.Model):
    """
    Stores every user action performed on the system.
    Logs are also periodically flushed to Azure Blob Storage as JSON files
    organized by organization/user/date.
    """

    ACTION_CHOICES = [
        ("CREATE", "Create"),
        ("READ", "Read"),
        ("UPDATE", "Update"),
        ("DELETE", "Delete"),
        ("LOGIN", "Login"),
        ("LOGOUT", "Logout"),
        ("OTHER", "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        help_text="User who performed the action. NULL if anonymous.",
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        help_text="Organization the user belongs to.",
    )

    # Action details
    action = models.CharField(max_length=10, choices=ACTION_CHOICES, default="OTHER")
    method = models.CharField(max_length=10, help_text="HTTP method (GET, POST, etc.)")
    path = models.TextField(help_text="Full request path")
    endpoint_name = models.CharField(max_length=255, blank=True, default="", help_text="DRF view name if available")
    event = models.CharField(max_length=255, blank=True, default="", help_text="Human readable event based on API")
    status_code = models.PositiveIntegerField(null=True, blank=True, help_text="HTTP response status code")

    # Request / Response metadata
    query_params = models.TextField(blank=True, default="", help_text="Query string parameters")
    request_body = models.TextField(blank=True, default="", help_text="Sanitized request body (passwords removed)")
    response_summary = models.TextField(blank=True, default="", help_text="Short summary of the response")
    ip_address = models.CharField(
        max_length=45, 
        null=True, 
        blank=True,
        help_text="Client IP address (IPv4, IPv6, or with port if proxy adds it)"
    )
    user_agent = models.TextField(blank=True, default="")

    # Target object (generic reference)
    target_model = models.CharField(max_length=255, blank=True, default="", help_text="e.g. 'jobs.JobApplication'")
    target_id = models.CharField(max_length=255, blank=True, default="", help_text="PK of the affected object")

    # Timestamps
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    # Blob storage sync flag
    flushed_to_blob = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this log has been written to a blob file.",
    )

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user", "timestamp"]),
            models.Index(fields=["organization", "timestamp"]),
            models.Index(fields=["action", "timestamp"]),
            models.Index(fields=["flushed_to_blob", "timestamp"]),
        ]

    def __str__(self):
        user_str = self.user.email if self.user else "Anonymous"
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {user_str} {self.method} {self.path} -> {self.status_code}"
