from django.db import models

# Create your models here.

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from onboarding.models import Admission


# ── Choice Constants ──────────────────────────────────────────────────────────

STUDENT_STATUS_CHOICES = [
    ('active','Active'),
    ('inactive','Inactive'),
    ('transferred',  'Transferred'),
    ('alumni','Alumni'),
    ('suspended','Suspended'),
]

GENDER_CHOICES = [
    ('male','Male'),
    ('female', 'Female'),
    ('other','Other'),
]

INVENTORY_ITEM_CHOICES = [
    ('uniform_shirt','Uniform Shirt'),
    ('uniform_trouser', 'Uniform Trouser'),
    ('uniform_blazer','Uniform Blazer'),
    ('book','Book'),
    ('id_card','ID Card'),
    ('other','Other'),
]

BLOOD_GROUP_CHOICES = [
    ('A+', 'A+'), ('A-', 'A-'),
    ('B+', 'B+'), ('B-', 'B-'),
    ('O+', 'O+'), ('O-', 'O-'),
    ('AB+', 'AB+'), ('AB-', 'AB-'),
    ('unknown', 'Unknown'),
]

RELATIONSHIP_CHOICES = [
    ('father','Father'),
    ('mother','Mother'),
    ('guardian','Guardian'),
    ('sibling','Sibling'),
    ('other','Other'),
]


# ── Upload Helpers ────────────────────────────────────────────────────────────

def student_document_path(instance, filename):
    return f"students/{instance.admission_number}/documents/{filename}"


def student_photo_path(instance, filename):
    return f"students/{instance.admission_number}/photo/{filename}"


def id_card_path(instance, filename):
    return f"students/{instance.student.admission_number}/id_card/{filename}"


# ── Admission Number Generator ────────────────────────────────────────────────

def generate_admission_number():
    """
    Format: ADM-YYYY-XXXXXX  (e.g. ADM-2025-000042)
    """
    year   = timezone.now().year
    prefix = f"ADM-{year}-"
    last   = (
        Student.objects
        .filter(admission_number__startswith=prefix)
        .order_by('-admission_number')
        .values_list('admission_number', flat=True)
        .first()
    )
    if last:
        seq = int(last.split('-')[-1]) + 1
    else:
        seq = 1
    return f"{prefix}{seq:06d}"


# ── Student Master Profile ────────────────────────────────────────────────────

