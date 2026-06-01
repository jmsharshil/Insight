from .models import TimetableSlot


def check_faculty_clash(faculty_id, day_of_week, start_time, end_time, exclude_id=None):
    """
    Returns list of conflicting TimetableSlot IDs if the faculty
    already has an overlapping slot on the same day.
    """
    qs = TimetableSlot.objects.filter(
        faculty_id=faculty_id,
        day_of_week=day_of_week,
        start_time__lt=end_time,
        end_time__gt=start_time,
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return list(qs.values_list('id', flat=True))


def check_classroom_clash(classroom_id, day_of_week, start_time, end_time, exclude_id=None):
    """
    Returns list of conflicting TimetableSlot IDs if the classroom
    already has an overlapping slot on the same day.
    """
    if not classroom_id:
        return []
    qs = TimetableSlot.objects.filter(
        classroom_id=classroom_id,
        day_of_week=day_of_week,
        start_time__lt=end_time,
        end_time__gt=start_time,
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return list(qs.values_list('id', flat=True))
