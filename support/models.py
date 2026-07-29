from django.db import models
from django.conf import settings
import uuid

class SupportQuery(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'auth_user.Organization',
        on_delete=models.CASCADE,
        related_name='support_queries',
        null=True,
        blank=True
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='support_queries',
        help_text="The user who raised the query."
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    attachment = models.FileField(upload_to='support_attachments/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} by {self.user.email}"
