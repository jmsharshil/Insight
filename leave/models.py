import uuid
from django.db import models
from django.conf import settings


LEAVE_TYPE_CHOICES = [
    ('paid', 'Paid Leave'), ('sick', 'Sick Leave'), ('casual', 'Casual Leave'),
    ('club', 'Club Leave'), ('unpaid', 'Unpaid Leave'),
]
LEAVE_STATUS_CHOICES = [
    ('approval_pending', 'Approval Pending'), ('approved', 'Approved'),
    ('rejected', 'Rejected'), ('cancelled', 'Cancelled'),
]
HALF_DAY_CHOICES = [('morning', 'Morning'), ('afternoon', 'Afternoon')]
PENALTY_TYPE_CHOICES = [
    ('half_day_deduction', 'Half Day Deduction'),
    ('salary_deduction', 'Salary Deduction'),
    ('warning', 'Warning'),
]


class PublicHoliday(models.Model):
    """
    NEW (FRD §4.9.3 — Sandwich Leave Policy):
    Public holidays that are counted as leave days when sandwiched between leave dates.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey('branch.Branch', on_delete=models.CASCADE, related_name='public_holidays')
    date = models.DateField()
    name = models.CharField(max_length=200)
    year = models.IntegerField()
    # denormalised for fast year-based lookups
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'public_holidays'
        unique_together = ('branch', 'date')
        ordering = ['date']

    def __str__(self):
        return f"{self.name} ({self.date})"


class LeavePolicy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey('branch.Branch', on_delete=models.CASCADE, related_name='leave_policies')
    leave_type = models.CharField(max_length=10, choices=LEAVE_TYPE_CHOICES)
    annual_quota = models.IntegerField()
    max_club_days = models.IntegerField(default=5)
    carry_forward = models.BooleanField(default=False)
    max_carry_days = models.IntegerField(default=0)
    min_advance_days = models.IntegerField(default=3)
    allow_half_day = models.BooleanField(default=True)
    sandwich_rule = models.BooleanField(default=False)
    # if True: weekends AND public holidays between leave dates counted as leave
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'leave_policies'
        unique_together = ('branch', 'leave_type')

    def __str__(self):
        return f"{self.branch} — {self.leave_type} ({self.annual_quota}d)"


class LeaveBalance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leave_balances')
    leave_type = models.CharField(max_length=10, choices=LEAVE_TYPE_CHOICES)
    year = models.IntegerField()
    total_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    used_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    carried_forward = models.DecimalField(max_digits=4, decimal_places=1, default=0)

    class Meta:
        db_table = 'leave_balances'
        unique_together = ('user', 'leave_type', 'year')

    @property
    def remaining_days(self):
        return self.total_days + self.carried_forward - self.used_days

    def __str__(self):
        return f"{self.user.name} — {self.leave_type} {self.year}: {self.remaining_days} left"


class LeaveApplication(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    applied_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leave_applications')
    branch = models.ForeignKey('branch.Branch', on_delete=models.CASCADE, related_name='leave_applications')
    leave_type = models.CharField(max_length=10, choices=LEAVE_TYPE_CHOICES)
    from_date = models.DateField()
    to_date = models.DateField()
    is_half_day = models.BooleanField(default=False)
    half_day_session = models.CharField(max_length=10, choices=HALF_DAY_CHOICES, blank=True)
    total_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    reason = models.TextField()

    supporting_document = models.FileField(upload_to='leave/documents/', null=True, blank=True)
    # NEW (FRD §4.9.2 + §4.9.1): optional for all; required for sick leave > 2 days

    is_auto_generated = models.BooleanField(default=False)
    # NEW (FRD §4.9.3): True when auto-created by late entry threshold task

    status = models.CharField(max_length=20, choices=LEAVE_STATUS_CHOICES, default='approval_pending')

    # Multi-level approval (FRD §4.9.2)
    first_approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='first_approvals')
    first_approved_at = models.DateTimeField(null=True, blank=True)
    second_approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='second_approvals')
    second_approved_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_leaves')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'leave_applications'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.applied_by.name} — {self.leave_type} ({self.from_date} → {self.to_date}) [{self.status}]"


class LateEntryRecord(models.Model):
    """
    FRD §4.9.3: tracks late arrivals via QR scan or manual entry.
    When monthly count >= LateEntryPolicy.late_entry_threshold,
    the system automatically creates a half-day LeaveApplication.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='late_entries')
    branch = models.ForeignKey('branch.Branch', on_delete=models.CASCADE)
    date = models.DateField()
    expected_time = models.TimeField()
    actual_time = models.TimeField()
    late_minutes = models.IntegerField()
    grace_minutes = models.IntegerField(default=15)
    is_penalized = models.BooleanField(default=False)
    penalty_type = models.CharField(max_length=20, choices=PENALTY_TYPE_CHOICES, blank=True)
    auto_deduction_triggered = models.BooleanField(default=False)
    # NEW: True when this record pushed monthly count over threshold
    notes = models.CharField(max_length=300, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_late_entries')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'late_entry_records'
        ordering = ['-date']

    def __str__(self):
        return f"{self.user.name} late {self.late_minutes}m on {self.date}"
