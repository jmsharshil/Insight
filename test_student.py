import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

from students.models import Student
from exams.models import Exam

print("Students:")
for s in Student.objects.all():
    print(f"ID: {s.id}, First: {s.first_name}, Surname: {s.surname}, Roll: {s.roll_number}, Admission: {s.admission_number}")

