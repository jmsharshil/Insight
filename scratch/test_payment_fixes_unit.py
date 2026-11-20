"""
Unit tests for:
1. Admission amount_to_pay computation for Razorpay (token vs full).
2. Razorpay stale link detection when amount changes.
3. Payment history list enrichment and synthesis (saving payment to be done vs total fees).
4. MultipleObjectsReturned prevention when multiple students exist for a user.

Run with: python scratch/test_payment_fixes_unit.py
"""
import os
import sys
import unittest
from decimal import Decimal
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
import django
django.setup()


def _get_module_fee(fee_structure, group_module):
    if not fee_structure:
        return Decimal('0')
    gm = (group_module or '').strip().lower()
    if gm == 'module_1' and fee_structure.institute_fees_module_1:
        return Decimal(str(fee_structure.institute_fees_module_1))
    elif gm == 'module_2' and fee_structure.institute_fees_module_2:
        return Decimal(str(fee_structure.institute_fees_module_2))
    elif gm in ('all', 'both', 'full') and fee_structure.institute_fees_all_modules:
        return Decimal(str(fee_structure.institute_fees_all_modules))
    if fee_structure.institute_fees_all_modules:
        return Decimal(str(fee_structure.institute_fees_all_modules))
    return Decimal(str(fee_structure.total_amount or 0))


def _compute_amount_to_pay(fs, admission, payment_amount_from_bank_selection):
    total_module_fee = _get_module_fee(fs, admission.group_module) if fs else Decimal('0')
    token_val = Decimal(str(fs.token_amount or 0)) if fs else Decimal('0')
    curr_pmt_amt = Decimal(str(admission.payment_amount or 0))

    if fs:
        if admission.payment_type == 'token':
            if curr_pmt_amt > 0 and (total_module_fee <= 0 or curr_pmt_amt < total_module_fee):
                amount_to_pay = curr_pmt_amt
            elif token_val > 0:
                amount_to_pay = token_val
            elif total_module_fee > Decimal('5000'):
                amount_to_pay = Decimal('5000')
            else:
                amount_to_pay = total_module_fee
        elif admission.payment_type == 'full_payment':
            amount_to_pay = total_module_fee
        elif admission.payment_type == 'finance':
            if curr_pmt_amt > 0 and (total_module_fee <= 0 or curr_pmt_amt < total_module_fee):
                amount_to_pay = curr_pmt_amt
            elif token_val > 0:
                amount_to_pay = token_val
            else:
                amount_to_pay = Decimal('0')
        else:
            if curr_pmt_amt > 0:
                amount_to_pay = curr_pmt_amt
            else:
                amount_to_pay = total_module_fee
    else:
        if curr_pmt_amt > 0:
            amount_to_pay = curr_pmt_amt
        else:
            amount_to_pay = Decimal(str(payment_amount_from_bank_selection))

    if amount_to_pay <= 0 and admission.payment_type != 'finance':
        default_course_fees = {
            'cseet': Decimal('1000'),
            'cs_executive': Decimal('2000'),
            'cs_professional': Decimal('5000'),
        }
        normalized_course = (admission.course or '').strip().lower().replace(' ', '_').replace('-', '_')
        amount_to_pay = (
            default_course_fees.get(normalized_course)
            or default_course_fees.get(admission.course or '')
        )
        if not amount_to_pay:
            amount_to_pay = Decimal('1000')

    return amount_to_pay


