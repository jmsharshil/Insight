from decimal import Decimal

from django.test import SimpleTestCase

from payroll.utils import build_deduction_note


class DeductionNoteFormattingTests(SimpleTestCase):
    def test_late_penalty_note_includes_penalty_minutes_and_rate(self):
        note = build_deduction_note(
            late_penalty=Decimal('150.00'),
            late_penalty_minutes=15,
            late_penalty_rate=Decimal('10.00'),
            late_dates=['2026-07-01'],
            absence_deductions=Decimal('0'),
            absent_dates=[],
            applied_leave_deductions=Decimal('0'),
            leave_dates=[],
            retention_deduction=Decimal('0'),
            retention_percentage=Decimal('0'),
            sunday_deduction=Decimal('0'),
        )

        self.assertIn('Late check-in/out', note)
        self.assertIn('15 min', note)
        self.assertIn('10.00/min', note)
        self.assertIn('-150.00', note)

    def test_other_deductions_are_described_with_counts(self):
        note = build_deduction_note(
            late_penalty=Decimal('0'),
            late_penalty_minutes=0,
            late_penalty_rate=Decimal('0'),
            late_dates=[],
            absence_deductions=Decimal('120.00'),
            absent_dates=['2026-07-02', '2026-07-03'],
            applied_leave_deductions=Decimal('80.00'),
            leave_dates=['2026-07-04 to 2026-07-04'],
            retention_deduction=Decimal('50.00'),
            retention_percentage=Decimal('10'),
            sunday_deduction=Decimal('20.00'),
        )

        self.assertIn('Absent (2 days)', note)
        self.assertIn('Leave (1 day)', note)
        self.assertIn('Retention (10%)', note)
        self.assertIn('Sunday Shortfall', note)
