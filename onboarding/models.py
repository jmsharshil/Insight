from django.db import models

# Create your models here.
from django.db import models
from django.conf import settings


# ── Re-use choice constants from leads (or duplicate them here if leads app is separate) ──
from leads.models import (
    COURSE_TYPE_CHOICES,
    GROUP_MODULE_CHOICES,
    ATTEMPT_TYPE_CHOICES,
    QUALIFICATION_TYPE_CHOICES,
    BOARD_TYPE_CHOICES,
    CATEGORY_TYPE_CHOICES,
    REFERENCE_TYPE_CHOICES,
)

ADMISSION_STATUS_CHOICES = [
    ('pending',  'Pending Review'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('enrolled', 'Enrolled'),
]


def admission_document_path(instance, filename):
    """All admission documents stored under admissions/<id>/documents/"""
    return f"admissions/{instance.id}/documents/{filename}"


class Admission(models.Model):

    # ── Optional back-link to a Lead ──────────────────────────────────────────
    # If the student had previously submitted an inquiry, link it here.
    lead = models.OneToOneField(
        'leads.Lead',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='admission',
        help_text="The inquiry lead this admission originated from, if any.",
    )

    # ── Personal Info ─────────────────────────────────────────────────────────
    first_name      = models.CharField(max_length=100)
    surname         = models.CharField(max_length=100)
    father_name     = models.CharField(max_length=100)
    mother_name     = models.CharField(max_length=100)
    dob             = models.DateField()
    category        = models.CharField(max_length=10, choices=CATEGORY_TYPE_CHOICES)

    # ── Contact ───────────────────────────────────────────────────────────────
    email           = models.EmailField()
    email_parent    = models.EmailField()
    phone_student   = models.CharField(max_length=15)
    phone_student_2 = models.CharField(max_length=15, blank=True)
    phone_father    = models.CharField(max_length=15)
    phone_father_2  = models.CharField(max_length=15, blank=True)

    # ── Address ───────────────────────────────────────────────────────────────
    street    = models.TextField()
    apartment = models.CharField(max_length=100, blank=True)
    city      = models.CharField(max_length=100)
    state     = models.CharField(max_length=100)
    pincode   = models.CharField(max_length=10)
    country   = models.CharField(max_length=100, default='India')

    # ── Course Details ────────────────────────────────────────────────────────
    course        = models.CharField(max_length=20, choices=COURSE_TYPE_CHOICES)
    group_module  = models.CharField(max_length=20, choices=GROUP_MODULE_CHOICES)
    batch_attempt = models.CharField(max_length=10, choices=ATTEMPT_TYPE_CHOICES)
    location      = models.CharField(max_length=100)

    # ── Qualification & Reference ─────────────────────────────────────────────
    qualification = models.CharField(max_length=20, choices=QUALIFICATION_TYPE_CHOICES)
    reference     = models.CharField(max_length=20, choices=REFERENCE_TYPE_CHOICES)
    consent       = models.BooleanField(default=False)

    # ── 10th Education ────────────────────────────────────────────────────────
    tenth_medium     = models.CharField(max_length=10, choices=BOARD_TYPE_CHOICES)
    tenth_school     = models.CharField(max_length=200)
    tenth_coaching   = models.CharField(max_length=200, blank=True)
    tenth_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    tenth_percentile = models.DecimalField(max_digits=5, decimal_places=2)

    # ── 12th Education ────────────────────────────────────────────────────────
    twelfth_medium     = models.CharField(max_length=10, choices=BOARD_TYPE_CHOICES)
    twelfth_school     = models.CharField(max_length=200)
    twelfth_coaching   = models.CharField(max_length=200, blank=True)
    twelfth_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    twelfth_percentile = models.DecimalField(max_digits=5, decimal_places=2)

    # ── Graduation ────────────────────────────────────────────────────────────
    grad_university = models.CharField(max_length=200, blank=True)
    grad_college    = models.CharField(max_length=200, blank=True)
    grad_last_sem   = models.CharField(max_length=200, blank=True)

    # ── Documents (Required) ──────────────────────────────────────────────────
    doc_signature       = models.FileField(upload_to=admission_document_path)
    doc_photo           = models.FileField(upload_to=admission_document_path)
    doc_dob_certificate = models.FileField(upload_to=admission_document_path)
    doc_id_card         = models.FileField(upload_to=admission_document_path)

    # ── Documents (Optional) ──────────────────────────────────────────────────
    doc_twelfth_receipt   = models.FileField(upload_to=admission_document_path, null=True, blank=True)
    doc_twelfth_marksheet = models.FileField(upload_to=admission_document_path, null=True, blank=True)
    doc_category_cert     = models.FileField(upload_to=admission_document_path, null=True, blank=True)

    # ── Status & Timestamps ───────────────────────────────────────────────────
    status       = models.CharField(max_length=20, choices=ADMISSION_STATUS_CHOICES, default='pending')
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'admissions'
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['course']),
            models.Index(fields=['submitted_at']),
        ]

    def __str__(self):
        return f"{self.first_name} {self.surname} | {self.course} | {self.status}"


class AdmissionStatusHistory(models.Model):
    """Tracks every status change on an Admission."""
    admission  = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='status_history')
    status     = models.CharField(max_length=20, choices=ADMISSION_STATUS_CHOICES)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    note       = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'admission_status_history'
        ordering = ['changed_at']

    def __str__(self):
        changed_by = self.changed_by.get_full_name() if self.changed_by else 'System'
        return f"{self.admission} → {self.status} by {changed_by}"