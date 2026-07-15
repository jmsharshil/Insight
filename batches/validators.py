from .models import TimetableSlot


def _format_time(t):
    """Return 'HH:MM' from a time object."""
    if t is None:
        return ''
    return t.strftime('%H:%M')


def _slot_conflict_detail(slot):
    """Build a rich dict describing a conflicting TimetableSlot."""
    day_label = dict(TimetableSlot._meta.get_field('day_of_week').choices or []).get(
        slot.day_of_week, str(slot.day_of_week)
    ) if slot.day_of_week is not None else None

    batch_name = slot.batch.name if slot.batch_id else None
    faculty_name = (
        slot.faculty.user.name
        if slot.faculty_id and hasattr(slot, 'faculty') and slot.faculty and slot.faculty.user
        else None
    )
    classroom_name = slot.classroom.name if slot.classroom_id and slot.classroom else None

    return {
        'id': str(slot.id),
        'batch': str(slot.batch_id) if slot.batch_id else None,
        'batch_name': batch_name,
        'faculty': str(slot.faculty_id) if slot.faculty_id else None,
        'faculty_name': faculty_name,
        'classroom': str(slot.classroom_id) if slot.classroom_id else None,
        'classroom_name': classroom_name,
        'day_of_week': slot.day_of_week,
        'day_label': day_label,
        'session_date': str(slot.session_date) if slot.session_date else None,
        'start_time': _format_time(slot.start_time),
        'end_time': _format_time(slot.end_time),
        'slot_code': slot.slot_code,
        'session_type': slot.session_type,
        'session_name': slot.session_name,
    }


def check_faculty_clash(faculty_id, day_of_week, start_time, end_time, exclude_id=None):
    """
    Returns list of rich conflict dicts if the faculty already has an
    overlapping slot on the same day.
    """
    qs = TimetableSlot.objects.select_related(
        'batch', 'faculty__user', 'classroom'
    ).filter(
        faculty_id=faculty_id,
        day_of_week=day_of_week,
        start_time__lt=end_time,
        end_time__gt=start_time,
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return [_slot_conflict_detail(s) for s in qs]


def check_classroom_clash(classroom_id, day_of_week, start_time, end_time, exclude_id=None):
    """
    Returns list of rich conflict dicts if the classroom already has an
    overlapping slot on the same day.
    """
    if not classroom_id:
        return []
    qs = TimetableSlot.objects.select_related(
        'batch', 'faculty__user', 'classroom'
    ).filter(
        classroom_id=classroom_id,
        day_of_week=day_of_week,
        start_time__lt=end_time,
        end_time__gt=start_time,
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return [_slot_conflict_detail(s) for s in qs]


def check_batch_clash(batch_id, day_of_week, start_time, end_time, exclude_id=None):
    """
    Returns list of rich conflict dicts if the batch already has an
    overlapping slot on the same day/time.
    """
    if not batch_id:
        return []
    qs = TimetableSlot.objects.select_related(
        'batch', 'faculty__user', 'classroom'
    ).filter(
        batch_id=batch_id,
        day_of_week=day_of_week,
        start_time__lt=end_time,
        end_time__gt=start_time,
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return [_slot_conflict_detail(s) for s in qs]
