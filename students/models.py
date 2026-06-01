import uuid
from django.db import models
from django.conf import settings


class StudentProfile(models.Model):
    """
    Stub model — will be expanded when the full students module is built.
    Contains the minimum fields referenced by the attendance app.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='studentprofile',
    )
    roll_number = models.CharField(max_length=50, unique=True)
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='students',
    )
    batch = models.ForeignKey(
        'batches.Batch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='students',
    )
    is_active = models.BooleanField(default=True)
    qr_blocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'student_profiles'

    def __str__(self):
        return f"{self.user.name} ({self.roll_number})"
