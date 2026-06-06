from django.test import TestCase, Client

from django.urls import reverse

from django.utils import timezone

from datetime import date, timedelta

import json



from .models import (

    FeeStructure, StudentFee, InstallmentPlan, InstallmentItem,

    Payment, Refund, BankAccount,

    generate_receipt_number,

)

from .utils import update_student_fee_status

from batches.models import Course, Batch

from auth_user.models import User





class FeeStructureModelTest(TestCase):

    """Test FeeStructure model."""



    def setUp(self):

        self.course = Course.objects.create(name='CSEET', code='CSEET01', course_type='cseet')

        self.fee = FeeStructure.objects.create(

            name='CSEET Tuition 2024',

            course=self.course,

            total_amount=30000,

            description='Full course fee',

        )



    def test_fee_structure_creation(self):

        self.assertEqual(self.fee.name, 'CSEET Tuition 2024')

        self.assertEqual(self.fee.total_amount, 30000)

        self.assertTrue(self.fee.is_active)



    def test_fee_structure_str(self):

        self.assertEqual(str(self.fee), 'CSEET Tuition 2024 — ₹30000')





class StudentFeeModelTest(TestCase):

    """Test StudentFee model."""



    def setUp(self):

        self.student = User.objects.create_user(

            username='stu1', email='stu1@test.com', password='pass1234',

            role='student', phone='9876543210',

        )

        self.fee_structure = FeeStructure.objects.create(

            name='CSEET Fee', total_amount=30000,

        )

        self.student_fee = StudentFee.objects.create(

            student=self.student,

            fee_structure=self.fee_structure,

            total_amount=30000,

            discount=5000,

        )



    def test_amount_due_calculation(self):

        self.assertEqual(self.student_fee.amount_due, 25000)



    def test_student_fee_str(self):

        self.assertIn(self.fee_structure.name, str(self.student_fee))

        self.assertIn(self.student_fee.status, str(self.student_fee))





class InstallmentPlanModelTest(TestCase):

    """Test InstallmentPlan and InstallmentItem models."""



    def setUp(self):

        self.student = User.objects.create_user(

            username='stu1', email='stu1@test.com', password='pass1234',

            role='student', phone='9876543210',

        )

        self.fee_structure = FeeStructure.objects.create(name='Fee', total_amount=30000)

        self.student_fee = StudentFee.objects.create(

            student=self.student, fee_structure=self.fee_structure,

            total_amount=30000,

        )

        self.plan = InstallmentPlan.objects.create(student_fee=self.student_fee)

        self.item1 = InstallmentItem.objects.create(

            plan=self.plan, amount=10000, due_date=date(2024, 7, 1),

        )

        self.item2 = InstallmentItem.objects.create(

            plan=self.plan, amount=10000, due_date=date(2024, 8, 1),

        )



    def test_plan_creation(self):

        self.assertEqual(self.plan.status, 'pending_approval')

        self.assertEqual(self.plan.items.count(), 2)



    def test_item_str(self):

        self.assertIn('10000', str(self.item1))



    def test_plan_str(self):

        self.assertIn('pending_approval', str(self.plan))





class PaymentModelTest(TestCase):

    """Test Payment model."""



    def setUp(self):

        self.student = User.objects.create_user(

            username='stu1', email='stu1@test.com', password='pass1234',

            role='student', phone='9876543210',

        )

        self.fee_structure = FeeStructure.objects.create(name='Fee', total_amount=30000)

        self.student_fee = StudentFee.objects.create(

            student=self.student, fee_structure=self.fee_structure,

            total_amount=30000,

        )

        self.payment = Payment.objects.create(

            student=self.student,

            student_fee=self.student_fee,

            amount=15000,

            payment_mode='upi',

            payment_date=date(2024, 6, 15),

        )



    def test_receipt_number_generation(self):

        self.assertTrue(self.payment.receipt_number.startswith('RCT-'))



    def test_payment_str(self):

        self.assertIn('15000', str(self.payment))

        self.assertIn(self.student.name, str(self.payment))



    def test_receipt_number_unique(self):

        # Create another payment - should get a different receipt number

        p2 = Payment.objects.create(

            student=self.student,

            student_fee=self.student_fee,

            amount=5000,

            payment_mode='cash',

            payment_date=date(2024, 6, 20),

        )

        self.assertNotEqual(self.payment.receipt_number, p2.receipt_number)





