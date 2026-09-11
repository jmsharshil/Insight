# leads/models.py  (updated — registration fields removed)

from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
import uuid
from auth_user.models import User

FORM_TYPE_CHOICES = [
    ('contact', 'Contact Us'),
    ('inquiry', 'Inquiry Form'),
    # 'registration' removed — handled by onboarding app
]

COURSE_TYPE_CHOICES = [
    ('cseet', 'CSEET'),
    ('cs_executive', 'CS Executive'),
    ('cs_professional', 'CS Professional'),
]

GROUP_MODULE_CHOICES = [
    ('full', 'Full Syllabus'),
    ('both', 'Both Modules'),
    ('module_1', '1st Module'),
    ('module_2', '2nd Module'),
    ('module_3', '3rd Module'),
]

ATTEMPT_TYPE_CHOICES = [
    ('june', 'June'),
    ('oct', 'October'),
    ('feb', 'February'),
    ('dec', 'December'),
]

STAGE_CHOICES = [
    ('new', 'New'),
    ('contacted', 'Contacted'),
    ('interested', 'Interested'),
    ('visit', 'Visit'),
    ('visited', 'Visited'),
    ('follow_up', 'Follow-up'),
    ('converted', 'Converted'),
    ('lost', 'Lost'),
]

QUALIFICATION_TYPE_CHOICES = [
    ('appearing_12', 'Appearing 10+2'),
    ('pass_12', '10+2 Pass or Equivalent'),
    ('cseet_pass', 'CSEET Pass'),
    ('graduate', 'Graduate'),
    ('post_graduate', 'Post Graduate'),
]

BOARD_TYPE_CHOICES = [
    ('gseb', 'Gujarat Board (GSEB)'),
    ('cbse', 'CBSE Board'),
    ('icse', 'ICSE Board'),
]

CATEGORY_TYPE_CHOICES = [
    ('gen', 'General'),
    ('obc', 'OBC'),
    ('sc_st', 'SC/ST'),
]

REFERENCE_TYPE_CHOICES = [
    ('offline_ad', 'Offline Ad'),
    ('existing', 'Existing Student'),
    ('social_media', 'Social Media'),
    ('google', 'Seen on Google'),
    ('seminar', 'Seminar'),
    ('none', 'None of the above'),
    ("other","Other"),
]

STAGE_NEW = 'new'


class Lead(models.Model):

    # ── Branch Scope ──────────────────────────────────────────────────────────
    branch = models.ForeignKey('branch.Branch',null=True,blank=True,on_delete=models.SET_NULL,related_name='leads',)

    # ── Section 1: Common Fields (Contact + Inquiry) ──────────────────────────
    form_type     = models.CharField(max_length=20, choices=FORM_TYPE_CHOICES)
    first_name    = models.CharField(max_length=100)
    email         = models.EmailField(null=True, blank=True)
    phone_student = models.CharField(max_length=15)
    course        = models.CharField(max_length=20, choices=COURSE_TYPE_CHOICES, null=True, blank=True)
    group_module  = models.CharField(max_length=20, choices=GROUP_MODULE_CHOICES, blank=True)
    batch_attempt = models.CharField(max_length=10, choices=ATTEMPT_TYPE_CHOICES, blank=True)
    location      = models.CharField(max_length=100, blank=True)
    consent       = models.BooleanField(default=False)
    current_stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default=STAGE_NEW)
    note          = models.TextField(blank=True, help_text="Latest note added during status update.")
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    # ── lead stage tracking ───────────────────────────────────────────────────────────────
    contacted_at = models.DateField(null=True, blank=True)
    interested_at = models.DateField(null=True, blank=True)
    followup_set_at = models.DateField(null=True, blank=True)
    converted_at = models.DateField(null=True, blank=True)
    visit_set_at = models.DateField(null=True, blank=True)
    lost_at = models.DateField(null=True, blank=True)
    followup_date = models.DateTimeField(null=True, blank=True)
    visit_date = models.DateTimeField(null=True, blank=True)
    is_visited = models.BooleanField(default=False)
    updated_by = models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True)

    # ── Reminders tracking ────────────────────────────────────────────────────────
    reminder_1d_sent = models.BooleanField(default=False)
    reminder_2h_sent = models.BooleanField(default=False)
    last_overdue_reminder_sent = models.DateField(null=True, blank=True)

    # ── Assignment (manual only — no auto-assignment) ──────────────────────────
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_leads',
        help_text="Counsellor / Sales Executive manually assigned to this lead. "
                  "Leave null if unassigned — only senior roles can then view it.",
    )

    # ── Section 2: Personal Info (Inquiry only) ───────────────────────────────
    surname      = models.CharField(max_length=100, blank=True)
    father_name  = models.CharField(max_length=100, blank=True)
    street       = models.TextField(blank=True)
    apartment    = models.CharField(max_length=100, blank=True)
    city         = models.CharField(max_length=100, blank=True)
    state        = models.CharField(max_length=100, blank=True)
    country      = models.CharField(max_length=100, blank=True, default='India')
    phone_father = models.CharField(max_length=15, blank=True)
    qualification = models.CharField(max_length=20, choices=QUALIFICATION_TYPE_CHOICES, blank=True)
    reference    = models.CharField(max_length=20, choices=REFERENCE_TYPE_CHOICES, blank=True)
    inquiry_date = models.DateField(null=True, blank=True)
    reference_name = models.CharField(max_length=100,blank=True)

    # ── Section 3: 10th Education (Inquiry only) ──────────────────────────────
    tenth_medium     = models.CharField(max_length=10, choices=BOARD_TYPE_CHOICES, blank=True)
    tenth_school     = models.CharField(max_length=200, blank=True)
    tenth_coaching   = models.CharField(max_length=200, blank=True)
    tenth_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    tenth_percentile = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # ── Section 4: 12th Education (Inquiry only) ──────────────────────────────
    twelfth_medium     = models.CharField(max_length=10, choices=BOARD_TYPE_CHOICES, blank=True)
    twelfth_school     = models.CharField(max_length=200, blank=True)
    twelfth_coaching   = models.CharField(max_length=200, blank=True)
    twelfth_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    twelfth_percentile = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # ── Section 5: Graduation (Inquiry only) ──────────────────────────────────
    grad_university = models.CharField(max_length=200, blank=True)
    grad_college    = models.CharField(max_length=200, blank=True)
    grad_last_sem   = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'leads'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['form_type']),
            models.Index(fields=['current_stage']),
            models.Index(fields=['course']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.first_name} {self.surname} | {self.form_type} | {self.current_stage}"


