# leads/models.py  (updated — registration fields removed)

from django.db import models
from django.conf import settings


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
        changed_by = self.changed_by.get_full_name() if self.changed_by else 'System'
        return f"{self.lead} → {self.stage} by {changed_by}"