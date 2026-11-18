import sys
from pathlib import Path
from decimal import Decimal
import unittest
from unittest.mock import MagicMock, patch

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Minimal django settings setup
import django
from django.conf import settings
if not settings.configured:
    settings.configure(
        BASE_DIR=BASE_DIR,
        TEMPLATES=[{
            'BACKEND': 'django.template.backends.django.DjangoTemplates',
            'DIRS': [BASE_DIR / 'templates'],
            'APP_DIRS': False,
        }],
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            }
        },
        INSTALLED_APPS=[
            'django.contrib.admin',
            'django.contrib.auth',
            'django.contrib.contenttypes',
            'django.contrib.sessions',
            'django.contrib.messages',
            'django.contrib.staticfiles',
            'rest_framework',
            'auth_user',
            'leads',
            'onboarding',
            'batches',
            'fees',
            'attendance',
            'exams',
            'results',
            'faculty',
            'payroll',
            'leave',
            'students',
            'branch',
            'core',
            'scheduler',
            'auditlog',
            'reports',
            'chat',
            'inventory',
            'dashboard',
        ],
        AUTH_USER_MODEL='auth_user.User',
    )
    from unittest.mock import patch, MagicMock

try:
    import scheduler.services
    scheduler.services.TaskScheduler.schedule = lambda *args, **kwargs: None
except Exception:
    pass

django.setup()

