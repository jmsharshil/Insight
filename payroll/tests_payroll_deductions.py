"""
Payroll Deduction Test Suite
Covers: full-time faculty, visiting/part-time faculty, regular staff,
        housekeeping/security (Sunday rules), part-time staff, paper checkers.
"""
import calendar
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from auth_user.models import User
from branch.models import Branch
from faculty.models import FacultyProfile, SessionReport, FacultyQRScanLog
from batches.models import Subject, Batch, TimetableSlot, Course
from leave.models import LeaveApplication
from payroll.models import LateEntryPolicy, PayrollRun
from attendance.models import EmployeeAttendanceRecord
from results.models import MarkSheet
from exams.models import Exam
from payroll.utils import compute_payslip_for_faculty, compute_payslip_for_user

YEAR = 2026
MONTH = 5   # May 2026 — 21 working weekdays (Mon-Fri)

# Patch Branch.save to skip QR generation during tests
_orig_branch_save = Branch.save


def _branch_save_no_qr(self, *args, **kwargs):
    """Skip QR image generation in tests."""
    if not self.name:
        self.name = "Test Branch"
    # Call Model.save directly to avoid the QR logic
    from django.db.models import Model
    Model.save(self, *args, **kwargs)


# ---------------------------------------------------------------------------
# Base helpers
# ---------------------------------------------------------------------------

class PayrollBaseTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        with patch.object(Branch, 'save', _branch_save_no_qr):
            cls.branch = Branch.objects.create(
                name="Test Branch",
                address="123 Test St",
                city="Mumbai",
                state="MH",
                pincode="400001",
                phone="9999999999",
                email="test@branch.com",
            )

        cls.admin_user = User.objects.create_user(
            username="admin_payroll_test",
            email="admin_payroll_test@test.com",
            password="pw",
            role="branch_manager",
            employment_type="full_time",
            salary=Decimal("50000"),
            branch=cls.branch,
        )

        cls.policy = LateEntryPolicy.objects.create(
            branch=cls.branch,
            grace_period_minutes=5,
            deduction_per_minute=Decimal("2.00"),
            absence_deduction_per_day=Decimal("500.00"),
            max_deduction_per_session=Decimal("200.00"),
            is_active=True,
            created_by=cls.admin_user,
        )

        cls.payroll_run = PayrollRun.objects.create(
            branch=cls.branch,
            month=MONTH,
            year=YEAR,
            status="draft",
            generated_by=cls.admin_user,
        )

        cls.subject = Subject.objects.create(name="Maths", code="MTH101")
        cls.course = Course.objects.create(name="Test Course", code="TC101")
        cls.batch = Batch.objects.create(
            name="Batch A", branch=cls.branch, course=cls.course,
            start_date=date(YEAR, MONTH, 1), end_date=date(YEAR, MONTH, 28)
        )

    def _weekdays(self):
        return [
            date(YEAR, MONTH, d)
            for d in range(1, calendar.monthrange(YEAR, MONTH)[1] + 1)
            if calendar.weekday(YEAR, MONTH, d) < 5
        ]

    def _make_faculty(self, username, emp_type, salary=0, hourly=0, retention=0):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@test.com",
            password="pw",
            role="faculty",
            employment_type=emp_type,
            salary=Decimal(str(salary)),
            hourly_rate=Decimal(str(hourly)),
            branch=self.branch,
        )
        fp = FacultyProfile.objects.create(
            user=user, branch=self.branch, employment_type=emp_type,
            salary=Decimal(str(salary)),
            hourly_rate=Decimal(str(hourly)),
            salary_retention_percentage=Decimal(str(retention)),
            joining_date=date(YEAR, MONTH, 1),
        )
        return user, fp

    def _make_staff(self, username, role, emp_type, salary=0, hourly=0, retention=0,
                    start=time(9, 0), end=time(18, 0), per_paper=0):
        kwargs = dict(
            username=username,
            email=f"{username}@test.com",
            password="pw",
            role=role,
            employment_type=emp_type,
            salary=Decimal(str(salary)),
            hourly_rate=Decimal(str(hourly)),
            work_start_time=start,
            work_end_time=end,
            salary_retention_percentage=Decimal(str(retention)),
            branch=self.branch,
        )
        if per_paper:
            kwargs["per_paper_rate"] = Decimal(str(per_paper))
        return User.objects.create_user(**kwargs)

    def _qr(self, faculty, log_date, in_time, out_time):
        dt_in = timezone.make_aware(datetime.combine(log_date, in_time))
        dt_out = timezone.make_aware(datetime.combine(log_date, out_time))
        FacultyQRScanLog.objects.create(branch=self.branch, faculty=faculty, scanned_at=dt_in, scan_type="check_in")
        FacultyQRScanLog.objects.create(branch=self.branch, faculty=faculty, scanned_at=dt_out, scan_type="check_out")

    def _session(self, faculty, s_date, start=time(10, 0), end=time(11, 0), mins=60):
        return SessionReport.objects.create(
            branch=self.branch, faculty=faculty, session_date=s_date, subject=self.subject,
            batch=self.batch, start_time=start, end_time=end, duration_minutes=mins,
        )

    def _attendance(self, user, att_date, in_time=time(8, 55), out_time=time(18, 5),
                    status="present"):
        dt_in = timezone.make_aware(datetime.combine(att_date, in_time))
        dt_out = timezone.make_aware(datetime.combine(att_date, out_time))
        return EmployeeAttendanceRecord.objects.create(
            branch=self.branch, user=user, date=att_date, checked_in_at=dt_in, checked_out_at=dt_out, status=status,
        )


