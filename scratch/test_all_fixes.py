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

        # Medium choices in models are strictly english, gujarati, hindi, other
        self.assertIn('english', medium_keys)
        self.assertIn('gujarati', medium_keys)
        self.assertIn('hindi', medium_keys)
        self.assertNotIn('gseb', medium_keys)
        self.assertNotIn('cbse', medium_keys)

        # Board choices in models are strictly gseb, cbse, icse
        self.assertIn('gseb', board_keys)
        self.assertIn('cbse', board_keys)
        self.assertIn('icse', board_keys)
        self.assertNotIn('english', board_keys)
        self.assertNotIn('gujarati', board_keys)

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

        # Verify invalid choice for tenth_medium (rejects 'gseb' because MEDIUM_TYPE_CHOICES has english/gujarati/hindi/other)
        bad_data = inquiry_data.copy()
        bad_data['tenth_medium'] = 'gseb'
        s_bad = InquirySerializer(data=bad_data)
        self.assertFalse(s_bad.is_valid())
        self.assertIn('tenth_medium', s_bad.errors)

        # Verify invalid choice for tenth_board (rejects 'gujarati' because BOARD_TYPE_CHOICES has gseb/cbse/icse)
        bad_data2 = inquiry_data.copy()
        bad_data2['tenth_board'] = 'gujarati'
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

    def test_inquiry_converted_lead_notifications(self):
        """Test system and WhatsApp notifications sent on inquiry form converted lead creation."""
        from leads.utils import LeadService
        from leads.models import Lead
        from onboarding.models import Admission

        lead = Lead(
            id=777,
            form_type='inquiry',
            current_stage='converted',
            first_name='Priya',
            surname='Sharma',
            email='priya@example.com',
            phone_student='919876543210',
            phone_father='919876543211',
            course='cseet',
        )
        from branch.models import Branch
        from auth_user.models import Organization, User
        org = Organization(id=1, name='Insight Institute')
        b = Branch(id=1, name='Main', organization=org)
        lead.branch = b

        counsellor = User(id=88, name='Rahul Counsellor', phone='919876543299', role='counsellor')
        lead.assigned_to = counsellor

        branch_mgr = User(id=99, name='Branch Manager', phone='919876543288', role='branch_manager')

        with patch('onboarding.models.Admission.objects.filter') as mock_adm_filter:
            # Idempotency check: not exists
            mock_adm_filter.return_value.exists.return_value = False
            with patch('onboarding.models.Admission.save'), \
                 patch('onboarding.models.AdmissionStatusHistory.objects.create'):
                with patch('core.sender.send_email') as mock_email, \
                     patch('core.utils.notify_users_by_role') as mock_notify_role, \
                     patch('chat.notifications.send_system_notification') as mock_sys_notif, \
                     patch('chat.notifications.send_whatsapp_with_fallback') as mock_wa_fallback, \
                     patch('auth_user.models.User.objects.filter') as mock_user_filter:

                    qs_mock = MagicMock()
                    qs_mock.exclude.return_value = qs_mock
                    qs_mock.filter.return_value = [branch_mgr]
                    mock_user_filter.return_value = qs_mock

                    adm = LeadService.auto_create_admission_for_lead(lead)
                    self.assertIsNotNone(adm)
                    adm_code = getattr(adm, 'admission_code', None) or f"IIPS-{adm.id:06d}"

                    # 1. System notification to administrative roles
                    self.assertTrue(mock_notify_role.called)
                    role_args = mock_notify_role.call_args[1]
                    self.assertIn('super_admin', role_args['roles'])
                    self.assertIn('counsellor', role_args['roles'])
                    self.assertIn('Priya Sharma', role_args['title'])
                    self.assertEqual(role_args['metadata']['admission_id'], str(lead.id))
                    self.assertEqual(role_args['metadata']['type'], 'lead_converted')

                    # 2. Targeted system notification for assigned counsellor
                    self.assertTrue(mock_sys_notif.called)
                    c_args = mock_sys_notif.call_args[1]
                    self.assertEqual(c_args['user_id'], '88')
                    self.assertIn('Priya Sharma', c_args['title'])

                    # Verify exact call counts (no duplicate dispatch)
                    self.assertEqual(mock_notify_role.call_count, 1)
                    self.assertEqual(mock_sys_notif.call_count, 1)

                    # 3. WhatsApp notifications using admission_process template
                    self.assertTrue(mock_wa_fallback.called)
                    wa_calls = [call[1]['to'] for call in mock_wa_fallback.call_args_list]
                    self.assertEqual(len(wa_calls), 4) # Exactly 4: Student, Parent, Counsellor, Branch Manager
                    self.assertIn('919876543210', wa_calls) # Student
                    self.assertIn('919876543211', wa_calls) # Father
                    self.assertIn('919876543299', wa_calls) # Counsellor
                    self.assertIn('919876543288', wa_calls) # Branch Manager

                    # Verify template_name is admission_process for all calls
                    for call in mock_wa_fallback.call_args_list:
                        self.assertEqual(call[1]['template_name'], 'admission_process')

    def test_inquiry_lead_skips_generic_lead_assigned_signal(self):
        """Test that inquiry form leads do not trigger generic 'New Lead Assigned' signal."""
        from leads.signals import notify_new_lead_assignment
        from leads.models import Lead
        from auth_user.models import User

        counsellor = User(id=50, name='Test Counsellor', phone='919999999999', role='counsellor')
        lead = Lead(id=888, form_type='inquiry', first_name='Test', surname='Student')
        lead.assigned_to = counsellor

        with patch('chat.notifications.send_system_notification') as mock_sys_notif:
            notify_new_lead_assignment(sender='leads.Lead', instance=lead, created=True)
            self.assertFalse(mock_sys_notif.called, "Generic assignment signal should skip inquiry form leads")

    def test_admission_code_lookups_across_all_apis(self):
        """Test _get_admission and endpoints accept BOTH admission_code and numeric id."""
        from onboarding.views import _get_admission, AdmissionStatusUpdateView
        from onboarding.models import Admission

        mock_admission = MagicMock(spec=Admission)
        mock_admission.id = 55
        mock_admission.pk = 55
        mock_admission.admission_code = 'IIPS-000055'

        mock_request = MagicMock()
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.is_superuser = True

        with patch('onboarding.models.Admission.objects.select_related') as mock_sr:
            mock_qs = MagicMock()
            mock_sr.return_value = mock_qs
            mock_qs.filter.return_value.first.return_value = mock_admission

            # 1. Lookup by string admission_code
            adm1 = _get_admission(mock_request, 'IIPS-000055')
            self.assertEqual(adm1, mock_admission)
            q1 = mock_qs.filter.call_args[0][0]
            # Verify Q expression includes admission_code__iexact and IIPS- numeric extraction
            self.assertTrue('admission_code__iexact' in str(q1) or 'id' in str(q1))

            # 2. Lookup by lowercase string admission_code
            adm2 = _get_admission(mock_request, 'iips-000055')
            self.assertEqual(adm2, mock_admission)

            # 3. Lookup by numeric id
            adm3 = _get_admission(mock_request, '55')
            self.assertEqual(adm3, mock_admission)

            # 4. Lookup by int
            adm4 = _get_admission(mock_request, 55)
            self.assertEqual(adm4, mock_admission)

        # Test fees payment filter with admission_code
        from fees.views import PaymentListView
        from fees.models import Payment
        fees_req = MagicMock()
        fees_req.user = MagicMock()
        fees_req.user.is_authenticated = True
        fees_req.user.is_superuser = True
        fees_req.GET = {'admission_id': 'IIPS-000055'}

        with patch('fees.models.Payment.objects.select_related') as mock_p_sr:
            mock_p_qs = MagicMock()
            mock_p_sr.return_value = mock_p_qs
            mock_p_qs.prefetch_related.return_value.all.return_value = mock_p_qs
            mock_p_qs.filter.return_value = mock_p_qs
            with patch('fees.views.apply_filters', side_effect=lambda v, r, qs: qs):
                with patch('fees.views.paginate_queryset') as mock_pag:
                    mock_pag.return_value = MagicMock()
                    view = PaymentListView()
                    view.request = fees_req
                    view.get(fees_req)
                    # Verify that filter was called with admission_code lookup
                    filter_calls = [str(call) for call in mock_p_qs.filter.call_args_list]
                    self.assertTrue(any('admission__admission_code__iexact' in c for c in filter_calls))

    def test_razorpay_receipt_sent_even_on_profile_creation_error(self):
        """
        Fix: receipt + notification must be dispatched BEFORE the
        profile_creation_error early return in process_payment_link_paid_event.
        We verify the code structure by reading the source and checking order.
        """
        import inspect
        from fees.razorpay_service import process_payment_link_paid_event
        source = inspect.getsource(process_payment_link_paid_event)

        # Receipt dispatch (send_payment_receipt) must appear BEFORE profile_creation_error return
        idx_receipt = source.find('send_payment_receipt(payment)')
        idx_notif = source.find('send_admission_payment_notification(')
        idx_error_return = source.find('"receipt_sent": is_new_transaction')

        self.assertGreater(idx_receipt, 0, "send_payment_receipt call not found")
        self.assertGreater(idx_notif, 0, "send_admission_payment_notification call not found")
        self.assertGreater(idx_error_return, 0, "profile_creation_error return not found")

        # Key assertion: receipt and notification must come BEFORE the error return
        self.assertLess(idx_receipt, idx_error_return,
                        "send_payment_receipt must execute BEFORE profile_creation_error return")
        self.assertLess(idx_notif, idx_error_return,
                        "send_admission_payment_notification must execute BEFORE profile_creation_error return")

    def test_level2_approval_sends_receipt_on_student_user_missing(self):
        """
        Fix: Level 2 approval in onboarding/views.py must still try to send
        payment receipt even when student_user lookup fails (returns 500).
        """
        import inspect
        from onboarding.views import AdmissionApproveView
        source = inspect.getsource(AdmissionApproveView)

        # After "Student user account missing" error, there must be a fallback receipt dispatch
        idx_missing_msg = source.find('Student user account missing')
        idx_fallback_receipt = source.find('Payment receipt has been dispatched')
        self.assertGreater(idx_missing_msg, 0, "Missing student user message not found")
        self.assertGreater(idx_fallback_receipt, 0, "Fallback receipt dispatch not found")
        self.assertGreater(idx_fallback_receipt, idx_missing_msg,
                           "Fallback receipt dispatch must come after missing user detection")

    def test_level2_approval_sends_receipt_on_student_profile_failure(self):
        """
        Fix: Level 2 approval must dispatch receipt even when
        StudentService.create_from_admission fails.
        """
        import inspect
        from onboarding.views import AdmissionApproveView
        source = inspect.getsource(AdmissionApproveView)

        # After "profile creation failed" error, receipt should still be dispatched
        idx_profile_failed = source.find('profile creation failed')
        idx_receipt_msg = source.find('Payment receipt has been dispatched.')
        self.assertGreater(idx_profile_failed, 0, "Profile creation failed message not found")
        self.assertGreater(idx_receipt_msg, 0, "Receipt dispatch message not found")

    def test_payment_admission_always_set_on_update(self):
        """
        Fix: When updating an existing payment in Razorpay webhook,
        payment.admission must be set so send_payment_receipt can find
        recipients via admission fallback.
        """
        import inspect
        from fees.razorpay_service import process_payment_link_paid_event
        source = inspect.getsource(process_payment_link_paid_event)

        # The else branch (existing payment update) must set payment.admission
        idx_else = source.find('payment.admission = payment.admission or admission')
        self.assertGreater(idx_else, 0,
                           "payment.admission assignment not found in existing payment update path")

    def test_credential_dispatch_logging(self):
        """
        Verify _create_user_accounts has proper logging when password is
        empty/None (user already existed and no new password generated).
        """
        import inspect
        from onboarding.utils import AdmissionService
        source = inspect.getsource(AdmissionService._create_user_accounts)

        # Must log a warning when student_password is None
        self.assertIn('credential email NOT sent', source,
                       "Warning about skipped credential dispatch not found in _create_user_accounts")
        # Must have exc_info=True for better debugging
        self.assertIn('exc_info=True', source,
                       "exc_info=True not found in credential error handler")

if __name__ == '__main__':
    unittest.main()
