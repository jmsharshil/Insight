"""Timetable utilisation report service."""
from django.db.models import Count, Q, F, Sum
from django.db.models.functions import Cast
from batches.models import TimetableSlot, Classroom, DAY_CHOICES


DAY_MAP = dict(DAY_CHOICES)
# Total possible slots per day per classroom (assume 8 slots max)
MAX_SLOTS_PER_DAY = 8
WORKING_DAYS = 6  # Mon-Sat


def get_timetable_report(user, params):
    role = getattr(user, 'role', None)

    # Classroom occupancy
    total_classrooms = Classroom.objects.filter(is_active=True).count() or 1
    total_possible = total_classrooms * WORKING_DAYS * MAX_SLOTS_PER_DAY
    total_used = TimetableSlot.objects.filter(classroom__isnull=False).count()
    occupancy_rate = round((total_used / total_possible) * 100, 2) if total_possible else 0

    # Faculty load
    faculty_load_qs = (
        TimetableSlot.objects.filter(faculty__isnull=False)
        .values('faculty_id', 'faculty__name')
        .annotate(total_slots=Count('id'))
        .order_by('-total_slots')
    )
    faculty_load = []
    for f in faculty_load_qs:
        # Estimate hours: each slot ~1 hour average
        slots = TimetableSlot.objects.filter(faculty_id=f['faculty_id'])
        total_mins = 0
        for s in slots.only('start_time', 'end_time'):
            from datetime import datetime, timedelta
            start_dt = datetime.combine(datetime.today(), s.start_time)
            end_dt = datetime.combine(datetime.today(), s.end_time)
            if end_dt < start_dt:
                end_dt += timedelta(days=1)
            total_mins += (end_dt - start_dt).total_seconds() / 60
        faculty_load.append({
            'faculty_id': f['faculty_id'],
            'faculty_name': f['faculty__name'] or '',
            'total_slots': f['total_slots'],
            'total_hours': round(total_mins / 60, 1),
        })

    # Free slot analysis per classroom per day
    free_slots = []
    classrooms = Classroom.objects.filter(is_active=True).values('id', 'name')
    for cr in classrooms:
        for day_num in range(WORKING_DAYS):
            used = TimetableSlot.objects.filter(
                classroom_id=cr['id'], day_of_week=day_num
            ).count()
            free = max(0, MAX_SLOTS_PER_DAY - used)
            if free > 0:
                free_slots.append({
                    'classroom_id': cr['id'],
                    'classroom_name': cr['name'],
                    'day_of_week': day_num,
                    'day_label': DAY_MAP.get(day_num, ''),
                    'free_slots': free,
                })

    return {
        'classroom_occupancy_rate': occupancy_rate,
        'faculty_load': faculty_load,
        'free_slot_analysis': free_slots,
    }
