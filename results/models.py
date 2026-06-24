import uuid
from django.db import models
from django.conf import settings


RECHECK_STATUS_CHOICES = [
    ('approval_pending', 'Approval Pending'), ('approved', 'Approved'),
    ('rejected', 'Rejected'), ('completed', 'Completed'),
]


class MarkSheet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam = models.ForeignKey('exams.Exam', on_delete=models.CASCADE, related_name='marksheets')
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='marksheets')
    paper_checker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_marksheets')
    marks_obtained = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    is_pass = models.BooleanField(null=True)
    remarks = models.TextField(blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    is_rechecked = models.BooleanField(default=False)
    recheck_request_at = models.DateTimeField(null=True, blank=True)
    is_submitted = models.BooleanField(default=False)
    is_absent = models.BooleanField(default=False)  # True if student did not appear for the exam

    class Meta:
        db_table = 'result_marksheets'

    def __str__(self):
        return f"{self.student} - {self.exam.title} ({self.marks_obtained or 'approval_pending'})"


class RecheckRequest(models.Model):
    """
    Extended per user query: Student can request recheck with reason + upload marksheet/answer sheet.
    Requires admin (ASE) approval; if approved, reassigns to (new) paper_checker.
    Checker can update marks/notes and resubmit (sets status=completed).
    On recheck pending/approved: original paper count removed from payroll (via query filter).
    On resubmit: added to new checker's payment.
    Supports bulk recheck requests for a batch (via dedicated view/endpoint).
    Answer key must be uploaded to Exam before rechecks allowed.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    marksheet = models.ForeignKey(MarkSheet, on_delete=models.CASCADE, related_name='recheck_requests')
    requested_by = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='recheck_requests')
    reason = models.TextField(blank=True)
    uploaded_marksheet = models.FileField(
        upload_to='recheck_uploads/',
        null=True,
        blank=True,
        help_text="Student-uploaded copy of marksheet/answer sheet for re-evaluation."
    )
    checker_notes = models.TextField(blank=True, help_text="Notes from paper checker on recheck/resubmit.")
    status = models.CharField(max_length=20, choices=RECHECK_STATUS_CHOICES, default='approval_pending')

    # ASE who approves/rejects
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reviewed_recheck_requests',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    # Assigned by ASE after approval
    new_checker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='recheck_assignments',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'result_recheck_requests'
        ordering = ['-created_at']

    def __str__(self):
        return f"Recheck {self.marksheet} — {self.status}"


class SubmissionReminderLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    marksheet = models.ForeignKey(MarkSheet, on_delete=models.CASCADE, related_name='reminders')
    sent_at = models.DateTimeField(auto_now_add=True)
    reminder_count = models.IntegerField(default=1)

    class Meta:
        db_table = 'result_submission_reminders'


class PublishedResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam = models.ForeignKey('exams.Exam', on_delete=models.CASCADE, related_name='published_results')
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='published_results')
    marks_obtained = models.DecimalField(max_digits=6, decimal_places=2)
    total_marks = models.IntegerField()
    percentage = models.FloatField()
    is_pass = models.BooleanField()
    rank = models.IntegerField(null=True, blank=True)
    published_at = models.DateTimeField(auto_now_add=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    class Meta:
        db_table = 'result_published'
        unique_together = ('exam', 'student')
        ordering = ['rank']

    def __str__(self):
        return f"{self.student} - {self.exam.title}: {self.marks_obtained}/{self.total_marks}"
