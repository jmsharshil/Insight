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