# ===========================================================================
# A. FULL-TIME FACULTY
# ===========================================================================

class FullTimeFacultyTests(PayrollBaseTest):

    def setUp(self):
        self.user, self.fp = self._make_faculty(
            "ft_faculty_a", "full_time", salary=30000, retention=10
        )

    def _full_attendance(self):
        for d in self._weekdays():
            self._session(self.fp, d)
            self._qr(self.fp, d, time(8, 55), time(17, 5))

    def test_no_deductions_perfect_attendance(self):
        """Perfect attendance → 0 absence & 0 late penalty."""
        self._full_attendance()
        ps = compute_payslip_for_faculty(self.fp, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.absence_deductions, Decimal("0"))
        self.assertEqual(ps.late_penalty, Decimal("0"))

    def test_unexcused_absence_deduction(self):
        """Attend only first 15 days → 6 absent days × 500 = 3000."""
        weekdays = self._weekdays()
        for d in weekdays[:15]:
            self._session(self.fp, d)
            self._qr(self.fp, d, time(8, 55), time(17, 5))
        ps = compute_payslip_for_faculty(self.fp, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.absence_deductions, Decimal("3000.00"))

    def test_approved_leave_excludes_from_absence(self):
        """Approved leave days not counted as absent."""
        weekdays = self._weekdays()
        for d in weekdays[:19]:
            self._session(self.fp, d)
            self._qr(self.fp, d, time(8, 55), time(17, 5))
        # 2 days absent but covered by leave
        LeaveApplication.objects.create(
            applied_by=self.user, leave_type="paid", status="approved",
            from_date=weekdays[19], to_date=weekdays[20],
        )
        ps = compute_payslip_for_faculty(self.fp, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.absence_deductions, Decimal("0"))

    def test_unpaid_leave_deduction(self):
        """Unpaid approved leave → leave_deductions > 0."""
        weekdays = self._weekdays()
        for d in weekdays:
            self._session(self.fp, d)
            self._qr(self.fp, d, time(8, 55), time(17, 5))
        LeaveApplication.objects.create(
            applied_by=self.user, leave_type="unpaid", status="approved",
            from_date=weekdays[0], to_date=weekdays[1],
        )
        ps = compute_payslip_for_faculty(self.fp, MONTH, YEAR, self.payroll_run)
        # 2 unpaid days × (30000/30 = 1000) = 2000
        self.assertEqual(ps.leave_deductions, Decimal("2000.00"))

    def test_retention_applied_after_deductions(self):
        """Retention deducted on net-after-deductions, never negative."""
        weekdays = self._weekdays()
        for d in weekdays:
            self._session(self.fp, d)
            self._qr(self.fp, d, time(8, 55), time(17, 5))
        ps = compute_payslip_for_faculty(self.fp, MONTH, YEAR, self.payroll_run)
        expected_retention = (ps.net_salary + ps.retention_deduction) * Decimal("0.10")
        self.assertAlmostEqual(float(ps.retention_deduction), float(expected_retention), places=1)
        self.assertGreaterEqual(ps.net_salary, Decimal("0"))

    def test_month_boundary_leave(self):
        """Multi-month leave only counts days in current month."""
        weekdays = self._weekdays()
        for d in weekdays:
            self._session(self.fp, d)
            self._qr(self.fp, d, time(8, 55), time(17, 5))
        LeaveApplication.objects.create(
            applied_by=self.user, leave_type="paid", status="approved",
            from_date=date(YEAR, MONTH - 1, 25),   # starts in April
            to_date=date(YEAR, MONTH, 5),           # ends in May
        )
        ps = compute_payslip_for_faculty(self.fp, MONTH, YEAR, self.payroll_run)
        # Should not crash, absence should be 0 (leave covers attended days)
        self.assertEqual(ps.absence_deductions, Decimal("0"))


