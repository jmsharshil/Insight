from django.db import models
from django.contrib.auth.models import AbstractBaseUser,PermissionsMixin,BaseUserManager
import uuid
import random
import secrets
from datetime import timedelta
from django.utils import timezone

LEVEL_CHOICES = [('executive', 'Executive'), ('professional', 'Professional')]
EMPLOYMENT_TYPE_CHOICES = [
    ('full_time', 'Full Time'), ('part_time', 'Part Time'), ('contract', 'Contract'), ('visiting', 'Visiting')
]
SCAN_TYPE_CHOICES = [('check_in', 'Check In'), ('check_out', 'Check Out')]
SESSION_STATUS_CHOICES = [('in_progress', 'In Progress'), ('completed', 'Completed')]

class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    logo_url = models.URLField(blank=True, default='')
    footer_text = models.TextField(blank=True, default='')
    primary_color = models.CharField(max_length=7, blank=True, default='#2563EB')
    website_url = models.URLField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class UserManager(BaseUserManager):
    def get_by_natural_key(self, username):
        return self.get(**{self.model.USERNAME_FIELD: username})

    def create_user(self,username,email,password=None,role='student',**extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(username=username,email=email,role=role,**extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self,username,email,password=None,**extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        return self.create_user(username=username,email=email,password=password,role='super_admin',**extra_fields)


class User(AbstractBaseUser, PermissionsMixin):

    ROLE_CHOICES = [
        ('super_admin', 'Super Admin'),
        ('branch_manager', 'Branch Manager'),
        ('admin_senior_executive', 'Admin Senior Executive'),
        ('admin_executive', 'Admin Executive'),
        ('front_desk','Front Desk'),
        ('counsellor','Counsellor'),
        ('sales_senior_executive','Sales Senior Executive'),
        ('sales_executive','Sales Executive'),
        ('tele_caller','Tele Caller'),
        ('exam_supervisor', 'Exam Supervisor'),
        ('paper_checker', 'Paper Checker'),
        ('accountant', 'Accountant'),
        ('student', 'Student'),
        ('parents', 'Parents'),
        ('faculty', 'Faculty'),
        ('house_keeping', 'House Keeping'),
        ('security', 'Security'),
        
    ]
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    organization = models.ForeignKey(Organization,on_delete=models.CASCADE,related_name='users',null=True,blank=True)
    username = models.CharField(max_length=100,unique=True)
    email = models.EmailField()
    phone = models.CharField(max_length=15)
    name = models.CharField(max_length=255)
    role = models.CharField(max_length=50,choices=ROLE_CHOICES,default='student')
    branch = models.ForeignKey('branch.Branch',null=True,blank=True,on_delete=models.SET_NULL,related_name='users',)
    linked_students = models.ManyToManyField('self', blank=True, symmetrical=False, related_name='linked_parents', limit_choices_to={'role': 'student'})
    profile_pic = models.ImageField(upload_to='profile_pics/', null=True, blank=True)
    fcm_token = models.TextField(blank=True, default='', help_text="Firebase Cloud Messaging device token for push notifications.")
    # Employee-specific fields
    employee_id = models.CharField(max_length=30, unique=True, blank=True, null=True)
    photo = models.ImageField(upload_to='employee/photos/', null=True, blank=True)
    qualification = models.CharField(max_length=200, blank=True)
    specialization = models.CharField(max_length=200, blank=True)
    subject_expertise = models.CharField(max_length=300, blank=True)
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='executive')
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, default='full_time')
    joining_date = models.DateField(null=True, blank=True)
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    session_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    bank_account = models.CharField(max_length=30, blank=True)
    ifsc_code = models.CharField(max_length=15, blank=True)
    pan_number = models.CharField(max_length=15, blank=True)
    aadhar_number = models.CharField(max_length=12, blank=True)
    qr_code = models.ImageField(upload_to='qr/employee/', null=True, blank=True)
    work_start_time = models.TimeField(null=True, blank=True)
    work_end_time = models.TimeField(null=True, blank=True)
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    salary_retention_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Percentage of gross salary to retain each month."
    )
    per_paper_rate = models.DecimalField(
        max_digits=8, decimal_places=2, default=0,
        help_text="Per-paper rate for paper_checker role (new FRD). Payment = papers_checked * rate - late_submission_penalties (5 days grace after exam.scheduled_date; then +5% per 7-day bracket)."
    )
    accessible_modules = models.JSONField(
        null=True, blank=True,
        help_text="List of modules this user has access to. If null, falls back to role default modules."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    objects = UserManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    def save(self, *args, **kwargs):
        # Auto-generate employee_id if not set, mirroring FacultyProfile logic
        if not self.employee_id:
            from django.utils import timezone
            year = timezone.now().year
            prefix = f"EMP-{year}-"
            # Look for existing IDs with same prefix
            last = User.objects.filter(employee_id__startswith=prefix).order_by('-employee_id').first()
            if last and last.employee_id:
                try:
                    seq = int(last.employee_id.split('-')[-1]) + 1
                except (ValueError, IndexError):
                    seq = 1
            else:
                seq = 1
            self.employee_id = f"{prefix}{seq:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email
    

class EmailOTP(models.Model):
    user = models.ForeignKey(User,on_delete=models.CASCADE)
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=10)

    @staticmethod
    def generate_otp():
        return str(random.randint(100000, 999999))


class PasswordSetToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(hours=24)

    @staticmethod
    def generate_token():
        return secrets.token_urlsafe(32)


class NotificationHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    body = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} - {self.title}"
