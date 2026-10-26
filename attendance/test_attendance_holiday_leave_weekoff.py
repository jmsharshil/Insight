import datetime
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from auth_user.models import User, Organization
from branch.models import Branch
from attendance.models import EmployeeAttendanceRecord
from attendance.tasks import auto_mark_staff_absentees_eod
from leave.models import LeaveApplication, PublicHoliday, LeaveBalance, LeavePolicy


class AttendanceHolidayLeaveWeekOffTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Holiday Test Org")
        self.branch = Branch.objects.create(
            name="Holiday Test Branch",
            organization=self.org,
            latitude=12.9716,
            longitude=77.5946,
            allowed_radius_meters=1000
        )

        self.admin = User.objects.create_user(
            username="admin_holiday",
            email="admin_holiday@test.com",
            password="password123",
            role="super_admin",
            organization=self.org,
            branch=self.branch,
            name="Admin Holiday",
            is_active=True
        )

        self.staff = User.objects.create_user(
            username="staff_holiday",
            email="staff_holiday@test.com",
            password="password123",
            role="admin_executive",
            organization=self.org,
            branch=self.branch,
            name="Staff Holiday",
            is_active=True,
            weekly_schedule={
                "sunday": {"is_off": True, "start_time": "10:00:00", "end_time": "19:00:00"},
                "monday": {"is_off": False, "start_time": "10:00:00", "end_time": "19:00:00"},
                "tuesday": {"is_off": False, "start_time": "10:00:00", "end_time": "19:00:00"},
                "wednesday": {"is_off": False, "start_time": "10:00:00", "end_time": "19:00:00"},
                "thursday": {"is_off": False, "start_time": "10:00:00", "end_time": "19:00:00"},
                "friday": {"is_off": False, "start_time": "10:00:00", "end_time": "19:00:00"},
                "saturday": {"is_off": False, "start_time": "10:00:00", "end_time": "19:00:00", "saturday_rule": "odd"},
            }
        )

        # Dates in October 2026:
        # 2026-10-18 is Sunday
        self.sunday = datetime.date(2026, 10, 18)
        # 2026-10-10 is the 2nd Saturday (even Saturday -> off under 'odd' saturday_rule)
        self.saturday_off = datetime.date(2026, 10, 10)
        # 2026-10-14 is Wednesday (regular weekday)
        self.wednesday = datetime.date(2026, 10, 14)
        # 2026-10-15 is Thursday (regular weekday)
        self.thursday = datetime.date(2026, 10, 15)

    def test_auto_mark_staff_absentees_sunday_is_marked_week_off(self):
        """
        On Sunday, when auto-mark staff absentees runs, staff members without check-in
        must receive a record with status='week_off', NOT 'absent'.
        """
        self.assertEqual(self.sunday.weekday(), 6)  # Sunday
        auto_mark_staff_absentees_eod(target_date=self.sunday)

        rec = EmployeeAttendanceRecord.objects.filter(user=self.staff, date=self.sunday).first()
        self.assertIsNotNone(rec)
        self.assertIn(rec.status, ['week_off', 'week_of'])
        self.assertEqual(rec.get_status_display(), 'Week Off')

    def test_auto_mark_staff_absentees_saturday_week_off_is_marked_week_of(self):
        """
        On Saturday, if the staff user has week off (e.g. 2nd Saturday under odd rule),
        they must receive status='week_of', NOT 'absent'.
        """
        self.assertEqual(self.saturday_off.weekday(), 5)  # Saturday
        self.assertTrue(self.staff.is_day_off(self.saturday_off))

        auto_mark_staff_absentees_eod(target_date=self.saturday_off)

        rec = EmployeeAttendanceRecord.objects.filter(user=self.staff, date=self.saturday_off).first()
        self.assertIsNotNone(rec)
        self.assertIn(rec.status, ['week_of', 'week_off'])
        self.assertEqual(rec.get_status_display(), 'Week Off')

    def test_auto_mark_staff_absentees_public_holiday(self):
        """
        On a date with a public holiday, staff without check-in must receive status='public_holiday'.
        """
        PublicHoliday.objects.create(
            organization=self.org,
            branch=self.branch,
            date=self.wednesday,
            name="Diwali Holiday",
            year=2026
        )

        auto_mark_staff_absentees_eod(target_date=self.wednesday)

        rec = EmployeeAttendanceRecord.objects.filter(user=self.staff, date=self.wednesday).first()
        self.assertIsNotNone(rec)
        self.assertEqual(rec.status, 'public_holiday')
        self.assertEqual(rec.get_status_display(), 'Public Holiday')

    def test_auto_mark_staff_absentees_approved_leave(self):
        """
        On a date where the user has an approved leave, their attendance record must arrive
        with their leave type (e.g. 'sick_leave', 'paid_leave'), NOT 'absent'.
        """
        LeaveApplication.objects.create(
            applied_by=self.staff,
            branch=self.branch,
            leave_type='sick',
            from_date=self.thursday,
            to_date=self.thursday,
            total_days=1,
            reason="Flu",
            status='approved'
        )

        auto_mark_staff_absentees_eod(target_date=self.thursday)

        rec = EmployeeAttendanceRecord.objects.filter(user=self.staff, date=self.thursday).first()
        self.assertIsNotNone(rec)
        self.assertEqual(rec.status, 'sick_leave')
        self.assertEqual(rec.get_status_display(), 'Sick Leave')

    def test_auto_mark_staff_absentees_regular_working_day_is_absent(self):
        """
        On a regular working day with no check-in, no holiday, no week off, and no approved leave,
        the staff member is marked as 'absent'.
        """
        # Tuesday 2026-10-13 (working day)
        tuesday = datetime.date(2026, 10, 13)
        self.assertFalse(self.staff.is_day_off(tuesday))

        auto_mark_staff_absentees_eod(target_date=tuesday)

        rec = EmployeeAttendanceRecord.objects.filter(user=self.staff, date=tuesday).first()
        self.assertIsNotNone(rec)
        self.assertEqual(rec.status, 'absent')
        self.assertEqual(rec.get_status_display(), 'Absent')

    @patch('auditlog.blob_service.download_log_file', return_value=None)
    @patch('auditlog.blob_service.upload_log_file', return_value=True)
    def test_attendance_history_summary_excludes_holiday_and_leave_from_absent_count_and_percentage(self, m1, m2):
        """
        Verify that in Employee Attendance History:
        1. Holidays, week offs, and leaves are NOT counted as absent.
        2. Attendance percentage is calculated based on working days (present / working_days),
           so holidays and leaves do not depress the percentage.
        """
        # Create:
        # 10 present days
        # 1 genuine absent day
        # 2 holidays (Sunday)
        # 2 week_of days (Saturday off)
        # 1 sick_leave day
        base_d = datetime.date(2026, 6, 1)
        for i in range(10):
            EmployeeAttendanceRecord.objects.create(
                user=self.staff, branch=self.branch,
                date=base_d + datetime.timedelta(days=i), status='present'
            )
        # 1 absent day
        EmployeeAttendanceRecord.objects.create(
            user=self.staff, branch=self.branch,
            date=base_d + datetime.timedelta(days=10), status='absent'
        )
        # 2 holidays
        EmployeeAttendanceRecord.objects.create(
            user=self.staff, branch=self.branch,
            date=base_d + datetime.timedelta(days=11), status='holiday'
        )
        EmployeeAttendanceRecord.objects.create(
            user=self.staff, branch=self.branch,
            date=base_d + datetime.timedelta(days=12), status='public_holiday'
        )
        # 2 week_of days
        EmployeeAttendanceRecord.objects.create(
            user=self.staff, branch=self.branch,
            date=base_d + datetime.timedelta(days=13), status='week_of'
        )
        EmployeeAttendanceRecord.objects.create(
            user=self.staff, branch=self.branch,
            date=base_d + datetime.timedelta(days=14), status='week_of'
        )
        # 1 sick leave
        EmployeeAttendanceRecord.objects.create(
            user=self.staff, branch=self.branch,
            date=base_d + datetime.timedelta(days=15), status='sick_leave'
        )

        self.client.force_authenticate(user=self.staff)
        url = reverse('employee-attendance-history')
        response = self.client.get(f"{url}?from_date=2026-06-01&to_date=2026-06-20")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        summary = response.data['summary']

        # Total days: 16
        self.assertEqual(summary['total_days'], 16)
        # Working days: 16 - 2 (holidays) - 2 (week_offs) - 1 (leave) = 11
        self.assertEqual(summary['working_days'], 11)
        # Present: 10
        self.assertEqual(summary['present_days'], 10)
        # Absent: 1 (ONLY the genuine absent day)
        self.assertEqual(summary['absent_days'], 1)
        # Holidays: 2
        self.assertEqual(summary['holidays'], 2)
        # Week offs: 2
        self.assertEqual(summary['week_offs'], 2)
        # On leave: 1
        self.assertEqual(summary['on_leave'], 1)
        # Percentage: 10 / 11 * 100 = 90.9% (NOT 10 / 16 = 62.5%)
        self.assertEqual(summary['attendance_percentage'], 90.9)

    @patch('auditlog.blob_service.download_log_file', return_value=None)
    @patch('auditlog.blob_service.upload_log_file', return_value=True)
    def test_attendance_detail_summary_and_recent_absences(self, m1, m2):
        """
        Verify that in Employee Attendance Detail API:
        1. absent_count is only 1.
        2. recent_absences only contains the actual absent date, not holidays or leaves.
        3. Serialized records include leave_type, is_holiday, is_week_off, is_leave.
        """
        target = datetime.date(2026, 7, 1)  # Wednesday
        EmployeeAttendanceRecord.objects.create(
            user=self.staff, branch=self.branch, date=target, status='present'
        )
        EmployeeAttendanceRecord.objects.create(
            user=self.staff, branch=self.branch, date=target + datetime.timedelta(days=1), status='holiday'
        )
        EmployeeAttendanceRecord.objects.create(
            user=self.staff, branch=self.branch, date=target + datetime.timedelta(days=2), status='week_of'
        )
        EmployeeAttendanceRecord.objects.create(
            user=self.staff, branch=self.branch, date=target + datetime.timedelta(days=3), status='paid_leave'
        )
        # Monday July 6 is a regular working weekday (genuine absence)
        monday = datetime.date(2026, 7, 6)
        EmployeeAttendanceRecord.objects.create(
            user=self.staff, branch=self.branch, date=monday, status='absent'
        )

        self.client.force_authenticate(user=self.admin)
        url = reverse('employee-attendance-detail', kwargs={'user_id': self.staff.id})
        response = self.client.get(f"{url}?start_date=2026-07-01&end_date=2026-07-10")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data['data']
        summary = data['summary']

        self.assertEqual(summary['present_count'], 1)
        self.assertEqual(summary['absent_count'], 1)
        self.assertEqual(summary['holiday_count'], 1)
        self.assertEqual(summary['week_off_count'], 1)
        self.assertEqual(summary['leave_count'], 1)
        self.assertEqual(summary['working_days'], 2)  # 1 present + 1 absent

        # Attendance percentage: 1 / 2 * 100 = 50.0%
        self.assertEqual(data['attendance_percentage'], 50.0)

        # Recent absences: only 1 entry (absent), no holidays or leaves
        recent = data['recent_absences']
        self.assertEqual(len(recent), 1)

        # Day wise attendance status check
        day_wise = data['day_wise_attendance']
        holiday_entries = [d for d in day_wise if d['status'] == 'holiday']
        self.assertEqual(len(holiday_entries), 1)
        self.assertTrue(holiday_entries[0]['is_holiday'])

        week_off_entries = [d for d in day_wise if d['status'] == 'week_of']
        self.assertEqual(len(week_off_entries), 1)
        self.assertTrue(week_off_entries[0]['is_week_off'])

        leave_entries = [d for d in day_wise if d['status'] == 'paid_leave']
        self.assertEqual(len(leave_entries), 1)
        self.assertTrue(leave_entries[0]['is_leave'])
        self.assertEqual(leave_entries[0]['leave_type'], 'paid_leave')

    @patch('auditlog.blob_service.download_log_file', return_value=None)
    @patch('auditlog.blob_service.upload_log_file', return_value=True)
    def test_employee_violations_excludes_holidays_and_weekoffs(self, m1, m2):
        """
        Verify that Employee Violations API does NOT treat Sunday (holiday),
        Saturday (week_of), public holidays, or leaves as violations.
        """
        # Create Sunday record as holiday
        EmployeeAttendanceRecord.objects.create(
            user=self.staff, branch=self.branch, date=self.sunday, status='holiday'
        )
        # Create Saturday record as week_of
        EmployeeAttendanceRecord.objects.create(
            user=self.staff, branch=self.branch, date=self.saturday_off, status='week_of'
        )
        # Create sick leave
        EmployeeAttendanceRecord.objects.create(
            user=self.staff, branch=self.branch, date=self.thursday, status='sick_leave'
        )
        # Create 1 real absent violation
        real_absent_date = datetime.date(2026, 10, 19)
        EmployeeAttendanceRecord.objects.create(
            user=self.staff, branch=self.branch, date=real_absent_date, status='absent'
        )

        self.client.force_authenticate(user=self.admin)
        url = reverse('employee-violations')
        response = self.client.get(f"{url}?user_id={self.staff.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        violations = response.data.get('results', response.data.get('data', []))
        if isinstance(violations, dict) and 'results' in violations:
            violations = violations['results']

        # There should only be 1 violation (the real absent date), NOT the holiday, week_of, or leave
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]['date'], real_absent_date.isoformat())
        self.assertEqual(violations[0]['violation_type'], 'no_show')

    def test_checkin_checkout_on_sunday_week_off_arrives_present(self):
        """
        If employee has week_off on Sunday and arrives, checks in, and checks out,
        their attendance entry must arrive as 'present' (not 'absent' and not shadowed
        by an unattended week_off record).
        """
        sunday_dt_checkin = timezone.make_aware(datetime.datetime.combine(self.sunday, datetime.time(9, 30)))
        sunday_dt_checkout = timezone.make_aware(datetime.datetime.combine(self.sunday, datetime.time(14, 0)))

        # Simulate placeholder unattended week_off record previously created for Sunday
        placeholder = EmployeeAttendanceRecord.objects.create(
            user=self.staff,
            branch=self.branch,
            date=self.sunday,
            status='week_off',
            checked_in_at=None,
            checked_out_at=None
        )

        self.client.force_authenticate(user=self.staff)
        url = reverse('employee-attendance-scan')

        # 1. Staff checks in on Sunday
        with patch('django.utils.timezone.now', return_value=sunday_dt_checkin):
            resp_in = self.client.post(url, {
                'scan_type': 'check_in',
                'latitude': 12.9716,
                'longitude': 77.5946,
            }, format='json')

        self.assertEqual(resp_in.status_code, status.HTTP_200_OK)
        # Old placeholder record must be removed and replaced by active session
        records_after_in = EmployeeAttendanceRecord.objects.filter(user=self.staff, date=self.sunday)
        self.assertEqual(records_after_in.count(), 1)
        self.assertEqual(records_after_in.first().status, 'checkout_pending')

        # 2. Staff checks out on Sunday (e.g. 4.5 hours worked - voluntarily on Sunday off-day)
        with patch('django.utils.timezone.now', return_value=sunday_dt_checkout):
            resp_out = self.client.post(url, {
                'scan_type': 'check_out',
                'latitude': 12.9716,
                'longitude': 77.5946,
            }, format='json')

        self.assertEqual(resp_out.status_code, status.HTTP_200_OK)

        # 3. Assert attendance record status is 'present'
        records_after_out = EmployeeAttendanceRecord.objects.filter(user=self.staff, date=self.sunday)
        self.assertEqual(records_after_out.count(), 1)
        rec = records_after_out.first()
        self.assertEqual(rec.status, 'present')
        self.assertEqual(rec.get_status_display(), 'Present')
        self.assertEqual(rec.shortfall_minutes, 0)

        # 4. In history API, verify it counts as present_days: 1, week_offs: 0, absent_days: 0, 100%
        history_url = reverse('employee-attendance-history')
        resp_hist = self.client.get(f"{history_url}?from_date={self.sunday.isoformat()}&to_date={self.sunday.isoformat()}")
        self.assertEqual(resp_hist.status_code, status.HTTP_200_OK)
        summary = resp_hist.data['summary']
        self.assertEqual(summary['total_days'], 1)
        self.assertEqual(summary['present_days'], 1)
        self.assertEqual(summary['absent_days'], 0)
        self.assertEqual(summary['week_offs'], 0)
        self.assertEqual(summary['attendance_percentage'], 100.0)