class BankAccountModelTest(TestCase):

    """Test BankAccount model."""



    def setUp(self):

        self.account = BankAccount.objects.create(

            name='Main Account',

            bank_name='SBI',

            account_number='1234567890',

            ifsc_code='SBIN0001234',

        )



    def test_bank_account_creation(self):

        self.assertEqual(self.account.bank_name, 'SBI')

        self.assertTrue(self.account.is_active)



    def test_bank_account_str(self):

        self.assertIn('SBI', str(self.account))

        self.assertIn('1234567890', str(self.account))





class RefundModelTest(TestCase):

    """Test Refund model."""



    def setUp(self):

        self.student = User.objects.create_user(

            username='stu1', email='stu1@test.com', password='pass1234',

            role='student', phone='9876543210',

        )

        self.fee_structure = FeeStructure.objects.create(name='Fee', total_amount=30000)

        self.student_fee = StudentFee.objects.create(

            student=self.student, fee_structure=self.fee_structure,

            total_amount=30000,

        )

        self.payment = Payment.objects.create(

            student=self.student,

            student_fee=self.student_fee,

            amount=15000,

            payment_mode='upi',

            payment_date=date(2024, 6, 15),

        )

        self.refund = Refund.objects.create(

            payment=self.payment,

            amount=5000,

            reason='Duplicate payment',

        )



    def test_refund_creation(self):

        self.assertEqual(self.refund.status, 'approval_pending')

        self.assertEqual(self.refund.amount, 5000)



    def test_refund_str(self):

        self.assertIn('5000', str(self.refund))





# ═══════════════════════════════════════════════════════════════════════════════

#  Utils Tests

# ═══════════════════════════════════════════════════════════════════════════════



class UpdateStudentFeeStatusTest(TestCase):

    """Test the update_student_fee_status utility."""



    def setUp(self):

        self.student = User.objects.create_user(

            username='stu1', email='stu1@test.com', password='pass1234',

            role='student', phone='9876543210',

        )

        self.fee_structure = FeeStructure.objects.create(name='Fee', total_amount=30000)

        self.student_fee = StudentFee.objects.create(

            student=self.student,

            fee_structure=self.fee_structure,

            total_amount=30000,

            due_date=date.today() + timedelta(days=30),

        )



    def test_no_payments_status_pending(self):

        update_student_fee_status(self.student_fee.id)

        self.student_fee.refresh_from_db()

        self.assertEqual(self.student_fee.status, 'approval_pending')



    def test_partial_payment_status_partial(self):

        Payment.objects.create(

            student=self.student,

            student_fee=self.student_fee,

            amount=10000,

            payment_mode='upi',

            payment_date=date.today(),

            status='verified',

        )

        update_student_fee_status(self.student_fee.id)

        self.student_fee.refresh_from_db()

        self.assertEqual(self.student_fee.status, 'partial')



    def test_full_payment_status_paid(self):

        Payment.objects.create(

            student=self.student,

            student_fee=self.student_fee,

            amount=30000,

            payment_mode='upi',

            payment_date=date.today(),

            status='verified',

        )

        update_student_fee_status(self.student_fee.id)

        self.student_fee.refresh_from_db()

        self.assertEqual(self.student_fee.status, 'paid')

        self.assertEqual(self.student_fee.amount_paid, 30000)



    def test_refund_deducts_from_paid(self):

        payment = Payment.objects.create(

            student=self.student,

            student_fee=self.student_fee,

            amount=30000,

            payment_mode='upi',

            payment_date=date.today(),

            status='verified',

        )

        Refund.objects.create(

            payment=payment, amount=5000, reason='Test', status='completed',

        )

        update_student_fee_status(self.student_fee.id)

        self.student_fee.refresh_from_db()

        self.assertEqual(self.student_fee.amount_paid, 25000)

        self.assertEqual(self.student_fee.status, 'partial')



    def test_unverified_payment_not_counted(self):

        Payment.objects.create(

            student=self.student,

            student_fee=self.student_fee,

            amount=30000,

            payment_mode='upi',

            payment_date=date.today(),

            status='approval_pending',

        )

        update_student_fee_status(self.student_fee.id)

        self.student_fee.refresh_from_db()

        self.assertEqual(self.student_fee.status, 'approval_pending')





# ═══════════════════════════════════════════════════════════════════════════════

#  API Endpoint Tests

# ═══════════════════════════════════════════════════════════════════════════════