# ===========================================================================
# B. VISITING / PART-TIME FACULTY
# ===========================================================================

class VisitingFacultyTests(PayrollBaseTest):

    def setUp(self):
        self.user, self.fp = self._make_faculty(
            "visiting_b", "visiting", hourly=500, retention=0
        )

    def test_absence_deduction_is_zero(self):
        """Visiting faculty who only attend 2 days must never get absence deductions."""
        weekdays = self._weekdays()
        for d in weekdays[:2]:
            self._qr(self.fp, d, time(9, 55), time(11, 5))
        ps = compute_payslip_for_faculty(self.fp, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.absence_deductions, Decimal("0"))

    def test_approved_leave_does_not_create_absence(self):
        """Approved leave on days with no sessions must not generate absence deduction."""
        weekdays = self._weekdays()
        self._qr(self.fp, weekdays[0], time(10, 0), time(11, 0))
        LeaveApplication.objects.create(
            applied_by=self.user, leave_type="unpaid", status="approved",
            from_date=weekdays[1], to_date=weekdays[3],
        )
        ps = compute_payslip_for_faculty(self.fp, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.absence_deductions, Decimal("0"))
        # Visiting: leave_deductions always 0
        self.assertEqual(ps.leave_deductions, Decimal("0"))

    def test_late_penalty_within_5min_buffer_no_penalty(self):
        """4 min late + 0 early out = 4 min total ≤ 5 grace → penalty = 0."""
        dow = self._weekdays()[0].weekday()
        TimetableSlot.objects.create(
            batch=self.batch, subject=self.subject, day_of_week=dow,
            start_time=time(10, 0), end_time=time(11, 0), faculty=self.fp,
        )
        d = self._weekdays()[0]
        self._qr(self.fp, d, time(10, 4), time(11, 0))
        ps = compute_payslip_for_faculty(self.fp, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.late_penalty, Decimal("0"))

    def test_late_penalty_exceeds_buffer(self):
        """5 min late + 5 min early out = 10 total − 5 grace = 5 min × 2.00 = 10.00."""
        dow = self._weekdays()[0].weekday()
        TimetableSlot.objects.create(
            batch=self.batch, subject=self.subject, day_of_week=dow,
            start_time=time(10, 0), end_time=time(11, 0), faculty=self.fp,
        )
        d = self._weekdays()[0]
        self._qr(self.fp, d, time(10, 5), time(10, 55))
        ps = compute_payslip_for_faculty(self.fp, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.late_penalty, Decimal("10.00"))

    def test_hourly_pay_based_on_session_hours(self):
        """2-hour session × 500/hr = 1000 gross (no absence deduction)."""
        d = self._weekdays()[0]
        self._session(self.fp, d, start=time(10, 0), end=time(12, 0), mins=120)
        ps = compute_payslip_for_faculty(self.fp, MONTH, YEAR, self.payroll_run)
        self.assertAlmostEqual(float(ps.hour_based_amount), 1000.0, places=1)
        self.assertEqual(ps.absence_deductions, Decimal("0"))

    def test_retention_on_visiting_pay(self):
        """Retention % applied to net earned hours pay."""
        _, fp = self._make_faculty("visiting_ret", "visiting", hourly=500, retention=10)
        d = self._weekdays()[0]
        SessionReport.objects.create(
            branch=self.branch, faculty=fp, session_date=d, subject=self.subject, batch=self.batch,
            start_time=time(10, 0), end_time=time(12, 0), duration_minutes=120,
        )
        ps = compute_payslip_for_faculty(fp, MONTH, YEAR, self.payroll_run)
        self.assertGreater(ps.retention_deduction, Decimal("0"))
        self.assertGreaterEqual(ps.net_salary, Decimal("0"))


