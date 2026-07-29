"""
Quick test: save a LeavePolicy and verify that the signal auto-creates LeaveBalance records.
"""
import os, sys, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "insight.settings")
django.setup()

from django.contrib.auth import get_user_model
from branch.models import Branch
from leave.models import LeavePolicy, LeaveBalance

User = get_user_model()

# Pick first branch
branch = Branch.objects.first()
if not branch:
    print("[FAIL] No branches exist in the database.")
    sys.exit(1)

print(f"Branch: {branch.name} (id={branch.id})")

# Count staff linked to this branch
staff_direct = User.objects.filter(branch=branch, is_active=True).exclude(
    role__in=['student', 'parents', 'house_keeping', 'security']
)
print(f"Staff with User.branch = this branch: {staff_direct.count()}")
for u in staff_direct[:5]:
    print(f"  - {u.name} ({u.role})")

# Count super admins
sa_count = User.objects.filter(role='super_admin', is_active=True).count()
print(f"Super admins: {sa_count}")

# Delete existing balances to start clean
deleted = LeaveBalance.objects.all().delete()
print(f"Cleared {deleted[0]} old balance records.")

# Save a policy (this triggers the signal)
policy, created = LeavePolicy.objects.update_or_create(
    branch=branch, leave_type='casual',
    defaults={'annual_quota': 12, 'is_active': True},
)
print(f"\nPolicy saved: casual, quota=12 (created={created})")

# Check results
balances = LeaveBalance.objects.filter(leave_type='casual')
print(f"LeaveBalance records created by signal: {balances.count()}")
for b in balances[:10]:
    print(f"  - {b.user.name} ({b.user.role}): {b.total_days} days")

if balances.count() > 0:
    print("\n[OK] Signal is working correctly!")
else:
    print("\n[FAIL] No balances were created. Check signals.py for errors.")