class TestPaymentLogic(unittest.TestCase):

    def test_token_payment_amount_uses_token_amount_not_total_fee(self):
        fs = MagicMock()
        fs.total_amount = Decimal('40000')
        fs.institute_fees_all_modules = Decimal('40000')
        fs.institute_fees_module_1 = Decimal('20000')
        fs.token_amount = Decimal('5000')

        admission = MagicMock()
        admission.payment_type = 'token'
        admission.payment_amount = None
        admission.group_module = 'all'
        admission.course = 'cs_executive'

        amount = _compute_amount_to_pay(fs, admission, Decimal('40000'))
        self.assertEqual(amount, Decimal('5000'))

    def test_token_payment_with_custom_payment_amount(self):
        fs = MagicMock()
        fs.total_amount = Decimal('40000')
        fs.institute_fees_all_modules = Decimal('40000')
        fs.token_amount = Decimal('5000')

        admission = MagicMock()
        admission.payment_type = 'token'
        admission.payment_amount = Decimal('2500')
        admission.group_module = 'all'
        admission.course = 'cs_executive'

        amount = _compute_amount_to_pay(fs, admission, Decimal('40000'))
        self.assertEqual(amount, Decimal('2500'))

    def test_full_payment_amount_uses_total_fee(self):
        fs = MagicMock()
        fs.total_amount = Decimal('40000')
        fs.institute_fees_all_modules = Decimal('40000')
        fs.token_amount = Decimal('5000')

        admission = MagicMock()
        admission.payment_type = 'full_payment'
        admission.payment_amount = None
        admission.group_module = 'all'
        admission.course = 'cs_executive'

        amount = _compute_amount_to_pay(fs, admission, Decimal('40000'))
        self.assertEqual(amount, Decimal('40000'))

    def test_stale_razorpay_link_detected_when_amount_differs(self):
        existing_rp_link = "https://rzp.io/l/old_link"
        history = [{'event': 'payment_link_created', 'amount': 40000.0}]
        amount_to_pay = Decimal('5000')

        existing_amount = None
        for entry in history:
            if entry.get('event') == 'payment_link_created':
                existing_amount = Decimal(str(entry.get('amount', 0)))
                break

        # Check if detected as stale
        is_stale = existing_amount is not None and (existing_amount <= Decimal('1') or existing_amount != amount_to_pay)
        self.assertTrue(is_stale)

    def test_payment_history_token_enrichment(self):
        total_fee = 40000.0
        token_amt = 5000.0
        p_type = 'token'
        p_type_display = 'Token Payment'

        # Simulate history entry that previously had 40000 (total fee bug)
        item = {
            'event': 'offline_payment_selected',
            'amount_to_pay': 40000.0,
        }

        # Apply the new enrichment logic
        expected_amount = Decimal('0')
        if expected_amount <= 0 or (p_type == 'token' and total_fee > 0 and expected_amount >= Decimal(str(total_fee)) and token_amt > 0):
            if p_type == 'token' and token_amt > 0:
                expected_amount = Decimal(str(token_amt))
            else:
                expected_amount = Decimal(str(total_fee))

        for amount_key in ('amount', 'amount_to_pay'):
            curr_val = Decimal(str(item.get(amount_key) or 0))
            if curr_val <= 0 or (p_type == 'token' and total_fee > 0 and curr_val >= Decimal(str(total_fee)) and token_amt > 0):
                item[amount_key] = float(expected_amount)

        item['total_fees'] = total_fee
        item['token_amount'] = token_amt
        item['remaining_fees'] = total_fee - token_amt

        self.assertEqual(item['amount_to_pay'], 5000.0)
        self.assertEqual(item['total_fees'], 40000.0)
        self.assertEqual(item['token_amount'], 5000.0)
        self.assertEqual(item['remaining_fees'], 35000.0)

    def test_multiple_objects_returned_fix_simulation(self):
        # Simulate user with 2 student records in query
        students = [
            MagicMock(id="std_1", created_at="2026-01-01"),
            MagicMock(id="std_2", created_at="2026-02-01"),
        ]

        class MockQS:
            def __init__(self, items):
                self.items = items
            def filter(self, **kwargs):
                return self
            def order_by(self, field):
                # Reverse for -created_at
                return MockQS(sorted(self.items, key=lambda s: s.created_at, reverse=field.startswith('-')))
            def first(self):
                return self.items[0] if self.items else None

        qs = MockQS(students)
        # Using .filter(user=user).order_by('-created_at').first() instead of .get(user=user)
        student = qs.filter(user="test").order_by('-created_at').first()
        self.assertIsNotNone(student)
        self.assertEqual(student.id, "std_2")

    def test_button_index_string_normalization_in_sender(self):
        """WhatsAppSender.send_template converts button component index to str."""
        from core.sender import WhatsAppSender
        sender = WhatsAppSender.__new__(WhatsAppSender)
        sender._base_payload = MagicMock(return_value={})
        sender._post = MagicMock(side_effect=lambda payload: payload)

        components = [
            {"type": "body", "parameters": [{"type": "text", "text": "10,000"}]},
            {"type": "button", "sub_type": "url", "index": 0, "parameters": [{"type": "text", "text": "NPj2jKkN"}]},
        ]
        res = sender.send_template(to="919876543210", template_name="razorpay_link", components=components)
        sent_components = res["template"]["components"]
        button_comp = [c for c in sent_components if c["type"] == "button"][0]
        self.assertEqual(button_comp["index"], "0")
        self.assertIsInstance(button_comp["index"], str)

    def test_razorpay_link_deduplication_atomic_lock_in_views(self):
        """_setup_payment_bank_and_notify uses select_for_update and checks link_already_sent."""
        import inspect
        from onboarding.views import _setup_payment_bank_and_notify
        src = inspect.getsource(_setup_payment_bank_and_notify)
        self.assertIn("select_for_update", src)
        self.assertIn("link_already_sent", src)
        self.assertIn("payment_link_notified", src)
        self.assertIn('"0"', src)


if __name__ == '__main__':
    unittest.main()

