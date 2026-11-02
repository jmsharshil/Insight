"""
Unit tests for AdmissionPaymentSetupView / _setup_payment_bank_and_notify amount logic.

Tests run fully in-memory with mocks — no database, Django ORM, or Razorpay calls required.
Run: python scratch/test_admission_payment_setup_amount_unit.py
"""
import sys
import os
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Paste the two pure helper functions here so we can test them standalone,
# without importing the entire Django app stack.
# ---------------------------------------------------------------------------

def _get_module_fee(fee_structure, group_module):
    """
    Resolves the fee component from the fee structure matching the student's group_module selection.
    Falls back to institute_fees_all_modules or total_amount if specific module fee is not set.
    """
    if not fee_structure:
        return Decimal('0')

    gm = (group_module or '').strip().lower()
    if gm == 'module_1' and fee_structure.institute_fees_module_1:
        return Decimal(str(fee_structure.institute_fees_module_1))
    elif gm == 'module_2' and fee_structure.institute_fees_module_2:
        return Decimal(str(fee_structure.institute_fees_module_2))
    elif gm == 'module_3' and fee_structure.institute_fees_module_3:
        return Decimal(str(fee_structure.institute_fees_module_3))
    elif gm == 'module_4' and fee_structure.institute_fees_module_4:
        return Decimal(str(fee_structure.institute_fees_module_4))
    elif gm == 'module_5' and fee_structure.institute_fees_module_5:
        return Decimal(str(fee_structure.institute_fees_module_5))
    elif gm in ('all', 'both', 'full') and fee_structure.institute_fees_all_modules:
        return Decimal(str(fee_structure.institute_fees_all_modules))

    if fee_structure.institute_fees_all_modules:
        return Decimal(str(fee_structure.institute_fees_all_modules))
    return Decimal(str(fee_structure.total_amount or 0))


def _compute_amount_to_pay(fs, admission, payment_amount_from_bank_selection):
    """
    Mirrors the amount_to_pay logic from _setup_payment_bank_and_notify.
    Extracted here for pure-logic testing.
    """
    payment_amount = Decimal(str(payment_amount_from_bank_selection))

    if fs:
        if admission.payment_type == 'token':
            amount_to_pay = Decimal(str(fs.token_amount or 0))
            if amount_to_pay <= 0:
                amount_to_pay = _get_module_fee(fs, admission.group_module)
        elif admission.payment_type == 'full_payment':
            amount_to_pay = _get_module_fee(fs, admission.group_module)
        else:
            # payment_type not set — treat as full payment from fee structure
            amount_to_pay = _get_module_fee(fs, admission.group_module)
            if amount_to_pay <= 0 and payment_amount > 0:
                amount_to_pay = payment_amount
    else:
        amount_to_pay = payment_amount

    # Fallback to hard-coded defaults; never 1 Rs
    if amount_to_pay <= 0:
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
            amount_to_pay = Decimal('1000')   # absolute minimum

    return amount_to_pay


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_fee_structure(
    total_amount=0,
    token_amount=0,
    institute_fees_all_modules=0,
    institute_fees_module_1=0,
    institute_fees_module_2=0,
    institute_fees_module_3=0,
    institute_fees_module_4=0,
    institute_fees_module_5=0,
):
    fs = MagicMock()
    fs.total_amount = Decimal(str(total_amount))
    fs.token_amount = Decimal(str(token_amount))
    fs.institute_fees_all_modules = Decimal(str(institute_fees_all_modules))
    fs.institute_fees_module_1 = Decimal(str(institute_fees_module_1))
    fs.institute_fees_module_2 = Decimal(str(institute_fees_module_2))
    fs.institute_fees_module_3 = Decimal(str(institute_fees_module_3))
    fs.institute_fees_module_4 = Decimal(str(institute_fees_module_4))
    fs.institute_fees_module_5 = Decimal(str(institute_fees_module_5))
    return fs


def make_admission(course='cseet', payment_type=None, group_module=None):
    adm = MagicMock()
    adm.course = course
    adm.payment_type = payment_type
    adm.group_module = group_module
    return adm


