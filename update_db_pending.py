import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

from results.models import RecheckRequest
from onboarding.models import Admission, AdmissionStatusHistory
from leave.models import LeaveApplication
from fees.models import Payment, Refund, StudentFee

def update_status(model_class):
    count = model_class.objects.filter(status='pending').update(status='approval_pending')
    print(f"Updated {count} records in {model_class.__name__}")

update_status(RecheckRequest)
update_status(Admission)
update_status(AdmissionStatusHistory)
update_status(LeaveApplication)
update_status(Payment)
update_status(Refund)
update_status(StudentFee)

print("Database update complete.")
