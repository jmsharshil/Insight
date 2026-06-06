import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

from onboarding.models import Admission

enrolled = Admission.objects.filter(status='enrolled')
print(f"Total enrolled admissions: {enrolled.count()}")
for a in enrolled:
    print(f"Admission {a.id} email {a.email}")

