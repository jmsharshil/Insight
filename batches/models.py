from django.db import models
from django.conf import settings
import uuid
from leads.models import COURSE_TYPE_CHOICES, GROUP_MODULE_CHOICES, ATTEMPT_TYPE_CHOICES


# ── Day-of-week choices ───────────────────────────────────────────────────────
DAY_CHOICES = [
    (0, 'Monday'),
    (1, 'Tuesday'),
    (2, 'Wednesday'),
    (3, 'Thursday'),
    (4, 'Friday'),
    (5, 'Saturday'),
    (6, 'Sunday'),
]

SESSION_CHOICES = [
    ('morning',   'Morning'),
    ('afternoon', 'Afternoon'),
    ('evening',   'Evening'),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  Course & Subject
# ═══════════════════════════════════════════════════════════════════════════════

class Course(models.Model):
    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('auth_user.Organization', on_delete=models.CASCADE, related_name='courses', null=True, blank=True)
    name             = models.CharField(max_length=200)
    code             = models.CharField(max_length=30, unique=True)
    course_type      = models.CharField(max_length=20, choices=COURSE_TYPE_CHOICES)
    duration_months  = models.PositiveIntegerField(default=0)
    fee_amount       = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    description      = models.TextField(blank=True)
    is_active        = models.BooleanField(default=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = 'courses'
        ordering  = ['name']
        indexes = [
            models.Index(fields=['course_type', 'is_active']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"


class Subject(models.Model):
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('auth_user.Organization', on_delete=models.CASCADE, related_name='subjects', null=True, blank=True)
    course      = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='subjects')
    name        = models.CharField(max_length=200)
    code        = models.CharField(max_length=30)
    total_hours = models.PositiveIntegerField(default=0)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = 'subjects'
        ordering  = ['name']
        unique_together = ('course', 'code')
        indexes = [
            models.Index(fields=['course', 'is_active']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Batch
# ═══════════════════════════════════════════════════════════════════════════════

class Batch(models.Model):
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization   = models.ForeignKey('auth_user.Organization', on_delete=models.CASCADE, related_name='batches', null=True, blank=True)
    course         = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='batches')
    name           = models.CharField(max_length=200)
    batch_code     = models.CharField(max_length=30, unique=True)
    group_module   = models.CharField(max_length=20, choices=GROUP_MODULE_CHOICES, blank=True)
    batch_attempt  = models.CharField(max_length=10, choices=ATTEMPT_TYPE_CHOICES, blank=True)
    location       = models.CharField(max_length=100, blank=True)
    start_date     = models.DateField()
    end_date       = models.DateField()
    max_students   = models.PositiveIntegerField(default=30)
    timing         = models.CharField(max_length=100, blank=True)
    is_active      = models.BooleanField(default=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = 'batches'
        ordering  = ['-created_at']
        indexes   = [
            models.Index(fields=['batch_code']),
            models.Index(fields=['is_active']),
            models.Index(fields=['course', 'is_active']),
            models.Index(fields=['start_date', 'end_date']),
        ]

    def __str__(self):
        return f"{self.batch_code} — {self.name}"


class BatchStudent(models.Model):
    """Links a student User to a Batch."""
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch       = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='batch_students')
    student     = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='batch_enrollments',
        limit_choices_to={'role': 'student'},
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'batch_students'
        unique_together = ('batch', 'student')
        indexes = [
            models.Index(fields=['student']),
            models.Index(fields=['-enrolled_at']),
        ]

    def __str__(self):
        return f"{self.student.name} → {self.batch.batch_code}"


class BatchFaculty(models.Model):
    """Links a faculty User to a Batch (+ optional Subject)."""
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch       = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='batch_faculty')
    faculty     = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='batch_assignments',
        limit_choices_to={'role': 'faculty'},
    )
    subject     = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True, related_name='faculty_assignments')
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'batch_faculty'
        unique_together = ('batch', 'faculty', 'subject')
        indexes = [
            models.Index(fields=['faculty']),
            models.Index(fields=['-assigned_at']),
        ]

    def __str__(self):
        return f"{self.faculty.name} → {self.batch.batch_code} ({self.subject})"


# ═══════════════════════════════════════════════════════════════════════════════
#  Classroom
# ═══════════════════════════════════════════════════════════════════════════════

class Classroom(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('auth_user.Organization', on_delete=models.CASCADE, related_name='classrooms', null=True, blank=True)
    name     = models.CharField(max_length=100)
    capacity = models.PositiveIntegerField(default=30)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = 'classrooms'
        ordering  = ['name']
        indexes = [
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return self.name


# ═══════════════════════════════════════════════════════════════════════════════
#  Timetable Slot
# ═══════════════════════════════════════════════════════════════════════════════

class TimetableSlot(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization  = models.ForeignKey('auth_user.Organization', on_delete=models.CASCADE, related_name='timetable_slots', null=True, blank=True)
    batch         = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='timetable_slots')
    subject       = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True, related_name='timetable_slots')
    faculty       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='timetable_slots',
        limit_choices_to={'role': 'faculty'},
    )
    classroom     = models.ForeignKey(Classroom, on_delete=models.SET_NULL, null=True, blank=True, related_name='timetable_slots')
    day_of_week   = models.IntegerField(choices=DAY_CHOICES)
    start_time    = models.TimeField()
    end_time      = models.TimeField()
    session       = models.CharField(max_length=20, choices=SESSION_CHOICES, default='morning')
    is_recurring  = models.BooleanField(default=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to   = models.DateField(null=True, blank=True)
    created_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_timetable_slots',
    )
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = 'timetable_slots'
        ordering  = ['day_of_week', 'start_time']
        indexes   = [
            models.Index(fields=['batch', 'day_of_week']),
            models.Index(fields=['faculty', 'day_of_week']),
            models.Index(fields=['classroom', 'day_of_week']),
            models.Index(fields=['batch', '-created_at']),
        ]

    def __str__(self):
        return f"{self.batch.batch_code} | Day {self.day_of_week} | {self.start_time}-{self.end_time}"
