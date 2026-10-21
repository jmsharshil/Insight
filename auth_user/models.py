from django.db import models
from django.contrib.auth.models import AbstractBaseUser,PermissionsMixin,BaseUserManager
import uuid
import random
import secrets
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from django.core.exceptions import ValidationError

LEVEL_CHOICES = [('executive', 'Executive'), ('professional', 'Professional')]
EMPLOYMENT_TYPE_CHOICES = [
    ('full_time', 'Full Time'), ('part_time', 'Part Time'), ('visiting', 'Visiting')
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
        phone = extra_fields.get('phone')
        if phone:
            extra_fields['phone'] = str(phone).strip()
        elif phone == '':
            extra_fields['phone'] = None
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
        ('head_coordinator', 'Head Coordinator'),
        ('senior_tele_caller', 'Senior Tele Caller'),
        ('cmo', 'CMO'),
        ('associate_bdm', 'Associate Business Development Manager'),
        ('printers', 'Printers'),
        ('exam_supervisor', 'Exam Supervisor'),
        ('paper_checker', 'Paper Checker'),
        ('accountant', 'Accountant'),
        ('student', 'Student'),
        ('parents', 'Parents'),
        ('faculty', 'Faculty'),
        ('house_keeping', 'House Keeping'),
        ('security', 'Security'),
        ('senior_bdm','Senior Business Development Manager'),
        ('deputy_bdm','Deputy Business Development Manager'),
        
    ]
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    organization = models.ForeignKey(Organization,on_delete=models.CASCADE,related_name='users',null=True,blank=True)
    username = models.CharField(max_length=100,unique=True)
    email = models.EmailField()
    phone = models.CharField(max_length=15, null=True, blank=True)
    name = models.CharField(max_length=255)
    role = models.CharField(max_length=50,choices=ROLE_CHOICES,default='student')
    branch = models.ForeignKey('branch.Branch', null=True, blank=True, on_delete=models.SET_NULL, related_name='users',)
    branches = models.ManyToManyField('branch.Branch', blank=True, related_name='multi_branch_users', help_text="Additional branches this user can access. The primary branch is set via the 'branch' FK above.")
    linked_students = models.ManyToManyField('self', blank=True, symmetrical=False, related_name='linked_parents', limit_choices_to={'role': 'student'})
    profile_pic = models.ImageField(upload_to='profile_pics/', null=True, blank=True)
    fcm_token = models.TextField(blank=True, default='', help_text="Firebase Cloud Messaging device token for push notifications.")
    # Employee-specific fields
    employee_id = models.CharField(max_length=100, unique=True, blank=True, null=True)
    photo = models.ImageField(upload_to='employee/photos/', null=True, blank=True)
    qualification = models.CharField(max_length=200, blank=True)
    specialization = models.CharField(max_length=200, blank=True)
    subject_expertise = models.CharField(max_length=300, blank=True)
    level = models.CharField(max_length=50, choices=LEVEL_CHOICES, default='executive', blank=True)
    levels = models.ManyToManyField('batches.CourseLevel', blank=True, related_name='faculty_users')
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
    working_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="Total working hours")
    weekly_schedule = models.JSONField(
        null=True, blank=True, default=dict,
        help_text="Day-wise shift timings and auto-calculated working hours for Sunday to Saturday."
    )
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
    additional_roles = models.JSONField(
        null=True, blank=True, default=list,
        help_text="List of additional roles for this user. Modules from these roles are merged into accessible_modules."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    objects = UserManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    def clean(self):
        super().clean()
        if self.phone:
            self.phone = self.phone.strip()
            # Uniqueness check disabled (existing data has duplicate phones)
            # qs = User.objects.filter(phone=self.phone)
            # if self.pk:
            #     qs = qs.exclude(pk=self.pk)
            # if qs.exists():
            #     raise ValidationError({'phone': 'User with this phone number already exists.'})

    def save(self, *args, **kwargs):
        # Auto-generate employee_id if not set, mirroring FacultyProfile logic
        if not self.employee_id or self.employee_id != self.username:
            self.employee_id = self.username
        if self.phone:
            self.phone = self.phone.strip()
        elif self.phone == '':
            self.phone = None

        if self.weekly_schedule:
            from auth_user.utils import process_weekly_schedule
            processed_sched, avg_hours = process_weekly_schedule(self.weekly_schedule)
            self.weekly_schedule = processed_sched
            if kwargs.get('update_fields') is not None:
                update_fields = set(kwargs['update_fields'])
                update_fields.add('weekly_schedule')
                if (self.working_hours is None or Decimal(str(self.working_hours)) == 0) and avg_hours > 0:
                    self.working_hours = avg_hours
                    update_fields.add('working_hours')
                kwargs['update_fields'] = update_fields
            elif (self.working_hours is None or Decimal(str(self.working_hours)) == 0) and avg_hours > 0:
                self.working_hours = avg_hours

        if (self.working_hours is None or Decimal(str(self.working_hours)) == 0) and self.work_start_time and self.work_end_time:
            from auth_user.utils import calculate_working_hours
            calculated_hours = calculate_working_hours(self.work_start_time, self.work_end_time)
            if calculated_hours > 0:
                self.working_hours = calculated_hours
                if kwargs.get('update_fields') is not None:
                    update_fields = set(kwargs['update_fields'])
                    update_fields.add('working_hours')
                    kwargs['update_fields'] = update_fields

        super().save(*args, **kwargs)

    def get_shift_timings_for_date(self, target_date=None):
        """
        Returns (start_time, end_time) as datetime.time objects (or None) for the given date/datetime or today.
        Falls back to (self.work_start_time, self.work_end_time).
        """
        from django.utils import timezone
        from datetime import datetime, date, time
        from auth_user.utils import normalize_day_name

        if target_date is None:
            target_date = timezone.localdate()
        elif isinstance(target_date, datetime):
            target_date = target_date.date()

        day_name = target_date.strftime('%A').lower() if isinstance(target_date, date) else normalize_day_name(target_date)

        if self.weekly_schedule and isinstance(self.weekly_schedule, dict) and day_name in self.weekly_schedule:
            day_data = self.weekly_schedule[day_name]
            if isinstance(day_data, dict):
                s_t = day_data.get('start_time')
                e_t = day_data.get('end_time')

                def _to_time(t):
                    if not t:
                        return None
                    if isinstance(t, time):
                        return t
                    t_str = str(t).strip()
                    for fmt in ('%H:%M:%S', '%H:%M'):
                        try:
                            return datetime.strptime(t_str, fmt).time()
                        except ValueError:
                            pass
                    return None

                parsed_s = _to_time(s_t)
                parsed_e = _to_time(e_t)
                if parsed_s or parsed_e:
                    return parsed_s or self.work_start_time, parsed_e or self.work_end_time

        return self.work_start_time, self.work_end_time

    def get_working_hours_for_date(self, target_date=None):
        """
        Returns Decimal working hours for the given date/datetime or today.
        Evaluates day-specific hours from weekly_schedule if available,
        otherwise falls back to self.working_hours or work_start_time/work_end_time.
        """
        from django.utils import timezone
        from datetime import datetime, date
        from auth_user.utils import normalize_day_name, calculate_working_hours

        if target_date is None:
            target_date = timezone.localdate()
        elif isinstance(target_date, datetime):
            target_date = target_date.date()

        if self.is_day_off(target_date):
            return Decimal('0.00')

        day_name = target_date.strftime('%A').lower() if isinstance(target_date, date) else normalize_day_name(target_date)

        if self.weekly_schedule and isinstance(self.weekly_schedule, dict) and day_name in self.weekly_schedule:
            day_data = self.weekly_schedule[day_name]
            if isinstance(day_data, dict):
                if day_data.get('is_off'):
                    return Decimal('0.00')
                wh = day_data.get('working_hours')
                if wh not in [None, '', 'null', 'undefined']:
                    try:
                        wh_dec = Decimal(str(wh))
                        if wh_dec > 0:
                            return wh_dec
                    except Exception:
                        pass
                s_t = day_data.get('start_time')
                e_t = day_data.get('end_time')
                if s_t and e_t:
                    return calculate_working_hours(s_t, e_t)

        if self.working_hours is not None and Decimal(str(self.working_hours)) > 0:
            return Decimal(str(self.working_hours))

        if self.work_start_time and self.work_end_time:
            return calculate_working_hours(self.work_start_time, self.work_end_time)

        return Decimal('0.00')

    def is_day_off(self, target_date=None):
        """
        Returns True if target_date is an off day for this user based on weekly_schedule.
        Supports saturday_rule:
          * 'odd': 1st, 3rd, 5th Saturday of month is working; 2nd, 4th Saturday is off.
          * 'even': 2nd, 4th Saturday of month is working; 1st, 3rd, 5th Saturday is off.
          * 'off': All Saturdays are off.
          * 'all': All Saturdays are working.
        If is_off is explicitly set to True for this day, returns True.
        If weekly_schedule is configured and is_off is False, returns False.
        Falls back to Sunday (weekday 6) being off if no weekly_schedule is configured.
        """
        from django.utils import timezone
        from datetime import datetime, date
        from auth_user.utils import normalize_day_name, is_saturday_off

        if target_date is None:
            target_date = timezone.localdate()
        elif isinstance(target_date, datetime):
            target_date = target_date.date()

        if isinstance(target_date, date):
            day_name = target_date.strftime('%A').lower()
            dow = target_date.weekday()
        else:
            day_name = normalize_day_name(target_date)
            dow = None

        if self.weekly_schedule and isinstance(self.weekly_schedule, dict) and day_name in self.weekly_schedule:
            day_data = self.weekly_schedule[day_name]
            if isinstance(day_data, dict):
                if day_name == 'saturday':
                    sat_rule = day_data.get('saturday_rule') or day_data.get('rule') or day_data.get('mode')
                    if sat_rule:
                        return is_saturday_off(target_date, sat_rule)
                return bool(day_data.get('is_off', False))

        return dow == 6 if dow is not None else False

    def update_today_working_hours(self, save=True):
        """
        Calculates and updates user.working_hours to today's working hours
        if day-specific schedule exists.
        """
        today_hours = self.get_working_hours_for_date()
        if today_hours > 0:
            self.working_hours = today_hours
            if save and self.pk:
                self.save(update_fields=['working_hours'])
        return self.working_hours



    def get_all_roles(self):
        """Return a set of all roles for this user (primary role + additional_roles)."""
        roles = set()
        if self.role:
            roles.add(self.role)
        if self.additional_roles and isinstance(self.additional_roles, (list, tuple, set)):
            roles.update(self.additional_roles)
        return roles

    def has_role(self, *roles):
        """Check if user has any of the given roles."""
        return bool(self.get_all_roles().intersection(roles))

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
    NOTIFICATION_TYPE_CHOICES = [
        ('system', 'System'),
        ('authentication', 'Authentication'),
        ('admission', 'Admission'),
        ('attendance', 'Attendance'),
        ('timetable', 'Timetable'),
        ('chat', 'Chat'),
        ('exam', 'Exam'),
        ('fees', 'Fees'),
        ('inventory', 'Inventory'),
        ('leads', 'Leads'),
        ('leave', 'Leave'),
        ('payroll', 'Payroll'),
        ('results', 'Results'),
        ('sales', 'Sales'),
        ('support', 'Support'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    body = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPE_CHOICES, default='system')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} - {self.title}"