class LeadAssignmentLog(models.Model):
    """
    Audit trail for every manual lead assignment / reassignment action.
    Created whenever assigned_to changes on a Lead.
    """
    lead          = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='assignment_logs')
    assigned_from = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', help_text="Previous assignee (null if unassigned before)."
    )
    assigned_to   = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', help_text="New assignee (null means unassigned)."
    )
    changed_by    = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', help_text="Staff member who made the assignment change."
    )
    note       = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'lead_assignment_logs'
        ordering = ['-changed_at']

    def __str__(self):
        frm = self.assigned_from.name if self.assigned_from else 'Unassigned'
        to  = self.assigned_to.name   if self.assigned_to   else 'Unassigned'
        by  = self.changed_by.name    if self.changed_by    else 'System'
        return f"Lead #{self.lead_id}: {frm} → {to} by {by}"


class LeadStage(models.Model):
    lead       = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='stage_history')
    stage      = models.CharField(max_length=20, choices=STAGE_CHOICES)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    note       = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'lead_stages'
        ordering = ['changed_at']

    def __str__(self):
        changed_by = self.changed_by.get_username() if self.changed_by else 'System'
        return f"{self.lead} → {self.stage} by {changed_by}"


class LeadTransferRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='transfer_requests')
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='initiated_transfers'
    )
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_transfers'
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='transferred_leads',
        help_text="The counsellor assigned upon approval."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'lead_transfer_requests'
        ordering = ['-created_at']

    def __str__(self):
        return f"Transfer Request for {self.lead} by {self.requested_by}"

class SalesDailyActivity(models.Model):
    """One field-activity container per sales user and calendar day."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sales_daily_activities',
    )
    activity_date = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sales_daily_activities'
        ordering = ['-activity_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'activity_date'],
                name='unique_sales_activity_per_user_day',
            )
        ]

    def __str__(self):
        return f"{self.user.name} - {self.activity_date}"

SALES_ACTIVITY_PHOTO_TYPES = [
    ('start_selfie', 'Start of Day Selfie'),
    ('start_odometer', 'Start of Day Odometer'),
    ('end_selfie', 'End of Day Selfie'),
    ('end_odometer', 'End of Day Odometer'),
    ('school_interior', 'School Interior'),
    ('school_exterior', 'School Exterior'),
    ('exhibition', 'Exhibition'),
]

class SalesActivityPhoto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    activity = models.ForeignKey(
        SalesDailyActivity,
        on_delete=models.CASCADE,
        related_name='photos',
    )
    photo_type = models.CharField(max_length=30, choices=SALES_ACTIVITY_PHOTO_TYPES)
    photo = models.ImageField(upload_to='sales/activity_photos/')
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    odometer_kms = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    captured_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sales_activity_photos'
        ordering = ['captured_at', 'created_at']

    def __str__(self):
        return f"{self.activity_id} - {self.photo_type}"


ODOMETER_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
]


class OdometerReading(models.Model):
    """
    Daily travel odometer claim linked to a SalesDailyActivity.
    Approved amounts are credited to the user's monthly pay on their payslip.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    activity = models.OneToOneField(
        SalesDailyActivity,
        on_delete=models.CASCADE,
        related_name='odometer_reading',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='odometer_readings',
    )
    start_kms = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    end_kms = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_kms = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    expense_per_km = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Reimbursement rate per kilometer (editable by approver)"
    )
    total_expense = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Calculated as total_kms * expense_per_km"
    )
    status = models.CharField(
        max_length=20,
        choices=ODOMETER_STATUS_CHOICES,
        default='pending'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_odometer_readings'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rejected_odometer_readings'
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    # Monthly Payroll Integration
    payroll_run = models.ForeignKey(
        'payroll.PayrollRun',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='odometer_readings',
        help_text="Payroll run in which this travel expense was included"
    )
    payslip = models.ForeignKey(
        'payroll.PaySlip',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='odometer_readings',
        help_text="Payslip in which this travel expense was credited"
    )
    is_paid = models.BooleanField(
        default=False,
        help_text="True when the corresponding payslip/payroll run has been disbursed"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sales_odometer_readings'
        ordering = ['-activity__activity_date', '-created_at']

    def calculate_totals(self):
        if self.start_kms is not None and self.end_kms is not None:
            self.total_kms = max(Decimal('0.00'), Decimal(str(self.end_kms)) - Decimal(str(self.start_kms)))
        else:
            self.total_kms = Decimal('0.00')

        if self.expense_per_km and self.total_kms:
            self.total_expense = (self.total_kms * Decimal(str(self.expense_per_km))).quantize(Decimal('0.01'))
        else:
            self.total_expense = Decimal('0.00')

    def save(self, *args, **kwargs):
        self.calculate_totals()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Odometer {self.activity.activity_date} - {self.user.name or self.user.email} ({self.total_kms} km, ₹{self.total_expense}) [{self.status}]"