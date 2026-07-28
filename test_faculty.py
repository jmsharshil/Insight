import os
import sys
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "insight.settings")
django.setup()

from django.contrib.auth import get_user_model
from branch.models import Branch, Organization
from faculty.models import FacultyProfile
from leave.models import LeavePolicy, LeaveBalance
from leave.utils import initialize_leave_balances_for_year

User = get_user_model()
org = Organization.objects.first() or Organization.objects.create(name="Test Org")
b = Branch.objects.first() or Branch.objects.create(name="Test Branch", organization=org)

LeavePolicy.objects.get_or_create(branch=b, leave_type='casual', defaults={'annual_quota': 10, 'is_active': True})

u, created = User.objects.get_or_create(username='faculty1', email='f@example.com', role='faculty', is_active=True, defaults={'organization': org, 'name': 'Faculty 1'})
if created:
    u.set_password('pass')
    u.save()

FacultyProfile.objects.get_or_create(user=u, branch=b, defaults={'qualification': 'phd', 'specialization': 'cs', 'joining_date': '2026-01-01'})

print("Faculty branch:", u.faculty_profile.branch_id)
LeaveBalance.objects.all().delete()
created_count = initialize_leave_balances_for_year(b, 2026)
print(f"Created {created_count} balances.")
print("Balances for faculty1:", LeaveBalance.objects.filter(user=u).count())