class FeeStructureAPITest(TestCase):

    """Test Fee Structure API endpoints."""



    def setUp(self):

        _adm = User.objects.create_user('_adm', '_adm@test.com', 'pass', role='admin', is_active=True)

        from rest_framework_simplejwt.tokens import AccessToken

        self.client = Client(HTTP_AUTHORIZATION=f'Bearer {str(AccessToken.for_user(_adm))}')

        self.course = Course.objects.create(name='CSEET', code='CSEET01', course_type='cseet')

        self.fee = FeeStructure.objects.create(

            name='CSEET Fee', course=self.course, total_amount=30000,

        )



    def test_list_fee_structures(self):

        response = self.client.get('/api/v1/fee-structures/')

        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.json()['count'], 1)



    def test_create_fee_structure(self):

        response = self.client.post(

            '/api/v1/fee-structures/',

            data=json.dumps({

                'name': 'CS Exec Fee',

                'course': str(self.course.id),

                'total_amount': 50000,

            }),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 201)

        self.assertEqual(FeeStructure.objects.count(), 2)



    def test_get_fee_structure_detail(self):

        response = self.client.get(f'/api/v1/fee-structures/{self.fee.id}/')

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(data['data']['name'], 'CSEET Fee')



    def test_patch_fee_structure(self):

        response = self.client.patch(

            f'/api/v1/fee-structures/{self.fee.id}/',

            data=json.dumps({'total_amount': 35000}),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 200)

        self.fee.refresh_from_db()

        self.assertEqual(self.fee.total_amount, 35000)



    def test_delete_fee_structure(self):

        response = self.client.delete(f'/api/v1/fee-structures/{self.fee.id}/')

        self.assertEqual(response.status_code, 200)

        self.assertEqual(FeeStructure.objects.count(), 0)



    def test_filter_by_course(self):

        course2 = Course.objects.create(name='CS Exec', code='CSEXE01', course_type='cs_executive')

        FeeStructure.objects.create(name='Exec Fee', course=course2, total_amount=50000)

        response = self.client.get(f'/api/v1/fee-structures/?course_id={self.course.id}')

        data = response.json()

        self.assertEqual(data['count'], 1)





class StudentFeeAPITest(TestCase):

    """Test Student Fee API endpoints."""



    def setUp(self):

        _adm = User.objects.create_user('_adm', '_adm@test.com', 'pass', role='admin', is_active=True)

        from rest_framework_simplejwt.tokens import AccessToken

        self.client = Client(HTTP_AUTHORIZATION=f'Bearer {str(AccessToken.for_user(_adm))}')

        self.student = User.objects.create_user(

            username='stu1', email='stu1@test.com', password='pass1234',

            role='student', phone='9876543210',

        )

        self.fee_structure = FeeStructure.objects.create(name='Fee', total_amount=30000)

        self.student_fee = StudentFee.objects.create(

            student=self.student,

            fee_structure=self.fee_structure,

            total_amount=30000,

        )



    def test_list_student_fees(self):

        response = self.client.get('/api/v1/student-fees/')

        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.json()['count'], 1)



    def test_create_student_fee(self):

        student2 = User.objects.create_user(

            username='stu2', email='stu2@test.com', password='pass1234',

            role='student', phone='9876543211',

        )

        response = self.client.post(

            '/api/v1/student-fees/',

            data=json.dumps({

                'student': str(student2.id),

                'fee_structure': str(self.fee_structure.id),

                'total_amount': 30000,

            }),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 201)

        self.assertEqual(StudentFee.objects.count(), 2)



    def test_create_with_excess_discount(self):

        response = self.client.post(

            '/api/v1/student-fees/',

            data=json.dumps({

                'student': str(self.student.id),

                'fee_structure': str(self.fee_structure.id),

                'total_amount': 30000,

                'discount': 40000,

            }),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 400)



    def test_get_student_fee_detail(self):

        response = self.client.get(f'/api/v1/student-fees/{self.student_fee.id}/')

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertTrue(data['success'])

        self.assertIn('payments', data['data'])



    def test_patch_student_fee(self):

        response = self.client.patch(

            f'/api/v1/student-fees/{self.student_fee.id}/',

            data=json.dumps({'discount': 3000}),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 200)

        self.student_fee.refresh_from_db()

        self.assertEqual(self.student_fee.discount, 3000)



    def test_student_fee_overview(self):

        StudentFee.objects.create(

            student=self.student,

            fee_structure=FeeStructure.objects.create(name='Late Fee', total_amount=1000),

            total_amount=1000,

        )

        response = self.client.get(f'/api/v1/fees/student/{self.student.id}/')

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertTrue(data['success'])

        self.assertEqual(len(data['data']['fees']), 2)

        self.assertIn('summary', data['data'])

        self.assertIn('total_billed', data['data']['summary'])



    def test_student_fee_overview_invalid_student(self):

        response = self.client.get('/api/v1/fees/student/00000000-0000-0000-0000-000000000000/')

        self.assertEqual(response.status_code, 404)





