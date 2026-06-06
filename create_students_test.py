import os
import django
import logging

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

from onboarding.models import Admission
from auth_user.models import User
from students.utils import StudentService

admissions = Admission.objects.filter(status='enrolled')
for a in admissions:
    print(f"Checking Admission {a.id} {a.email}")
    student_user = User.objects.filter(email=a.email, role='student').first()
    if not student_user:
        print(f"No student user for {a.email}")
        continue
    
    try:
        student = StudentService.create_from_admission(
            admission=a,
            user=student_user,
        )
        print(f"Student created successfully: {student.id}")
    except Exception as e:
        print(f"Failed to create student: {e}")

