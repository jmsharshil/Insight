import uuid
from django.db import models
from django.conf import settings


# ═══════════════════════════════════════════════════════════════════════════════
# CHOICES
# ═══════════════════════════════════════════════════════════════════════════════

ATTENDANCE_STATUS_CHOICES = [
    ('present', 'Present'),
    ('absent', 'Absent'),
    ('late', 'Late'),
    ('half_day', 'Half Day'),
    ('on_leave', 'On Leave'),
    ('checkout_pending', 'Checkout Pending'),
]

SCAN_TYPE_CHOICES = [
    ('check_in', 'Check In'),
    ('check_out', 'Check Out'),
    ('exam_entry', 'Exam Entry'),
]

ALERT_TYPE_CHOICES = [
    ('low_attendance', 'Low Attendance'),
    ('absent_streak', 'Absent Streak'),
    # FRD §4.4.2 Delay Alerts
    ('checkin_delay_15', 'Check-in Delay 15 min'),
    ('checkin_delay_30', 'Check-in Delay 30 min'),
    # FRD §4.4.2 Missing Scan Alerts (v3: split from single 'missing_scan')
    ('missing_checkout_scan', 'Missing Check-out Scan'),
    ('missing_checkin_scan', 'Missing Check-in Scan'),
    # Violation threshold
    ('violation', 'Violation'),
]

VIOLATION_TYPE_CHOICES = [
    ('missing_checkout', 'Missing Check-out'),
    ('no_show', 'No Show'),
    ('late_entry', 'Late Entry'),
    ('missing_checkin_scan', 'Missing Check-in Scan'),
    # v3: FRD §4.4.3 — manual admin types
    ('unauthorised_absence', 'Unauthorised Absence'),
    ('repeated_delay', 'Repeated Delay'),
]


# ═══════════════════════════════════════════════════════════════════════════════
# AttendanceRecord
# ═══════════════════════════════════════════════════════════════════════════════

class AttendanceRecord(models.Model):
    """
    One record per student per date.
    Tracks presence STATUS + raw check-in / check-out timestamps.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ── Student / Batch / Branch links ────────────────────────────────────────
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='attendance_records',
    )
    batch = models.ForeignKey(
        'batches.Batch',
        on_delete=models.SET_NULL,
        null=True,
        related_name='attendance_records',
    )
    branch = models.ForeignKey(
        'branch.Branch',
        on_delete=models.CASCADE,
        related_name='attendance_records',
    )

    # ── Attendance data ───────────────────────────────────────────────────────
    date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=ATTENDANCE_STATUS_CHOICES,
        default='absent',
    )

    # ── Entry / Exit ──────────────────────────────────────────────────────────
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)

    # ── Marked by ─────────────────────────────────────────────────────────────
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='attendance_marked',
        help_text='Faculty or admin who marked this record.',
    )
    marked_at = models.DateTimeField(auto_now_add=True)

    # ── Correction fields ─────────────────────────────────────────────────────
    is_corrected = models.BooleanField(default=False)
    corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='attendance_corrected',
    )
    correction_note = models.TextField(blank=True)

    class Meta:
        db_table = 'attendance_records'
        unique_together = ('student', 'date', 'batch')
        ordering = ['-date']
        indexes = [
            models.Index(fields=['date', 'branch']),
            models.Index(fields=['student', 'date']),
            models.Index(fields=['batch', 'date']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.student} | {self.date} → {self.status}"


# ═══════════════════════════════════════════════════════════════════════════════
# QRScanLog  (v3: added device_id per FRD §4.4.1)
# ═══════════════════════════════════════════════════════════════════════════════

class QRScanLog(models.Model):
    """
    Raw log of every QR scan event.
    FRD §4.4.1: logs student ID, scan type (IN/OUT), timestamp, device ID.
    Student's digital QR ID can be displayed from the student mobile app for scanning.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='qr_scans',
    )
    branch = models.ForeignKey(
        'branch.Branch',
        on_delete=models.CASCADE,
        related_name='qr_scans',
    )

    scanned_at = models.DateTimeField(auto_now_add=True)
    scan_type = models.CharField(max_length=20, choices=SCAN_TYPE_CHOICES)

    # v3 NEW (FRD §4.4.1): ID of the QR reader or mobile scan point.
    # Use "mobile_app" when student uses in-app QR display.
    device_id = models.CharField(max_length=255, blank=True)

    # If scanned by exam supervisor (null when self-scanned by student)
    scanned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='qr_scans_performed',
    )

    is_valid = models.BooleanField(default=True)
    invalid_reason = models.CharField(max_length=255, blank=True)

    # E3 — Location & timing validation fields
    latitude          = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude         = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_verified = models.BooleanField(null=True, blank=True)
    time_verified     = models.BooleanField(null=True, blank=True)
    validation_reason = models.CharField(max_length=255, blank=True)
    timetable_slot    = models.ForeignKey(
        'batches.TimetableSlot',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='qr_scans',
    )

    class Meta:
        db_table = 'qr_scan_logs'
        ordering = ['-scanned_at']
        indexes = [
            models.Index(fields=['student', 'scanned_at']),
            models.Index(fields=['scan_type']),
        ]

    def __str__(self):
        return f"{self.student} | {self.scan_type} | {self.scanned_at:%Y-%m-%d %H:%M}"


