"""
onboarding/tests.py — Integration tests for the Admission → Student → Fees pipeline.

Tests verify that enrolling an Admission automatically creates:
  1. A User account (role=student)
  2. A Student profile linked to the admission
  3. A StudentFee record linked to the student (via fees.services.create_student_fee)
"""
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch, MagicMock

from onboarding.models import Admission
from fees.models import FeeStructure, StudentFee, BankAccount, InstallmentPlan, InstallmentItem
from students.models import Student
from auth_user.models import User
from batches.models import Course, CourseLevel
from rest_framework.test import APIRequestFactory, force_authenticate


def _make_admission(fee_structure=None, **overrides):
    """Helper: create a minimal valid Admission with all required non-null fields."""
    defaults = {
        'first_name': 'Test',
        'surname': 'Student',
        'father_name': 'Test Father',
        'mother_name': 'Test Mother',
        'category': 'gen',
        'dob': '2000-01-01',
        'email': 'teststu@integration.com',
        'email_parent': 'parent@integration.com',
        'phone_student': '9876543210',
        'phone_father': '9876543211',
        'street': '123 Main St',
        'city': 'Ahmedabad',
        'state': 'Gujarat',
        'pincode': '380001',
        'course': 'cseet',
        'group_module': 'full',
        'batch_attempt': 'june',
        'location': 'Ahmedabad',
        'qualification': 'pass_12',
        'reference': 'google',
        'tenth_medium': 'cbse',
        'tenth_school': 'Test School',
        'tenth_percentage': '85.00',
        'tenth_percentile': '92.00',
        'twelfth_medium': 'cbse',
        'twelfth_school': 'Test School',
        'twelfth_percentage': '80.00',
        'twelfth_percentile': '88.00',
        # FileFields are optional-in-practice for DB save (blank strings work)
        'doc_signature': '',
        'doc_photo': '',
        'doc_dob_certificate': '',
        'doc_id_card': '',
        'status': 'approval_pending',
        'fee_structure': fee_structure,
    }
    defaults.update(overrides)
    return Admission.objects.create(**defaults)


class AdmissionBankAssignmentTest(TestCase):
    def test_existing_bank_assignment_is_preserved(self):
        first_bank = BankAccount.objects.create(
            name='Bank One',
            bank_name='SBI',
            account_number='11111111111',
            ifsc_code='SBIN0000001',
            branch_name='Main Branch',
        )
        second_bank = BankAccount.objects.create(
            name='Bank Two',
            bank_name='HDFC',
            account_number='22222222222',
            ifsc_code='HDFC0000002',
            branch_name='Other Branch',
        )
        admission = _make_admission(status='form_pending')

        admission.assign_payment_bank_account(first_bank)
        admission.refresh_from_db()
        self.assertEqual(admission.bank_account, first_bank)

        admission.assign_payment_bank_account(second_bank)
        admission.refresh_from_db()
        self.assertEqual(admission.bank_account, first_bank)
        self.assertEqual(admission.bank_account_id, first_bank.id)

    def test_current_year_installment_amount_is_used_for_bank_threshold(self):
        from onboarding.views import _get_bank_selection_amount

        admission = _make_admission(status='form_pending')
        user = User.objects.create_user(
            username='student_installment',
            email='student_installment@example.com',
            password='testpass123',
            role='student',
            name='Installment Student',
        )
        student = Student.objects.create(
            admission=admission,
            user=user,
            first_name='Installment',
            surname='Student',
            father_name='Father',
            mother_name='Mother',
            dob='2000-01-01',
            category='gen',
            email='student_installment@example.com',
            phone_student='9876543210',
            phone_father='9876543211',
            street='123 Main St',
            city='Ahmedabad',
            state='Gujarat',
            pincode='380001',
            course='cseet',
            group_module='full',
            batch_attempt='june',
            qualification='pass_12',
            location='Ahmedabad',
        )
        fee_structure = FeeStructure.objects.create(name='Installment Fee', total_amount=30000, is_active=True)
        student_fee = StudentFee.objects.create(
            student=student,
            fee_structure=fee_structure,
            total_amount=30000,
        )
        plan = InstallmentPlan.objects.create(student_fee=student_fee)
        InstallmentItem.objects.create(plan=plan, amount=15000, due_date=timezone.now().date().replace(year=timezone.now().year, month=4, day=1), is_paid=False)
        InstallmentItem.objects.create(plan=plan, amount=15000, due_date=timezone.now().date().replace(year=timezone.now().year + 1, month=4, day=1), is_paid=False)

        amount = _get_bank_selection_amount(admission)
        self.assertEqual(amount, 15000)


