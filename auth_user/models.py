from django.db import models
from django.contrib.auth.models import AbstractBaseUser,PermissionsMixin,BaseUserManager
import uuid
import random
import secrets
from datetime import timedelta
from django.utils import timezone

class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class UserManager(BaseUserManager):
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
        
    ]
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    organization = models.ForeignKey(Organization,on_delete=models.CASCADE,related_name='users',null=True,blank=True)
    username = models.CharField(max_length=100,unique=True)
    email = models.EmailField()
    phone = models.CharField(max_length=15)
    name = models.CharField(max_length=255)
    role = models.CharField(max_length=50,choices=ROLE_CHOICES,default='student')
    branch = models.ForeignKey('branch.Branch',null=True,blank=True,on_delete=models.SET_NULL,related_name='users',)
    linked_student = models.ForeignKey('self',null=True,blank=True,on_delete=models.SET_NULL,related_name='linked_parents',limit_choices_to={'role': 'student'},)
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = UserManager()
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    def __str__(self):
        return self.email
    

class EmailOTP(models.Model):
    user = models.ForeignKey(User,on_delete=models.CASCADE)
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=5)

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
