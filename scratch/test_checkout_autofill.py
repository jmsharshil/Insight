import os, sys, django
sys.path.insert(0, r'c:\Users\Admin\OneDrive - JMS Advisory Services Private Limited\Desktop\Insight')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

import json
from datetime import datetime, timedelta, time
from django.utils import timezone
from django.db.models import Q
from faculty.models import FacultyProfile, SessionReport, FacultyQRScanLog
from batches.models import TimetableSlot, Chapter, BatchFaculty, Batch, Subject
from attendance.models import EmployeeAttendanceRecord

def parse_time_str(t):
    if not t:
        return None
    if isinstance(t, time):
        return t
    t_str = str(t).strip()
    for fmt in ('%H:%M:%S', '%H:%M'):
        try:
            return datetime.strptime(t_str, fmt).time()
        except ValueError:
            pass
    return None

def build_checkout_autofill_data(fp, request=None):
    local_now = timezone.localtime(timezone.now())
    today = local_now.date()
    dow = today.weekday()

    # 1. Attendance check
    open_record = EmployeeAttendanceRecord.objects.filter(
        user=fp.user, date=today, checked_in_at__isnull=False, checked_out_at__isnull=True
    ).order_by('-checked_in_at').first()

    latest_record = EmployeeAttendanceRecord.objects.filter(
        user=fp.user, date=today, checked_in_at__isnull=False
    ).order_by('-checked_in_at').first()

    checkin_log = FacultyQRScanLog.objects.filter(
        faculty=fp, scan_type='check_in', scanned_at__date=today
    ).order_by('-scanned_at').first()

    if open_record and open_record.checked_in_at:
        checkin_dt = timezone.localtime(open_record.checked_in_at)
        is_checked_in = True
        att_rec_id = str(open_record.id)
    elif checkin_log and checkin_log.scanned_at:
        checkin_dt = timezone.localtime(checkin_log.scanned_at)
        is_checked_in = True
        att_rec_id = None
    elif latest_record and latest_record.checked_in_at:
        checkin_dt = timezone.localtime(latest_record.checked_in_at)
        is_checked_in = False
        att_rec_id = str(latest_record.id)
    else:
        checkin_dt = None
        is_checked_in = False
        att_rec_id = None

    check_in_time_str = checkin_dt.strftime('%H:%M:%S') if checkin_dt else None
    check_in_short_str = checkin_dt.strftime('%H:%M') if checkin_dt else None
    check_out_time_str = local_now.strftime('%H:%M:%S')
    check_out_short_str = local_now.strftime('%H:%M')

    elapsed_minutes = 0
    if checkin_dt:
        elapsed_minutes = max(0, int((local_now - checkin_dt).total_seconds() / 60))

    # 2. Existing session reports today for this faculty
    existing_reports = list(SessionReport.objects.filter(
        faculty=fp, session_date=today
    ).select_related('batch', 'subject').prefetch_related('chapters'))

    used_report_ids = set()

    # 3. Timetable slots for today
    slots_qs = TimetableSlot.objects.filter(
        Q(day_of_week=dow) | Q(session_date=today),
        faculty=fp, batch__is_active=True
    ).filter(
        Q(effective_from__isnull=True) | Q(effective_from__lte=today)
    ).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=today)
    ).select_related('batch', 'subject', 'classroom').prefetch_related('chapters').order_by('start_time')

    slots = list(slots_qs)

    # 4. Process slots & match existing reports
    today_slots_data = []
    pending_slots = []

    for slot in slots:
        matched_sr = None
        if slot.start_time:
            slot_start_dt = datetime.combine(today, slot.start_time)
            for sr in existing_reports:
                if sr.id in used_report_ids:
                    continue
                if sr.batch_id == slot.batch_id and sr.subject_id == slot.subject_id:
                    sr_start_dt = datetime.combine(today, sr.start_time)
                    diff_mins = abs((sr_start_dt - slot_start_dt).total_seconds() / 60)
                    if diff_mins <= 45:
                        matched_sr = sr
                        used_report_ids.add(sr.id)
                        break

        slot_start_str = slot.start_time.strftime('%H:%M') if slot.start_time else ''
        slot_end_str = slot.end_time.strftime('%H:%M') if slot.end_time else ''
        sched_duration = 0
        if slot.start_time and slot.end_time:
            st_dt = datetime.combine(today, slot.start_time)
            et_dt = datetime.combine(today, slot.end_time)
            if et_dt < st_dt:
                et_dt += timedelta(days=1)
            sched_duration = int((et_dt - st_dt).total_seconds() / 60)

        slot_item = {
            'timetable_slot_id': str(slot.id),
            'slot_code': slot.slot_code or '',
            'session_type': slot.session_type,
            'session_name': slot.session_name or '',
            'batch_id': str(slot.batch.id) if slot.batch else None,
            'batch_name': slot.batch.name if slot.batch else '',
            'subject_id': str(slot.subject.id) if slot.subject else None,
            'subject_name': slot.subject.name if slot.subject else '',
            'classroom_id': str(slot.classroom.id) if slot.classroom else None,
            'classroom_name': getattr(slot.classroom, 'room_number', None) or getattr(slot.classroom, 'name', '') if slot.classroom else '',
            'scheduled_start_time': slot_start_str,
            'scheduled_end_time': slot_end_str,
            'duration_minutes': sched_duration,
            'already_submitted': matched_sr is not None,
            'existing_report_id': str(matched_sr.id) if matched_sr else None,
            'existing_report': {
                'id': str(matched_sr.id),
                'chapter_covered': matched_sr.chapter_covered,
                'topics_covered': matched_sr.topics_covered,
                'status': matched_sr.status,
                'completion_percentage': matched_sr.completion_percentage,
                'start_time': matched_sr.start_time.strftime('%H:%M') if matched_sr.start_time else '',
                'end_time': matched_sr.end_time.strftime('%H:%M') if matched_sr.end_time else '',
                'duration_minutes': matched_sr.duration_minutes,
            } if matched_sr else None
        }

        today_slots_data.append(slot_item)
        if not matched_sr:
            pending_slots.append((slot, slot_item))

    # 5. Determine active / current slot to autofill
    current_slot = None
    current_slot_item = None

    if pending_slots:
        # Match closest pending slot to checkin_dt or local_now
        ref_time = checkin_dt.time() if checkin_dt else local_now.time()
        ref_dt = datetime.combine(today, ref_time)
        best_diff = None
        for s, s_item in pending_slots:
            if s.start_time:
                s_dt = datetime.combine(today, s.start_time)
                diff = abs((s_dt - ref_dt).total_seconds())
                if best_diff is None or diff < best_diff:
                    best_diff = diff
                    current_slot = s
                    current_slot_item = s_item
        if not current_slot and pending_slots:
            current_slot, current_slot_item = pending_slots[0]
    elif slots:
        # All slots already submitted, use the last one
        current_slot = slots[-1]
        current_slot_item = today_slots_data[-1]

    # Helper to resolve chapters & suggested topics for a given batch & subject
    def get_chapters_and_suggestion(batch, subject, slot=None):
        if not subject:
            return [], [], [], "", ""

        chapters_qs = Chapter.objects.filter(subject=subject, is_active=True).order_by('order')
        all_chapters_data = [
            {'id': str(c.id), 'name': c.name, 'order': c.order, 'description': c.description or ''}
            for c in chapters_qs
        ]

        suggested_chapters = []
        if slot and slot.chapters.exists():
            suggested_chapters = list(slot.chapters.all())
        else:
            # Query last session report for this batch and subject
            prev_sr = SessionReport.objects.filter(
                batch=batch, subject=subject
            ).exclude(session_date=today, id__in=used_report_ids).order_by('-session_date', '-start_time').first()

            if prev_sr:
                if prev_sr.completion_percentage < 100:
                    suggested_chapters = list(prev_sr.chapters.all())
                else:
                    prev_last_ch = prev_sr.chapters.order_by('-order').first()
                    if prev_last_ch and prev_last_ch.order is not None:
                        next_ch = chapters_qs.filter(order__gt=prev_last_ch.order).order_by('order').first()
                        suggested_chapters = [next_ch] if next_ch else [prev_last_ch]
                    else:
                        first_ch = chapters_qs.first()
                        suggested_chapters = [first_ch] if first_ch else []
            else:
                first_ch = chapters_qs.first()
                suggested_chapters = [first_ch] if first_ch else []

        suggested_chapters = [c for c in suggested_chapters if c is not None]
        suggested_ids = [str(c.id) for c in suggested_chapters]
        suggested_names = [c.name for c in suggested_chapters]
        chapter_str = ", ".join(suggested_names)

        topics = ""
        if slot and slot.session_name:
            topics = slot.session_name
        elif suggested_names:
            topics = f"Covered {chapter_str}"

        return all_chapters_data, suggested_ids, suggested_names, chapter_str, topics

    # Build pre-filled session reports for all pending slots
    prefilled_reports = []
    for s, s_item in pending_slots:
        all_ch, ch_ids, ch_names, ch_str, topics = get_chapters_and_suggestion(s.batch, s.subject, slot=s)

        # Actual or scheduled start/end times
        # If this is the active current slot and checked in:
        is_cur = (current_slot and s.id == current_slot.id)
        st_time = s.start_time.strftime('%H:%M') if s.start_time else (check_in_short_str or '09:00')
        et_time = s.end_time.strftime('%H:%M') if s.end_time else (check_out_short_str or '10:00')
        
        dur_mins = s_item['duration_minutes']
        if is_cur and check_in_short_str and check_out_short_str:
            # can use scheduled duration or actual elapsed duration
            pass

        rep_dict = {
            'timetable_slot_id': str(s.id),
            'batch_id': str(s.batch.id) if s.batch else None,
            'batch_name': s.batch.name if s.batch else '',
            'subject_id': str(s.subject.id) if s.subject else None,
            'subject_name': s.subject.name if s.subject else '',
            'classroom_id': str(s.classroom.id) if s.classroom else None,
            'classroom_name': getattr(s.classroom, 'room_number', None) or getattr(s.classroom, 'name', '') if s.classroom else '',
            'session_type': s.session_type,
            'session_name': s.session_name or '',
            'slot_code': s.slot_code or '',
            'scheduled_start_time': s_item['scheduled_start_time'],
            'scheduled_end_time': s_item['scheduled_end_time'],
            'start_time': st_time,
            'end_time': et_time,
            'duration_minutes': dur_mins,
            'session_date': today.strftime('%Y-%m-%d'),
            'chapter_ids': ch_ids,
            'chapter_names': ch_names,
            'chapter_covered': ch_str,
            'topics_covered': topics,
            'completion_percentage': 100,
            'status': 'completed',
            'notes': '',
            'already_submitted': False,
            'is_current': is_cur,
            'available_chapters': all_ch
        }
        prefilled_reports.append(rep_dict)

    # 6. Build current_session object
    current_session = None
    if current_slot:
        # Check if already in prefilled_reports
        for pr in prefilled_reports:
            if pr['timetable_slot_id'] == str(current_slot.id):
                current_session = pr
                break
        if not current_session:
            all_ch, ch_ids, ch_names, ch_str, topics = get_chapters_and_suggestion(current_slot.batch, current_slot.subject, slot=current_slot)
            current_session = {
                'timetable_slot_id': str(current_slot.id),
                'batch_id': str(current_slot.batch.id) if current_slot.batch else None,
                'batch_name': current_slot.batch.name if current_slot.batch else '',
                'subject_id': str(current_slot.subject.id) if current_slot.subject else None,
                'subject_name': current_slot.subject.name if current_slot.subject else '',
                'classroom_id': str(current_slot.classroom.id) if current_slot.classroom else None,
                'classroom_name': getattr(current_slot.classroom, 'room_number', None) or getattr(current_slot.classroom, 'name', '') if current_slot.classroom else '',
                'session_type': current_slot.session_type,
                'session_name': current_slot.session_name or '',
                'slot_code': current_slot.slot_code or '',
                'scheduled_start_time': current_slot.start_time.strftime('%H:%M') if current_slot.start_time else '',
                'scheduled_end_time': current_slot.end_time.strftime('%H:%M') if current_slot.end_time else '',
                'start_time': current_slot.start_time.strftime('%H:%M') if current_slot.start_time else (check_in_short_str or '09:00'),
                'end_time': current_slot.end_time.strftime('%H:%M') if current_slot.end_time else (check_out_short_str or '10:00'),
                'duration_minutes': current_slot_item['duration_minutes'] if current_slot_item else 0,
                'session_date': today.strftime('%Y-%m-%d'),
                'chapter_ids': ch_ids,
                'chapter_names': ch_names,
                'chapter_covered': ch_str,
                'topics_covered': topics,
                'completion_percentage': 100,
                'status': 'completed',
                'notes': '',
                'already_submitted': current_slot_item['already_submitted'] if current_slot_item else False,
                'is_current': True,
                'available_chapters': all_ch
            }
    else:
        # Fallback: No slots today, check BatchFaculty
        bf = BatchFaculty.objects.filter(faculty=fp, batch__is_active=True).select_related('batch', 'subject').first()
        b = bf.batch if bf else None
        s = bf.subject if bf else None
        all_ch, ch_ids, ch_names, ch_str, topics = get_chapters_and_suggestion(b, s)

        st_time = check_in_short_str or '09:00'
        et_time = check_out_short_str or '10:00'
        dur_mins = elapsed_minutes if elapsed_minutes > 0 else 60

        current_session = {
            'timetable_slot_id': None,
            'batch_id': str(b.id) if b else None,
            'batch_name': b.name if b else '',
            'subject_id': str(s.id) if s else None,
            'subject_name': s.name if s else '',
            'classroom_id': None,
            'classroom_name': '',
            'session_type': 'regular',
            'session_name': '',
            'slot_code': '',
            'scheduled_start_time': None,
            'scheduled_end_time': None,
            'start_time': st_time,
            'end_time': et_time,
            'duration_minutes': dur_mins,
            'session_date': today.strftime('%Y-%m-%d'),
            'chapter_ids': ch_ids,
            'chapter_names': ch_names,
            'chapter_covered': ch_str,
            'topics_covered': topics,
            'completion_percentage': 100,
            'status': 'completed',
            'notes': '',
            'already_submitted': False,
            'is_current': True,
            'available_chapters': all_ch
        }
        if b and s:
            prefilled_reports.append(current_session)

    # 7. Build hierarchy of all assigned batches, subjects, and chapters for dropdown selection
    batches_dict = {}
    # First from today's slots
    for slot in slots:
        if not slot.batch:
            continue
        b_id = str(slot.batch.id)
        if b_id not in batches_dict:
            batches_dict[b_id] = {
                'id': b_id,
                'name': slot.batch.name,
                'subjects': []
            }
        if slot.subject:
            sub_id = str(slot.subject.id)
            if not any(sb['id'] == sub_id for sb in batches_dict[b_id]['subjects']):
                chs = Chapter.objects.filter(subject=slot.subject, is_active=True).order_by('order')
                batches_dict[b_id]['subjects'].append({
                    'id': sub_id,
                    'name': slot.subject.name,
                    'chapters': [{'id': str(c.id), 'name': c.name, 'order': c.order} for c in chs]
                })

    # Add any from BatchFaculty
    bf_qs = BatchFaculty.objects.filter(faculty=fp, batch__is_active=True).select_related('batch', 'subject')
    for bf in bf_qs:
        if not bf.batch:
            continue
        b_id = str(bf.batch.id)
        if b_id not in batches_dict:
            batches_dict[b_id] = {
                'id': b_id,
                'name': bf.batch.name,
                'subjects': []
            }
        if bf.subject:
            sub_id = str(bf.subject.id)
            if not any(sb['id'] == sub_id for sb in batches_dict[b_id]['subjects']):
                chs = Chapter.objects.filter(subject=bf.subject, is_active=True).order_by('order')
                batches_dict[b_id]['subjects'].append({
                    'id': sub_id,
                    'name': bf.subject.name,
                    'chapters': [{'id': str(c.id), 'name': c.name, 'order': c.order} for c in chs]
                })

    # Mark `is_current` on today_slots_data
    if current_slot:
        for s_item in today_slots_data:
            if s_item['timetable_slot_id'] == str(current_slot.id):
                s_item['is_current'] = True
            else:
                s_item['is_current'] = False

    return {
        # Top-level legacy keys
        'faculty_id': str(fp.id),
        'faculty_name': fp.user.name if fp.user else '',
        'employee_id': fp.employee_id,
        'branch_id': str(fp.branch_id) if fp.branch_id else None,
        'branch_name': fp.branch.name if fp.branch else '',
        'date': today.strftime('%d-%m-%Y'),
        'iso_date': today.strftime('%Y-%m-%d'),
        'start_time': check_in_short_str or (current_session['start_time'] if current_session else None),
        'end_time': check_out_short_str or (current_session['end_time'] if current_session else None),

        # Attendance details
        'attendance': {
            'is_checked_in': is_checked_in,
            'check_in_time': check_in_time_str,
            'check_out_time': check_out_time_str,
            'duration_minutes': elapsed_minutes,
            'attendance_record_id': att_rec_id,
        },

        # Current session to autofill
        'current_session': current_session,

        # All pending session reports for today
        'session_reports': prefilled_reports,

        # All scheduled slots for today with submission status
        'today_slots': today_slots_data,

        # Full hierarchy for dropdown selections
        'batches': list(batches_dict.values()),
        'has_pending_reports': len(prefilled_reports) > 0
    }

fp = FacultyProfile.objects.filter(employee_id='EMP-7E78-0002').first()
res = build_checkout_autofill_data(fp)
print(json.dumps(res, indent=2))