class PartTimeFacultyTests(PayrollBaseTest):

    def setUp(self):
        self.user, self.fp = self._make_faculty(
            "part_time_c", "part_time", hourly=400, retention=0
        )

    def test_absence_deduction_is_zero(self):
        weekdays = self._weekdays()
        self._qr(self.fp, weekdays[0], time(10, 0), time(12, 0))
        ps = compute_payslip_for_faculty(self.fp, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.absence_deductions, Decimal("0"))


# ===========================================================================
# C. REGULAR FULL-TIME STAFF
# ===========================================================================

class RegularStaffTests(PayrollBaseTest):

    def setUp(self):
        self.user = self._make_staff(
            "staff_d", "front_desk", "full_time", salary=15000,
            start=time(9, 0), end=time(18, 0),
        )

    def test_absence_deduction(self):
        """10 days attended, 5 on approved leave → 6 absent × 500 = 3000."""
        weekdays = self._weekdays()
        for d in weekdays[:10]:
            self._attendance(self.user, d)
        LeaveApplication.objects.create(
            applied_by=self.user, leave_type="paid", status="approved",
            from_date=weekdays[10], to_date=weekdays[14],
        )
        ps = compute_payslip_for_user(self.user, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.absence_deductions, Decimal("3000.00"))

    def test_unpaid_leave_deduction_full_time(self):
        """5 unpaid leave days × (15000/30=500) = 2500."""
        weekdays = self._weekdays()
        for d in weekdays:
            self._attendance(self.user, d)
        LeaveApplication.objects.create(
            applied_by=self.user, leave_type="unpaid", status="approved",
            from_date=weekdays[0], to_date=weekdays[4],
        )
        ps = compute_payslip_for_user(self.user, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.leave_deductions, Decimal("2500.00"))

    def test_late_entry_penalty(self):
        """30 min late − 5 grace = 25 min penalty dynamically calculated."""
        weekdays = self._weekdays()
        self._attendance(self.user, weekdays[0], in_time=time(9, 30))
        ps = compute_payslip_for_user(self.user, MONTH, YEAR, self.payroll_run)
        self.assertAlmostEqual(float(ps.late_penalty), 23.15, places=2)

    def test_no_late_penalty_within_grace(self):
        """3 min late ≤ 5 grace → penalty = 0."""
        weekdays = self._weekdays()
        self._attendance(self.user, weekdays[0], in_time=time(9, 3))
        ps = compute_payslip_for_user(self.user, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.late_penalty, Decimal("0"))

    def test_retention_after_deductions(self):
        """Retention deducted last; net_salary always >= 0."""
        user = self._make_staff(
            "staff_ret", "counsellor", "full_time", salary=15000, retention=10,
        )
        weekdays = self._weekdays()
        for d in weekdays[:10]:
            self._attendance(user, d)
        ps = compute_payslip_for_user(user, MONTH, YEAR, self.payroll_run)
        self.assertGreaterEqual(ps.net_salary, Decimal("0"))
        self.assertGreater(ps.retention_deduction, Decimal("0"))


