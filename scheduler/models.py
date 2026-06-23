# scheduler/models.py

import uuid
from django.db import models
from django.utils import timezone


class ScheduledTask(models.Model):
    """
    Persists every scheduled/recurring background task so that incomplete
    tasks survive a service restart and can be re-scheduled automatically.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ── What to run ──────────────────────────────────────────────
    task_type = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Registry key, e.g. 'interview_feedback_reminder'",
    )
    task_kwargs = models.JSONField(
        default=dict,
        blank=True,
        help_text="Serialisable keyword arguments passed to the task function",
    )

    # ── Lifecycle ────────────────────────────────────────────────
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
        db_index=True,
    )
    scheduled_at = models.DateTimeField(
        db_index=True,
        help_text="When the task should next execute",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    # ── Retry ────────────────────────────────────────────────────
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)

    # ── Recurrence ───────────────────────────────────────────────
    is_recurring = models.BooleanField(
        default=False,
        help_text="If True the task auto-reschedules after completion",
    )
    interval_seconds = models.IntegerField(
        null=True,
        blank=True,
        help_text="Seconds between recurring executions",
    )

    # ── Timestamps ───────────────────────────────────────────────
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "scheduled_at"],
                name="idx_sched_status_at",
            ),
        ]

    def __str__(self):
        return (
            f"{self.task_type} | {self.status} | "
            f"scheduled={self.scheduled_at:%Y-%m-%d %H:%M}"
        )