class Student(models.Model):
    """
    Central student record created when an Admission is approved → enrolled.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admission_number = models.CharField(max_length=20, unique=True, editable=False, db_index=True)

    # ── Links ─────────────────────────────────────────────────────────────────
    admission = models.OneToOneField(Admission,on_delete=models.PROTECT,related_name='student_profile',help_text="The admission record this student was created from.",)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='student_profiles',help_text="Login account for this student.",)
    branch = models.ForeignKey('branch.Branch',null=True, blank=True,on_delete=models.SET_NULL,related_name='students',)
    current_batch_name = models.CharField(max_length=200, blank=True, help_text="Batch name — will link to Batch.")
    # ── Personal Info ─────────────────────────────────────────────────────────
    first_name  = models.CharField(max_length=100)
    surname     = models.CharField(max_length=100)
    father_name = models.CharField(max_length=100)
    mother_name = models.CharField(max_length=100)
    dob         = models.DateField()
    gender      = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True)
    blood_group = models.CharField(max_length=10, choices=BLOOD_GROUP_CHOICES, default='unknown')
    category    = models.CharField(max_length=10)
    nationality = models.CharField(max_length=50, default='Indian')

    # ── Contact ───────────────────────────────────────────────────────────────
    email           = models.EmailField()
    email_parent    = models.EmailField(blank=True)
    phone_student   = models.CharField(max_length=15)
    phone_student_2 = models.CharField(max_length=15, blank=True)
    phone_father    = models.CharField(max_length=15)
    phone_father_2  = models.CharField(max_length=15, blank=True)

    # ── Address ───────────────────────────────────────────────────────────────
    street    = models.TextField()
    apartment = models.CharField(max_length=100, blank=True)
    city      = models.CharField(max_length=100)
    state     = models.CharField(max_length=100)
    pincode   = models.CharField(max_length=10)
    country   = models.CharField(max_length=100, default='India')

    # ── Emergency Contact ─────────────────────────────────────────────────────
    emergency_contact_name         = models.CharField(max_length=150, blank=True)
    emergency_contact_phone        = models.CharField(max_length=15, blank=True)
    emergency_contact_relationship = models.CharField(max_length=20, choices=RELATIONSHIP_CHOICES, blank=True)

    # ── Course / Academic ─────────────────────────────────────────────────────
    course        = models.CharField(max_length=20)
    group_module  = models.CharField(max_length=20)
    batch_attempt = models.CharField(max_length=10)
    qualification = models.CharField(max_length=20)
    location      = models.CharField(max_length=100)

    # ── Photo (mandatory for ID card) ─────────────────────────────────────────
    photo = models.ImageField(upload_to=student_photo_path,null=True, blank=True,help_text="Profile photo — mandatory for digital ID card generation.",)

    # ── Documents ─────────────────────────────────────────────────────────────
    doc_signature       = models.FileField(upload_to=student_document_path, null=True, blank=True)
    doc_dob_certificate = models.FileField(upload_to=student_document_path, null=True, blank=True)
    doc_id_proof        = models.FileField(upload_to=student_document_path, null=True, blank=True)
    doc_tenth_marksheet = models.FileField(upload_to=student_document_path, null=True, blank=True)
    doc_twelfth_marksheet = models.FileField(upload_to=student_document_path, null=True, blank=True)
    doc_category_cert   = models.FileField(upload_to=student_document_path, null=True, blank=True)
    doc_graduation_cert = models.FileField(upload_to=student_document_path, null=True, blank=True)

    # ── Counsellor ────────────────────────────────────────────────────────────
    assigned_counsellor = models.ForeignKey(settings.AUTH_USER_MODEL,null=True, blank=True,on_delete=models.SET_NULL,related_name='counselled_students',limit_choices_to={'role': 'counsellor'},)

    # ── Status & Timestamps ───────────────────────────────────────────────────
    status     = models.CharField(max_length=15, choices=STUDENT_STATUS_CHOICES, default='active', db_index=True)
    enrolled_at = models.DateTimeField(default=timezone.now)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    # ── Misc ──────────────────────────────────────────────────────────────────
    notes = models.TextField(blank=True, help_text="Internal admin notes.")

    class Meta:
        db_table = 'students'
        ordering = ['-enrolled_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['course']),
            models.Index(fields=['enrolled_at']),
            models.Index(fields=['email']),
        ]

    def save(self, *args, **kwargs):
        if not self.admission_number:
            self.admission_number = generate_admission_number()
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        return f"{self.first_name} {self.surname}".strip()

    @property
    def has_photo(self):
        return bool(self.photo)

    @property
    def id_card_ready(self):
        """A digital ID card can only be generated when a photo exists."""
        return self.has_photo

    def __str__(self):
        return f"{self.admission_number} | {self.full_name} | {self.course}"


# ── Parent Link ───────────────────────────────────────────────────────────────

class ParentLink(models.Model):
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='parent_links')
    parent  = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='linked_children',limit_choices_to={'role': 'parents'},)
    relationship = models.CharField(max_length=20, choices=RELATIONSHIP_CHOICES, default='father')
    is_primary   = models.BooleanField(default=False, help_text="Primary contact parent.")
    linked_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table       = 'student_parent_links'
        unique_together = [('student', 'parent')]
        ordering       = ['-is_primary', 'linked_at']

    def __str__(self):
        return f"{self.student.admission_number} ← {self.parent.name} ({self.relationship})"


# ── Batch History ─────────────────────────────────────────────────────────────

class BatchHistory(models.Model):
    """Immutable log of every batch assignment / change for a student."""
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student    = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='batch_history')
    batch_name = models.CharField(max_length=200)            # snapshot in case batch is deleted
    reason     = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL,null=True, blank=True,on_delete=models.SET_NULL,)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'student_batch_history'
        ordering = ['changed_at']

    def __str__(self):
        return f"{self.student.admission_number} → {self.batch_name} @ {self.changed_at:%Y-%m-%d}"


# ── Inventory Issue ───────────────────────────────────────────────────────────

class InventoryIssue(models.Model):
    """Records each uniform / book / ID-card item issued to a student."""
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student     = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='inventory_issues')
    item_type   = models.CharField(max_length=30, choices=INVENTORY_ITEM_CHOICES)
    item_name   = models.CharField(max_length=200, blank=True, help_text="e.g. Book title, ISBN, uniform size")
    quantity    = models.PositiveSmallIntegerField(default=1)
    size        = models.CharField(max_length=20, blank=True, help_text="For uniform items.")
    isbn        = models.CharField(max_length=20, blank=True, help_text="For books.")
    issued_by   = models.ForeignKey(settings.AUTH_USER_MODEL,null=True, blank=True,on_delete=models.SET_NULL,related_name='issued_inventory',)
    issued_at   = models.DateTimeField(default=timezone.now)
    returned_at = models.DateTimeField(null=True, blank=True)
    notes       = models.TextField(blank=True)

    class Meta:
        db_table = 'student_inventory_issues'
        ordering = ['-issued_at']

    def __str__(self):
        return f"{self.student.admission_number} | {self.item_type} × {self.quantity}"


# ── Digital ID Card ───────────────────────────────────────────────────────────

class DigitalIDCard(models.Model):
    """
    Generated once when the student has a photo.
    The QR code encodes the student's UUID for attendance check-in.
    """
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.OneToOneField(Student, on_delete=models.CASCADE, related_name='id_card')

    qr_data       = models.CharField(max_length=500, help_text="Data encoded in QR (student UUID).")
    qr_image      = models.ImageField(upload_to=id_card_path, null=True, blank=True)
    card_image    = models.ImageField(upload_to=id_card_path, null=True, blank=True)
    is_active     = models.BooleanField(default=True)
    generated_at  = models.DateTimeField(auto_now_add=True)
    regenerated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'student_digital_id_cards'

    def __str__(self):
        return f"ID Card — {self.student.admission_number}"


# ── Status Change Log ─────────────────────────────────────────────────────────

class StudentStatusHistory(models.Model):
    """Tracks every status change (active → inactive → alumni etc.)."""
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student    = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='status_history')
    old_status = models.CharField(max_length=15, choices=STUDENT_STATUS_CHOICES)
    new_status = models.CharField(max_length=15, choices=STUDENT_STATUS_CHOICES)
    reason     = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL,null=True, blank=True,on_delete=models.SET_NULL,)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'student_status_history'
        ordering = ['changed_at']

    def __str__(self):
        return (
            f"{self.student.admission_number}: "
            f"{self.old_status} → {self.new_status} @ {self.changed_at:%Y-%m-%d}"
        )