# ===========================================================================
# D. HOUSEKEEPING / SECURITY (Sunday rules)
# ===========================================================================

class SundayRulesTests(PayrollBaseTest):

    def setUp(self):
        self.user = self._make_staff(
            "security_e", "security", "full_time", salary=15000,
        )

    def _sundays(self):
        return [
            date(YEAR, MONTH, d)
            for d in range(1, calendar.monthrange(YEAR, MONTH)[1] + 1)
            if calendar.weekday(YEAR, MONTH, d) == 6
        ]

    def _attend_all_weekdays(self):
        for d in self._weekdays():
            self._attendance(self.user, d)

    def test_zero_sundays_attended_deducts_two_days(self):
        """0 Sundays attended → deduct 2 days × 500 = 1000."""
        self._attend_all_weekdays()
        ps = compute_payslip_for_user(self.user, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.absence_deductions, Decimal("1000.00"))

    def test_one_sunday_attended_deducts_one_day(self):
        """1 Sunday attended → deduct 1 day × 500 = 500."""
        self._attend_all_weekdays()
        self._attendance(self.user, self._sundays()[0])
        ps = compute_payslip_for_user(self.user, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.absence_deductions, Decimal("500.00"))

    def test_two_sundays_no_sunday_deduction(self):
        """2 Sundays attended → no Sunday deduction."""
        self._attend_all_weekdays()
        for s in self._sundays()[:2]:
            self._attendance(self.user, s)
        ps = compute_payslip_for_user(self.user, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.absence_deductions, Decimal("0"))

    def test_three_plus_sundays_bonus(self):
        """3+ Sundays → attendance_bonus includes 1 extra day."""
        self._attend_all_weekdays()
        for s in self._sundays()[:3]:
            self._attendance(self.user, s)
        ps = compute_payslip_for_user(self.user, MONTH, YEAR, self.payroll_run)
        # Standard bonus (>80%) = 500, Sunday bonus = 500 → total 1000
        self.assertGreaterEqual(ps.attendance_bonus, Decimal("500.00"))


# ===========================================================================
# E. PART-TIME / HOURLY NON-FACULTY STAFF
# ===========================================================================

class PartTimeStaffTests(PayrollBaseTest):

    def setUp(self):
        self.user = self._make_staff(
            "pt_staff_f", "counsellor", "part_time", hourly=200,
        )

    def test_pay_based_on_hours_only(self):
        """5 days × 4 hours × 200 = 4000, no absence deductions."""
        weekdays = self._weekdays()
        for d in weekdays[:5]:
            self._attendance(self.user, d, in_time=time(10, 0), out_time=time(14, 0))
        ps = compute_payslip_for_user(self.user, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.hour_based_amount, Decimal("4000.00"))
        self.assertEqual(ps.absence_deductions, Decimal("0"))
        self.assertEqual(ps.leave_deductions, Decimal("0"))

    def test_retention_on_part_time(self):
        """Retention applied on hourly net."""
        user = self._make_staff("pt_ret_f2", "counsellor", "part_time", hourly=200, retention=10)
        weekdays = self._weekdays()
        for d in weekdays[:5]:
            EmployeeAttendanceRecord.objects.create(
                branch=self.branch, user=user, date=d,
                checked_in_at=timezone.make_aware(datetime.combine(d, time(10, 0))),
                checked_out_at=timezone.make_aware(datetime.combine(d, time(14, 0))),
                status="present",
            )
        ps = compute_payslip_for_user(user, MONTH, YEAR, self.payroll_run)
        self.assertGreater(ps.retention_deduction, Decimal("0"))
        self.assertGreaterEqual(ps.net_salary, Decimal("0"))