# ============================================================================
# Tests for _get_module_fee
# ============================================================================
class TestGetModuleFee(unittest.TestCase):

    def test_module_1_returns_module_1_fee(self):
        fs = make_fee_structure(institute_fees_module_1=15000, institute_fees_all_modules=40000)
        self.assertEqual(_get_module_fee(fs, 'module_1'), Decimal('15000'))

    def test_module_2_returns_module_2_fee(self):
        fs = make_fee_structure(institute_fees_module_2=12000, institute_fees_all_modules=40000)
        self.assertEqual(_get_module_fee(fs, 'module_2'), Decimal('12000'))

    def test_module_3_returns_module_3_fee(self):
        fs = make_fee_structure(institute_fees_module_3=11000)
        self.assertEqual(_get_module_fee(fs, 'module_3'), Decimal('11000'))

    def test_all_returns_all_modules_fee(self):
        fs = make_fee_structure(institute_fees_all_modules=40000, total_amount=45000)
        self.assertEqual(_get_module_fee(fs, 'all'), Decimal('40000'))

    def test_both_returns_all_modules_fee(self):
        fs = make_fee_structure(institute_fees_all_modules=35000)
        self.assertEqual(_get_module_fee(fs, 'both'), Decimal('35000'))

    def test_full_returns_all_modules_fee(self):
        fs = make_fee_structure(institute_fees_all_modules=38000)
        self.assertEqual(_get_module_fee(fs, 'full'), Decimal('38000'))

    def test_module_not_set_falls_back_to_all_modules(self):
        fs = make_fee_structure(institute_fees_all_modules=42000)
        self.assertEqual(_get_module_fee(fs, 'module_1'), Decimal('42000'))

    def test_no_all_modules_falls_back_to_total_amount(self):
        fs = make_fee_structure(total_amount=30000)
        self.assertEqual(_get_module_fee(fs, 'module_1'), Decimal('30000'))

    def test_none_fee_structure_returns_zero(self):
        self.assertEqual(_get_module_fee(None, 'module_1'), Decimal('0'))

    def test_none_group_module_falls_back_to_all_modules(self):
        fs = make_fee_structure(institute_fees_all_modules=50000)
        self.assertEqual(_get_module_fee(fs, None), Decimal('50000'))

    def test_empty_group_module_falls_back_to_total(self):
        fs = make_fee_structure(total_amount=25000)
        self.assertEqual(_get_module_fee(fs, ''), Decimal('25000'))


# ============================================================================
# Tests for amount_to_pay computation logic
# ============================================================================
class TestAmountToPayCalculation(unittest.TestCase):

    # ── Token payment ─────────────────────────────────────────────────────────

    def test_token_payment_uses_token_amount(self):
        fs = make_fee_structure(token_amount=5000, institute_fees_all_modules=30000)
        adm = make_admission(payment_type='token')
        self.assertEqual(_compute_amount_to_pay(fs, adm, 0), Decimal('5000'))

    def test_token_payment_zero_token_falls_back_to_module_fee(self):
        fs = make_fee_structure(token_amount=0, institute_fees_all_modules=28000)
        adm = make_admission(payment_type='token')
        self.assertEqual(_compute_amount_to_pay(fs, adm, 0), Decimal('28000'))

    # ── Full payment ──────────────────────────────────────────────────────────

    def test_full_payment_cseet_uses_all_modules_fee(self):
        fs = make_fee_structure(institute_fees_all_modules=32000)
        adm = make_admission(course='cseet', payment_type='full_payment')
        self.assertEqual(_compute_amount_to_pay(fs, adm, 0), Decimal('32000'))

    def test_full_payment_executive_module_1(self):
        fs = make_fee_structure(institute_fees_module_1=18000, total_amount=35000)
        adm = make_admission(course='cs_executive', payment_type='full_payment', group_module='module_1')
        self.assertEqual(_compute_amount_to_pay(fs, adm, 0), Decimal('18000'))

    def test_full_payment_executive_module_2(self):
        fs = make_fee_structure(institute_fees_module_2=16000, total_amount=34000)
        adm = make_admission(course='cs_executive', payment_type='full_payment', group_module='module_2')
        self.assertEqual(_compute_amount_to_pay(fs, adm, 0), Decimal('16000'))

    def test_full_payment_executive_all_modules(self):
        fs = make_fee_structure(
            institute_fees_module_1=18000, institute_fees_module_2=16000,
            institute_fees_all_modules=31000,
        )
        adm = make_admission(course='cs_executive', payment_type='full_payment', group_module='all')
        self.assertEqual(_compute_amount_to_pay(fs, adm, 0), Decimal('31000'))

    def test_full_payment_professional_no_module_fee_falls_back_to_total(self):
        fs = make_fee_structure(total_amount=60000)
        adm = make_admission(course='cs_professional', payment_type='full_payment', group_module='module_1')
        self.assertEqual(_compute_amount_to_pay(fs, adm, 0), Decimal('60000'))

    # ── payment_type not set → treat as full ──────────────────────────────────

    def test_no_payment_type_uses_module_fee_from_fee_structure(self):
        fs = make_fee_structure(institute_fees_all_modules=25000)
        adm = make_admission(course='cseet', payment_type=None)
        self.assertEqual(_compute_amount_to_pay(fs, adm, 0), Decimal('25000'))

    def test_no_payment_type_zero_module_fee_uses_bank_selection_amount(self):
        fs = make_fee_structure(total_amount=0, institute_fees_all_modules=0)
        adm = make_admission(course='cseet', payment_type=None)
        self.assertEqual(_compute_amount_to_pay(fs, adm, 20000), Decimal('20000'))

    # ── No fee structure ──────────────────────────────────────────────────────

    def test_no_fee_structure_uses_bank_selection_amount(self):
        adm = make_admission(course='cseet', payment_type='full_payment')
        self.assertEqual(_compute_amount_to_pay(None, adm, 15000), Decimal('15000'))

    def test_no_fee_structure_zero_bank_amount_falls_back_cseet(self):
        adm = make_admission(course='cseet', payment_type='full_payment')
        self.assertEqual(_compute_amount_to_pay(None, adm, 0), Decimal('1000'))

    def test_no_fee_structure_zero_bank_amount_falls_back_cs_executive(self):
        adm = make_admission(course='cs_executive', payment_type='full_payment')
        self.assertEqual(_compute_amount_to_pay(None, adm, 0), Decimal('2000'))

    def test_no_fee_structure_zero_bank_amount_falls_back_cs_professional(self):
        adm = make_admission(course='cs_professional', payment_type='full_payment')
        self.assertEqual(_compute_amount_to_pay(None, adm, 0), Decimal('5000'))

    # ── Never 1 Rs ────────────────────────────────────────────────────────────

    def test_never_returns_1_rs_for_unknown_course(self):
        adm = make_admission(course='unknown_course', payment_type='full_payment')
        amount = _compute_amount_to_pay(None, adm, 0)
        self.assertGreater(amount, Decimal('1'), f"Amount must never be 1 Rs; got {amount}")
        self.assertGreaterEqual(amount, Decimal('1000'), f"Minimum fallback should be 1000; got {amount}")

    def test_never_returns_1_rs_when_fee_structure_all_zero(self):
        fs = make_fee_structure(total_amount=0, token_amount=0, institute_fees_all_modules=0)
        adm = make_admission(course='cseet', payment_type='full_payment')
        amount = _compute_amount_to_pay(fs, adm, 0)
        self.assertGreater(amount, Decimal('1'), f"Amount must never be 1 Rs; got {amount}")

    def test_cs_executive_course_name_variation_normalized(self):
        """Normalized 'cs executive' → 'cs_executive' should still give 2000."""
        adm = make_admission(course='cs executive', payment_type='full_payment')
        amount = _compute_amount_to_pay(None, adm, 0)
        self.assertEqual(amount, Decimal('2000'),
                         f"Expected 2000 for normalized 'cs executive', got {amount}")

    def test_cs_professional_course_name_with_hyphen_normalized(self):
        """'cs-professional' should normalize to 'cs_professional' → 5000."""
        adm = make_admission(course='cs-professional', payment_type='full_payment')
        amount = _compute_amount_to_pay(None, adm, 0)
        self.assertEqual(amount, Decimal('5000'),
                         f"Expected 5000 for normalized 'cs-professional', got {amount}")


