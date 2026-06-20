import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

from faculty.models import FacultyProfile, FacultyQRScanLog, SessionReport
from payroll.models import PayrollRun, LateEntryPolicy, PaySlip
from branch.models import Branch
from datetime import datetime, time, date
from decimal import Decimal

branch = Branch.objects.first()
if not branch:
    branch = Branch.objects.create(name='Test Branch', code='TST1')

policy, _ = LateEntryPolicy.objects.get_or_create(
    branch=branch,
    defaults={
        'grace_period_minutes': 5,
        'deduction_per_minute': Decimal('10.00'),
        'max_deduction_per_session': Decimal('100.00'),
        'is_active': True
    }
)
policy.is_active = True
policy.deduction_per_minute = Decimal('10.00')
policy.save()

fp = FacultyProfile.objects.filter(branch=branch).first()
if not fp:
    from django.contrib.auth import get_user_model
    User = get_user_model()
    u, _ = User.objects.get_or_create(email='test_fac@test.com', defaults={'role': 'faculty'})
    fp = FacultyProfile.objects.create(user=u, branch=branch, salary=Decimal('10000.00'), employment_type='full_time')

log = FacultyQRScanLog.objects.create(
    faculty=fp,
    branch=branch,
    scan_type='check_in',
    is_late=True,
    late_minutes=15
)
log.scanned_at = datetime.now()
log.save()

pr, _ = PayrollRun.objects.get_or_create(
    branch=branch,
    month=log.scanned_at.month,
    year=log.scanned_at.year,
    status='draft'
)

from payroll.utils import compute_payslip_for_faculty
ps = compute_payslip_for_faculty(fp, pr.month, pr.year, pr)
print("Late penalty on Payslip:", ps.late_penalty)
