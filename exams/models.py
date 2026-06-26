import uuid
import logging
from django.db import models
from django.conf import settings

logger = logging.getLogger(__name__)


EXAM_TYPE_CHOICES = [('online', 'Online'), ('offline', 'Offline')]
EXAM_STATUS_CHOICES = [
    ('draft', 'Draft'), ('scheduled', 'Scheduled'), ('ongoing', 'Ongoing'),
    ('completed', 'Completed'), ('results_published', 'Results Published'),
]
QUESTION_TYPE_CHOICES = [('mcq', 'MCQ'), ('subjective', 'Subjective'), ('true_false', 'True/False')]
SCAN_EVENT_CHOICES = [('lock_breach', 'Lock Breach'), ('split_screen', 'Split Screen')]
EVENT_ACTION_CHOICES = [
    ('logged', 'Logged'), ('warning_issued', 'Warning Issued'),
    ('auto_submitted', 'Auto Submitted'), ('flagged', 'Flagged'),   # v2: flagged added
]
SEVERITY_CHOICES = [('minor', 'Minor'), ('major', 'Major'), ('disqualified', 'Disqualified')]
SCREEN_ACTION_CHOICES = [('flag_only', 'Flag Only'), ('auto_submit', 'Auto Submit')]
RESULT_RELEASE_CHOICES = [('instant', 'Instant'), ('manual', 'Manual')]


class Exam(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey('branch.Branch', on_delete=models.CASCADE, related_name='exams')
    batch = models.ForeignKey('batches.Batch', on_delete=models.SET_NULL, null=True, related_name='exams')
    subject = models.ForeignKey('batches.Subject', on_delete=models.SET_NULL, null=True, blank=True, related_name='exams')
    faculty = models.ForeignKey('faculty.FacultyProfile', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_exams')
    title = models.CharField(max_length=200)
    exam_type = models.CharField(max_length=20, choices=EXAM_TYPE_CHOICES)
    total_marks = models.IntegerField(
        default=0,
        help_text='Auto-calculated as sum of all questions.marks (questions including MCQs can have varying marks per question). Updated automatically via signals.'
    )
    pass_marks = models.IntegerField()
    duration_minutes = models.IntegerField(help_text='Drives the countdown timer')
    scheduled_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    status = models.CharField(max_length=20, choices=EXAM_STATUS_CHOICES, default='draft')
    instructions = models.TextField(blank=True)

    # Geo-boundary enforcement (FRD §4.6.1)
    geo_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    geo_lon = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    geo_radius_meters = models.IntegerField(default=0, help_text='0 = geo check disabled')
    # v2 NEW: periodic geo check interval during exam
    geo_check_interval_minutes = models.IntegerField(
        default=0,
        help_text='0 = check only at start. >0 = also check periodically during exam at this interval.',
    )

    # Screen violation configuration (FRD §4.6.1 — "configurable to auto-submit or flag")
    # v2 NEW: per-exam configurable thresholds and actions
    screen_lock_max_violations = models.IntegerField(default=3)
    screen_lock_action = models.CharField(max_length=20, choices=SCREEN_ACTION_CHOICES, default='auto_submit')
    split_screen_max_warnings = models.IntegerField(default=2)
    split_screen_action = models.CharField(max_length=20, choices=SCREEN_ACTION_CHOICES, default='auto_submit')

    # Result release mode (FRD §4.6.1 Instant Results)
    # v2 NEW: "instant" = auto-publish MCQ results on submit; "manual" = admin triggers
    result_release_mode = models.CharField(max_length=20, choices=RESULT_RELEASE_CHOICES, default='instant')

    # Paper checkers assignment (NEW: auto-assign to marksheets from available checkers in exam time slot)
    # Allows selecting possible assignable paper_checkers (role='paper_checker') for this exam.
    # Used by assign_papers_to_checker() to filter by availability matching exam.scheduled_date + start/end_time
    # with checker's work_start_time/work_end_time overlap.
    paper_checkers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='exams_to_check',
        limit_choices_to={'role': 'paper_checker', 'is_active': True},
        help_text='Available paper checkers assignable to this exam\'s marksheets. '
                  'Auto-assignment uses these + time slot availability.'
    )

    # Answer key upload (required for recheck flow per user query)
    answer_key = models.FileField(
        upload_to='answer_keys/',
        null=True,
        blank=True,
        help_text='Uploaded answer key (PDF/image). Must be present before allowing recheck requests or bulk recheck.'
    )

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_exams')
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'exams'
        ordering = ['-scheduled_date', '-start_time']

    def __str__(self):
        return f"{self.title} ({self.scheduled_date})"

    def recalculate_total_marks(self):
        """Auto-calculate and update total_marks based on sum of all associated questions' marks.
        Questions (MCQ, subjective, true_false) can have independent/varying marks.
        Called automatically from exams/signals.py receivers on Question create/update/delete.
        """
        from django.db.models import Sum
        total = self.questions.aggregate(Sum('marks'))['marks__sum'] or 0
        if self.total_marks != total:
            self.total_marks = total
            self.save(update_fields=['total_marks'])
        return total

    def ensure_paper_checkers(self):
        """Ensure Exam.paper_checkers M2M is populated (with branch-scoped fallback if empty).
        Called by post_save signal (signals.py) on every Exam creation/update and explicitly
        from views on create/schedule. This guarantees the M2M for paper_checker visibility
        *before* any MarkSheet exists. FK assignment to MarkSheet.paper_checker is strictly
        delayed until update_exam_statuses task (after auto_mark_absent_after_exam).
        """
        from django.contrib.auth import get_user_model
        from .utils import get_available_paper_checkers  # only the helper we need

        if self.paper_checkers.exists():
            logger.debug(f"Exam {self.id} already has {self.paper_checkers.count()} paper checkers.")
            return list(self.paper_checkers.values_list('id', flat=True))

        # Use shared helper (with prefetch/fallbacks)
        checker_ids = get_available_paper_checkers(self)
        if checker_ids:
            self.paper_checkers.add(*checker_ids)
            logger.info(f"Ensured {len(checker_ids)} paper checkers for exam {self.id} via M2M.")
            # Clear prefetch cache if this instance was loaded with it
            if hasattr(self, '_prefetched_objects_cache'):
                self._prefetched_objects_cache.pop('paper_checkers', None)
        return checker_ids


class Question(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPE_CHOICES)
    marks = models.IntegerField()
    order = models.IntegerField()
    image = models.ImageField(upload_to='exam_questions/', null=True, blank=True)

    class Meta:
        db_table = 'exam_questions'
        ordering = ['order']

    def __str__(self):
        return f"Q{self.order}: {self.question_text[:50]}"


class Choice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices')
    choice_text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)

    class Meta:
        db_table = 'exam_choices'

    def __str__(self):
        return self.choice_text[:50]


class ExamSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='sessions')
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='exam_sessions')
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    is_submitted = models.BooleanField(default=False)
    auto_submitted = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    device_fingerprint = models.CharField(max_length=200, blank=True)
    student_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    student_lon = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    screen_lock_violations = models.IntegerField(default=0)
    split_screen_warnings = models.IntegerField(default=0)

    # v2 NEW: periodic geo-check tracking (FRD §4.6.1)
    last_geo_check_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'exam_sessions'
        unique_together = ('exam', 'student')

    def __str__(self):
        return f"{self.student} - {self.exam.title}"


class StudentAnswer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(ExamSession, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='student_answers')
    selected_choice = models.ForeignKey(Choice, on_delete=models.SET_NULL, null=True, blank=True)
    text_answer = models.TextField(blank=True)
    answered_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'exam_student_answers'
        unique_together = ('session', 'question')

    def __str__(self):
        return f"Answer: {self.session} - Q{self.question.order}"


class SeatArrangement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='seating')
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='seat_arrangements')
    room_name = models.CharField(max_length=100)
    seat_number = models.CharField(max_length=20)
    row_number = models.IntegerField(null=True, blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    class Meta:
        db_table = 'exam_seating'
        unique_together = ('exam', 'room_name', 'seat_number')

    def __str__(self):
        return f"{self.student} - {self.room_name}/{self.seat_number}"


class MalpracticeReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='malpractice_reports')
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='malpractice_reports')
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    description = models.TextField()
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    reported_at = models.DateTimeField(auto_now_add=True)
    action_taken = models.TextField(blank=True)

    class Meta:
        db_table = 'exam_malpractice'

    def __str__(self):
        return f"{self.student} - {self.severity} ({self.exam.title})"


class ScreenEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(ExamSession, on_delete=models.CASCADE, related_name='screen_events')
    event_type = models.CharField(max_length=20, choices=SCAN_EVENT_CHOICES)
    occurred_at = models.DateTimeField(auto_now_add=True)
    action_taken = models.CharField(max_length=20, choices=EVENT_ACTION_CHOICES, default='logged')

    class Meta:
        db_table = 'exam_screen_events'

    def __str__(self):
        return f"{self.event_type} - {self.action_taken}"


class CheckerToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    marksheet = models.ForeignKey('results.MarkSheet', on_delete=models.CASCADE, related_name='tokens')
    token = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        db_table = 'exam_checker_tokens'

    def __str__(self):
        return f"Token for {self.marksheet} ({'used' if self.is_used else 'active'})"


class AnswerKeyDistributionLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='answer_key_logs')
    sent_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    sent_at = models.DateTimeField(auto_now_add=True)
    link_expires = models.DateTimeField()

    class Meta:
        db_table = 'exam_answer_key_logs'

    def __str__(self):
        return f"Answer key sent to {self.sent_to} for {self.exam.title}"
