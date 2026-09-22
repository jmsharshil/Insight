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
    ('cs_executive_pass','CS Executive Pass'),
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

class SalesDailyPlan(models.Model):
    """
    Daily plan / scheduled event record created by a salesperson.
    Holds the high-level description, event type, time, and location.
    Multiple events can be scheduled across dates or on the same date.
    All field activities (photos, odometer) for the day can be linked to this plan.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sales_daily_plans',
    )
    plan_date = models.DateField(default=timezone.localdate, help_text="The date this plan is for.")
    type = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="Type of event/plan, e.g. School Visit, Seminar, Exhibition, Meeting, Demo"
    )
    start_time = models.TimeField(null=True, blank=True, help_text="Start time of the scheduled event/plan")
    end_time = models.TimeField(null=True, blank=True, help_text="End time of the scheduled event/plan")
    place = models.CharField(max_length=255, blank=True, default='', help_text="Location/venue of the plan or event")
    description = models.TextField(
        blank=True,
        default='',
        help_text="Describe what the salesperson plans to do — schools to visit, targets, agenda, etc."
    )
    reminder_two_days_before_sent = models.BooleanField(
        default=False,
        help_text="True once the 8:00 AM 2-days-before reminder has been sent."
    )
    reminder_one_day_before_sent = models.BooleanField(
        default=False,
        help_text="True once the 8:00 AM 1-day-before reminder has been sent."
    )
    reminder_day_of_event_sent = models.BooleanField(
        default=False,
        help_text="True once the 8:00 AM day-of-event reminder has been sent."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def date(self):
        return self.plan_date

    @date.setter
    def date(self, value):
        self.plan_date = value

    def clean(self):
        """
        Validate that this event's time slot does not overlap with any other
        event for the same user on the same date.
        Overlap condition: existing.start_time < self.end_time AND existing.end_time > self.start_time
        Only checked when both start_time and end_time are provided.
        """
        from django.core.exceptions import ValidationError
        
        if not getattr(self, 'user_id', None):
            return  # Cannot check conflicts without a user

        if self.start_time and self.end_time:
            if self.end_time <= self.start_time:
                raise ValidationError(
                    "end_time must be after start_time."
                )
            conflicting_qs = SalesDailyPlan.objects.filter(
                user_id=self.user_id,
                plan_date=self.plan_date,
                start_time__isnull=False,
                end_time__isnull=False,
                start_time__lt=self.end_time,
                end_time__gt=self.start_time,
            )
            if self.pk:
                conflicting_qs = conflicting_qs.exclude(pk=self.pk)
            if conflicting_qs.exists():
                conflict = conflicting_qs.first()
                raise ValidationError(
                    f"This event conflicts with an existing event "
                    f"'{conflict.type or 'Unnamed'}' on {self.plan_date} "
                    f"({conflict.start_time.strftime('%H:%M')} – {conflict.end_time.strftime('%H:%M')}). "
                    f"Please choose a different time slot."
                )

    class Meta:
        db_table = 'sales_daily_plans'
        ordering = ['-plan_date', 'start_time', '-created_at']

    def __str__(self):
        event_str = f" [{self.type}]" if self.type else ""
        return f"{self.user.name} - Plan for {self.plan_date}{event_str}"


class SalesDailyActivity(models.Model):
    """
    Field activity container. Multiple activities per user per day are now supported
    (unique constraint on (user, activity_date) has been removed). The optional
    `name` field helps distinguish multiple activities on the same date.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="Optional name/title for this activity (e.g. 'Morning School Visit', "
                  "'Seminar at XYZ College', 'Lead Follow-up'). Useful when multiple "
                  "activities occur on the same day."
    )
    plan = models.ForeignKey(
        SalesDailyPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activities',
        help_text="The daily plan this activity belongs to.",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sales_daily_activities',
    )
    activity_date = models.DateField(default=timezone.localdate)
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('ongoing', 'Ongoing'),
        ('completed', 'Completed'),
    ]
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='pending',
        help_text="Current status of the activity"
    )
    
    notes = models.TextField(blank=True)
    students_expected = models.PositiveIntegerField(null=True, blank=True, help_text="Number of students expected to attend")
    students_attended = models.PositiveIntegerField(null=True, blank=True, help_text="Number of students actually attended")
    
    target_name = models.CharField(max_length=100, blank=True, help_text="Name of the person being targeted/visited")
    target_number = models.CharField(max_length=20, blank=True, help_text="WhatsApp number of the target")
    
    ACTIVITY_STANDARD_CHOICES = [
        ('12th', '12th'),
        ('11th_12th', '11th & 12th'),
        ('11th', '11th'),
        ('10th', '10th'),
    ]
    ACTIVITY_BOARD_CHOICES = [
        ('cbse', 'CBSE'),
        ('gseb', 'GSEB'),
        ('cbic_ib', 'CBIC/IB'),
    ]
    ACTIVITY_MEDIUM_CHOICES = [
        ('english', 'English'),
        ('gujarati', 'Gujarati'),
        ('hindi', 'Hindi'),
    ]

    standard = models.CharField(max_length=20, choices=ACTIVITY_STANDARD_CHOICES, default='12th', blank=True)
    board = models.CharField(max_length=20, choices=ACTIVITY_BOARD_CHOICES, default='cbse', blank=True)
    medium = models.CharField(max_length=20, choices=ACTIVITY_MEDIUM_CHOICES, default='english', blank=True)

    seminar_reference_by = models.CharField(max_length=200, blank=True, help_text="Who gave the reference for the seminar")
    seminar_given_by = models.CharField(max_length=200, blank=True, help_text="Who gave the seminar")
    location_link = models.URLField(blank=True,null=True,help_text="Google Map link for location/venue")
    from_date = models.DateField(null=True, blank=True, help_text="Start date of the activity")
    to_date = models.DateField(null=True, blank=True, help_text="End date of the activity")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sales_daily_activities'
        ordering = ['-activity_date', '-created_at', 'name']
        # Note: UniqueConstraint on (user, activity_date) removed to allow multiple
        # activities per user per calendar day.

    def __str__(self):
        name_str = f" - {self.name}" if self.name else ""
        return f"{self.user.name} - {self.activity_date}{name_str}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        if self.target_number:
            from chat.notifications import send_whatsapp_text
            action = "scheduled" if is_new else "updated"
            message = (
                f"Hello {self.target_name or 'there'},\n"
                f"An activity '{self.name}' has been {action} for {self.activity_date.strftime('%d %b %Y')} "
                f"by {self.user.name or 'our team'}."
            )
            send_whatsapp_text(to=self.target_number, body=message)


