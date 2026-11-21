"""
Unit tests to verify asynchronous post-payment task dispatching and idempotency in razorpay_service.py.
"""
import os
import sys
import unittest
from decimal import Decimal

# Setup Django
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
import django
django.setup()

from unittest.mock import patch, MagicMock


class TestRazorpayWebhookAsyncFix(unittest.TestCase):

    @patch('fees.models.Payment')
    def test_early_idempotency_returns_success_immediately(self, mock_payment_cls):
        from fees.razorpay_service import process_payment_link_paid_event

        existing_mock = MagicMock()
        existing_mock.id = "payment-uuid-1234"
        mock_payment_cls.objects.filter.return_value.first.return_value = existing_mock

        payload = {
            'event': 'payment_link.paid',
            'payload': {
                'payment_link': {
                    'entity': {
                        'id': 'plink_TEST123',
                        'reference_id': 'SF_1732172746_655e44f636ee415c',
                        'amount_paid': 6000000,
                    }
                },
                'payment': {
                    'entity': {
                        'id': 'pay_U2jZ6orPBGn4mC',
                        'amount': 6000000,
                    }
                }
            }
        }

        result = process_payment_link_paid_event(payload)

        self.assertTrue(result.get('success'))
        self.assertTrue(result.get('duplicate'))
        self.assertEqual(result.get('payment_id'), "payment-uuid-1234")

    @patch('fees.razorpay_service._dispatch_sf_post_payment_tasks')
    @patch('fees.utils.update_student_fee_status')
    @patch('fees.models.StudentFee')
    @patch('fees.models.Payment')
    def test_sf_flow_dispatches_async_tasks(self, mock_payment_cls, mock_sf_cls, mock_update_fee, mock_dispatch):
        from fees.razorpay_service import process_payment_link_paid_event

        # No duplicate exists
        mock_payment_cls.objects.filter.return_value.first.return_value = None

        new_payment = MagicMock()
        new_payment.id = "new-payment-uuid-5678"
        mock_payment_cls.objects.create.return_value = new_payment

        mock_sf = MagicMock()
        mock_sf.id = "sf-uuid-999"
        mock_sf.pk = "sf-uuid-999"
        mock_sf.student.id = "student-uuid-888"
        mock_sf.student.email = "student@example.com"
        mock_sf_cls.objects.select_related.return_value.get.return_value = mock_sf
        mock_sf_cls.objects.select_for_update.return_value.select_related.return_value.get.return_value = mock_sf

        payload = {
            'event': 'payment_link.paid',
            'payload': {
                'payment_link': {
                    'entity': {
                        'id': 'plink_NEW123',
                        'reference_id': 'SF_1732172746_sf-uuid-999',
                        'amount_paid': 6000000,
                        'notes': {'student_fee_id': 'sf-uuid-999'}
                    }
                },
                'payment': {
                    'entity': {
                        'id': 'pay_NEW_TX_999',
                        'amount': 6000000,
                    }
                }
            }
        }

        result = process_payment_link_paid_event(payload, async_dispatch=True)

        self.assertTrue(result.get('success'))
        self.assertEqual(result.get('processed'), 'SF')
        self.assertEqual(result.get('payment_id'), 'new-payment-uuid-5678')

        # Verify async dispatch was called with expected arguments
        mock_dispatch.assert_called_once_with(
            payment_id=new_payment.id,
            sf_id=mock_sf.id,
            rp_payment_id='pay_NEW_TX_999',
            amount_paid=Decimal('60000.00'),
            student_email='student@example.com'
        )


if __name__ == '__main__':
    unittest.main()
