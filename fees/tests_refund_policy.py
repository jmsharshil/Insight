from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from fees.utils import get_refund_policy


class RefundPolicyTests(SimpleTestCase):
    def test_refund_is_rejected_after_seven_days(self):
        payment = SimpleNamespace(
            amount=Decimal('1000'),
            payment_date=datetime.now() - timedelta(days=8),
            created_at=datetime.now() - timedelta(days=8),
        )

        policy = get_refund_policy(payment, Decimal('900'))

        self.assertFalse(policy['eligible'])
        self.assertIn('7 days', policy['reason'])
        self.assertEqual(policy['max_refundable_amount'], Decimal('0'))

    def test_refund_is_capped_at_90_percent_within_seven_days(self):
        payment = SimpleNamespace(
            amount=Decimal('1000'),
            payment_date=datetime.now() - timedelta(days=3),
            created_at=datetime.now() - timedelta(days=3),
        )

        policy = get_refund_policy(payment, Decimal('950'))

        self.assertTrue(policy['eligible'])
        self.assertEqual(policy['max_refundable_amount'], Decimal('900'))