class SalesActivityPhoto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    activity = models.ForeignKey(
        SalesDailyActivity,
        on_delete=models.CASCADE,
        related_name='photos',
    )
    photo_type = models.CharField(max_length=50, help_text="Type/category of the photo (e.g. 'start_selfie', 'venue', 'meeting')")
    photo = models.ImageField(upload_to='sales/activity_photos/')
    name = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text="Optional label/name for this photo (e.g. 'Ryan International Visit', "
                  "'Exhibition Day 1 — Stall Setup'). Useful for per-event photo identification."
    )
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

VEHICLE_TYPE_CHOICES = [
    ('bike', 'Bike'),
    ('car', 'Car'),
]

VEHICLE_RATES = {
    'bike': Decimal('5.00'),
    'car': Decimal('12.00'),
}


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
    vehicle_type = models.CharField(
        max_length=20,
        choices=VEHICLE_TYPE_CHOICES,
        default='bike',
        help_text="Type of vehicle used: bike (₹5/km) or car (₹12/km)"
    )
    start_kms = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    end_kms = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_kms = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    expense_per_km = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal('5.00'),
        help_text="Reimbursement rate per kilometer (auto-set based on vehicle_type: ₹5 for bike, ₹12 for car)"
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

    def calculate_totals(self, override_expense_per_km=None, override_total_kms=None):
        if override_total_kms is not None:
            self.total_kms = max(Decimal('0.00'), Decimal(str(override_total_kms)))
        elif self.status != 'approved' and self.start_kms is not None and self.end_kms is not None:
            self.total_kms = max(Decimal('0.00'), Decimal(str(self.end_kms)) - Decimal(str(self.start_kms)))
        elif self.start_kms is None or self.end_kms is None:
            self.total_kms = Decimal('0.00')

        if override_expense_per_km is not None:
            self.expense_per_km = override_expense_per_km
        else:
            # Auto calculate expense rate based on vehicle_type: ₹5/km for bike, ₹12/km for car
            vtype_str = str(self.vehicle_type).lower()
            vtype = 'car' if 'car' in vtype_str or '4' in vtype_str or 'four' in vtype_str else 'bike'
            rate = VEHICLE_RATES.get(vtype, Decimal('5.00'))
            self.expense_per_km = rate

        if self.total_kms:
            self.total_expense = (self.total_kms * self.expense_per_km).quantize(Decimal('0.01'))
        else:
            self.total_expense = Decimal('0.00')

    def save(self, *args, **kwargs):
        override_rate = kwargs.pop('override_expense_per_km', None)
        override_kms = kwargs.pop('override_total_kms', None)
        self.calculate_totals(override_expense_per_km=override_rate, override_total_kms=override_kms)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Odometer {self.activity.activity_date} - {self.user.name or self.user.email} ({self.total_kms} km @ ₹{self.expense_per_km}/km = ₹{self.total_expense}) [{self.status}]"


class SalesPlanReminder(models.Model):
    """
    Custom reminder times for a SalesDailyPlan.
    Users can add multiple specific dates and times for reminders.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(
        SalesDailyPlan,
        on_delete=models.CASCADE,
        related_name='custom_reminders',
        help_text="The sales plan this reminder is for."
    )
    reminder_time = models.DateTimeField(help_text="The exact time to send this reminder.")
    purpose = models.CharField(max_length=255, blank=True, help_text="What this reminder is for (e.g. call, follow-up meeting, etc.)")
    is_sent = models.BooleanField(default=False, help_text="Whether this reminder has been sent.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sales_plan_reminders'
        ordering = ['reminder_time']

    def __str__(self):
        return f"Reminder for {self.plan.id} at {self.reminder_time} (Sent: {self.is_sent})"