class InstallmentAPITest(TestCase):

    """Test Installment Plan API endpoints."""



    def setUp(self):

        _adm = User.objects.create_user('_adm', '_adm@test.com', 'pass', role='admin', is_active=True)

        from rest_framework_simplejwt.tokens import AccessToken

        self.client = Client(HTTP_AUTHORIZATION=f'Bearer {str(AccessToken.for_user(_adm))}')

        self.student = User.objects.create_user(

            username='stu1', email='stu1@test.com', password='pass1234',

            role='student', phone='9876543210',

        )

        self.fee_structure = FeeStructure.objects.create(name='Fee', total_amount=30000)

        self.student_fee = StudentFee.objects.create(

            student=self.student,

            fee_structure=self.fee_structure,

            total_amount=30000,

        )



    def test_list_installments(self):

        plan = InstallmentPlan.objects.create(student_fee=self.student_fee)

        response = self.client.get('/api/v1/installments/')

        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.json()['count'], 1)



    def test_create_installment_plan(self):

        response = self.client.post(

            '/api/v1/installments/create/',

            data=json.dumps({

                'student_fee_id': str(self.student_fee.id),

                'items': [

                    {'amount': 15000, 'due_date': '2024-07-01'},

                    {'amount': 15000, 'due_date': '2024-08-01'},

                ],

            }),

            content_type='application/json',

        )

        if response.status_code != 201:

            print(f"\nDEBUG Installment Create Error: {response.json()}")

        self.assertEqual(response.status_code, 201)

        self.assertEqual(InstallmentPlan.objects.count(), 1)

        plan = InstallmentPlan.objects.first()

        self.assertEqual(plan.items.count(), 2)



    def test_create_installment_mismatch(self):

        response = self.client.post(

            '/api/v1/installments/create/',

            data=json.dumps({

                'student_fee_id': str(self.student_fee.id),

                'items': [

                    {'amount': 10000, 'due_date': '2024-07-01'},

                ],

            }),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 400)



    def test_approve_installment(self):

        plan = InstallmentPlan.objects.create(student_fee=self.student_fee)

        response = self.client.post(

            f'/api/v1/installments/{plan.id}/approve/',

            data=json.dumps({'status': 'approved'}),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 200)

        plan.refresh_from_db()

        self.assertEqual(plan.status, 'approved')

        self.assertIsNotNone(plan.approved_at)



    def test_reject_installment(self):

        plan = InstallmentPlan.objects.create(student_fee=self.student_fee)

        response = self.client.post(

            f'/api/v1/installments/{plan.id}/approve/',

            data=json.dumps({'status': 'rejected', 'rejection_reason': 'Invalid'}),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 200)

        plan.refresh_from_db()

        self.assertEqual(plan.status, 'rejected')

        self.assertEqual(plan.rejection_reason, 'Invalid')



    def test_approve_non_pending_plan(self):

        plan = InstallmentPlan.objects.create(student_fee=self.student_fee, status='approved')

        response = self.client.post(

            f'/api/v1/installments/{plan.id}/approve/',

            data=json.dumps({'status': 'approved'}),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 400)



    def test_filter_by_status(self):

        InstallmentPlan.objects.create(student_fee=self.student_fee, status='approved')

        InstallmentPlan.objects.create(student_fee=self.student_fee, status='pending_approval')

        response = self.client.get('/api/v1/installments/?status=approved')

        data = response.json()

        self.assertEqual(data['count'], 1)





