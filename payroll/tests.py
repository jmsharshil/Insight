from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase
from .serializers import MyPaySlipSerializer, PaySlipSerializer


class PaySlipReimbursementNotesTests(SimpleTestCase):
    def test_includes_reimbursements_and_travel_expenses(self):
        reimbursement = SimpleNamespace(
            expense_date=date(2026, 5, 12),
            title='Taxi fare',
            description='Travel to client meeting',
            amount=Decimal('450.00'),
            status='approved',
        )
        activity = SimpleNamespace(
            activity_date=date(2026, 5, 13),
            name='School visit',
        )
        odometer_reading = SimpleNamespace(
            activity=activity,
            total_kms=Decimal('18.50'),
            total_expense=Decimal('92.50'),
            status='approved',
            vehicle_type='bike',
            expense_per_km=Decimal('5.00'),
        )

        class RelatedItems:
            def __init__(self, items):
                self.items = items

            def all(self):
                return self.items

        payslip = SimpleNamespace(
            reimbursements=RelatedItems([reimbursement]),
            odometer_readings=RelatedItems([odometer_reading]),
            payroll_run=SimpleNamespace(year=2026, month=5),
        )

        self.assertEqual(
            PaySlipSerializer().get_reimbursement_notes(payslip),
            [
                {
                    'date': '2026-05-12',
                    'event': 'Taxi fare',
                    'description': 'Travel to client meeting',
                    'expense': 450.0,
                },
            ],
        )

        self.assertEqual(
            PaySlipSerializer().get_odometer_notes(payslip),
            [{
                'date': '2026-05-13',
                'event': 'School visit',
                'vehicle_type': 'bike',
                'kms': 18.5,
                'rate_per_km': 5.0,
                'expense': 92.5,
            }],
        )

    def test_personal_payslip_exposes_reimbursement_notes(self):
        self.assertIn('reimbursement_notes', MyPaySlipSerializer.Meta.fields)