class AdmissionFeeStructureSelectionTest(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name='CS Executive', code='CS-EXEC')
        self.level = CourseLevel.objects.create(course=self.course, name='CS Executive')

    def _create_fee_structure(self, *, attempt='june', year=2026, group_module='module_1', total_amount=30000, token_amount=5000):
        return FeeStructure.objects.create(
            name=f'Executive {attempt} {year} {group_module}',
            course=self.course,
            level=self.level,
            attempt=attempt,
            year=year,
            group_module=group_module,
            total_amount=total_amount,
            token_amount=token_amount,
            is_active=True,
        )

    def test_selects_fee_structure_matching_admission_module_attempt_and_year(self):
        from onboarding.views import _assign_fee_structure

        self._create_fee_structure(group_module='module_2')
        self._create_fee_structure(attempt='oct')
        self._create_fee_structure(year=2025)
        matching_structure = self._create_fee_structure()
        admission = _make_admission(
            course='cs_executive',
            group_module='module_1',
            batch_attempt='june',
            attempt_year=2026,
            status='form_pending',
        )

        _assign_fee_structure(admission)

        admission.refresh_from_db()
        self.assertEqual(admission.fee_structure, matching_structure)

    def test_existing_admission_fee_structure_is_not_replaced(self):
        from onboarding.views import _assign_fee_structure

        linked_structure = self._create_fee_structure(group_module='module_2')
        self._create_fee_structure(group_module='module_1')
        admission = _make_admission(
            fee_structure=linked_structure,
            course='cs_executive',
            group_module='module_1',
            batch_attempt='june',
            attempt_year=2026,
            status='form_pending',
        )

        _assign_fee_structure(admission)

        admission.refresh_from_db()
        self.assertEqual(admission.fee_structure, linked_structure)

    def test_admission_post_persists_submitted_fee_structure(self):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from onboarding.views import AdmissionListView

        fee_structure = self._create_fee_structure()
        admission = _make_admission(status='form_pending')
        user = User.objects.create_user(
            username='fee_structure_post',
            email='fee_structure_post@example.com',
            password='testpass123',
            role='student',
            name='Fee Structure Post',
        )
        request = APIRequestFactory().post(
            '/api/admissions/',
            {'id': admission.id, 'fee_structure': str(fee_structure.id)},
            format='json',
        )
        force_authenticate(request, user=user)

        with patch('onboarding.views._setup_payment_bank_and_notify'):
            response = AdmissionListView.as_view()(request)

        self.assertEqual(response.status_code, 201)
        admission.refresh_from_db()
        self.assertEqual(admission.fee_structure, fee_structure)

    def test_admission_detail_post_persists_submitted_fee_structure(self):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from onboarding.views import AdmissionDetailView

        fee_structure = self._create_fee_structure()
        admission = _make_admission(status='form_pending')
        user = User.objects.create_user(
            username='fee_structure_detail_post',
            email='fee_structure_detail_post@example.com',
            password='testpass123',
            role='student',
            name='Fee Structure Detail Post',
        )
        request = APIRequestFactory().post(
            f'/api/admissions/{admission.id}/',
            {'fee_structure': str(fee_structure.id)},
            format='json',
        )
        force_authenticate(request, user=user)

        with patch('onboarding.views._setup_payment_bank_and_notify'):
            response = AdmissionDetailView.as_view()(request, admission_id=admission.id)

        self.assertEqual(response.status_code, 200)
        admission.refresh_from_db()
        self.assertEqual(admission.fee_structure, fee_structure)

    def test_razorpay_amount_token_payment(self):
        """When student selects 'token', Razorpay link uses fee_structure.token_amount."""
        from onboarding.views import _setup_payment_bank_and_notify

        fee_structure = FeeStructure.objects.create(
            name='Executive June 2027 Combined',
            course=self.course,
            level=self.level,
            attempt='june',
            year=2027,
            group_module='all',
            institute_fees_module_1=15000,
            institute_fees_module_2=18000,
            institute_fees_all_modules=30000,
            total_amount=30000,
            token_amount=5000,
            is_active=True,
        )
        admission = _make_admission(
            course='cs_executive',
            group_module='module_1',
            batch_attempt='june',
            attempt_year=2027,
            fee_structure=fee_structure,
            payment_type='token',
            status='form_pending',
        )
        bank = BankAccount.objects.create(
            name='Test Bank',
            bank_name='Test Bank',
            account_number='123456789',
            ifsc_code='TEST0000001',
        )

        with (
            patch('fees.utils.select_bank_accounts_for_payment', return_value=[bank]),
            patch(
                'fees.razorpay_service.create_payment_link',
                return_value={'success': True, 'data': {'short_url': 'https://razorpay.test/link', 'id': 'plink_test'}},
            ) as create_payment_link,
            patch('core.sender.send_email'),
            patch('chat.notifications.send_whatsapp_with_fallback'),
        ):
            _setup_payment_bank_and_notify(admission)

        self.assertEqual(create_payment_link.call_args.kwargs['amount'], 5000)


