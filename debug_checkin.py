import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'insight.settings'
django.setup()

from attendance.models import AttendanceRecord
from students.models import Student
from batches.models import TimetableSlot, Batch
from django.utils import timezone
from datetime import timedelta, datetime

# Mock a check-in flow manually to see where it might fail
student = Student.objects.first()
if not student:
    print("No students found in DB.")
    import sys; sys.exit(0)

print(f"Testing check-in for student: {student}")
local = timezone.localtime()
current_time = local.time()
current_dow = local.weekday()

enrolled_batch_ids = [student.batch_id] if student.batch_id else []
print(f"Enrolled batches: {enrolled_batch_ids}")

all_today_slots = TimetableSlot.objects.filter(
    batch_id__in=enrolled_batch_ids,
    day_of_week=current_dow,
).order_by('start_time')
print(f"Total slots today: {all_today_slots.count()}")

attended_slot_ids = set(
    AttendanceRecord.objects.filter(
        student=student, date=local.date(), timetable_slot__isnull=False
    ).values_list('timetable_slot_id', flat=True)
)
print(f"Attended slot IDs: {attended_slot_ids}")

active_slot = None
for slot in all_today_slots:
    if slot.id not in attended_slot_ids and slot.end_time >= current_time:
        active_slot = slot
        break

if not active_slot and all_today_slots.exists():
    active_slot = all_today_slots.last()

print(f"Active slot resolved: {active_slot}")
if active_slot:
    print(f"  Slot Time: {active_slot.start_time} - {active_slot.end_time}")

now = timezone.now()
open_record = AttendanceRecord.objects.filter(
    student=student, date=now.date(), checked_in_at__isnull=False, checked_out_at__isnull=True
).order_by('-checked_in_at').first()
print(f"Open record: {open_record}")

completed_today = AttendanceRecord.objects.filter(
    student=student, batch_id=student.batch_id, date=now.date(),
    checked_in_at__isnull=False, checked_out_at__isnull=False
).exists()
print(f"Completed today: {completed_today}")

if open_record:
    print("BLOCKED: You are already checked in. Please check out first.")
elif active_slot:
    slot_record = AttendanceRecord.objects.filter(
        student=student, date=now.date(), timetable_slot=active_slot
    ).first()
    if slot_record:
        print("BLOCKED: You have already marked attendance for this slot today.")
    else:
        print("SUCCESS: Check in allowed for active_slot.")
else:
    if completed_today:
        print("BLOCKED: You have already completed attendance for this session today.")
    else:
        print("SUCCESS: Check in allowed (fallback, no slot).")
