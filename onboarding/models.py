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
    ('approval_pending', 'Approval Pending'),
    ('approved',          'Approved'),
    ('payment_pending',   'Payment Pending'),
    ('payment_submitted', 'Payment Submitted'),
    ('rejected',          'Rejected'),
    ('enrolled',          'Enrolled'),
]

# ── 5 Bank Accounts (round-robin assignment) ─────────────────────────────────
BANK_ACCOUNTS = [
    {
        'id': 1,
        'bank_name': 'State Bank of India (SBI)',
        'account_holder': 'Insight Institute Pvt. Ltd.',
        'account_number': '38976542103',
        'ifsc_code': 'SBIN0001234',
        'branch': 'Ashram Road, Ahmedabad',
        'account_type': 'Current Account',
    },
    {
        'id': 2,
        'bank_name': 'HDFC Bank',
        'account_holder': 'Insight Institute Pvt. Ltd.',
        'account_number': '50200045678901',
        'ifsc_code': 'HDFC0000567',
        'branch': 'CG Road, Ahmedabad',
        'account_type': 'Current Account',
    },
    {
        'id': 3,
        'bank_name': 'ICICI Bank',
        'account_holder': 'Insight Institute Pvt. Ltd.',
        'account_number': '123405001234',
        'ifsc_code': 'ICIC0003456',
        'branch': 'Navrangpura, Ahmedabad',
        'account_type': 'Current Account',
    },
    {
        'id': 4,
        'bank_name': 'Bank of Baroda',
        'account_holder': 'Insight Institute Pvt. Ltd.',
        'account_number': '21340100045678',
        'ifsc_code': 'BARB0AHMEDA',
        'branch': 'Law Garden, Ahmedabad',
        'account_type': 'Current Account',
    },
    {
        'id': 5,
        'bank_name': 'Kotak Mahindra Bank',
        'account_holder': 'Insight Institute Pvt. Ltd.',
        'account_number': '9876543210012',
        'ifsc_code': 'KKBK0007890',
        'branch': 'Prahlad Nagar, Ahmedabad',
        'account_type': 'Current Account',
    },
]


def admission_document_path(instance, filename):
    """All admission documents stored under admissions/<id>/documents/"""
    return f"onboarding/media/{instance.id}/documents/{filename}"


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

    # ── Branch Scope ──────────────────────────────────────────────────────────
    branch = models.ForeignKey('branch.Branch',null=True,blank=True,on_delete=models.SET_NULL,related_name='admissions',)

    # ── Personal Info ─────────────────────────────────────────────────────────
    first_name      = models.CharField(max_length=100)
    surname         = models.CharField(max_length=100)
    father_name     = models.CharField(max_length=100)
    mother_name     = models.CharField(max_length=100)
    dob             = models.DateField(blank=True,null=True)
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

    # ── Counsellor Assignment ─────────────────────────────────────────────────
    assigned_counsellor = models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name='assigned_admissions',limit_choices_to={'role': 'counsellor'},help_text="Counsellor assigned to review this admission.",)

    # ── Batch Attempt Year (for auto batch assignment) ───────────────────────
    attempt_year  = models.PositiveSmallIntegerField(null=True, blank=True)
    fee_structure = models.ForeignKey(
        'fees.FeeStructure',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='admissions',
    )

    # ── Status & Timestamps ───────────────────────────────────────────────────
    status       = models.CharField(max_length=20, choices=ADMISSION_STATUS_CHOICES, default='approval_pending')
    note         = models.TextField(blank=True, help_text="Latest note added during status update.")
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    # ── Fee Payment Tracking ──────────────────────────────────────────────────
    assigned_bank_id      = models.IntegerField(null=True, blank=True, help_text="ID of the bank from BANK_ACCOUNTS assigned to this student.")
    payment_screenshot    = models.FileField(upload_to=admission_document_path, null=True, blank=True)
    transaction_id        = models.CharField(max_length=100, blank=True, help_text="UPI / Bank transaction reference number.")
    payment_note          = models.TextField(blank=True, help_text="Optional note from student regarding payment.")
    payment_submitted_at  = models.DateTimeField(null=True, blank=True)

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