import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'insight.settings'
django.setup()

from batches.models import TimetableSlot
from django.utils import timezone
from datetime import timedelta

local = timezone.localtime()
current_time = local.time()
buffered_time = (local + timedelta(minutes=15)).time()

print(f"Current Time: {current_time}")
print(f"Buffered Time (current + 15m): {buffered_time}")

# Simulate slot at 18:30
class MockSlot:
    start_time = timezone.datetime.strptime("18:30", "%H:%M").time()
    end_time = timezone.datetime.strptime("19:30", "%H:%M").time()

slot = MockSlot()
print(f"\nNext slot starts at: {slot.start_time}")
print(f"Is slot.start_time <= buffered_time? {slot.start_time <= buffered_time}")

if slot.start_time <= buffered_time:
    print("-> Slot MATCHES. User can check in.")
else:
    print("-> Slot DOES NOT MATCH. User is too early.")
    print("-> System will fall back to 'completed_today' check and show the confusing error message.")