class TestAllFixes(unittest.TestCase):

    def test_fee_calculation_and_balance(self):
        """Test remaining_fees == max(0, total_fees - paid_amount)."""
        from onboarding.models import Admission

        adm = Admission()
        adm.id = 101
        adm.pk = 101
        adm._state.adding = False
        adm.admission_code = 'IIPS-000101'
        adm.payment_type = 'token'
        adm.payment_amount = Decimal('5000')
        adm.group_module = 'all'
        adm.icsi_fees_payment = None

        mock_fs = MagicMock()
        mock_fs.total_amount = Decimal('35000')
        mock_fs.token_amount = Decimal('5000')
        mock_fs.institute_fees_all_modules = Decimal('30000')

        with patch.object(Admission, 'fee_structure', new_callable=unittest.mock.PropertyMock, return_value=mock_fs):
            with patch('onboarding.views._get_module_fee', return_value=Decimal('35000')):
                with patch('fees.models.Payment.objects.filter') as mock_filter:
                    with patch.object(Admission, 'is_paid', new_callable=unittest.mock.PropertyMock, return_value=False):
                        with patch.object(Admission, 'is_razorpay_paid', new_callable=unittest.mock.PropertyMock, return_value=False):
                            # No verified payments yet
                            mock_filter.return_value.aggregate.return_value = {'total': None}
                            
                            self.assertEqual(adm.total_fees, Decimal('35000'))
                            self.assertEqual(adm.paid_amount, Decimal('0'))
                            # Crucial fix: before payment was made, remaining_fees must be 35000, NOT 0 or 30000!
                            self.assertEqual(adm.remaining_fees, Decimal('35000'))

                            try:
                                from fees.models import Payment
                                from django.db.models import Sum, Q
                                q_filter = Q(admission=adm, status='verified')
                                total_verified = Payment.objects.filter(q_filter).aggregate(total=Sum('amount'))['total']
                                print("DEBUG QUERY RESULT:", total_verified)
                            except Exception as ex:
                                print("DEBUG QUERY EXC:", ex)

                        # Now simulate 5000 verified payment
                            mock_filter.return_value.aggregate.return_value = {'total': Decimal('5000')}
                            self.assertEqual(adm.paid_amount, Decimal('5000'))
                            self.assertEqual(adm.remaining_fees, Decimal('30000'))
                            self.assertEqual(adm.remaining_fees, adm.total_fees - adm.paid_amount)

                            # Now simulate full 35000 verified payment
                            mock_filter.return_value.aggregate.return_value = {'total': Decimal('35000')}
                            self.assertEqual(adm.paid_amount, Decimal('35000'))
                            self.assertEqual(adm.remaining_fees, Decimal('0'))

    def test_get_module_fee_logic(self):
        """Test get_module_fee returns total_amount when no single module selected."""
        from onboarding.utils import get_module_fee

        fs = MagicMock()
        fs.total_amount = Decimal('45000')
        fs.institute_fees_all_modules = Decimal('38000')
        fs.institute_fees_module_1 = Decimal('20000')
        fs.institute_fees_module_2 = Decimal('20000')
        fs.institute_fees_module_3 = None
        fs.institute_fees_module_4 = None
        fs.institute_fees_module_5 = None
        fs.icsi_registration_fees = Decimal('5000')
        fs.icsi_exam_fees = Decimal('2000')
        fs.icsi_registration_fees_via_cseet = None
        fs.icsi_registration_fees_direct = None

        # Single module
        self.assertEqual(get_module_fee(fs, 'module_1'), Decimal('20000'))
        self.assertEqual(get_module_fee(fs, 'module_2'), Decimal('20000'))

        # Full/all modules without ICSI reduction returns total_amount
        self.assertEqual(get_module_fee(fs, 'all'), Decimal('45000'))
        self.assertEqual(get_module_fee(fs, 'both'), Decimal('45000'))
        self.assertEqual(get_module_fee(fs, ''), Decimal('45000'))
        self.assertEqual(get_module_fee(fs, None), Decimal('45000'))

        # ICSI pay by self deducts 7000 ICSI fees
        self.assertEqual(get_module_fee(fs, 'all', icsi_fees_payment='pay_yourself'), Decimal('38000'))

    def test_pdf_receipt_generation_and_fallback(self):
        """Test pure reportlab receipt generation in memory."""
        from fees.pdf_services import _reportlab_receipt_pdf
        from core.number_utils import num2words

        context = {
            'receipt_no': 'RCT-202611-0001',
            'receipt_date': '18 Nov, 2026',
            'student_name': 'Test Student',
            'amount': 'Rs. 15,000.00',
            'amount_words': num2words(Decimal('15000.00')),
            'batch_name': 'CS Executive June 2026',
            'payment_type': 'token',
            'payment_mode': 'Cash',
            'transaction_ref': 'CSH-001',
            'transaction_date': '18 Nov, 2026',
        }
        buf = _reportlab_receipt_pdf(context)
        self.assertIsNotNone(buf)
        pdf_bytes = buf.getvalue()
        self.assertTrue(len(pdf_bytes) > 1000)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))

    def test_send_payment_receipt_guaranteed_attachment(self):
        """Test send_payment_receipt attaches PDF even if primary generator returns None."""
        from fees.services import send_payment_receipt

        payment = MagicMock()
        payment.id = 999
        payment.receipt_number = 'RCT-TEST-999'
        payment.amount = Decimal('25000.00')
        payment.payment_mode = 'cheque'
        payment.transaction_ref = 'CHQ-888999'
        payment.payment_date = None
        payment._receipt_generated = False
        payment.student = MagicMock()
        payment.student.email = 'student@test.com'
        payment.student.email_parent = 'parent@test.com'
        payment.student.phone_student = '9876543210'
        payment.student.phone_father = '9876543211'
        payment.admission = None

        with patch('fees.pdf_services.generate_payment_receipt_pdf', return_value=(None, None)):
            with patch('core.sender.send_email') as mock_send_email:
                with patch('chat.notifications.send_whatsapp_with_fallback') as mock_send_wa:
                    send_payment_receipt(payment)

                    self.assertTrue(mock_send_email.called)
                    call_kwargs = mock_send_email.call_args[1]
                    attachments = call_kwargs.get('attachments')
                    self.assertIsNotNone(attachments)
                    self.assertEqual(len(attachments), 1)
                    filename, content, mime = attachments[0]
                    self.assertTrue(filename.endswith('.pdf'))
                    self.assertEqual(mime, 'application/pdf')
                    self.assertTrue(len(content) > 1000)

    def test_medium_fields_inquiry_and_admission(self):
        """Test 10th and 12th medium/board fields use strict choices from models."""
        from leads.models import BOARD_TYPE_CHOICES, MEDIUM_TYPE_CHOICES

        board_keys = [k for k, _ in BOARD_TYPE_CHOICES]
        medium_keys = [k for k, _ in MEDIUM_TYPE_CHOICES]

        # Board choices must be strictly gseb, cbse, icse
        self.assertIn('gseb', board_keys)
        self.assertIn('cbse', board_keys)
        self.assertIn('icse', board_keys)
        self.assertNotIn('english', board_keys)
        self.assertNotIn('gujarati', board_keys)

        # Medium choices must be strictly english, gujarati, hindi, other
        self.assertIn('english', medium_keys)
        self.assertIn('gujarati', medium_keys)
        self.assertIn('hindi', medium_keys)
        self.assertNotIn('gseb', medium_keys)
        self.assertNotIn('cbse', medium_keys)

        from leads.serializers import InquirySerializer

        inquiry_data = {
            'form_type': 'inquiry',
            'first_name': 'Test',
            'surname': 'User',
            'father_name': 'Father Test',
            'email': 'test@example.com',
            'phone_student': '9988776655',
            'phone_father': '9988776654',
            'course': 'cseet',
            'group_module': 'full',
            'batch_attempt': 'june',
            'street': 'Street 1',
            'city': 'Ahmedabad',
            'state': 'Gujarat',
            'qualification': 'appearing_12',
            'reference': 'google',
            'consent': True,
            'inquiry_date': '2026-11-18',
            'tenth_medium': 'gujarati',
            'tenth_board': 'gseb',
            'tenth_school': 'ABC High School',
            'tenth_percentage': '85.50',
            'tenth_percentile': '92.00',
            'twelfth_medium': 'english',
            'twelfth_board': 'cbse',
            'twelfth_school': 'XYZ Higher Secondary',
            'twelfth_percentage': '88.00',
            'twelfth_percentile': '95.00',
        }
        s = InquirySerializer(data=inquiry_data)
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(s.validated_data['tenth_medium'], 'gujarati')
        self.assertEqual(s.validated_data['tenth_board'], 'gseb')
        self.assertEqual(s.validated_data['twelfth_medium'], 'english')
        self.assertEqual(s.validated_data['twelfth_board'], 'cbse')

        # Verify invalid medium choice is rejected
        bad_data = inquiry_data.copy()
        bad_data['tenth_medium'] = 'gseb'  # board value in medium field
        s_bad = InquirySerializer(data=bad_data)
        self.assertFalse(s_bad.is_valid())
        self.assertIn('tenth_medium', s_bad.errors)

        # Verify invalid board choice is rejected
        bad_data2 = inquiry_data.copy()
        bad_data2['tenth_board'] = 'english'  # medium value in board field
        s_bad2 = InquirySerializer(data=bad_data2)
        self.assertFalse(s_bad2.is_valid())
        self.assertIn('tenth_board', s_bad2.errors)

    def test_user_credential_generation_when_user_exists(self):
        """Test _create_or_update_user generates and sets password even if user already exists."""
        from onboarding.utils import AdmissionService
        from auth_user.models import User

        existing_user = MagicMock()
        existing_user.username = 'STU_EXISTING'
        existing_user.email = 'exist@test.com'
        existing_user.name = 'Existing Student'

        with patch.object(User.objects, 'filter') as mock_user_filter:
            mock_user_filter.return_value.first.return_value = existing_user
            with patch('onboarding.utils.generate_temporary_password', return_value='TempPass123!'):
                user, password = AdmissionService._create_or_update_user(
                    email='exist@test.com',
                    phone='9876543210',
                    name='Existing Student',
                    role='student',
                )
                self.assertEqual(user, existing_user)
                self.assertEqual(password, 'TempPass123!')
                existing_user.set_password.assert_called_once_with('TempPass123!')

if __name__ == '__main__':
    unittest.main()