# ============================================================================
# Tests for stale 1-Rs link detection logic
# ============================================================================
class TestStale1RsLinkDetection(unittest.TestCase):

    def _is_stale(self, payment_history, existing_link, amount_to_pay):
        """Mirror of the stale-link detection logic."""
        if not existing_link or amount_to_pay <= Decimal('1'):
            return False
        existing_amount = None
        for entry in (payment_history or []):
            if entry.get('event') == 'payment_link_created':
                try:
                    existing_amount = Decimal(str(entry.get('amount', 0)))
                except Exception:
                    pass
                break
        return existing_amount is not None and existing_amount <= Decimal('1')

    def test_1rs_link_detected_as_stale(self):
        history = [{'event': 'payment_link_created', 'amount': 1}]
        self.assertTrue(self._is_stale(history, 'https://rzp.io/link', Decimal('30000')))

    def test_0rs_link_detected_as_stale(self):
        history = [{'event': 'payment_link_created', 'amount': 0}]
        self.assertTrue(self._is_stale(history, 'https://rzp.io/link', Decimal('30000')))

    def test_valid_link_not_flagged_as_stale(self):
        history = [{'event': 'payment_link_created', 'amount': 30000}]
        self.assertFalse(self._is_stale(history, 'https://rzp.io/link', Decimal('30000')))

    def test_no_history_not_flagged_as_stale(self):
        self.assertFalse(self._is_stale([], 'https://rzp.io/link', Decimal('30000')))

    def test_no_existing_link_not_flagged(self):
        history = [{'event': 'payment_link_created', 'amount': 1}]
        self.assertFalse(self._is_stale(history, None, Decimal('30000')))

    def test_new_amount_is_also_1_not_flagged(self):
        """If new amount is also 1 (edge case), don't regenerate."""
        history = [{'event': 'payment_link_created', 'amount': 1}]
        self.assertFalse(self._is_stale(history, 'https://rzp.io/link', Decimal('1')))


# ============================================================================
# Run tests
# ============================================================================
if __name__ == '__main__':
    print("=" * 70)
    print("Admission Payment Setup Amount — Unit Tests")
    print("=" * 70)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestGetModuleFee))
    suite.addTests(loader.loadTestsFromTestCase(TestAmountToPayCalculation))
    suite.addTests(loader.loadTestsFromTestCase(TestStale1RsLinkDetection))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'='*70}")
    print(f"Results: {passed}/{total} passed")
    print('='*70)
    sys.exit(0 if result.wasSuccessful() else 1)
