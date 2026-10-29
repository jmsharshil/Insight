import calendar
from datetime import date, time
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from auth_user.models import User
from branch.models import Branch
from leave.models import LateEntryRecord, LeaveApplication, LeaveBalance
from payroll.models import LateEntryPolicy, PayrollRun
from payroll.utils import compute_payslip_for_user
from leave.utils import check_late_entry_threshold


def _branch_save_no_qr(self, *args, **kwargs):
    if not self.name:
        self.name = "Test Branch"
    from django.db.models import Model
    Model.save(self, *args, **kwargs)


class LateEntryThresholdTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with patch.object(Branch, 'save', _branch_save_no_qr):
            cls.branch = Branch.objects.create(
                name="Test Branch Late",
                city="Mumbai",
                state="MH",
                phone="9999999999",
                email="late@branch.com",
            )

        cls.user = User.objects.create_user(
            username="test_employee_late",
            email="test_employee_late@test.com",
            password="password123",
            role="counsellor",
            employment_type="full_time",
            salary=Decimal("30000"),
            branch=cls.branch,
        )

        cls.policy = LateEntryPolicy.objects.create(
            branch=cls.branch,
            grace_period_minutes=5,
            deduction_per_minute=Decimal("2.00"),
            late_entry_threshold=3,
            auto_halfday_deduction=True,
            is_active=True,
        )

    def _create_late_entry(self, entry_date, late_mins=20, is_penalized=True):
        return LateEntryRecord.objects.create(
            user=self.user,
            branch=self.branch,
            date=entry_date,
            expected_time=time(9, 0),
            actual_time=time(9, 20),
            late_minutes=late_mins,
            grace_minutes=5,
            is_penalized=is_penalized,
            penalty_type="salary_deduction" if is_penalized else "",
        )

    def test_less_than_3_late_entries_no_deduction(self):
        """1 or 2 late entries -> 0 half-day deductions."""
        self._create_late_entry(date(2026, 5, 2))
        check_late_entry_threshold(self.user, 5, 2026)
        self.assertEqual(
            LeaveApplication.objects.filter(applied_by=self.user, is_auto_generated=True, from_date__month=5).count(),
            0
        )

        self._create_late_entry(date(2026, 5, 4))
        check_late_entry_threshold(self.user, 5, 2026)
        self.assertEqual(
            LeaveApplication.objects.filter(applied_by=self.user, is_auto_generated=True, from_date__month=5).count(),
            0
        )

    def test_exactly_3_late_entries_one_half_day_deduction(self):
        """3 late entries -> exactly 1 half-day deduction (0.5 day)."""
        self._create_late_entry(date(2026, 5, 2))
        self._create_late_entry(date(2026, 5, 4))
        rec3 = self._create_late_entry(date(2026, 5, 6))

        check_late_entry_threshold(self.user, 5, 2026)

        auto_leaves = LeaveApplication.objects.filter(applied_by=self.user, is_auto_generated=True, from_date__month=5)
        self.assertEqual(auto_leaves.count(), 1)
        leave = auto_leaves.first()
        self.assertTrue(leave.is_half_day)
        self.assertEqual(leave.total_days, Decimal("0.5"))
        self.assertEqual(leave.from_date, date(2026, 5, 6))

        rec3.refresh_from_db()
        self.assertTrue(rec3.auto_deduction_triggered)

    def test_non_multiplier_counts_no_extra_deduction(self):
        """4 and 5 late entries -> still only 1 half-day deduction."""
        for d in [2, 4, 6, 8, 11]:
            self._create_late_entry(date(2026, 5, d))
            check_late_entry_threshold(self.user, 5, 2026)

        auto_leaves = LeaveApplication.objects.filter(applied_by=self.user, is_auto_generated=True, from_date__month=5)
        # 5 late entries // 3 = 1 deduction. Entries 4 and 5 do not trigger deductions.
        self.assertEqual(auto_leaves.count(), 1)

    def test_multiples_of_3_trigger_subsequent_deductions(self):
        """
        6 late entries -> 2 half-day deductions (1.0 day total).
        7, 8 late entries -> still 2 half-day deductions.
        9 late entries -> 3 half-day deductions (1.5 days total).
        """
        # Add 6 entries
        for d in [1, 4, 5, 6, 7, 8]:
            self._create_late_entry(date(2026, 5, d))
        check_late_entry_threshold(self.user, 5, 2026)

        auto_leaves = LeaveApplication.objects.filter(applied_by=self.user, is_auto_generated=True, from_date__month=5)
        self.assertEqual(auto_leaves.count(), 2)
        total_days = sum((l.total_days for l in auto_leaves), Decimal("0"))
        self.assertEqual(total_days, Decimal("1.0"))

        # Add 7th and 8th entries
        self._create_late_entry(date(2026, 5, 11))
        self._create_late_entry(date(2026, 5, 12))
        check_late_entry_threshold(self.user, 5, 2026)

        auto_leaves = LeaveApplication.objects.filter(applied_by=self.user, is_auto_generated=True, from_date__month=5)
        self.assertEqual(auto_leaves.count(), 2)

        # Add 9th entry
        self._create_late_entry(date(2026, 5, 13))
        check_late_entry_threshold(self.user, 5, 2026)

        auto_leaves = LeaveApplication.objects.filter(applied_by=self.user, is_auto_generated=True, from_date__month=5)
        self.assertEqual(auto_leaves.count(), 3)
        total_days = sum((l.total_days for l in auto_leaves), Decimal("0"))
        self.assertEqual(total_days, Decimal("1.5"))

    def test_monthly_refresh_no_rollover_to_next_month(self):
        """
        Month 5 has 5 late entries -> 1 half-day deducted (remainder 2 not deducted).
        Month 6 begins refreshed with 0 count.
        2 late entries in Month 6 -> 0 deductions.
        3rd late entry in Month 6 -> 1 deduction for Month 6.
        """
        # 5 late entries in May (month 5)
        for d in [2, 4, 6, 8, 11]:
            self._create_late_entry(date(2026, 5, d))
        check_late_entry_threshold(self.user, 5, 2026)

        may_leaves = LeaveApplication.objects.filter(applied_by=self.user, is_auto_generated=True, from_date__month=5)
        self.assertEqual(may_leaves.count(), 1)

        # Month 6 (June) starts fresh
        # 1st late entry in June
        self._create_late_entry(date(2026, 6, 1))
        check_late_entry_threshold(self.user, 6, 2026)
        june_leaves = LeaveApplication.objects.filter(applied_by=self.user, is_auto_generated=True, from_date__month=6)
        self.assertEqual(june_leaves.count(), 0)

        # 2nd late entry in June (total 2 in June; May's leftover 2 do NOT roll over to make 4)
        self._create_late_entry(date(2026, 6, 2))
        check_late_entry_threshold(self.user, 6, 2026)
        june_leaves = LeaveApplication.objects.filter(applied_by=self.user, is_auto_generated=True, from_date__month=6)
        self.assertEqual(june_leaves.count(), 0)

        # 3rd late entry in June -> triggers June's 1st deduction
        self._create_late_entry(date(2026, 6, 3))
        check_late_entry_threshold(self.user, 6, 2026)
        june_leaves = LeaveApplication.objects.filter(applied_by=self.user, is_auto_generated=True, from_date__month=6)
        self.assertEqual(june_leaves.count(), 1)
        self.assertEqual(june_leaves.first().from_date, date(2026, 6, 3))

    def test_payroll_deduction_integration(self):
        """
        Payroll computation accounts for 3 late entries = 1 half-day deduction.
        Salary = 30000 -> daily_rate = 1000 -> 1 half-day = 500 deduction.
        """
        from attendance.models import EmployeeAttendanceRecord
        # Attend all working days in May
        for d in range(1, 32):
            cur = date(2026, 5, d)
            if cur.weekday() < 5:
                EmployeeAttendanceRecord.objects.create(
                    branch=self.branch,
                    user=self.user,
                    date=cur,
                    status="present",
                    checked_in_at=timezone.make_aware(timezone.datetime.combine(cur, time(9, 0))),
                    checked_out_at=timezone.make_aware(timezone.datetime.combine(cur, time(18, 0))),
                )

        # 3 late entries in May
        for d in [4, 5, 6]:
            self._create_late_entry(date(2026, 5, d))

        pr = PayrollRun.objects.create(
            branch=self.branch,
            month=5,
            year=2026,
            status="draft",
            generated_by=self.user,
        )

        ps = compute_payslip_for_user(self.user, 5, 2026, pr)
        # Daily rate = 30000 / 30 = 1000. 1 half-day = 500.00
        self.assertEqual(ps.leave_deductions, Decimal("500.00"))
        self.assertEqual(ps.leaves_taken, 0)  # half day rounds to int 0 in leaves_taken or 1 if int(0.5)
        # Net salary: 30000 (basic) + 1000 (attendance bonus) - 500 (leave deduction) = 30500
        self.assertEqual(ps.net_salary, Decimal("30500.00"))

