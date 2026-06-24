import uuid
from django.db import models
from django.conf import settings


PAYROLL_STATUS_CHOICES = [
    ('draft', 'Draft'), ('pending_approval', 'Pending Approval'),
    ('approved', 'Approved'), ('disbursed', 'Disbursed'),
]


class LateEntryPolicy(models.Model):
    """
    Configurable deduction rules for sessions started beyond grace period.
    Also configures the late entry threshold that triggers automatic half-day deduction.
    FRD §4.8.4 + §4.9.3.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey('branch.Branch', on_delete=models.CASCADE, related_name='late_policies')
    grace_period_minutes = models.IntegerField(default=5)
    deduction_per_minute = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    max_deduction_per_session = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    # 0 = no cap
    absence_deduction_per_day = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    # NEW (FRD §4.8.4): amount deducted per day of unexcused absence

    # NEW (FRD §4.9.3 — Late Entry Rules):
    late_entry_threshold = models.IntegerField(default=3)
    # number of late entries in a calendar month that triggers auto half-day leave deduction
    auto_halfday_deduction = models.BooleanField(default=True)
    # if True: when monthly late count >= threshold, system auto-creates half-day LeaveApplication

    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payroll_late_policies'
        unique_together = ('branch',)

    def __str__(self):
        return f"Late policy — {self.branch} (grace={self.grace_period_minutes}m)"


class PayrollRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey('branch.Branch', on_delete=models.CASCADE, related_name='payroll_runs')
    month = models.IntegerField()
    year = models.IntegerField()
    status = models.CharField(max_length=20, choices=PAYROLL_STATUS_CHOICES, default='draft')
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='generated_payrolls')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_payrolls')
    generated_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'payroll_runs'
        unique_together = ('branch', 'month', 'year')
        ordering = ['-year', '-month']

    def __str__(self):
        return f"Payroll {self.month}/{self.year} — {self.branch} ({self.status})"


class PaySlip(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='payslips')
    faculty = models.ForeignKey('faculty.FacultyProfile', on_delete=models.CASCADE, related_name='payslips', null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payslips', null=True, blank=True)
    basic_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_session_hours = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    # sum of SessionReport.duration_minutes / 60 + QR hours
    hour_based_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # sum of (session_hours_per_subject * subject_hourly_rate)
    late_penalty = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    absence_deductions = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    # NEW (FRD §4.8.4): days absent * absence_deduction_per_day
    leave_deductions = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    retention_deduction = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    other_deductions = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    deduction_note = models.CharField(max_length=300, blank=True)
    bonus = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    attendance_bonus = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    leave_encashment = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    net_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    leaves_taken = models.IntegerField(default=0)
    working_days = models.IntegerField(default=0)
    sessions_conducted = models.IntegerField(default=0)
    is_disbursed = models.BooleanField(default=False)

    class Meta:
        db_table = 'payroll_payslips'

    def __str__(self):
        name = self.faculty.user.name if self.faculty else (self.user.name if self.user else 'Unknown')
        return f"{name} — {self.payroll_run}"


class SessionLatePenaltyLog(models.Model):
    """Audit: which session triggered a late penalty and how much"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payslip = models.ForeignKey(PaySlip, on_delete=models.CASCADE, related_name='late_logs')
    session_report = models.ForeignKey('faculty.SessionReport', on_delete=models.CASCADE)
    scheduled_time = models.TimeField()
    actual_start = models.TimeField()
    late_minutes = models.IntegerField()
    penalty_amount = models.DecimalField(max_digits=8, decimal_places=2)
    grace_applied = models.BooleanField(default=False)

    class Meta:
        db_table = 'payroll_late_penalty_logs'

    def __str__(self):
        return f"Late {self.late_minutes}m → ₹{self.penalty_amount}"

class ExtraHoursApproval(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    faculty = models.ForeignKey('faculty.FacultyProfile', on_delete=models.CASCADE, related_name='extra_hours_requests')
    chapter = models.ForeignKey('batches.Chapter', on_delete=models.CASCADE, related_name='extra_hours_requests')
    payroll_month = models.IntegerField()
    payroll_year = models.IntegerField()
    extra_minutes = models.IntegerField()
    status = models.CharField(
        max_length=20,
        choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')],
        default='pending'
    )
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payroll_extra_hours_approval'
        unique_together = ('faculty', 'chapter', 'payroll_month', 'payroll_year')

    def __str__(self):
        return f"{self.faculty.user.name} - {self.chapter.name} - {self.extra_minutes}m ({self.status})"

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Sum

@receiver(post_save, sender=PaySlip)
@receiver(post_delete, sender=PaySlip)
def update_payroll_total(sender, instance, **kwargs):
    if instance.payroll_run_id:
        try:
            pr = instance.payroll_run
            total = pr.payslips.aggregate(total=Sum('net_salary'))['total'] or 0
            PayrollRun.objects.filter(id=pr.id).update(total_amount=total)
        except PayrollRun.DoesNotExist:
            pass
