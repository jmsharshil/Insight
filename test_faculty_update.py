import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

from faculty.models import FacultyProfile
from payroll.models import PayrollRun, PaySlip
from faculty.serializers import FacultyUpdateSerializer
from decimal import Decimal

# Find a faculty with a draft payroll
ps = PaySlip.objects.filter(payroll_run__status='draft').first()
if ps:
    fp = ps.faculty
    pr = ps.payroll_run
    print(f"Found faculty: {fp.id}, current salary: {fp.salary}")
    print(f"Current Payslip basic_salary: {ps.basic_salary}")
    
    # Update via serializer
    ser = FacultyUpdateSerializer(fp, data={'salary': '55000.00'}, partial=True)
    if ser.is_valid():
        ser.save()
        print(f"Updated faculty salary to {fp.salary}")
    else:
        print("Validation failed:", ser.errors)
        
    # Check payslip again
    ps_new = PaySlip.objects.filter(faculty=fp, payroll_run=pr).first()
    if ps_new:
        print(f"New Payslip basic_salary: {ps_new.basic_salary}")
    else:
        print("Payslip deleted but not recreated?")
else:
    print("No draft payslips found.")
