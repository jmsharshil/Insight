import unittest
from decimal import Decimal
from datetime import date
import calendar

class TestFirstDayAbsencePayslip(unittest.TestCase):
    def test_first_working_day_absence_ongoing_month(self):
        """
        On the 1st working day of the month/week (e.g. Nov 2, 2026),
        if an employee is absent, only 1 day of salary must be deducted,
        NOT the entire 30 days (basic_salary).
        """
        year = 2026
        month = 11
        today = date(2026, 11, 2)  # Monday, 1st working day of month
        last_day_of_month = calendar.monthrange(year, month)[1]  # 30
        last_day = min(today.day, last_day_of_month)  # 2

        working_days = 21  # Total working days in Nov 2026
        working_days_passed = 1  # Only 1 working day (Nov 2) passed so far
        basic_salary = Decimal('30000.00')
        daily_rate = basic_salary / Decimal(30)  # 1000.00

        reg_attended = 0
        valid_hd_count = 0
        full_day_leaves_count = 0
        half_days_count = 0

        # Logic under test:
        is_month_completed = (
            year < today.year
            or (year == today.year and month < today.month)
            or (last_day >= last_day_of_month)
        )

        self.assertFalse(is_month_completed, "Nov 2 is NOT a completed month")

        if is_month_completed and working_days_passed > 0 and (reg_attended + valid_hd_count + full_day_leaves_count) == 0:
            absent_days = Decimal(30)
            absence_deductions = basic_salary if basic_salary > 0 else Decimal(0)
        else:
            absent_days = Decimal(max(0, working_days_passed - reg_attended - valid_hd_count - full_day_leaves_count))
            absent_days += Decimal(half_days_count) * Decimal('0.5')
            absence_deduction_rate = daily_rate
            absence_deductions = min(basic_salary if basic_salary > 0 else Decimal('9999999'), absent_days * absence_deduction_rate)

        self.assertEqual(absent_days, Decimal('1'), "Only 1 day should be marked absent")
        self.assertEqual(absence_deductions, Decimal('1000.00'), "Only 1 day's pay (1000) should be deducted")
        
        net_salary = basic_salary - absence_deductions
        self.assertEqual(net_salary, Decimal('29000.00'), "Net salary should be 29,000, NOT 0")

    def test_full_month_absence_past_month(self):
        """
        When evaluating a completed past month where an employee had 0 attendance
        for all working days, the full 30 days / basic_salary is deducted.
        """
        year = 2026
        month = 10
        today = date(2026, 11, 2)  # Today is Nov, evaluating October
        last_day_of_month = calendar.monthrange(year, month)[1]  # 31
        last_day = last_day_of_month

        working_days = 22
        working_days_passed = working_days
        basic_salary = Decimal('30000.00')
        daily_rate = basic_salary / Decimal(30)

        reg_attended = 0
        valid_hd_count = 0
        full_day_leaves_count = 0
        half_days_count = 0

        is_month_completed = (
            year < today.year
            or (year == today.year and month < today.month)
            or (last_day >= last_day_of_month)
        )

        self.assertTrue(is_month_completed, "October is a completed month when today is in November")

        if is_month_completed and working_days_passed > 0 and (reg_attended + valid_hd_count + full_day_leaves_count) == 0:
            absent_days = Decimal(30)
            absence_deductions = basic_salary if basic_salary > 0 else Decimal(0)
        else:
            absent_days = Decimal(max(0, working_days_passed - reg_attended - valid_hd_count - full_day_leaves_count))
            absent_days += Decimal(half_days_count) * Decimal('0.5')
            absence_deduction_rate = daily_rate
            absence_deductions = min(basic_salary if basic_salary > 0 else Decimal('9999999'), absent_days * absence_deduction_rate)

        self.assertEqual(absent_days, Decimal('30'))
        self.assertEqual(absence_deductions, basic_salary)

    def test_mid_month_partial_absence_ongoing_month(self):
        """
        On day 10 of an ongoing month, 7 working days have passed.
        Employee attended 5, absent 2.
        """
        year = 2026
        month = 11
        today = date(2026, 11, 10)
        last_day_of_month = 30
        last_day = 10

        working_days_passed = 7
        basic_salary = Decimal('30000.00')
        daily_rate = basic_salary / Decimal(30)  # 1000

        reg_attended = 5
        valid_hd_count = 0
        full_day_leaves_count = 0
        half_days_count = 0

        is_month_completed = (
            year < today.year
            or (year == today.year and month < today.month)
            or (last_day >= last_day_of_month)
        )

        self.assertFalse(is_month_completed)

        absent_days = Decimal(max(0, working_days_passed - reg_attended - valid_hd_count - full_day_leaves_count))
        absent_days += Decimal(half_days_count) * Decimal('0.5')
        absence_deductions = min(basic_salary, absent_days * daily_rate)

        self.assertEqual(absent_days, Decimal('2'))
        self.assertEqual(absence_deductions, Decimal('2000.00'))

if __name__ == '__main__':
    unittest.main()

