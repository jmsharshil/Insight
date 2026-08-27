import os
import sys
import django
import time

# Setup Django
sys.path.append('c:/Users/Admin/OneDrive - JMS Advisory Services Private Limited/Desktop/Insight')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

from onboarding.models import Admission
from fees.models import FeeStructure, Payment, Refund
from branch.models import Branch
from django.contrib.auth import get_user_model
from fees.razorpay_service import process_payment_link_paid_event, process_refund_processed_event
from students.utils import StudentService

User = get_user_model()

def test_flow():
    print("--- Starting Razorpay Test Flow ---")
    
    # Setup test data
    branch = Branch.objects.filter(is_active=True).first()
    counsellor, _ = User.objects.get_or_create(email="testcounsellor@example.com", username="testcounsellor", defaults={'role': 'counsellor'})
    
    # Get a fee structure
    fs = FeeStructure.objects.filter(is_active=True).first()
    
    admission = Admission.objects.last()
    if not admission:
        print("No admissions found in the DB. Please create one from the UI to test.")
        return
        
    admission.status = "payment_pending"
    admission.save()
    print(f"1. Using existing Admission {admission.id} in status: {admission.status}")
    
    # Generate reference_id like we do in onboarding
    reference_id = f"ADM_{admission.id}_{int(time.time())}"
    rp_payment_id = f"pay_test_{int(time.time())}"
    rp_refund_id = f"rfnd_test_{int(time.time())}"
    
    # 2. Simulate payment_link.paid webhook
    paid_payload = {
        "event": "payment_link.paid",
        "payload": {
            "payment_link": {
                "entity": {
                    "reference_id": reference_id,
                    "amount_paid": 100000, # 1000 INR
                    "id": "plink_test"
                }
            },
            "payment": {
                "entity": {
                    "id": rp_payment_id
                }
            }
        }
    }
    print(f"2. Simulating payment_link.paid for reference {reference_id}...")
    res = process_payment_link_paid_event(paid_payload)
    print("   Webhook Response:", res)
    
    admission.refresh_from_db()
    print(f"   Admission Status after payment: {admission.status}")
    print(f"   Transaction ID: {admission.transaction_id}")
    
    # 3. Simulate refund.processed before approval
    refund_payload = {
        "event": "refund.processed",
        "payload": {
            "refund": {
                "entity": {
                    "payment_id": rp_payment_id,
                    "id": rp_refund_id,
                    "amount": 100000
                }
            }
        }
    }
    print(f"\n3. Simulating refund.processed before approval for payment {rp_payment_id}...")
    res = process_refund_processed_event(refund_payload)
    print("   Webhook Response:", res)
    
    admission.refresh_from_db()
    print(f"   Admission Status after refund: {admission.status}")
    print(f"   Transaction ID: {admission.transaction_id}")
    
    # 4. Pay again and approve admission
    rp_payment_id_2 = f"pay_test_2_{int(time.time())}"
    paid_payload["payload"]["payment"]["entity"]["id"] = rp_payment_id_2
    print(f"\n4. Paying again with new payment ID {rp_payment_id_2}...")
    process_payment_link_paid_event(paid_payload)
    
    admission.refresh_from_db()
    print(f"   Admission Status after 2nd payment: {admission.status}")
    
    print("\n5. Approving admission via StudentService...")
    student = StudentService.create_from_admission(admission, counsellor, counsellor)
    print(f"   Student created: {student.admission_number}")
    
    # Verify Payment was created
    payment = Payment.objects.filter(transaction_ref=rp_payment_id_2).first()
    if payment:
        print(f"   Payment record created! ID: {payment.id}, Amount: {payment.amount}")
    else:
        print("   ERROR: Payment record not created!")
        
    # 6. Refund after approval
    rp_refund_id_2 = f"rfnd_test_2_{int(time.time())}"
    refund_payload["payload"]["refund"]["entity"]["payment_id"] = rp_payment_id_2
    refund_payload["payload"]["refund"]["entity"]["id"] = rp_refund_id_2
    print(f"\n6. Simulating refund.processed AFTER approval for payment {rp_payment_id_2}...")
    res = process_refund_processed_event(refund_payload)
    print("   Webhook Response:", res)
    
    refund = Refund.objects.filter(payment=payment).first()
    if refund:
        print(f"   Refund record created! ID: {refund.id}, Amount: {refund.amount}")
    else:
        print("   ERROR: Refund record not created!")
        
    print("\n--- Test Finished ---")

if __name__ == '__main__':
    test_flow()
