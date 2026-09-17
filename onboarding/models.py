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
    ('form_pending',      'Form Pending'),
    ('payment_pending',   'Payment Pending'),
    ('payment_submitted', 'Payment Submitted'),
    ('rejected',          'Rejected'),
    ('enrolled',          'Enrolled'),
    ('approval_pending',  'Approval Pending'),
    ('approved',          'Approved'),
]

PAYMENT_TYPE_CHOICES = [
    ('full_payment', 'Full Payment'),
    ('finance', 'Finance'),
]

ICSI_FEES_PAYMENT_CHOICES = [
    ('pay_yourself', 'Pay Yourself'),
    ('pay_through_institute', 'Pay through Institute'),
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
    surname         = models.CharField(max_length=100, blank=True, null=True)
    father_name     = models.CharField(max_length=100, blank=True, null=True)
    mother_name     = models.CharField(max_length=100, blank=True, null=True)
    dob             = models.DateField(blank=True,null=True)
    category        = models.CharField(max_length=10, choices=CATEGORY_TYPE_CHOICES, blank=True, null=True)

    # ── Contact ───────────────────────────────────────────────────────────────
    email           = models.EmailField(blank=True, null=True)
    email_parent    = models.EmailField(blank=True, null=True)
    phone_student   = models.CharField(max_length=15)
    phone_student_2 = models.CharField(max_length=15, blank=True)
    phone_father    = models.CharField(max_length=15, blank=True, null=True)
    phone_father_2  = models.CharField(max_length=15, blank=True)

    # ── Address ───────────────────────────────────────────────────────────────
    street    = models.TextField(blank=True, null=True)
    apartment = models.CharField(max_length=100, blank=True)
    city      = models.CharField(max_length=100, blank=True, null=True)
    state     = models.CharField(max_length=100, blank=True, null=True)
    pincode   = models.CharField(max_length=10, blank=True, null=True)
    country   = models.CharField(max_length=100, default='India', blank=True, null=True)

    # ── Course Details ────────────────────────────────────────────────────────
    course        = models.CharField(max_length=20, choices=COURSE_TYPE_CHOICES, blank=True, null=True)
    group_module  = models.CharField(max_length=20, choices=GROUP_MODULE_CHOICES, blank=True, null=True)
    batch_attempt = models.CharField(max_length=10, choices=ATTEMPT_TYPE_CHOICES, blank=True, null=True)
    location      = models.CharField(max_length=100, blank=True, null=True)

    # ── Qualification & Reference ─────────────────────────────────────────────
    qualification = models.CharField(max_length=20, choices=QUALIFICATION_TYPE_CHOICES, blank=True, null=True)
    reference     = models.CharField(max_length=20, choices=REFERENCE_TYPE_CHOICES, blank=True, null=True)
    consent       = models.BooleanField(default=False)
    reference_name = models.CharField(max_length=100,blank=True)

    # ── 10th Education ────────────────────────────────────────────────────────
    tenth_medium     = models.CharField(max_length=10, choices=BOARD_TYPE_CHOICES, blank=True, null=True)
    tenth_school     = models.CharField(max_length=200, blank=True, null=True)
    tenth_coaching   = models.CharField(max_length=200, blank=True)
    tenth_percentage = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    tenth_percentile = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)

    # ── 12th Education ────────────────────────────────────────────────────────
    twelfth_medium     = models.CharField(max_length=10, choices=BOARD_TYPE_CHOICES, blank=True, null=True)
    twelfth_school     = models.CharField(max_length=200, blank=True, null=True)
    twelfth_coaching   = models.CharField(max_length=200, blank=True)
    twelfth_percentage = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    twelfth_percentile = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)

    # ── Graduation ────────────────────────────────────────────────────────────
    grad_university = models.CharField(max_length=200, blank=True)
    grad_college    = models.CharField(max_length=200, blank=True)
    grad_last_sem   = models.CharField(max_length=200, blank=True)

    # ── Documents (Required) ──────────────────────────────────────────────────
    doc_signature       = models.FileField(upload_to=admission_document_path, blank=True, null=True)
    doc_photo           = models.FileField(upload_to=admission_document_path, blank=True, null=True)
    doc_dob_certificate = models.FileField(upload_to=admission_document_path, blank=True, null=True)
    doc_id_card         = models.FileField(upload_to=admission_document_path, blank=True, null=True)

    # ── Documents (Optional) ──────────────────────────────────────────────────
    doc_tenth_marksheet   = models.FileField(upload_to=admission_document_path, null=True, blank=True)
    doc_twelfth_receipt   = models.FileField(upload_to=admission_document_path, null=True, blank=True)
    doc_twelfth_marksheet = models.FileField(upload_to=admission_document_path, null=True, blank=True)
    doc_category_cert     = models.FileField(upload_to=admission_document_path, null=True, blank=True)
    doc_pan_card          = models.FileField(upload_to=admission_document_path, null=True, blank=True)

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
    
    # ── Payment Options ───────────────────────────────────────────────────────
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES, blank=True, null=True)
    icsi_fees_payment = models.CharField(max_length=30, choices=ICSI_FEES_PAYMENT_CHOICES, blank=True, null=True)

    # ── Status & Timestamps ───────────────────────────────────────────────────
    status       = models.CharField(max_length=20, choices=ADMISSION_STATUS_CHOICES, default='form_pending')
    note         = models.TextField(blank=True, help_text="Latest note added during status update.")
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    
    #Razor Pay
    razorpay_payment_link = models.URLField(blank=True, null=True)
    razorpay_payment_link_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    
    # ── Fee Payment Tracking ──────────────────────────────────────────────────
    bank_account = models.ForeignKey(
        'fees.BankAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='admissions',
        help_text="Bank account assigned for this admission's fee payment (threshold-aware selection).",
    )
    payment_screenshot    = models.FileField(upload_to=admission_document_path, null=True, blank=True)
    transaction_id        = models.CharField(max_length=100, blank=True, help_text="UPI / Bank transaction reference number.")
    payment_note          = models.TextField(blank=True, help_text="Optional note from student regarding payment.")
    payment_submitted_at  = models.DateTimeField(null=True, blank=True)
    payment_amount        = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Amount paid by the student.")

    class Meta:
        db_table = 'admissions'
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['course']),
            models.Index(fields=['submitted_at']),
            models.Index(fields=['bank_account']),
        ]

    def __str__(self):
        return f"{self.first_name} {self.surname} | {self.course} | {self.status}"

    def assign_payment_bank_account(self, bank_account, *, status='payment_pending', note='Form submitted. Waiting for fee payment.'):
        """Assign a bank account only once so subsequent updates keep the original selection."""
        if self.bank_account:
            return False

        self.bank_account = bank_account
        self.status = status
        self.note = note
        self.save(update_fields=['bank_account', 'status', 'note', 'updated_at'])
        return True


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
        changed_by = self.changed_by.get_username() if self.changed_by else 'System'
        return f"{self.admission} → {self.status} by {changed_by}"