import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

from students.models import Student

print("Total students:", Student.objects.count())
for s in Student.objects.all():
    print(f"Student: {s.id}, Name: {s.first_name}, Branch: {s.branch_id}")