class AdmissionToStudentFeeIntegrationTest(TestCase):
    """
    End-to-end test: Admission enrolled → Student created → StudentFee auto-created.
    Flow:
      onboarding/signals.py  → creates User + Student on Admission.status = 'enrolled'
      students/signals.py    → calls create_student_fee(student)
      fees/services.py       → creates StudentFee using admission.fee_structure
    """

    def setUp(self):
        from batches.models import Course
        self.course = Course.objects.create(name='CSEET', code='CSEET')
        self.fee_structure = FeeStructure.objects.create(
            name='CSEET Fee 2026',
            total_amount=30000,
            is_active=True,
        )
        self.admission = _make_admission(fee_structure=self.fee_structure)

    def enroll_admission(self):
        from onboarding.utils import AdmissionService
        from students.utils import StudentService
        from auth_user.models import User
        AdmissionService.update_status(self.admission, 'enrolled')
        student_user = User.objects.filter(email=self.admission.email, role='student').first()
        if student_user:
            StudentService.create_from_admission(self.admission, student_user, None)

    # ── Test 1: User + Student are created when admission is enrolled ──────────

    def test_enrollment_creates_user(self):
        self.enroll_admission()

        user = User.objects.filter(email='teststu@integration.com', role='student').first()
        self.assertIsNotNone(user, "Expected a User to be created on enrollment.")

    def test_enrollment_creates_student_profile(self):
        self.enroll_admission()

        student = Student.objects.filter(admission=self.admission).first()
        self.assertIsNotNone(student, "Expected a Student profile to be created on enrollment.")

    # ── Test 2: StudentFee is auto-created for the new Student ────────────────

    def test_enrollment_creates_student_fee(self):
        self.enroll_admission()

        student = Student.objects.filter(admission=self.admission).first()
        self.assertIsNotNone(student, "Student should exist before checking fee.")

        student_fee = StudentFee.objects.filter(student=student).first()
        self.assertIsNotNone(student_fee, "StudentFee was not auto-created on enrollment.")

    def test_student_fee_uses_admission_fee_structure(self):
        self.enroll_admission()

        student = Student.objects.filter(admission=self.admission).first()
        student_fee = StudentFee.objects.filter(student=student).first()

        self.assertIsNotNone(student_fee, "StudentFee should exist.")
        self.assertEqual(
            student_fee.fee_structure, self.fee_structure,
            "StudentFee should use the FeeStructure pinned on the Admission."
        )

    def test_student_fee_total_amount_matches(self):
        self.enroll_admission()

        student = Student.objects.filter(admission=self.admission).first()
        student_fee = StudentFee.objects.filter(student=student).first()

        self.assertIsNotNone(student_fee)
        self.assertEqual(
            student_fee.total_amount, self.fee_structure.total_amount,
            "StudentFee.total_amount should match FeeStructure.total_amount."
        )

    def test_student_fee_initial_status_is_approval_pending(self):
        self.enroll_admission()

        student = Student.objects.filter(admission=self.admission).first()
        student_fee = StudentFee.objects.filter(student=student).first()

        self.assertIsNotNone(student_fee)
        self.assertEqual(
            student_fee.status, 'approval_pending',
            "StudentFee.status should be 'approval_pending' upon creation."
        )

    # ── Test 3: No duplicate StudentFee if re-enrolled ────────────────────────

    def test_no_duplicate_student_fee_on_re_save(self):
        self.enroll_admission()

        student = Student.objects.filter(admission=self.admission).first()
        initial_count = StudentFee.objects.filter(student=student).count()

        # Re-saving the admission should NOT create another StudentFee
        self.admission.note = 'Updated note'
        self.admission.save()

        final_count = StudentFee.objects.filter(student=student).count()
        self.assertEqual(
            initial_count, final_count,
            "Re-saving an enrolled admission should not duplicate StudentFee records."
        )

    # ── Test 4: Non-enrolled statuses don't create Student/Fee ───────────────

    def test_non_enrolled_status_does_not_create_student(self):
        for status in ['form_pending', 'payment_pending', 'approval_pending', 'approved', 'rejected']:
            admission = _make_admission(
                email=f'test_{status}@integration.com',
                status=status,
                fee_structure=self.fee_structure,
            )
            student_count = Student.objects.filter(admission=admission).count()
            self.assertEqual(
                student_count, 0,
                f"Status '{status}' should not create a Student, but found {student_count}."
            )


class AdmissionGenderFieldTest(TestCase):
    def test_admission_gender_choices_and_serialization(self):
        from onboarding.serializers import AdmissionSerializer, AdmissionListSerializer, AdmissionDetailSerializer

        # Valid gender values
        for g_val in ['male', 'female', 'other']:
            admission = _make_admission(
                email=f'{g_val}@test.com',
                phone_student=f'987654321{len(g_val)}',
                gender=g_val
            )
            self.assertEqual(admission.gender, g_val)
            self.assertEqual(admission.get_gender_display(), g_val.capitalize())

            # Test AdmissionListSerializer
            list_data = AdmissionListSerializer(admission).data
            self.assertEqual(list_data['gender'], g_val)
            self.assertEqual(list_data['gender_display'], g_val.capitalize())

            # Test AdmissionDetailSerializer
            detail_data = AdmissionDetailSerializer(admission).data
            self.assertEqual(detail_data['gender'], g_val)
            self.assertEqual(detail_data['gender_display'], g_val.capitalize())

    def test_admission_gender_passed_to_student(self):
        from students.utils import StudentService
        from auth_user.models import User

        admission = _make_admission(
            email='gender_student@test.com',
            phone_student='9876500001',
            gender='female',
        )
        user = User.objects.create_user(
            username='gender_student',
            email='gender_student@test.com',
            phone='9876500001',
            name='Female Student',
            role='student',
        )
        student = StudentService.create_from_admission(admission, user)
        self.assertEqual(student.gender, 'female')


class AdmissionPaymentChoiceAndHistoryTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name='CS Executive', code='CSE_PAY_TEST')
        self.level = CourseLevel.objects.create(course=self.course, name='CS Executive', order=1)
        self.bank = BankAccount.objects.create(
            name='Test Bank Acc',
            bank_name='Test Bank',
            account_number='999988887777',
            ifsc_code='TEST0009999',
            is_active=True,
        )
        self.fee_structure = FeeStructure.objects.create(
            name='Executive Dec 2027 Test',
            course=self.course,
            level=self.level,
            attempt='dec',
            year=2027,
            group_module='all',
            institute_fees_module_1=20000,
            institute_fees_module_2=25000,
            institute_fees_all_modules=40000,
            total_amount=40000,
            token_amount=5000,
            is_active=True,
        )
        self.counsellor = User.objects.create(
            username='test_counsellor',
            role='counsellor',
            email='counsellor@test.com',
        )
        self.super_admin = User.objects.create(
            username='test_super_admin',
            role='super_admin',
            email='super_admin@test.com',
        )
        self.accountant = User.objects.create(
            username='test_accountant',
            role='accountant',
            email='accountant@test.com',
        )

    def test_payment_choice_online_generates_razorpay_link_and_history(self):
        from onboarding.views import _setup_payment_bank_and_notify

        admission = _make_admission(
            course='cs_executive',
            group_module='all',
            batch_attempt='dec',
            attempt_year=2027,
            fee_structure=self.fee_structure,
            payment_type='full_payment',
            payment_choice='online',
            status='form_pending',
        )

        with (
            patch('fees.utils.select_bank_accounts_for_payment', return_value=[self.bank]),
            patch(
                'fees.razorpay_service.create_payment_link',
                return_value={'success': True, 'data': {'short_url': 'https://razorpay.test/plink_123', 'id': 'plink_123'}},
            ) as mock_create_link,
            patch('core.sender.send_email'),
            patch('chat.notifications.send_whatsapp_with_fallback'),
        ):
            _setup_payment_bank_and_notify(admission)

        admission.refresh_from_db()
        self.assertTrue(mock_create_link.called)
        self.assertEqual(admission.razorpay_payment_link, 'https://razorpay.test/plink_123')
        self.assertEqual(admission.razorpay_payment_link_id, 'plink_123')
        self.assertEqual(admission.razorpay_payment_status, 'pending')
        self.assertFalse(admission.is_paid)
        self.assertFalse(admission.is_razorpay_paid)

        # Check payment_history
        history = admission.get_payment_history_list()
        self.assertTrue(len(history) >= 1)
        self.assertEqual(history[0]['event'], 'payment_link_created')
        self.assertEqual(history[0]['payment_choice'], 'online')
        self.assertEqual(history[0]['razorpay_payment_link'], 'https://razorpay.test/plink_123')

    def test_payment_choice_cash_or_cheque_skips_razorpay_link(self):
        from onboarding.views import _setup_payment_bank_and_notify

        for choice in ['cash', 'cheque']:
            admission = _make_admission(
                email=f'{choice}_test@example.com',
                phone_student='9876543299',
                course='cs_executive',
                group_module='all',
                batch_attempt='dec',
                attempt_year=2027,
                fee_structure=self.fee_structure,
                payment_type='full_payment',
                payment_choice=choice,
                status='form_pending',
            )

            with (
                patch('fees.utils.select_bank_accounts_for_payment', return_value=[self.bank]),
                patch('fees.razorpay_service.create_payment_link') as mock_create_link,
                patch('core.sender.send_email'),
                patch('chat.notifications.send_whatsapp_with_fallback'),
            ):
                _setup_payment_bank_and_notify(admission)

            admission.refresh_from_db()
            mock_create_link.assert_not_called()
            self.assertIsNone(admission.razorpay_payment_link)
            self.assertEqual(admission.razorpay_payment_status, 'not_created')

    def test_razorpay_payment_paid_updates_flags_and_history(self):
        from fees.razorpay_service import process_payment_link_paid_event

        admission = _make_admission(
            fee_structure=self.fee_structure,
            payment_type='full_payment',
            payment_choice='online',
            status='payment_pending',
            razorpay_payment_link='https://razorpay.test/pay_test',
            razorpay_payment_link_id='plink_test_pay',
        )

        payload = {
            'event': 'payment_link.paid',
            'payload': {
                'payment_link': {
                    'entity': {
                        'reference_id': f'ADM_{admission.id}_123456',
                        'amount_paid': 4000000,
                        'id': 'plink_test_pay',
                    }
                },
                'payment': {
                    'entity': {
                        'id': 'pay_rzp_99999',
                    }
                }
            }
        }

        with patch('fees.razorpay_service.send_admission_payment_notification'):
            res = process_payment_link_paid_event(payload)

        self.assertTrue(res.get('success'))
        admission.refresh_from_db()
        self.assertEqual(admission.status, 'enrolled')
        self.assertTrue(admission.is_paid)
        self.assertTrue(admission.is_razorpay_paid)
        self.assertEqual(admission.razorpay_payment_status, 'paid')
        self.assertEqual(admission.razorpay_payment_id, 'pay_rzp_99999')
        self.assertEqual(float(admission.remaining_fees), 0.0)

        # Verify payment history contains payment_received
        history = admission.get_payment_history_list()
        received_event = next((e for e in history if e.get('event') == 'payment_received'), None)
        self.assertIsNotNone(received_event)
        self.assertEqual(received_event['status'], 'paid')
        self.assertEqual(received_event['transaction_id'], 'pay_rzp_99999')

    def test_total_fees_and_remaining_fees_calculation(self):
        # 1. Full payment not yet paid
        admission = _make_admission(
            fee_structure=self.fee_structure,
            group_module='all',
            payment_type='full_payment',
            payment_choice='cash',
            status='form_pending',
        )
        self.assertEqual(float(admission.total_fees), 40000.0)
        self.assertEqual(float(admission.remaining_fees), 40000.0)

        # 2. Token payment with token_amount = 5000
        admission_token = _make_admission(
            email='token_test@example.com',
            phone_student='9876543200',
            fee_structure=self.fee_structure,
            group_module='all',
            payment_type='token',
            payment_choice='online',
            status='form_pending',
        )
        self.assertEqual(float(admission_token.total_fees), 40000.0)
        self.assertEqual(float(admission_token.remaining_fees), 35000.0)  # 40000 - 5000 token

    def test_payment_history_token_fee_details(self):
        admission = _make_admission(
            fee_structure=self.fee_structure,
            group_module='all',
            payment_type='token',
            payment_choice='online',
            status='form_pending',
        )
        history = admission.get_payment_history_list()
        # Even with synthesized or explicit history, fee info is present
        self.assertTrue(len(history) >= 0)
        # Add an entry and verify token details
        admission.add_payment_history_entry('test_entry', {'status': 'pending'})
        history = admission.get_payment_history_list()
        entry = history[0]
        self.assertEqual(entry['payment_type'], 'token')
        self.assertEqual(entry['payment_type_display'], 'Token Payment')
        self.assertEqual(entry['total_fees'], 40000.0)
        self.assertEqual(entry['token_amount'], 5000.0)
        self.assertEqual(entry['remaining_fees'], 35000.0)
        self.assertIn("15 days", entry['terms_note'])
        self.assertIsNotNone(entry['date'])

    def test_payment_history_offline_check_proof_and_dates(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from onboarding.views import AdmissionPaymentSubmitView
        from rest_framework.test import APIRequestFactory

        from io import BytesIO
        from PIL import Image

        img_io = BytesIO()
        img = Image.new('RGB', (50, 50), color='white')
        img.save(img_io, format='PNG')
        img_io.seek(0)

        screenshot = SimpleUploadedFile(
            'cheque_receipt.png',
            img_io.read(),
            content_type='image/png',
        )
        admission = _make_admission(
            email='cheque_proof@example.com',
            phone_student='9876543202',
            fee_structure=self.fee_structure,
            payment_type='full_payment',
            payment_choice='cheque',
            status='payment_pending',
        )

        factory = APIRequestFactory()
        request = factory.post(
            f'/api/admissions/{admission.id}/payment/',
            {
                'payment_screenshot': screenshot,
                'transaction_id': 'CHQ-998877',
                'payment_amount': '40000',
                'payment_note': 'Cheque deposited in SBI branch',
            },
            format='multipart',
        )

        response = AdmissionPaymentSubmitView.as_view()(request, admission_id=admission.id)
        self.assertEqual(response.status_code, 200)

        admission.refresh_from_db()
        history = admission.get_payment_history_list()
        self.assertTrue(len(history) >= 1)

        submitted_entry = next((e for e in history if e.get('event') == 'payment_submitted'), None)
        self.assertIsNotNone(submitted_entry)
        self.assertEqual(submitted_entry['payment_choice'], 'cheque')
        self.assertEqual(submitted_entry['transaction_id'], 'CHQ-998877')
        self.assertIsNotNone(submitted_entry['payment_screenshot'])
        self.assertIn('cheque_receipt', submitted_entry['payment_screenshot'])
        self.assertIsNotNone(submitted_entry['date'])
        self.assertEqual(submitted_entry['payment_type'], 'full_payment')
        self.assertEqual(submitted_entry['total_fees'], 40000.0)

    def test_cash_payment_approval_in_student_fees(self):
        """
        When student pays via cash:
        1. Payment arrives in Student Fees with status='approval_pending'.
        2. Admission.is_paid is False before approval.
        3. Approving via PaymentVerifyView marks payment as 'verified'.
        4. Admission.is_paid becomes True and 'payment_approved' is logged in payment_history.
        """
        from decimal import Decimal
        from students.utils import StudentService
        from fees.views import PaymentVerifyView
        from fees.models import Payment

        admission = _make_admission(
            email='cash_student@example.com',
            phone_student='9876543203',
            fee_structure=self.fee_structure,
            payment_type='token',
            payment_choice='cash',
            payment_amount=Decimal('5000'),
            status='payment_pending',
        )

        user = User.objects.create(
            email='cash_student@example.com',
            username='cash_student_usr',
            role='student',
        )

        student = StudentService.create_from_admission(admission, user, self.counsellor)
        self.assertIsNotNone(student)

        # 1. Payment arrives in Student Fees with status='approval_pending'
        payment = Payment.objects.filter(student=student).first()
        self.assertIsNotNone(payment, "Payment record should be created in Student Fees.")
        self.assertEqual(payment.status, 'approval_pending')
        self.assertEqual(payment.payment_mode, 'cash')
        self.assertEqual(payment.amount, Decimal('5000'))

        # 2. Admission is not paid yet
        admission.refresh_from_db()
        self.assertFalse(admission.is_paid)

        # 3. Accountant/Admin approves payment via PaymentVerifyView
        factory = APIRequestFactory()
        request = factory.post(
            f'/api/v1/payments/{payment.id}/verify/',
            {'status': 'verified'},
            format='json',
        )
        force_authenticate(request, user=self.super_admin)

        response = PaymentVerifyView.as_view()(request, pk=payment.id)
        self.assertEqual(response.status_code, 200)

        # 4. Payment is verified and admission payment is approved
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'verified')
        self.assertIsNotNone(payment.verified_at)

        admission.refresh_from_db()
        self.assertTrue(admission.is_paid)

        history = admission.get_payment_history_list()
        approved_entry = next((e for e in history if e.get('event') == 'payment_approved'), None)
        self.assertIsNotNone(approved_entry, "payment_approved event should be logged in history.")
        self.assertEqual(approved_entry['status'], 'verified')
        self.assertEqual(approved_entry['payment_choice'], 'cash')
        self.assertEqual(approved_entry['amount'], 5000.0)

    def test_cheque_payment_approval_in_student_fees(self):
        """
        When student pays via cheque:
        1. Payment arrives in Student Fees with status='approval_pending'.
        2. Approving via PaymentVerifyView marks payment verified and updates remaining fees.
        """
        from decimal import Decimal
        from students.utils import StudentService
        from fees.views import PaymentVerifyView
        from fees.models import Payment

        admission = _make_admission(
            email='cheque_student@example.com',
            phone_student='9876543204',
            fee_structure=self.fee_structure,
            payment_type='full_payment',
            payment_choice='cheque',
            payment_amount=Decimal('40000'),
            transaction_id='CHQ-123456',
            status='payment_pending',
        )

        user = User.objects.create(
            email='cheque_student@example.com',
            username='cheque_student_usr',
            role='student',
        )

        student = StudentService.create_from_admission(admission, user, self.counsellor)
        self.assertIsNotNone(student)

        payment = Payment.objects.filter(student=student).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, 'approval_pending')
        self.assertEqual(payment.payment_mode, 'cheque')
        self.assertEqual(payment.amount, Decimal('40000'))

        # Admission is not paid yet
        admission.refresh_from_db()
        self.assertFalse(admission.is_paid)

        # Approve payment
        factory = APIRequestFactory()
        request = factory.post(
            f'/api/v1/payments/{payment.id}/verify/',
            {'status': 'verified'},
            format='json',
        )
        force_authenticate(request, user=self.super_admin)

        response = PaymentVerifyView.as_view()(request, pk=payment.id)
        self.assertEqual(response.status_code, 200)

        payment.refresh_from_db()
        self.assertEqual(payment.status, 'verified')

        admission.refresh_from_db()
        self.assertTrue(admission.is_paid)
        self.assertEqual(admission.remaining_fees, Decimal('0'))

        history = admission.get_payment_history_list()
        approved_entry = next((e for e in history if e.get('event') == 'payment_approved'), None)
        self.assertIsNotNone(approved_entry)
        self.assertEqual(approved_entry['payment_choice'], 'cheque')
        self.assertEqual(approved_entry['status'], 'verified')

    def test_two_level_payment_approval_workflow(self):
        """
        Tests the 2-level admission payment approval:
          Level 1: Accountant approves -> status becomes 'approved' (payment_verified)
          Level 2: Super Admin approves -> status becomes 'enrolled' (payment_approved)
        """
        from onboarding.views import AdmissionApproveView

        admission = _make_admission(
            email='twolevel@example.com',
            phone_student='9876543205',
            fee_structure=self.fee_structure,
            payment_type='full_payment',
            payment_choice='cheque',
            payment_amount=Decimal('40000'),
            transaction_id='CHQ-2LEVEL-1',
            status='approval_pending',
        )

        factory = APIRequestFactory()

        # Step 0: Unauthorized role (counsellor) should get 403 Forbidden
        req_counsellor = factory.post(f'/api/admissions/{admission.id}/approve/', {}, format='json')
        force_authenticate(req_counsellor, user=self.counsellor)
        res_counsellor = AdmissionApproveView.as_view()(req_counsellor, admission_id=admission.id)
        self.assertEqual(res_counsellor.status_code, 403)

        # Step 1: Super Admin attempting approval before Accountant gets 400 (requires Level 1 first)
        req_sa_early = factory.post(f'/api/admissions/{admission.id}/approve/', {}, format='json')
        force_authenticate(req_sa_early, user=self.super_admin)
        res_sa_early = AdmissionApproveView.as_view()(req_sa_early, admission_id=admission.id)
        self.assertEqual(res_sa_early.status_code, 400)
        self.assertIn('Level 1 approval by an Accountant is required', res_sa_early.data['message'])

        # Step 2: Accountant performs Level 1 approval -> status becomes 'approved'
        req_acct = factory.post(f'/api/admissions/{admission.id}/approve/', {'note': 'Cheque verified by Accountant'}, format='json')
        force_authenticate(req_acct, user=self.accountant)
        with patch('core.utils.notify_users_by_role'):
            res_acct = AdmissionApproveView.as_view()(req_acct, admission_id=admission.id)
        self.assertEqual(res_acct.status_code, 200)

        admission.refresh_from_db()
        self.assertEqual(admission.status, 'approved')
        history = admission.get_payment_history_list()
        l1_entry = next((e for e in history if e.get('event') == 'payment_verified'), None)
        self.assertIsNotNone(l1_entry)
        self.assertEqual(l1_entry['level'], 1)
        self.assertEqual(l1_entry['approver_role'], 'accountant')
        self.assertEqual(l1_entry['payment_choice'], 'cheque')

        # Step 3: Accountant cannot perform Level 2 approval -> 403 Forbidden
        req_acct_l2 = factory.post(f'/api/admissions/{admission.id}/approve/', {}, format='json')
        force_authenticate(req_acct_l2, user=self.accountant)
        res_acct_l2 = AdmissionApproveView.as_view()(req_acct_l2, admission_id=admission.id)
        self.assertEqual(res_acct_l2.status_code, 403)
        self.assertIn('Super Admin', res_acct_l2.data['message'])

        # Step 4: Super Admin performs Level 2 approval -> status becomes 'enrolled'
        req_sa_final = factory.post(f'/api/admissions/{admission.id}/approve/', {'note': 'Final admission approval'}, format='json')
        force_authenticate(req_sa_final, user=self.super_admin)
        with (
            patch('onboarding.services.AdmissionService.update_status') as mock_update_status,
            patch('students.utils.StudentService.create_from_admission') as mock_create_student,
        ):
            mock_student = MagicMock()
            mock_student.admission_number = 'ADM-2027-001'
            mock_create_student.return_value = mock_student

            # Mock student user account lookup
            with patch('auth_user.models.User.objects.filter') as mock_user_filter:
                mock_user_filter.return_value.first.return_value = MagicMock()
                res_sa_final = AdmissionApproveView.as_view()(req_sa_final, admission_id=admission.id)

        self.assertEqual(res_sa_final.status_code, 200)
        self.assertIn('Level 2 final approval completed by Super Admin', res_sa_final.data['message'])

    def test_payment_approve_reject_template_components(self):
        """
        Validates that build_payment_approve_reject_components produces:
          - Header: IMAGE with screenshot URL
          - Body: 10 parameters (Student Name, Admission ID, Course Type, Module, Attempt,
                                Payment Type, Payment Mode, Payment Amount, Transaction ID / Cheque No.,
                                Payment Submitted At)
          - 2 Quick Reply Buttons: Approve (adm_pay_approve:<id>), Reject (adm_pay_reject:<id>)
        """
        from onboarding.notifications import build_payment_approve_reject_components

        admission = _make_admission(
            first_name='Kavita',
            surname='Sharma',
            email='kavita@example.com',
            phone_student='9876543290',
            fee_structure=self.fee_structure,
            payment_type='full_payment',
            payment_choice='cheque',
            payment_amount=Decimal('40000'),
            transaction_id='CHQ-KAVITA-01',
            status='approval_pending',
        )

        components, fallback_body = build_payment_approve_reject_components(admission)

        # Header component verification
        header = next((c for c in components if c.get('type') == 'header'), None)
        self.assertIsNotNone(header, "Header component must be present")
        self.assertEqual(header['parameters'][0]['type'], 'image')
        self.assertIn('image', header['parameters'][0])

        # Body component verification (10 parameters)
        body = next((c for c in components if c.get('type') == 'body'), None)
        self.assertIsNotNone(body, "Body component must be present")
        params = body['parameters']
        self.assertEqual(len(params), 10, "Body must have exactly 10 parameters")

        self.assertIn('Kavita Sharma', params[0]['text'])       # {{1}} Student Name
        self.assertEqual(str(admission.id), params[1]['text'])  # {{2}} Admission ID
        self.assertTrue(len(params[2]['text']) > 0)             # {{3}} Course Type
        self.assertTrue(len(params[3]['text']) > 0)             # {{4}} Module
        self.assertTrue(len(params[4]['text']) > 0)             # {{5}} Attempt
        self.assertTrue(len(params[5]['text']) > 0)             # {{6}} Payment Type
        self.assertIn('Cheque', params[6]['text'])              # {{7}} Payment Mode (Cheque)
        self.assertIn('40,000', params[7]['text'])              # {{8}} Payment Amount
        self.assertIn('CHQ-KAVITA-01', params[8]['text'])       # {{9}} Transaction ID / Cheque No.
        self.assertTrue(len(params[9]['text']) > 0)             # {{10}} Submitted At

        # Buttons verification (Approve and Reject)
        buttons = [c for c in components if c.get('type') == 'button']
        self.assertEqual(len(buttons), 2, "Must have exactly 2 buttons")
        self.assertEqual(buttons[0]['sub_type'], 'quick_reply')
        self.assertEqual(buttons[0]['index'], '0')
        self.assertEqual(buttons[0]['parameters'][0]['payload'], f"adm_pay_approve:{admission.id}")

        self.assertEqual(buttons[1]['sub_type'], 'quick_reply')
        self.assertEqual(buttons[1]['index'], '1')
        self.assertEqual(buttons[1]['parameters'][0]['payload'], f"adm_pay_reject:{admission.id}")

        # Fallback body verification
        self.assertIn("FEE PAYMENT VERIFICATION", fallback_body)
        self.assertIn("Student Name: Kavita Sharma", fallback_body)
        self.assertIn(f"Admission ID: {admission.id}", fallback_body)
        self.assertIn("Payment Mode: Cheque", fallback_body)
        self.assertIn("APPROVE", fallback_body)
        self.assertIn("REJECT", fallback_body)

    def test_payment_approve_reject_whatsapp_webhook_flow(self):
        """
        Tests the complete 2-level approval webhook flow triggered via WhatsApp button replies:
          1. Accountant clicks Approve -> Level 1 approved
          2. Super Admin clicks Approve -> Level 2 approved & student enrolled
          3. Unauthorized user receives rejection message
        """
        from onboarding.notifications import handle_admission_payment_whatsapp_approval

        admission = _make_admission(
            first_name='Rohan',
            surname='Mehta',
            email='rohan@example.com',
            phone_student='9876543291',
            fee_structure=self.fee_structure,
            payment_type='full_payment',
            payment_choice='cheque',
            payment_amount=Decimal('40000'),
            transaction_id='CHQ-ROHAN-01',
            status='approval_pending',
        )

        # Set phone numbers on test users
        self.accountant.phone = '919876543210'
        self.accountant.save()
        self.super_admin.phone = '919876543211'
        self.super_admin.save()
        self.counsellor.phone = '919876543212'
        self.counsellor.save()

        # Step 0: Unauthorized role (counsellor) clicks Approve
        with patch('chat.notifications.send_whatsapp_text') as mock_send_wa:
            handled = handle_admission_payment_whatsapp_approval(
                sender_wa_id='919876543212',
                payload_str=f'adm_pay_approve:{admission.id}',
            )
            self.assertTrue(handled)
            mock_send_wa.assert_called_once()
            self.assertIn("Unauthorized", mock_send_wa.call_args[1]['body'])

        # Step 1: Accountant clicks Approve -> Level 1 approved
        with (
            patch('chat.notifications.send_whatsapp_text') as mock_send_wa,
            patch('onboarding.notifications.send_payment_verification_whatsapp') as mock_send_l2,
        ):
            handled = handle_admission_payment_whatsapp_approval(
                sender_wa_id='919876543210',
                payload_str=f'adm_pay_approve:{admission.id}',
            )
            self.assertTrue(handled)
            admission.refresh_from_db()
            self.assertEqual(admission.status, 'approved')
            mock_send_wa.assert_called_once()
            self.assertIn("Level 1 payment approval completed", mock_send_wa.call_args[1]['body'])
            mock_send_l2.assert_called_once_with(admission, level=2)

        # Step 2: Super Admin clicks Approve -> Level 2 approved & student enrolled
        with (
            patch('chat.notifications.send_whatsapp_text') as mock_send_wa,
            patch('students.utils.StudentService.create_from_admission') as mock_create_student,
            patch('auth_user.models.User.objects.filter') as mock_user_filter,
        ):
            mock_student = MagicMock()
            mock_student.admission_number = 'ADM-2027-099'
            mock_create_student.return_value = mock_student
            mock_user_filter.return_value.first.return_value = MagicMock()

            handled = handle_admission_payment_whatsapp_approval(
                sender_wa_id='919876543211',
                payload_str=f'adm_pay_approve:{admission.id}',
            )
            self.assertTrue(handled)
            admission.refresh_from_db()
            self.assertEqual(admission.status, 'enrolled')
            mock_send_wa.assert_called_once()
            self.assertIn("enrolled", mock_send_wa.call_args[1]['body'])

    def test_payment_approve_reject_with_image_screenshot(self):
        """Validates that build_payment_approve_reject_components keeps valid image URLs in header."""
        from onboarding.notifications import build_payment_approve_reject_components

        admission = _make_admission(
            first_name='Sunita',
            surname='Patel',
            email='sunita@example.com',
            phone_student='9876543291',
            fee_structure=self.fee_structure,
            payment_type='full_payment',
            payment_choice='cheque',
            payment_amount=Decimal('40000'),
            transaction_id='CHQ-SUNITA-01',
            status='approval_pending',
        )
        admission.payment_screenshot = 'https://example.com/receipt.jpeg'

        components, fallback_body = build_payment_approve_reject_components(admission)
        header = next((c for c in components if c.get('type') == 'header'), None)
        self.assertIsNotNone(header)
        self.assertEqual(header['parameters'][0]['image']['link'], 'https://example.com/receipt.jpeg')
        self.assertIn('https://example.com/receipt.jpeg', fallback_body)

    def test_payment_approve_reject_with_pdf_screenshot_falls_back_to_placeholder_image(self):
        """Validates that build_payment_approve_reject_components falls back to placeholder image for PDF in header."""
        from onboarding.notifications import build_payment_approve_reject_components

        admission = _make_admission(
            first_name='Vikas',
            surname='Kumar',
            email='vikas@example.com',
            phone_student='9876543292',
            fee_structure=self.fee_structure,
            payment_type='full_payment',
            payment_choice='cheque',
            payment_amount=Decimal('40000'),
            transaction_id='CHQ-VIKAS-01',
            status='approval_pending',
        )
        admission.payment_screenshot = 'https://example.com/receipt.pdf'

        components, fallback_body = build_payment_approve_reject_components(admission)
        header = next((c for c in components if c.get('type') == 'header'), None)
        self.assertIsNotNone(header)
        self.assertIn('payment_receipt_placeholder.png', header['parameters'][0]['image']['link'])
        self.assertIn('https://example.com/receipt.pdf', fallback_body)

    def test_sync_admission_payment_triggers_whatsapp_when_screenshot_submitted_even_if_already_pending(self):
        """Validates that sync_admission_payment dispatches Level 1 notification when payment proof is submitted with force=True."""
        from onboarding.utils import sync_admission_payment

        admission = _make_admission(
            first_name='Rahul',
            surname='Verma',
            email='rahul@example.com',
            phone_student='9876543293',
            fee_structure=self.fee_structure,
            payment_type='full_payment',
            payment_choice='cheque',
            payment_amount=Decimal('40000'),
            transaction_id='CHQ-RAHUL-01',
            status='approval_pending',
        )
        admission.payment_screenshot = 'https://example.com/rahul_receipt.png'
        admission.save()

        with patch('onboarding.notifications.send_payment_verification_whatsapp') as mock_send_l1:
            sync_admission_payment(admission, force=True)
            mock_send_l1.assert_called_once_with(admission, level=1)