# ═══════════════════════════════════════════════════════════════════════════════
# AlertLog  (v3: split missing_scan → missing_checkout_scan + missing_checkin_scan)
# ═══════════════════════════════════════════════════════════════════════════════

class AlertLog(models.Model):
    """
    Every push/in-app notification sent to parents or admins.
    FRD §4.4.2 defines the four delay/missing-scan triggers.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='attendance_alerts',
    )

    alert_type = models.CharField(max_length=40, choices=ALERT_TYPE_CHOICES)
    message = models.TextField()
    threshold = models.FloatField(
        null=True,
        blank=True,
        help_text='e.g. 75.0 for low_attendance alerts',
    )
    current_pct = models.FloatField(
        null=True,
        blank=True,
        help_text='Current attendance percentage when alert was generated.',
    )
    sent_at = models.DateTimeField(auto_now_add=True)
    notified_parent = models.BooleanField(default=False)
    notified_admin = models.BooleanField(default=False)

    class Meta:
        db_table = 'attendance_alert_logs'
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['student', 'sent_at']),
            models.Index(fields=['alert_type']),
        ]

    def __str__(self):
        pct = f"{self.current_pct}%" if self.current_pct is not None else 'N/A'
        return f"{self.student} | {self.alert_type} | {pct}"


# ═══════════════════════════════════════════════════════════════════════════════
# ViolationRecord  (v3: added unauthorised_absence, repeated_delay,
#                       logged_by_admin, created_by per FRD §4.4.3)
# ═══════════════════════════════════════════════════════════════════════════════

class ViolationRecord(models.Model):
    """
    FRD §4.4.3: individual attendance violations.
    Created automatically by system/Celery OR manually logged by admin.
    3rd unresolved violation → student QR temporarily blocked.
    Violations are visible on the student profile and included in reports.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='violations',
    )

    violation_type = models.CharField(max_length=40, choices=VIOLATION_TYPE_CHOICES)
    date = models.DateField()
    description = models.TextField(blank=True)

    # v3 NEW: True = manually created via POST /violations/
    #         False = auto-generated by Celery task
    logged_by_admin = models.BooleanField(default=False)

    is_resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='violations_resolved',
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    # v3 NEW: who created this violation (admin for manual, null for auto)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='violations_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'attendance_violations'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['student', 'is_resolved']),
            models.Index(fields=['date']),
        ]

    def __str__(self):
        status = 'resolved' if self.is_resolved else 'active'
        return f"{self.student} | {self.violation_type} | {self.date} ({status})"


# ═══════════════════════════════════════════════════════════════════════════════
# EmployeeAttendanceRecord — check-in/check-out for ALL staff (non-student) users
# ═══════════════════════════════════════════════════════════════════════════════

EMPLOYEE_ATTENDANCE_STATUS_CHOICES = [
    ('present', 'Present'),
    ('absent', 'Absent'),
    ('late', 'Late'),
    ('half_day', 'Half Day'),
    ('on_leave', 'On Leave'),
    ('checkout_pending', 'Checkout Pending'),
]


class EmployeeAttendanceRecord(models.Model):
    """
    One record per employee (User) per date.
    Tracks presence STATUS + raw check-in / check-out timestamps for all staff.
    Works alongside FacultyQRScanLog — this is the canonical attendance record,
    while QR scan logs are the raw audit trail.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='employee_attendance_records',
    )
    branch = models.ForeignKey(
        'branch.Branch',
        on_delete=models.CASCADE,
        related_name='employee_attendance_records',
    )

    date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=EMPLOYEE_ATTENDANCE_STATUS_CHOICES,
        default='absent',
    )

    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)

    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='employee_attendance_marked',
        help_text='Admin who marked this record (null for self-scan).',
    )
    marked_at = models.DateTimeField(auto_now_add=True)

    is_corrected = models.BooleanField(default=False)
    corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employee_attendance_corrected',
    )
    correction_note = models.TextField(blank=True)

    class Meta:
        db_table = 'employee_attendance_records'
        unique_together = ('user', 'date')
        ordering = ['-date']
        indexes = [
            models.Index(fields=['date', 'branch']),
            models.Index(fields=['user', 'date']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.user.name} | {self.date} → {self.status}"