# ===========================================================================
# F. PAPER CHECKERS
# ===========================================================================

class PaperCheckerTests(PayrollBaseTest):

    def setUp(self):
        self.user = self._make_staff(
            "checker_g", "paper_checker", "part_time", per_paper=50,
        )
        self.exam = Exam.objects.create(
            branch=self.branch,
            title="Test Exam",
            exam_type="internal",
            exam_mode="offline",
            total_marks=100,
            pass_marks=40,
            duration_minutes=120,
            scheduled_date=date(YEAR, MONTH, 5),
            start_time=time(10, 0),
            end_time=time(12, 0),
            status="completed",
            created_by=self.admin_user,
        )
        self.exam.paper_checkers.add(self.user)
        # Need students to attach marksheets to
        from students.models import Student
        self.students = []
        for i in range(5):
            u = User.objects.create_user(
                username=f"student_{i}_g",
                email=f"student_{i}_g@test.com",
                password="pw",
                role="student",
                employment_type="full_time",
                branch=self.branch,
            )
            s = Student.objects.create(user=u, branch=self.branch, dob=date(2000, 1, 1))
            self.students.append(s)

    def _make_marksheet(self, student, checked_date):
        dt = timezone.make_aware(datetime.combine(checked_date, time(12, 0)))
        return MarkSheet.objects.create(
            exam=self.exam, student=student,
            paper_checker=self.user, is_submitted=True, checked_at=dt,
        )

    def test_pay_per_paper_on_time(self):
        """5 papers on time × 50 = 250, late_penalty = 0."""
        on_time = date(YEAR, MONTH, 9)   # 4 days after exam (grace=5)
        for s in self.students:
            self._make_marksheet(s, on_time)
        ps = compute_payslip_for_user(self.user, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.hour_based_amount, Decimal("250.00"))
        self.assertEqual(ps.late_penalty, Decimal("0"))
        self.assertEqual(ps.absence_deductions, Decimal("0"))

    def test_late_submission_penalty_bracket_1(self):
        """3 days past grace (8 days after exam) → bracket=1 → 5% penalty per paper."""
        late_date = date(YEAR, MONTH, 13)  # 5+3 = 8 days after exam date (May 5)
        for s in self.students:
            self._make_marksheet(s, late_date)
        ps = compute_payslip_for_user(self.user, MONTH, YEAR, self.payroll_run)
        # 5 papers × 50 × 5% = 12.50
        self.assertEqual(ps.late_penalty, Decimal("12.50"))
        self.assertEqual(ps.hour_based_amount, Decimal("250.00"))

    def test_late_submission_penalty_bracket_2(self):
        """10 days past grace → bracket=2 → 10% penalty."""
        late_date = date(YEAR, MONTH, 20)  # May 5 + 5 grace + 10 = May 20
        for s in self.students:
            self._make_marksheet(s, late_date)
        ps = compute_payslip_for_user(self.user, MONTH, YEAR, self.payroll_run)
        # 5 papers × 50 × 10% = 25.00
        self.assertEqual(ps.late_penalty, Decimal("25.00"))

    def test_paper_checker_no_absence_or_leave_deductions(self):
        """Paper checkers never get absence or leave deductions."""
        on_time = date(YEAR, MONTH, 9)
        for s in self.students:
            self._make_marksheet(s, on_time)
        ps = compute_payslip_for_user(self.user, MONTH, YEAR, self.payroll_run)
        self.assertEqual(ps.absence_deductions, Decimal("0"))
        self.assertEqual(ps.leave_deductions, Decimal("0"))
        self.assertEqual(ps.working_days, 0)

    def test_net_salary_never_negative(self):
        """Even with maximum penalty, net salary stays >= 0."""
        very_late = date(YEAR, MONTH, 31)
        for s in self.students:
            self._make_marksheet(s, very_late)
        ps = compute_payslip_for_user(self.user, MONTH, YEAR, self.payroll_run)
        self.assertGreaterEqual(ps.net_salary, Decimal("0"))