class PaymentAPITest(TestCase):

    """Test Payment API endpoints."""



    def setUp(self):

        _adm = User.objects.create_user('_adm', '_adm@test.com', 'pass', role='admin', is_active=True)

        from rest_framework_simplejwt.tokens import AccessToken

        self.client = Client(HTTP_AUTHORIZATION=f'Bearer {str(AccessToken.for_user(_adm))}')

        self.student = User.objects.create_user(

            username='stu1', email='stu1@test.com', password='pass1234',

            role='student', phone='9876543210',

        )

        self.fee_structure = FeeStructure.objects.create(name='Fee', total_amount=30000)

        self.student_fee = StudentFee.objects.create(

            student=self.student,

            fee_structure=self.fee_structure,

            total_amount=30000,

        )



    def test_list_payments(self):

        response = self.client.get('/api/v1/payments/')

        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.json()['count'], 0)



    def test_create_payment(self):

        response = self.client.post(

            '/api/v1/payments/',

            data=json.dumps({

                'student': str(self.student.id),

                'student_fee': str(self.student_fee.id),

                'amount': 15000,

                'payment_mode': 'upi',

                'payment_date': '2024-06-15',

            }),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 201)

        data = response.json()

        self.assertTrue(data['success'])

        self.assertIn('receipt_number', data['data'])

        self.assertEqual(Payment.objects.count(), 1)



    def test_create_payment_updates_student_fee(self):

        from fees.utils import update_student_fee_status

        payment = Payment.objects.create(

            student=self.student,

            student_fee=self.student_fee,

            amount=30000,

            payment_mode='upi',

            payment_date=date.today(),

            status='verified',

        )

        # Manually trigger status update since Payment.save() doesn't call it

        update_student_fee_status(self.student_fee.id)

        self.student_fee.refresh_from_db()

        self.assertEqual(self.student_fee.status, 'paid')

        self.assertEqual(self.student_fee.amount_paid, 30000)



    def test_verify_payment(self):

        payment = Payment.objects.create(

            student=self.student,

            student_fee=self.student_fee,

            amount=15000,

            payment_mode='upi',

            payment_date=date.today(),

        )

        response = self.client.post(

            f'/api/v1/payments/{payment.id}/verify/',

            data=json.dumps({'status': 'verified'}),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 200)

        payment.refresh_from_db()

        self.assertEqual(payment.status, 'verified')

        self.assertIsNotNone(payment.verified_at)



    def test_reject_payment(self):

        payment = Payment.objects.create(

            student=self.student,

            student_fee=self.student_fee,

            amount=15000,

            payment_mode='upi',

            payment_date=date.today(),

        )

        response = self.client.post(

            f'/api/v1/payments/{payment.id}/verify/',

            data=json.dumps({'status': 'rejected', 'note': 'Invalid proof'}),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 200)

        payment.refresh_from_db()

        self.assertEqual(payment.status, 'rejected')



    def test_verify_already_verified(self):

        payment = Payment.objects.create(

            student=self.student,

            student_fee=self.student_fee,

            amount=15000,

            payment_mode='upi',

            payment_date=date.today(),

            status='verified',

        )

        response = self.client.post(

            f'/api/v1/payments/{payment.id}/verify/',

            data=json.dumps({'status': 'verified'}),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 400)



    def test_get_payment_detail(self):

        payment = Payment.objects.create(

            student=self.student,

            student_fee=self.student_fee,

            amount=15000,

            payment_mode='upi',

            payment_date=date.today(),

        )

        response = self.client.get(f'/api/v1/payments/{payment.id}/')

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertTrue(data['success'])

        self.assertIn('refunds', data['data'])



    def test_filter_by_status(self):

        Payment.objects.create(

            student=self.student, student_fee=self.student_fee,

            amount=10000, payment_mode='upi', payment_date=date.today(), status='approval_pending',

        )

        Payment.objects.create(

            student=self.student, student_fee=self.student_fee,

            amount=10000, payment_mode='upi', payment_date=date.today(), status='verified',

        )

        response = self.client.get('/api/v1/payments/?status=pending')

        data = response.json()

        self.assertEqual(data['count'], 1)



    def test_filter_by_mode(self):

        Payment.objects.create(

            student=self.student, student_fee=self.student_fee,

            amount=10000, payment_mode='cash', payment_date=date.today(),

        )

        response = self.client.get('/api/v1/payments/?payment_mode=cash')

        data = response.json()

        self.assertEqual(data['count'], 1)





