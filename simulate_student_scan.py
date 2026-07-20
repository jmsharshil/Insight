import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'insight.settings'
django.setup()

from attendance.models import AttendanceRecord
from batches.models import TimetableSlot
from students.models import Student
from django.utils import timezone
from datetime import timedelta

def simulate_scan():
    # Let's find a student who checked in today
    today = timezone.localtime().date()
    recent_records = AttendanceRecord.objects.filter(date=today, checked_out_at__isnull=False).order_by('-checked_out_at')
    
    if not recent_records.exists():
        print(f"No completed check-ins found for today ({today}).")
        
        # fallback: find any student with slots today
        dow = timezone.localtime().weekday()
        slots_today = TimetableSlot.objects.filter(day_of_week=dow).select_related('batch')
        if not slots_today:
            print("No slots scheduled for today.")
            return
            
        slot = slots_today.first()
        student = Student.objects.filter(batch=slot.batch).first()
        if not student:
            print("No student in that batch.")
            return
    else:
        student = recent_records.first().student

    print(f"Simulating for student: {student.first_name} (ID: {student.id})")
    
    local = timezone.localtime()
    current_time = local.time()
    current_dow = local.weekday()
    buffered_time = (local + timedelta(minutes=15)).time()
    
    print(f"Local time: {local}")
    print(f"Current DOW: {current_dow}")
    print(f"Buffered time: {buffered_time}")

    enrolled_batch_ids = []
    if getattr(student, 'batch_id', None):
        enrolled_batch_ids.append(student.batch_id)
        
    print(f"Enrolled batches: {enrolled_batch_ids}")

    all_slots = TimetableSlot.objects.filter(
        batch_id__in=enrolled_batch_ids,
        day_of_week=current_dow,
    ).order_by('start_time')
    
    print("\n--- ALL SLOTS FOR STUDENT TODAY ---")
    for s in all_slots:
        print(f"  Slot ID: {s.id} | {s.start_time} to {s.end_time}")
        
    matching_slots = TimetableSlot.objects.filter(
        batch_id__in=enrolled_batch_ids,
        day_of_week=current_dow,
        start_time__lte=buffered_time,
        end_time__gte=current_time
    ).order_by('start_time')
    
    print("\n--- MATCHING SLOTS WITHIN BUFFER ---")
    for s in matching_slots:
        print(f"  Slot ID: {s.id} | {s.start_time} to {s.end_time}")

    attended_slot_ids = set(
        AttendanceRecord.objects.filter(
            student=student, date=local.date(), timetable_slot__isnull=False
        ).values_list('timetable_slot_id', flat=True)
    )
    print(f"\nAttended Slot IDs today: {attended_slot_ids}")

    active_slot = None
    for slot in matching_slots:
        if slot.id not in attended_slot_ids:
            active_slot = slot
            print(f"  -> Picked active_slot: {slot.id} ({slot.start_time}-{slot.end_time})")
            break

    if not active_slot and matching_slots.exists():
        active_slot = matching_slots.last()
        print(f"  -> Fallback active_slot: {active_slot.id} ({active_slot.start_time}-{active_slot.end_time})")
        
    if not active_slot:
        print("\nRESULT: active_slot is NONE.")
    else:
        print(f"\nRESULT: active_slot found (ID: {active_slot.id})")
        
if __name__ == '__main__':
    simulate_scan()
