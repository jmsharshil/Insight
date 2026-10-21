from datetime import datetime, time, timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase

from attendance.utils import get_attendance_buffer_minutes, get_attendance_entry_status


class AttendancePolicyTests(SimpleTestCase):
    def test_first_class_of_day_gets_15_min_buffer(self):
        slot = SimpleNamespace(start_time=time(9, 0), end_time=time(10, 0))
        today = datetime.now().date()
        scan_time = datetime.combine(today, time(9, 12))

        self.assertEqual(get_attendance_buffer_minutes(slot, scan_time, is_first_class_of_day=True), 15)

    def test_other_classes_get_5_min_buffer(self):
        slot = SimpleNamespace(start_time=time(9, 0), end_time=time(10, 0))
        today = datetime.now().date()
        scan_time = datetime.combine(today, time(9, 4))

        self.assertEqual(get_attendance_buffer_minutes(slot, scan_time, is_first_class_of_day=False), 5)

    def test_late_entry_is_detected_when_past_buffer(self):
        slot = SimpleNamespace(start_time=time(9, 0), end_time=time(10, 0))
        today = datetime.now().date()
        scan_time = datetime.combine(today, time(9, 20))

        status = get_attendance_entry_status(slot, scan_time, is_first_class_of_day=False)

        self.assertEqual(status, 'late_entry')

    def test_checkout_less_than_5_hours_marked_absent(self):
        from decimal import Decimal
        from unittest.mock import MagicMock
        from attendance.utils import apply_half_day_rule

        user = SimpleNamespace(
            working_hours=Decimal('9.00'),
            get_working_hours_for_date=lambda dt: Decimal('9.00'),
        )
        record = MagicMock()
        record.date = datetime(2026, 10, 19).date()
        record.checked_in_at = datetime(2026, 10, 19, 10, 0, 0)
        record.checked_out_at = datetime(2026, 10, 19, 13, 30, 0)  # 3.5 hours worked (< 5)
        record.status = 'present'
        record.timetable_slot = None

        msg = apply_half_day_rule(record, user)

        self.assertEqual(record.status, 'absent')
        self.assertIn("less than 5 hours", msg)
        self.assertIn("considered as absent", msg)
        record.save.assert_called_once_with(update_fields=['status'])

    def test_checkout_between_5_hours_and_required_marked_half_day(self):
        from decimal import Decimal
        from unittest.mock import MagicMock
        from attendance.utils import apply_half_day_rule

        user = SimpleNamespace(
            working_hours=Decimal('9.00'),
            get_working_hours_for_date=lambda dt: Decimal('9.00'),
        )
        record = MagicMock()
        record.date = datetime(2026, 10, 19).date()
        record.checked_in_at = datetime(2026, 10, 19, 10, 0, 0)
        record.checked_out_at = datetime(2026, 10, 19, 16, 0, 0)  # 6.0 hours worked (>= 5, but shortfall = 3 >= 1)
        record.status = 'present'
        record.timetable_slot = None

        msg = apply_half_day_rule(record, user)

        self.assertEqual(record.status, 'half_day')
        self.assertIn("considered as a half day", msg)
        record.save.assert_called_once_with(update_fields=['status'])

    def test_checkout_full_working_hours_remains_present(self):
        from decimal import Decimal
        from unittest.mock import MagicMock
        from attendance.utils import apply_half_day_rule

        user = SimpleNamespace(
            working_hours=Decimal('9.00'),
            get_working_hours_for_date=lambda dt: Decimal('9.00'),
        )
        record = MagicMock()
        record.date = datetime(2026, 10, 19).date()
        record.checked_in_at = datetime(2026, 10, 19, 10, 0, 0)
        record.checked_out_at = datetime(2026, 10, 19, 18, 30, 0)  # 8.5 hours worked (shortfall = 0.5 < 1)
        record.status = 'present'
        record.timetable_slot = None

        msg = apply_half_day_rule(record, user)

        self.assertEqual(record.status, 'present')
        self.assertEqual(msg, '')
        record.save.assert_not_called()

    def test_half_day_leave_afternoon_session_less_than_5_hours_marked_absent(self):
        from decimal import Decimal
        from unittest.mock import MagicMock
        from attendance.utils import apply_half_day_rule

        mock_leave = SimpleNamespace(
            half_day_session='afternoon',
            get_half_day_session_display=lambda: 'Afternoon',
        )
        user = SimpleNamespace(
            working_hours=Decimal('9.00'),
            get_working_hours_for_date=lambda dt: Decimal('9.00'),
            active_half_day_leave=mock_leave,
        )
        record = MagicMock()
        record.date = datetime(2026, 10, 21).date()
        record.checked_in_at = datetime(2026, 10, 21, 9, 0, 0)
        record.checked_out_at = datetime(2026, 10, 21, 13, 30, 0)  # 4.5 hours worked (< 5)
        record.status = 'present'
        record.timetable_slot = None

        msg = apply_half_day_rule(record, user)

        self.assertEqual(record.status, 'absent')
        self.assertIn("applied for half day leave (Afternoon session)", msg)
        self.assertIn("less than 5 hours", msg)
        self.assertIn("considered as absent", msg)
        record.save.assert_called_once_with(update_fields=['status'])

    def test_half_day_leave_morning_session_less_than_5_hours_marked_absent(self):
        from decimal import Decimal
        from unittest.mock import MagicMock
        from attendance.utils import apply_half_day_rule

        mock_leave = SimpleNamespace(
            half_day_session='morning',
            get_half_day_session_display=lambda: 'Morning',
        )
        user = SimpleNamespace(
            working_hours=Decimal('9.00'),
            get_working_hours_for_date=lambda dt: Decimal('9.00'),
            active_half_day_leave=mock_leave,
        )
        record = MagicMock()
        record.date = datetime(2026, 10, 21).date()
        record.checked_in_at = datetime(2026, 10, 21, 14, 0, 0)
        record.checked_out_at = datetime(2026, 10, 21, 17, 30, 0)  # 3.5 hours worked (< 5)
        record.status = 'present'
        record.timetable_slot = None

        msg = apply_half_day_rule(record, user)

        self.assertEqual(record.status, 'absent')
        self.assertIn("applied for half day leave (Morning session)", msg)
        self.assertIn("less than 5 hours", msg)
        self.assertIn("considered as absent", msg)
        record.save.assert_called_once_with(update_fields=['status'])

    def test_half_day_leave_afternoon_session_5_hours_marked_half_day(self):
        from decimal import Decimal
        from unittest.mock import MagicMock
        from attendance.utils import apply_half_day_rule

        mock_leave = SimpleNamespace(
            half_day_session='afternoon',
            get_half_day_session_display=lambda: 'Afternoon',
        )
        user = SimpleNamespace(
            working_hours=Decimal('9.00'),
            get_working_hours_for_date=lambda dt: Decimal('9.00'),
            active_half_day_leave=mock_leave,
        )
        record = MagicMock()
        record.date = datetime(2026, 10, 21).date()
        record.checked_in_at = datetime(2026, 10, 21, 9, 0, 0)
        record.checked_out_at = datetime(2026, 10, 21, 14, 0, 0)  # 5.0 hours worked (>= 5)
        record.status = 'present'
        record.timetable_slot = None

        msg = apply_half_day_rule(record, user)

        self.assertEqual(record.status, 'half_day')
        self.assertIn("with half day leave (Afternoon session)", msg)
        self.assertIn("considered as a half day", msg)
        record.save.assert_called_once_with(update_fields=['status'])

    def test_half_day_leave_morning_session_6_hours_marked_half_day(self):
        from decimal import Decimal
        from unittest.mock import MagicMock
        from attendance.utils import apply_half_day_rule

        mock_leave = SimpleNamespace(
            half_day_session='morning',
            get_half_day_session_display=lambda: 'Morning',
        )
        user = SimpleNamespace(
            working_hours=Decimal('9.00'),
            get_working_hours_for_date=lambda dt: Decimal('9.00'),
            active_half_day_leave=mock_leave,
        )
        record = MagicMock()
        record.date = datetime(2026, 10, 21).date()
        record.checked_in_at = datetime(2026, 10, 21, 13, 0, 0)
        record.checked_out_at = datetime(2026, 10, 21, 19, 0, 0)  # 6.0 hours worked (>= 5)
        record.status = 'present'
        record.timetable_slot = None

        msg = apply_half_day_rule(record, user)

        self.assertEqual(record.status, 'half_day')
        self.assertIn("with half day leave (Morning session)", msg)
        self.assertIn("considered as a half day", msg)
        record.save.assert_called_once_with(update_fields=['status'])

    def test_get_required_shift_minutes_with_half_day_leave(self):
        from unittest.mock import patch, MagicMock
        from attendance.views import _get_required_shift_minutes

        user = MagicMock()
        user.id = 'some-uuid'
        target_date = datetime(2026, 10, 21).date()

        with patch('leave.models.LeaveApplication.objects.filter') as mock_filter:
            mock_filter.return_value.exists.return_value = True
            mins = _get_required_shift_minutes(user, target_date)
            self.assertEqual(mins, 300)  # 5 hours = 300 minutes

    def test_get_required_shift_minutes_without_half_day_leave(self):
        from unittest.mock import patch, MagicMock
        from decimal import Decimal
        from attendance.views import _get_required_shift_minutes

        user = MagicMock()
        user.id = 'some-uuid'
        user.get_working_hours_for_date.return_value = Decimal('9.00')
        target_date = datetime(2026, 10, 21).date()

        with patch('leave.models.LeaveApplication.objects.filter') as mock_filter:
            mock_filter.return_value.exists.return_value = False
            mins = _get_required_shift_minutes(user, target_date)
            self.assertEqual(mins, 540)  # 9 hours = 540 minutes