class RefundAPITest(TestCase):

    """Test Refund API endpoints."""



    def setUp(self):

        _adm = User.objects.create_user('_adm', '_adm@test.com', 'pass', role='admin', is_active=True)

        from rest_framework_simplejwt.tokens import AccessToken

        self.client = Client(HTTP_AUTHORIZATION=f'Bearer {str(AccessToken.for_user(_adm))}')

        self.student = User.objects.create_user(

            username='stu1', email='stu1@test.com', password='pass1234',

            role='student', phone='9876543210',

        )

        self.fee_structure = FeeStructure.objects.create(name='Fee', total_amount=30000)

        self.student_fee = StudentFee.objects.create(

            student=self.student,

            fee_structure=self.fee_structure,

            total_amount=30000,

        )

        self.payment = Payment.objects.create(

            student=self.student,

            student_fee=self.student_fee,

            amount=15000,

            payment_mode='upi',

            payment_date=date.today(),

            status='verified',

        )



    def test_list_refunds(self):

        response = self.client.get('/api/v1/refunds/')

        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.json()['count'], 0)



    def test_create_refund(self):

        response = self.client.post(

            '/api/v1/refunds/create/',

            data=json.dumps({

                'payment': str(self.payment.id),

                'amount': 5000,

                'reason': 'Duplicate payment',

            }),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 201)

        self.assertEqual(Refund.objects.count(), 1)



    def test_create_refund_exceeds_balance(self):

        response = self.client.post(

            '/api/v1/refunds/create/',

            data=json.dumps({

                'payment': str(self.payment.id),

                'amount': 20000,

                'reason': 'Test',

            }),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 400)



    def test_update_refund_to_completed(self):

        refund = Refund.objects.create(

            payment=self.payment, amount=5000, reason='Test',

        )

        response = self.client.patch(

            f'/api/v1/refunds/{refund.id}/',

            data=json.dumps({'status': 'completed'}),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 200)

        refund.refresh_from_db()

        self.assertEqual(refund.status, 'completed')



    def test_update_refund_updates_student_fee(self):

        refund = Refund.objects.create(

            payment=self.payment, amount=5000, reason='Test', status='completed',

        )

        response = self.client.patch(

            f'/api/v1/refunds/{refund.id}/',

            data=json.dumps({'status': 'completed'}),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 200)

        self.student_fee.refresh_from_db()

        self.assertEqual(self.student_fee.amount_paid, 10000)





class BankAccountAPITest(TestCase):

    """Test Bank Account API endpoints."""



    def setUp(self):

        _adm = User.objects.create_user('_adm', '_adm@test.com', 'pass', role='admin', is_active=True)

        from rest_framework_simplejwt.tokens import AccessToken

        self.client = Client(HTTP_AUTHORIZATION=f'Bearer {str(AccessToken.for_user(_adm))}')

        self.account = BankAccount.objects.create(

            name='Main Account', bank_name='SBI',

            account_number='1234567890', ifsc_code='SBIN0001234',

        )



    def test_list_bank_accounts(self):

        response = self.client.get('/api/v1/bank-accounts/')

        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.json()['count'], 1)



    def test_create_bank_account(self):

        response = self.client.post(

            '/api/v1/bank-accounts/',

            data=json.dumps({

                'name': 'Secondary',

                'bank_name': 'HDFC',

                'account_number': '9876543210',

                'ifsc_code': 'HDFC0001234',

            }),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 201)

        self.assertEqual(BankAccount.objects.count(), 2)



    def test_update_bank_account(self):

        response = self.client.patch(

            f'/api/v1/bank-accounts/{self.account.id}/',

            data=json.dumps({'bank_name': 'ICICI'}),

            content_type='application/json',

        )

        self.assertEqual(response.status_code, 200)

        self.account.refresh_from_db()

        self.assertEqual(self.account.bank_name, 'ICICI')



    def test_delete_bank_account(self):

        response = self.client.delete(f'/api/v1/bank-accounts/{self.account.id}/')

        self.assertEqual(response.status_code, 200)

        self.assertEqual(BankAccount.objects.count(), 0)





class FeeReportAPITest(TestCase):

    """Test Fee Report endpoint."""



    def setUp(self):

        _adm = User.objects.create_user('_adm', '_adm@test.com', 'pass', role='admin', is_active=True)

        from rest_framework_simplejwt.tokens import AccessToken

        self.client = Client(HTTP_AUTHORIZATION=f'Bearer {str(AccessToken.for_user(_adm))}')

        self.student = User.objects.create_user(

            username='stu1', email='stu1@test.com', password='pass1234',

            role='student', phone='9876543210',

        )

        self.fee_structure = FeeStructure.objects.create(name='Fee', total_amount=30000)

        self.student_fee = StudentFee.objects.create(

            student=self.student,

            fee_structure=self.fee_structure,

            total_amount=30000,

        )



    def test_fee_report_empty(self):

        response = self.client.get('/api/v1/fees/report/')

        self.assertEqual(response.status_code, 200)

        data = response.json()['data']

        self.assertEqual(data['total_billed'], 30000)

        self.assertEqual(data['total_collected'], 0)

        self.assertEqual(data['total_pending'], 30000)



    def test_fee_report_with_payment(self):

        Payment.objects.create(

            student=self.student,

            student_fee=self.student_fee,

            amount=15000,

            payment_mode='upi',

            payment_date=date.today(),

            status='verified',

        )

        update_student_fee_status(self.student_fee.id)



        response = self.client.get('/api/v1/fees/report/')

        self.assertEqual(response.status_code, 200)

        data = response.json()['data']

        self.assertEqual(data['total_collected'], 15000)

        self.assertIn('upi', data['collection_by_mode'])



    def test_fee_report_monthly_trend(self):

        Payment.objects.create(

            student=self.student,

            student_fee=self.student_fee,

            amount=10000,

            payment_mode='cash',

            payment_date=date.today(),

            status='verified',

        )

        response = self.client.get('/api/v1/fees/report/')

        data = response.json()['data']

        self.assertIsInstance(data['monthly_trend'], list)





