from django.db import models
from django.contrib.auth.models import AbstractBaseUser,PermissionsMixin,BaseUserManager
import uuid
import random
from datetime import timedelta
from django.utils import timezone


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
        ('student', 'Student'),
        ('parents', 'Parents'),
        ('faculty', 'Faculty'),
        ('exam_supervisor', 'Exam Supervisor'),
        ('paper_checker', 'Paper Checker'),
        ('accountant', 'Accountant'),
    ]
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    username = models.CharField(max_length=100,unique=True)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15,unique=True)
    name = models.CharField(max_length=255)
    role = models.CharField(max_length=50,choices=ROLE_CHOICES,default='student')
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = UserManager()
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

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