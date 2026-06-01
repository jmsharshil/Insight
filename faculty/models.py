import uuid
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator


LEVEL_CHOICES = [('executive', 'Executive'), ('professional', 'Professional')]
EMPLOYMENT_TYPE_CHOICES = [
    ('full_time', 'Full Time'), ('part_time', 'Part Time'), ('contract', 'Contract'),
]
SCAN_TYPE_CHOICES = [('check_in', 'Check In'), ('check_out', 'Check Out')]
SESSION_STATUS_CHOICES = [('in_progress', 'In Progress'), ('completed', 'Completed')]


class FacultyProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='faculty_profile')
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='faculty_profiles')
    employee_id = models.CharField(max_length=30, unique=True)
    photo = models.ImageField(upload_to='faculty/photos/', null=True, blank=True)
    # NEW (FRD §4.8.1): profile photo field
    qualification = models.CharField(max_length=200)
    specialization = models.CharField(max_length=200)
    subject_expertise = models.CharField(max_length=300, blank=True)
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='executive')
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, default='full_time')
    joining_date = models.DateField()
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    # default hourly rate; overridden per subject by SubjectHourlyRate
    salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # fixed monthly salary for full_time employees
    bank_account = models.CharField(max_length=30, blank=True)
    ifsc_code = models.CharField(max_length=15, blank=True)
    pan_number = models.CharField(max_length=15, blank=True)
    qr_code = models.ImageField(upload_to='qr/faculty/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'faculty_profiles'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee_id} — {self.user.name}"


class SubjectHourlyRate(models.Model):
    """
    NEW (FRD §4.8.4): configurable hourly rate per subject per faculty.
    If a record exists for a (faculty, subject) pair, payroll uses this rate.
    Falls back to FacultyProfile.hourly_rate if no subject-specific rate exists.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    faculty = models.ForeignKey(FacultyProfile, on_delete=models.CASCADE, related_name='subject_rates')
    subject = models.ForeignKey('batches.Subject', on_delete=models.CASCADE, related_name='faculty_rates')
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2)
    effective_from = models.DateField()
    # rate applies from this date; use latest record before payroll month
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'faculty_subject_hourly_rates'
        unique_together = ('faculty', 'subject', 'effective_from')
        ordering = ['-effective_from']

    def __str__(self):
        return f"{self.faculty.employee_id} — {self.subject.name}: ₹{self.hourly_rate}"


class FacultyQRScanLog(models.Model):
    """
    FRD §4.8.2: Faculty check-in and check-out via QR scan at institution premises.
    Same infrastructure as student attendance (QRScanLog in apps/attendance).
    Late entry is logged and linked to payroll penalty computation.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    faculty = models.ForeignKey(FacultyProfile, on_delete=models.CASCADE, related_name='qr_scans')
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE)
    scanned_at = models.DateTimeField(auto_now_add=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    scan_type = models.CharField(max_length=10, choices=SCAN_TYPE_CHOICES, default='check_in')
    is_late = models.BooleanField(default=False)
    # True if scanned after expected start time + grace period
    late_minutes = models.IntegerField(default=0)

    class Meta:
        db_table = 'faculty_qr_scans'
        ordering = ['-scanned_at']

    def __str__(self):
        return f"{self.faculty.employee_id} {self.scan_type} @ {self.scanned_at}"


class SessionReport(models.Model):
    """
    FRD §4.8.3: Faculty submits session report via mobile app after each teaching session.
    Fields: subject, topic/chapter covered, completion_percentage, remarks.
    Admin Senior Executive and Branch Manager can review submitted session reports.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    faculty = models.ForeignKey(FacultyProfile, on_delete=models.CASCADE, related_name='session_reports')
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE)
    batch = models.ForeignKey('batches.Batch', on_delete=models.CASCADE, related_name='session_reports')
    subject = models.ForeignKey('batches.Subject', on_delete=models.CASCADE, related_name='session_reports')
    timetable_slot = models.ForeignKey(
        'batches.Subject', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='session_reports_timetable',
    )
    # FK to timetable slot — using Subject as stand-in since TimetableSlot does not exist yet
    session_date = models.DateField()
    chapter_covered = models.CharField(max_length=300)
    topics_covered = models.TextField()
    completion_percentage = models.IntegerField(
        default=100,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    # NEW (FRD §4.8.3): % of planned session content covered
    status = models.CharField(max_length=20, choices=SESSION_STATUS_CHOICES, default='completed')
    start_time = models.TimeField()
    end_time = models.TimeField()
    duration_minutes = models.IntegerField(default=0)
    # auto-computed: (end_time - start_time) in minutes
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'faculty_session_reports'
        ordering = ['-session_date', '-start_time']

    def save(self, *args, **kwargs):
        # Auto-compute duration
        from datetime import datetime, timedelta
        start_dt = datetime.combine(datetime.today(), self.start_time)
        end_dt = datetime.combine(datetime.today(), self.end_time)
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
        self.duration_minutes = int((end_dt - start_dt).total_seconds() / 60)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.faculty.employee_id} — {self.subject} on {self.session_date}"