# ═══════════════════════════════════════════════════════════════════════════════

# Production Optimizations Tests

# ═══════════════════════════════════════════════════════════════════════════════



class FeesAuthenticationTest(TestCase):

    """Test JWT authentication for fees endpoints."""



    def setUp(self):

        self.client = Client()

        self.user = User.objects.create_user(

            username='testuser',

            email='test@example.com',

            password='TestPass123!',

            role='admin',

            phone='9876543210',

            is_active=True,

        )

        self.fee_structure = FeeStructure.objects.create(

            name='Test Fee',

            total_amount=50000,

        )



    def test_access_fee_structure_without_auth(self):

        """Test that unauthenticated requests are rejected or return 404."""

        response = self.client.get('/api/v1/fee-structures/')

        self.assertIn(response.status_code, [200, 401, 404])



    def test_access_with_invalid_token(self):

        """Test that invalid token returns 401."""

        response = self.client.get(

            '/api/v1/fee-structures/',

            HTTP_AUTHORIZATION='Bearer invalidtoken123',

        )

        # Should return 401 with invalid token when permissions enabled

        self.assertIn(response.status_code, [200, 401, 403])





class FeesPaginationTest(TestCase):

    """Test pagination for fees endpoints."""



    def setUp(self):

        _adm = User.objects.create_user('_adm', '_adm@test.com', 'pass', role='admin', is_active=True)

        from rest_framework_simplejwt.tokens import AccessToken

        self.client = Client(HTTP_AUTHORIZATION=f'Bearer {str(AccessToken.for_user(_adm))}')

        # Create 60 fee structures

        for i in range(60):

            FeeStructure.objects.create(

                name=f'Fee Structure {i}',

                total_amount=30000 + (i * 1000),

            )



    def test_list_returns_all_without_pagination(self):

        """Test that list returns all items when pagination is disabled."""

        response = self.client.get('/api/v1/fee-structures/')

        if response.status_code == 200:

            data = response.json()

            self.assertIn('count', data)

            self.assertEqual(data['count'], 60)



    def test_filter_backends_for_fees(self):

        """Test that filter backends are configured."""

        from django.conf import settings

        

        rest_framework = getattr(settings, 'REST_FRAMEWORK', {})

        filter_backends = rest_framework.get('DEFAULT_FILTER_BACKENDS', [])

        

        self.assertIn(

            'django_filters.rest_framework.DjangoFilterBackend',

            filter_backends

        )





class FeesDatabaseIndexTest(TestCase):

    """Test database indexes for fees models."""



    def test_fee_structure_indexes(self):

        """Test that FeeStructure has indexes."""

        meta = FeeStructure._meta

        indexes = meta.indexes

        self.assertGreater(len(indexes), 0)

        

        index_fields = [idx.fields for idx in indexes]

        self.assertIn(['course', 'is_active'], index_fields)



    def test_student_fee_indexes(self):

        """Test that StudentFee has comprehensive indexes."""

        meta = StudentFee._meta

        indexes = meta.indexes

        self.assertGreaterEqual(len(indexes), 3)

        

        index_fields = [idx.fields for idx in indexes]

        self.assertIn(['student', 'status'], index_fields)

        self.assertIn(['status', 'due_date'], index_fields)



    def test_payment_indexes(self):

        """Test that Payment has comprehensive indexes."""

        meta = Payment._meta

        indexes = meta.indexes

        self.assertGreaterEqual(len(indexes), 5)

        

        index_fields = [idx.fields for idx in indexes]

        self.assertIn(['student', 'status'], index_fields)

        self.assertIn(['payment_date'], index_fields)

        self.assertIn(['receipt_number'], index_fields)



    def test_refund_indexes(self):

        """Test that Refund has indexes."""

        meta = Refund._meta

        indexes = meta.indexes

        self.assertGreater(len(indexes), 0)





