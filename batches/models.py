import uuid
from django.db import models


class Batch(models.Model):
    """
    Stub model — will be expanded when the full batches module is built.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.CASCADE,
        related_name='batches',
    )
    course = models.CharField(max_length=50, blank=True)
    session_start_time = models.TimeField(
        null=True,
        blank=True,
        help_text='Start time used by attendance delay tasks.',
    )
    session_end_time = models.TimeField(
        null=True,
        blank=True,
        help_text='End time used by attendance checkout tasks.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'batches'
        verbose_name_plural = 'batches'

    def __str__(self):
        return self.name


class Subject(models.Model):
    """Subject taught within a batch."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, blank=True)
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='subjects', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'subjects'

    def __str__(self):
        return self.name
