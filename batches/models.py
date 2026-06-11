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

# E4 ─ Session type choices for TimetableSlot
SESSION_TYPE_CHOICES = [
    ('regular',    'Regular'),
    ('class_test', 'Class Test'),
    ('prelim',     'Prelim'),
    ('practice',   'Practice'),
    ('custom',     'Custom'),
]

SLOT_CODE_CHOICES = [
    ('P1', 'P1 08:00–10:00'),
    ('P2', 'P2 10:15–12:15'),
    ('P3', 'P3 12:45–14:45'),
    ('P4', 'P4 15:00–17:00'),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  Course & Subject
# ═══════════════════════════════════════════════════════════════════════════════

class Course(models.Model):
    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('auth_user.Organization', on_delete=models.CASCADE, related_name='courses', null=True, blank=True)
    name             = models.CharField(max_length=200)
    code             = models.CharField(max_length=30, unique=True, blank=True)
    description      = models.TextField(blank=True)
    is_active        = models.BooleanField(default=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = 'courses'
        ordering  = ['name']
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"

    def save(self, *args, **kwargs):
        if not self.code:
            last = Course.objects.filter(code__startswith='CRS-').order_by('-code').first()
            if last and last.code:
                try:
                    seq = int(last.code.split('-')[-1]) + 1
                except (ValueError, IndexError):
                    seq = 1
            else:
                seq = 1
            self.code = f"CRS-{seq:04d}"
        super().save(*args, **kwargs)


class Subject(models.Model):
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('auth_user.Organization', on_delete=models.CASCADE, related_name='subjects', null=True, blank=True)
    level       = models.ForeignKey('batches.CourseLevel', on_delete=models.CASCADE, related_name='subjects', null=True, blank=True)
    name        = models.CharField(max_length=200)
    code        = models.CharField(max_length=30, blank=True)
    total_hours = models.PositiveIntegerField(default=0)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = 'subjects'
        ordering  = ['name']
        unique_together = ('level', 'code')
        indexes = [
            models.Index(fields=['level', 'is_active']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"

    def save(self, *args, **kwargs):
        if not self.code:
            last = Subject.objects.filter(code__startswith='SUB-').order_by('-code').first()
            if last and last.code:
                try:
                    seq = int(last.code.split('-')[-1]) + 1
                except (ValueError, IndexError):
                    seq = 1
            else:
                seq = 1
            self.code = f"SUB-{seq:04d}"
        super().save(*args, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
#  Batch
# ═══════════════════════════════════════════════════════════════════════════════

class Batch(models.Model):
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization   = models.ForeignKey('auth_user.Organization', on_delete=models.CASCADE, related_name='batches', null=True, blank=True)
    branch         = models.ForeignKey('branch.Branch', null=True, blank=True, on_delete=models.SET_NULL, related_name='batches')
    course         = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='batches')
    name           = models.CharField(max_length=200)
    batch_code     = models.CharField(max_length=30, unique=True, blank=True)
    group_module   = models.CharField(max_length=20, choices=GROUP_MODULE_CHOICES, blank=True)
    batch_attempt  = models.CharField(max_length=10, choices=ATTEMPT_TYPE_CHOICES, blank=True)
    start_date     = models.DateField()
    end_date       = models.DateField()
    max_students   = models.PositiveIntegerField(default=30)
    timing         = models.CharField(max_length=100, blank=True)
    is_active      = models.BooleanField(default=True)
    # E1 ─ auto batch fields
    attempt_year    = models.PositiveSmallIntegerField(null=True, blank=True)
    auto_sequence   = models.PositiveIntegerField(null=True, blank=True)
    is_auto_created = models.BooleanField(default=False)
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

    def save(self, *args, **kwargs):
        if not self.batch_code:
            from django.utils import timezone
            year = timezone.now().year
            prefix = f"BAT-{year}-"
            last = Batch.objects.filter(batch_code__startswith=prefix).order_by('-batch_code').first()
            if last and last.batch_code:
                try:
                    seq = int(last.batch_code.split('-')[-1]) + 1
                except (ValueError, IndexError):
                    seq = 1
            else:
                seq = 1
            self.batch_code = f"{prefix}{seq:04d}"
        super().save(*args, **kwargs)


from students.models import Student

class BatchStudent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='batch_students')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='batch_enrollments')
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'batch_students'
        unique_together = ('batch', 'student')
        indexes = [
            models.Index(fields=['student']),
            models.Index(fields=['-enrolled_at']),
        ]

    def __str__(self):
        return f"{self.student.full_name} → {self.batch.batch_code}"

from faculty.models import FacultyProfile

# E1 ─ Sequence counter for auto batch naming
class BatchSequenceCounter(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course_type   = models.CharField(max_length=20)   # 'cseet' / 'cs_executive' / 'cs_professional'
    batch_attempt = models.CharField(max_length=10)   # 'june' / 'oct' / 'feb' / 'dec'
    attempt_year  = models.PositiveSmallIntegerField()
    last_sequence = models.PositiveIntegerField(default=100)

    class Meta:
        db_table = 'batch_sequence_counters'
        unique_together = ('course_type', 'batch_attempt', 'attempt_year')

    def __str__(self):
        return f"{self.course_type}_{self.batch_attempt}_{self.attempt_year}: seq={self.last_sequence}"

class BatchFaculty(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(Batch,on_delete=models.CASCADE, related_name='batch_faculty')
    faculty = models.ForeignKey(FacultyProfile,on_delete=models.CASCADE,related_name='batch_assignments')
    subject = models.ForeignKey(Subject,on_delete=models.SET_NULL,null=True,blank=True,related_name='faculty_assignments')
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'batch_faculty'
        unique_together = ('batch', 'faculty', 'subject')
        indexes = [
            models.Index(fields=['faculty']),
            models.Index(fields=['-assigned_at']),
        ]

    def __str__(self):
        return f"{self.faculty.user.name} → {self.batch.batch_code} ({self.subject})"

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


# E2 ─ Course Levels
class CourseLevel(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('auth_user.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='course_levels')
    course       = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='levels')
    name         = models.CharField(max_length=100)
    course_type  = models.CharField(max_length=20, choices=COURSE_TYPE_CHOICES, default='standard')
    duration_months  = models.PositiveIntegerField(default=0)
    fee_amount       = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    order        = models.PositiveSmallIntegerField()
    description  = models.TextField(blank=True)
    is_active    = models.BooleanField(default=True)

    class Meta:
        db_table = 'course_levels'
        unique_together = ('course', 'order')
        ordering = ['order']

    def __str__(self):
        return f"{self.course.code} | Level {self.order}: {self.name}"


# E2 ─ Subject Chapters
class Chapter(models.Model):
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject     = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='chapters')
    name        = models.CharField(max_length=200)
    order       = models.PositiveSmallIntegerField()
    description = models.TextField(blank=True)
    is_active   = models.BooleanField(default=True)

    class Meta:
        db_table = 'subject_chapters'
        unique_together = ('subject', 'order')
        ordering = ['order']

    def __str__(self):
        return f"{self.subject.code} | Ch {self.order}: {self.name}"


# E4 ─ Timetable Exam Type
class TimetableExamType(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('auth_user.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='timetable_exam_types')
    name         = models.CharField(max_length=100, unique=True)
    description  = models.TextField(blank=True)
    is_active    = models.BooleanField(default=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'timetable_exam_types'
        ordering = ['name']

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
    faculty = models.ForeignKey(
        FacultyProfile,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='timetable_slots',
    )
    classroom     = models.ForeignKey(Classroom, on_delete=models.SET_NULL, null=True, blank=True, related_name='timetable_slots')
    # E4: made nullable — special sessions use session_date instead
    day_of_week   = models.IntegerField(choices=DAY_CHOICES, null=True, blank=True)
    start_time    = models.TimeField(null=True, blank=True)
    end_time      = models.TimeField(null=True, blank=True)
    is_recurring  = models.BooleanField(default=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to   = models.DateField(null=True, blank=True)
    # E4: new fields
    session_type        = models.CharField(max_length=20, choices=SESSION_TYPE_CHOICES, default='regular')
    slot_code           = models.CharField(max_length=2, choices=SLOT_CODE_CHOICES, null=True, blank=True)
    session_date        = models.DateField(null=True, blank=True)
    chapter             = models.ForeignKey('batches.Chapter', on_delete=models.SET_NULL, null=True, blank=True, related_name='timetable_slots')
    examiner            = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='examiner_slots')
    paper_checker       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='checker_slots')
    timetable_exam_type = models.ForeignKey(TimetableExamType, on_delete=models.SET_NULL, null=True, blank=True, related_name='timetable_slots')
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
            models.Index(fields=['session_type']),
            models.Index(fields=['session_date']),
        ]

    def __str__(self):
        return f"{self.batch.batch_code} | {self.session_type} | Day {self.day_of_week} | {self.start_time}-{self.end_time}"