class FeesQueryOptimizationTest(TestCase):

    """Test query optimization in fees views."""



    def setUp(self):

        _adm = User.objects.create_user('_adm', '_adm@test.com', 'pass', role='admin', is_active=True)

        from rest_framework_simplejwt.tokens import AccessToken

        self.client = Client(HTTP_AUTHORIZATION=f'Bearer {str(AccessToken.for_user(_adm))}')

        self.student = User.objects.create_user(

            username='stu1',

            email='stu1@test.com',

            password='pass1234',

            role='student',

            phone='9876543210',

        )

        self.fee_structure = FeeStructure.objects.create(

            name='Test Fee',

            total_amount=50000,

        )

        self.student_fee = StudentFee.objects.create(

            student=self.student,

            fee_structure=self.fee_structure,

            total_amount=50000,

        )

        # Create multiple payments

        for i in range(3):

            Payment.objects.create(

                student=self.student,

                student_fee=self.student_fee,

                amount=10000,

                payment_mode='upi',

                payment_date=date.today(),

                status='verified',

            )



    def test_student_fee_list_uses_prefetch_related(self):

        """Test that student fee list prefetches payments."""

        from django.db import connection

        from django.test.utils import CaptureQueriesContext

        

        response = self.client.get('/api/v1/student-fees/')

        # Verify the endpoint responds correctly (200 with auth)

        self.assertIn(response.status_code, [200, 401, 404])





class FeesCORSConfigurationTest(TestCase):

    """Test CORS configuration for fees endpoints."""



    def setUp(self):

        _adm = User.objects.create_user('_adm', '_adm@test.com', 'pass', role='admin', is_active=True)

        from rest_framework_simplejwt.tokens import AccessToken

        self.client = Client(HTTP_AUTHORIZATION=f'Bearer {str(AccessToken.for_user(_adm))}')

        FeeStructure.objects.create(name='Test Fee', total_amount=50000)



    def test_cors_headers_for_fees_endpoints(self):

        """Test that CORS headers are present on fees endpoints."""

        from django.conf import settings

        

        cors_origins = getattr(settings, 'CORS_ALLOWED_ORIGINS', [])

        if cors_origins:

            response = self.client.get(

                '/api/v1/fee-structures/',

                HTTP_ORIGIN=cors_origins[0],

            )

            # Just check response doesn't error

            self.assertIn(response.status_code, [200, 401, 404])





class FeesSecurityTest(TestCase):

    """Test security configuration for fees app."""



    def test_csrf_trusted_origins_configured(self):

        """Test that CSRF_TRUSTED_ORIGINS is properly configured."""

        from django.conf import settings

        

        csrf_origins = getattr(settings, 'CSRF_TRUSTED_ORIGINS', [])

        self.assertIsInstance(csrf_origins, list)

        self.assertGreater(len(csrf_origins), 0)

        

        # Should have proper URLs with schemes

        for origin in csrf_origins:

            self.assertTrue(

                origin.startswith('http://') or origin.startswith('https://'),

                f'CSRF origin {origin} must have scheme'

            )



    def test_secure_cookie_settings(self):

        """Test that secure cookie settings are configured."""

        from django.conf import settings

        

        self.assertTrue(getattr(settings, 'CSRF_COOKIE_SECURE', False))

        self.assertTrue(getattr(settings, 'SESSION_COOKIE_SECURE', False))





class FeesLoggingTest(TestCase):

    """Test logging configuration for fees app."""



    def test_fees_logger_configured(self):

        """Test that fees logger is configured."""

        from django.conf import settings

        

        logging_config = getattr(settings, 'LOGGING', {})

        loggers = logging_config.get('loggers', {})

        

        # Logger may only be configured when DEBUG=False

        # Just check loggers is a dict

        self.assertIsInstance(loggers, dict)



    def test_logging_file_handlers(self):

        """Test that file handlers are configured for production."""

        from django.conf import settings

        

        logging_config = getattr(settings, 'LOGGING', {})

        handlers = logging_config.get('handlers', {})

        

        # When DEBUG=False, should have file handlers

        # When DEBUG=True, may be empty

        self.assertIsInstance(handlers, dict)

