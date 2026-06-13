import csv
import logging
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Count, Q, Avg
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from core.pagination import paginate_queryset
from .models import AttendanceRecord, ViolationRecord, QRScanLog
from .serializers import ViolationRecordSerializer, ViolationCreateSerializer, ViolationResolveSerializer
from .utils import get_batch_attendance_sheet, get_active_violations_count, should_block_qr

from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


class SafeAPIView(APIView):
    def handle_exception(self, exc):
        response = None
        if isinstance(exc, ValidationError):
            msg = exc.message_dict if hasattr(exc, 'message_dict') else (exc.messages if hasattr(exc, 'messages') else str(exc))
            if isinstance(msg, list) and len(msg) == 1:
                msg = msg[0]
            response = Response({
                'success': False,
                'message': 'Validation error.',
                'errors': msg
            }, status=status.HTTP_400_BAD_REQUEST)
        elif isinstance(exc, ValueError):
            response = Response({
                'success': False,
                'message': 'Invalid parameter value.',
                'errors': str(exc)
            }, status=status.HTTP_400_BAD_REQUEST)
        else:
            response = super().handle_exception(exc)

        # Explicitly negotiate and assign renderer to prevent AssertionError
        if response and isinstance(response, Response):
            if not getattr(response, 'accepted_renderer', None):
                try:
                    renderers = self.get_renderers()
                    response.accepted_renderer = renderers[0]
                    response.accepted_media_type = renderers[0].media_type
                    response.renderer_context = self.get_renderer_context()
                except Exception:
                    pass

        return response


# ═══════════════════════════════════════════════════════════════════════════════
# 1. GET /api/attendance/dashboard/
# ═══════════════════════════════════════════════════════════════════════════════

class DashboardSummaryAPIView(SafeAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        role = getattr(user, 'role', None)

        if role in ['student', 'parents']:
            return Response({'success': False, 'message': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

        # Filters
        date_str = request.GET.get('date')
        if date_str:
            try:
                target_date = timezone.datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return Response({'success': False, 'message': 'Invalid date format. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            target_date = timezone.now().date()

        branch_id = request.GET.get('branch')
        batch_id = request.GET.get('batch')
        faculty_id = request.GET.get('faculty')

        # Base querysets
        from students.models import Student
        from faculty.models import FacultyProfile, FacultyQRScanLog
        from branch.models import Branch

        student_qs = Student.objects.filter(is_active=True)
        record_qs = AttendanceRecord.objects.filter(date=target_date)
        violation_qs = ViolationRecord.objects.filter(is_resolved=False)

        # Scoping by organization
        if getattr(user, 'organization', None):
            student_qs = student_qs.filter(branch__organization=user.organization)
            record_qs = record_qs.filter(branch__organization=user.organization)
            violation_qs = violation_qs.filter(student__branch__organization=user.organization)

        # Scoping by role (Faculty is restricted to their assigned batches)
        if role == 'faculty':
            batch_ids = list(user.faculty_profile.batch_assignments.values_list('batch_id', flat=True)) if hasattr(user, 'faculty_profile') else []
            student_qs = student_qs.filter(batch_id__in=batch_ids)
            record_qs = record_qs.filter(batch_id__in=batch_ids)
            violation_qs = violation_qs.filter(student__batch_id__in=batch_ids)

        # Branch filter
        if branch_id:
            student_qs = student_qs.filter(branch_id=branch_id)
            record_qs = record_qs.filter(branch_id=branch_id)
            violation_qs = violation_qs.filter(student__branch_id=branch_id)

        # Batch filter
        if batch_id:
            student_qs = student_qs.filter(batch_id=batch_id)
            record_qs = record_qs.filter(batch_id=batch_id)
            violation_qs = violation_qs.filter(student__batch_id=batch_id)

        # Faculty filter
        if faculty_id:
            faculty_batches = list(FacultyProfile.objects.filter(id=faculty_id).values_list('batch_assignments__batch_id', flat=True))
            student_qs = student_qs.filter(batch_id__in=faculty_batches)
            record_qs = record_qs.filter(batch_id__in=faculty_batches)
            violation_qs = violation_qs.filter(student__batch_id__in=faculty_batches)

        # Counts
        total_students = student_qs.count()
        present_today = record_qs.filter(status__in=['present', 'late', 'half_day']).count()
        absent_today = record_qs.filter(status='absent').count()
        late_today = record_qs.filter(status='late').count()
        active_violations = violation_qs.count()

        total_marked = present_today + absent_today
        attendance_percentage = round((present_today / total_marked) * 100, 2) if total_marked > 0 else 0.0

        # Faculty attendance summary
        faculty_qs = FacultyProfile.objects.all()
        if getattr(user, 'organization', None):
            faculty_qs = faculty_qs.filter(branch__organization=user.organization)
        if branch_id:
            faculty_qs = faculty_qs.filter(branch_id=branch_id)

        total_faculty = faculty_qs.count()
        faculty_present_ids = FacultyQRScanLog.objects.filter(
            scanned_at__date=target_date,
            scan_type='check_in'
        ).values_list('faculty_id', flat=True).distinct()
        
        faculty_present = faculty_qs.filter(id__in=faculty_present_ids).count()
        faculty_absent = total_faculty - faculty_present

        # Branch-wise attendance
        branch_wise = []
        branches = Branch.objects.all()
        if getattr(user, 'organization', None):
            branches = branches.filter(organization=user.organization)
        if branch_id:
            branches = branches.filter(id=branch_id)

        for b in branches:
            b_records = AttendanceRecord.objects.filter(date=target_date, branch=b)
            b_present = b_records.filter(status__in=['present', 'late', 'half_day']).count()
            b_total = b_records.exclude(status='on_leave').count()
            b_pct = round((b_present / b_total) * 100, 2) if b_total > 0 else 0.0
            branch_wise.append({
                'branch_id': str(b.id),
                'branch_name': b.name,
                'percentage': b_pct
            })

        return Response({
            'success': True,
            'data': {
                'total_students': total_students,
                'present_today': present_today,
                'absent_today': absent_today,
                'late_today': late_today,
                'attendance_percentage': attendance_percentage,
                'active_violations': active_violations,
                'faculty_attendance_summary': {
                    'total_faculty': total_faculty,
                    'present': faculty_present,
                    'absent': faculty_absent
                },
                'branch_wise_attendance': branch_wise
            }
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 2. GET /api/attendance/students/
# ═══════════════════════════════════════════════════════════════════════════════

class StudentAttendanceListAPIView(SafeAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        role = getattr(user, 'role', None)

        from students.models import Student
        student_qs = Student.objects.filter(is_active=True).select_related('user', 'branch', 'batch')

        if getattr(user, 'organization', None):
            student_qs = student_qs.filter(branch__organization=user.organization)

        if role == 'student':
            student_qs = student_qs.filter(user=user)
        elif role == 'parents':
            if user.linked_student:
                student_qs = student_qs.filter(user=user.linked_student)
            else:
                student_qs = student_qs.none()
        elif role == 'faculty':
            batch_ids = list(user.faculty_profile.batch_assignments.values_list('batch_id', flat=True)) if hasattr(user, 'faculty_profile') else []
            student_qs = student_qs.filter(batch_id__in=batch_ids)

        # Filters
        student_id = request.GET.get('student_id')
        enrollment_no = request.GET.get('enrollment_no')
        branch_id = request.GET.get('branch_id')
        batch_id = request.GET.get('batch_id')
        course_id = request.GET.get('course_id')
        status_filter = request.GET.get('status')
        search_query = request.GET.get('search')

        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')

        if student_id and role not in ['student', 'parents']:
            student_qs = student_qs.filter(id=student_id)
        if enrollment_no:
            student_qs = student_qs.filter(admission_number=enrollment_no)
        if branch_id:
            student_qs = student_qs.filter(branch_id=branch_id)
        if batch_id:
            student_qs = student_qs.filter(batch_id=batch_id)
        if course_id:
            student_qs = student_qs.filter(batch__course_id=course_id)
        if status_filter:
            val = status_filter.lower() in ['true', 'active']
            student_qs = student_qs.filter(is_active=val)
        if search_query:
            student_qs = student_qs.filter(
                Q(first_name__icontains=search_query) |
                Q(surname__icontains=search_query) |
                Q(roll_number__icontains=search_query) |
                Q(admission_number__icontains=search_query)
            )

        date_from_parsed = None
        date_to_parsed = None
        if date_from:
            try:
                date_from_parsed = timezone.datetime.strptime(date_from, '%Y-%m-%d').date()
            except ValueError:
                pass
        if date_to:
            try:
                date_to_parsed = timezone.datetime.strptime(date_to, '%Y-%m-%d').date()
            except ValueError:
                pass

        students_list = []
        for s in student_qs:
            records = AttendanceRecord.objects.filter(student=s)
            if date_from_parsed:
                records = records.filter(date__gte=date_from_parsed)
            if date_to_parsed:
                records = records.filter(date__lte=date_to_parsed)

            total_days = records.exclude(status='on_leave').count()
            present_count = records.filter(status__in=['present', 'late', 'half_day']).count()
            absent_count = records.filter(status='absent').count()
            late_count = records.filter(status='late').count()
            pct = round((present_count / total_days) * 100, 2) if total_days > 0 else 0.0

            # Filter by percentage range
            pct_min = request.GET.get('attendance_percentage_min')
            pct_max = request.GET.get('attendance_percentage_max')
            if pct_min and pct < float(pct_min):
                continue
            if pct_max and pct > float(pct_max):
                continue

            # Filter by late entries
            filter_late = request.GET.get('late_entries')
            if filter_late == 'true' and late_count == 0:
                continue

            # Filter by active violations
            filter_violations = request.GET.get('active_violations')
            active_viol_count = ViolationRecord.objects.filter(student=s, is_resolved=False).count()
            if filter_violations == 'true' and active_viol_count == 0:
                continue

            last_rec = AttendanceRecord.objects.filter(student=s).order_by('-date').first()

            students_list.append({
                'id': str(s.id),
                'student_profile': {
                    'id': str(s.id),
                    'name': f"{s.first_name} {s.surname}",
                    'roll_number': s.roll_number,
                    'admission_number': s.admission_number,
                    'photo': s.photo.url if s.photo else None,
                    'branch_name': s.branch.name if s.branch else None,
                    'batch_name': s.batch.name if s.batch else None,
                },
                'attendance_percentage': pct,
                'present_count': present_count,
                'absent_count': absent_count,
                'late_count': late_count,
                'last_attendance_date': last_rec.date if last_rec else None,
            })

        # Manual pagination
        page = request.GET.get('page', 1)
        page_size = request.GET.get('page_size', 50)
        try:
            page = int(page)
            page_size = int(page_size)
        except ValueError:
            page = 1
            page_size = 50

        total_count = len(students_list)
        start = (page - 1) * page_size
        end = start + page_size
        paginated_data = students_list[start:end]

        return Response({
            'success': True,
            'count': total_count,
            'page_size': page_size,
            'data': paginated_data
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 3. GET /api/attendance/students/{student_id}/
# ═══════════════════════════════════════════════════════════════════════════════

class StudentAttendanceDetailAPIView(SafeAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        user = request.user
        role = getattr(user, 'role', None)

        from students.models import Student
        from batches.models import TimetableSlot

        try:
            s = Student.objects.get(id=student_id)
        except Student.DoesNotExist:
            return Response({'success': False, 'message': 'Student not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Scoping check
        if role == 'student':
            student_profile = Student.objects.filter(user=user).first()
            if not student_profile or student_profile.id != s.id:
                return Response({'success': False, 'message': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)
        elif role == 'parents':
            if not user.linked_student or Student.objects.filter(user=user.linked_student).first().id != s.id:
                return Response({'success': False, 'message': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)
        elif role == 'faculty':
            batch_ids = list(user.faculty_profile.batch_assignments.values_list('batch_id', flat=True)) if hasattr(user, 'faculty_profile') else []
            if s.batch_id not in batch_ids:
                return Response({'success': False, 'message': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

        if getattr(user, 'organization', None) and s.branch and s.branch.organization != user.organization:
            return Response({'success': False, 'message': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

        # Attendance data
        records = AttendanceRecord.objects.filter(student=s)
        
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        date_filter = request.GET.get('date')
        status_filter = request.GET.get('status')
        
        if start_date:
            records = records.filter(date__gte=start_date)
        if end_date:
            records = records.filter(date__lte=end_date)
        if date_filter:
            records = records.filter(date=date_filter)
        if status_filter:
            records = records.filter(status=status_filter)

        total_days = records.exclude(status='on_leave').count()
        present_count = records.filter(status__in=['present', 'late', 'half_day']).count()
        absent_count = records.filter(status='absent').count()
        late_count = records.filter(status='late').count()
        pct = round((present_count / total_days) * 100, 2) if total_days > 0 else 0.0

        # Check-in and check-out logs
        check_in_history = []
        check_out_history = []
        day_wise_attendance = []
        for r in records.order_by('-date'):
            day_wise_attendance.append({
                'date': r.date,
                'status': r.status
            })
            if r.checked_in_at:
                check_in_history.append({
                    'date': r.date,
                    'time': r.checked_in_at,
                    'status': r.status
                })
            if r.checked_out_at:
                check_out_history.append({
                    'date': r.date,
                    'time': r.checked_out_at
                })

        # Violations
        violations = ViolationRecord.objects.filter(student=s).order_by('-date')
        if start_date:
            violations = violations.filter(date__gte=start_date)
        if end_date:
            violations = violations.filter(date__lte=end_date)
        if date_filter:
            violations = violations.filter(date=date_filter)
        violations_data = [{
            'id': str(v.id),
            'violation_type': v.violation_type,
            'date': v.date,
            'description': v.description,
            'is_resolved': v.is_resolved,
            'created_at': v.created_at,
            'resolution_details': {
                'resolved_by': v.resolved_by.name if v.resolved_by else None,
                'resolved_at': v.resolved_at
            } if v.is_resolved else None
        } for v in violations]

        # Monthly trends
        monthly_trend = []
        today = timezone.now().date()
        for i in range(5, -1, -1):
            m = today.month - i
            y = today.year
            if m <= 0:
                m += 12
                y -= 1
            month_str = f"{y}-{m:02d}"
            
            m_records = AttendanceRecord.objects.filter(student=s, date__year=y, date__month=m).exclude(status='on_leave')
            m_total = m_records.count()
            m_present = m_records.filter(status__in=['present', 'late', 'half_day']).count()
            m_pct = round((m_present / m_total) * 100, 2) if m_total > 0 else 0.0

            monthly_trend.append({
                'month': month_str,
                'percentage': m_pct
            })

        # Subject-wise & Session-wise attendance
        subject_stats = {}
        session_stats = {}
        
        if s.batch:
            slots = list(TimetableSlot.objects.filter(batch=s.batch).select_related('subject'))
            
            for r in records.exclude(status='on_leave'):
                day_slots = []
                for slot in slots:
                    if slot.is_recurring:
                        if slot.day_of_week == r.date.weekday():
                            if (not slot.effective_from or slot.effective_from <= r.date) and \
                               (not slot.effective_to or slot.effective_to >= r.date):
                                day_slots.append(slot)
                    else:
                        if slot.session_date == r.date:
                            day_slots.append(slot)
                            
                is_present = r.status in ['present', 'late', 'half_day']
                
                # If no scheduled slots are found for that day, we still want to count the day's record
                if not day_slots:
                    subj_id = "general"
                    subj_name = "General / Other"
                    if subj_id not in subject_stats:
                        subject_stats[subj_id] = {'subject_id': subj_id, 'subject_name': subj_name, 'total': 0, 'present': 0}
                    subject_stats[subj_id]['total'] += 1
                    if is_present:
                        subject_stats[subj_id]['present'] += 1
                        
                    sess = "General"
                    if sess not in session_stats:
                        session_stats[sess] = {'total': 0, 'present': 0}
                    session_stats[sess]['total'] += 1
                    if is_present:
                        session_stats[sess]['present'] += 1
                else:
                    for slot in day_slots:
                        subj = slot.subject
                        subj_id = str(subj.id) if subj else "general"
                        subj_name = subj.name if subj else "General / Other"
                        
                        if subj_id not in subject_stats:
                            subject_stats[subj_id] = {
                                'subject_id': subj_id,
                                'subject_name': subj_name,
                                'total': 0,
                                'present': 0
                            }
                        subject_stats[subj_id]['total'] += 1
                        if is_present:
                            subject_stats[subj_id]['present'] += 1
                            
                        sess = slot.slot_code or "General"
                        if sess not in session_stats:
                            session_stats[sess] = {
                                'total': 0,
                                'present': 0
                            }
                        session_stats[sess]['total'] += 1
                        if is_present:
                            session_stats[sess]['present'] += 1

        subject_wise = []
        for sid, stats in subject_stats.items():
            subject_wise.append({
                'subject_id': stats['subject_id'],
                'subject_name': stats['subject_name'],
                'percentage': round((stats['present'] / stats['total']) * 100, 2) if stats['total'] > 0 else 0.0
            })

        session_wise = []
        for sess, stats in session_stats.items():
            session_wise.append({
                'session': sess,
                'percentage': round((stats['present'] / stats['total']) * 100, 2) if stats['total'] > 0 else 0.0
            })

        return Response({
            'success': True,
            'data': {
                'student_profile': {
                    'id': str(s.id),
                    'name': f"{s.first_name} {s.surname}",
                    'roll_number': s.roll_number,
                    'admission_number': s.admission_number,
                    'branch_name': s.branch.name if s.branch else None,
                    'batch_name': s.batch.name if s.batch else None,
                },
                'attendance_percentage': pct,
                'summary': {
                    'present_count': present_count,
                    'absent_count': absent_count,
                    'late_count': late_count,
                },
                'day_wise_attendance': day_wise_attendance,
                'check_in_history': check_in_history,
                'check_out_history': check_out_history,
                'violations': violations_data,
                'monthly_trend': monthly_trend,
                'subject_wise_attendance': subject_wise,
                'session_wise_attendance': session_wise
            }
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 4. GET /api/attendance/history/
# ═══════════════════════════════════════════════════════════════════════════════

class AttendanceHistoryAPIView(SafeAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        role = getattr(user, 'role', None)

        from students.models import Student
        from batches.models import TimetableSlot

        qs = AttendanceRecord.objects.all().select_related('student', 'student__user', 'batch', 'branch')

        # Scoping by organization
        if getattr(user, 'organization', None):
            qs = qs.filter(branch__organization=user.organization)

        # Scoping by role
        if role == 'student':
            qs = qs.filter(student__user=user)
        elif role == 'parents':
            if user.linked_student:
                qs = qs.filter(student__user=user.linked_student)
            else:
                qs = qs.none()
        elif role == 'faculty':
            batch_ids = list(user.faculty_profile.batch_assignments.values_list('batch_id', flat=True)) if hasattr(user, 'faculty_profile') else []
            qs = qs.filter(batch_id__in=batch_ids)

        # Filters
        student_id = request.GET.get('student_id')
        branch_id = request.GET.get('branch_id')
        batch_id = request.GET.get('batch_id')
        faculty_id = request.GET.get('faculty_id')
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        status_filter = request.GET.get('attendance_status')
        session_filter = request.GET.get('session')
        subject_filter = request.GET.get('subject')

        if student_id and role not in ['student', 'parents']:
            qs = qs.filter(student_id=student_id)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        if faculty_id:
            from faculty.models import FacultyProfile
            faculty_batches = list(FacultyProfile.objects.filter(id=faculty_id).values_list('batch_assignments__batch_id', flat=True))
            qs = qs.filter(batch_id__in=faculty_batches)
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        if status_filter:
            qs = qs.filter(status=status_filter)

        # Order by date
        qs = qs.order_by('-date')

        # Map to response list
        history_list = []
        for r in qs:
            scan_log = QRScanLog.objects.filter(
                student=r.student,
                scan_type='check_in',
                scanned_at__date=r.date
            ).select_related('timetable_slot', 'timetable_slot__subject').first()

            subj_name = None
            sess_name = None
            device = "N/A"

            if scan_log:
                device = scan_log.device_id or "N/A"
                if scan_log.timetable_slot:
                    sess_name = scan_log.timetable_slot.slot_code
                    if scan_log.timetable_slot.subject:
                        subj_name = scan_log.timetable_slot.subject.name

            if not subj_name or not sess_name:
                day_slots = []
                if r.batch:
                    slots = TimetableSlot.objects.filter(batch=r.batch).select_related('subject')
                    for slot in slots:
                        if slot.is_recurring:
                            if slot.day_of_week == r.date.weekday():
                                if (not slot.effective_from or slot.effective_from <= r.date) and \
                                   (not slot.effective_to or slot.effective_to >= r.date):
                                    day_slots.append(slot)
                        else:
                            if slot.session_date == r.date:
                                day_slots.append(slot)

                if day_slots:
                    first_slot = day_slots[0]
                    subj_name = first_slot.subject.name if first_slot.subject else "General / Other"
                    sess_name = first_slot.slot_code or "General"
                else:
                    subj_name = "General / Other"
                    sess_name = "General"

            if session_filter and session_filter.lower() not in sess_name.lower():
                continue
            if subject_filter and subject_filter.lower() not in subj_name.lower():
                continue

            history_list.append({
                'date': r.date,
                'check_in_time': r.checked_in_at,
                'check_out_time': r.checked_out_at,
                'status': r.status,
                'late_status': 'late' if r.status == 'late' else 'normal',
                'session': sess_name,
                'subject': subj_name,
                'scanner_device': device
            })

        # Manual pagination
        page = request.GET.get('page', 1)
        page_size = request.GET.get('page_size', 50)
        try:
            page = int(page)
            page_size = int(page_size)
        except ValueError:
            page = 1
            page_size = 50

        total_count = len(history_list)
        start = (page - 1) * page_size
        end = start + page_size
        paginated_data = history_list[start:end]

        return Response({
            'success': True,
            'count': total_count,
            'page_size': page_size,
            'data': paginated_data
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 5. GET /api/attendance/batches/{batch_id}/register/
# ═══════════════════════════════════════════════════════════════════════════════

class BatchAttendanceRegisterAPIView(SafeAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, batch_id):
        # Filters
        month = request.GET.get('month')
        if not month:
            month = timezone.now().strftime('%Y-%m')

        sheet = get_batch_attendance_sheet(batch_id, month)

        from .utils import get_all_dates_in_month
        dates = get_all_dates_in_month(month)

        students_matrix = []
        for sid, info in sheet.items():
            row = {
                'student_id': sid,
                'student_name': info['name'],
                'roll_number': info['roll_number'],
                'attendance': {}
            }
            for d in dates:
                val = info['dates'].get(d, {'status': 'absent', 'checked_in_at': None, 'checked_out_at': None})
                row['attendance'][d] = val
            students_matrix.append(row)

        return Response({
            'success': True,
            'data': {
                'month': month,
                'dates': dates,
                'register': students_matrix
            }
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 6. GET /api/attendance/faculty/
# ═══════════════════════════════════════════════════════════════════════════════

class FacultyAttendanceAPIView(SafeAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        role = getattr(user, 'role', None)

        if role in ['student', 'parents']:
            return Response({'success': False, 'message': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

        from faculty.models import FacultyProfile, FacultyQRScanLog
        from leave.models import LeaveApplication

        faculty_qs = FacultyProfile.objects.all().select_related('user', 'branch')

        if getattr(user, 'organization', None):
            faculty_qs = faculty_qs.filter(branch__organization=user.organization)

        # Filters
        faculty_id = request.GET.get('faculty_id')
        branch_id = request.GET.get('branch_id')
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')

        if faculty_id:
            faculty_qs = faculty_qs.filter(id=faculty_id)
        if branch_id:
            faculty_qs = faculty_qs.filter(branch_id=branch_id)

        date_from_parsed = None
        date_to_parsed = None
        if date_from:
            try:
                date_from_parsed = timezone.datetime.strptime(date_from, '%Y-%m-%d').date()
            except ValueError:
                pass
        if date_to:
            try:
                date_to_parsed = timezone.datetime.strptime(date_to, '%Y-%m-%d').date()
            except ValueError:
                pass

        if not date_from_parsed:
            date_from_parsed = timezone.now().date() - timezone.timedelta(days=30)
        if not date_to_parsed:
            date_to_parsed = timezone.now().date()

        faculty_list = []
        for f in faculty_qs:
            present_days = FacultyQRScanLog.objects.filter(
                faculty=f,
                scan_type='check_in',
                scanned_at__date__gte=date_from_parsed,
                scanned_at__date__lte=date_to_parsed
            ).values_list('scanned_at__date', flat=True).distinct().count()

            leave_days = LeaveApplication.objects.filter(
                applied_by=f.user,
                status='approved',
                from_date__lte=date_to_parsed,
                to_date__gte=date_from_parsed
            ).count()

            from batches.models import TimetableSlot
            assigned_slots = TimetableSlot.objects.filter(faculty=f)
            working_days_set = set()
            curr = date_from_parsed
            while curr <= date_to_parsed:
                weekday = curr.weekday()
                has_slot = False
                for slot in assigned_slots:
                    if slot.is_recurring:
                        if slot.day_of_week == weekday:
                            if (not slot.effective_from or slot.effective_from <= curr) and (not slot.effective_to or slot.effective_to >= curr):
                                has_slot = True
                                break
                    else:
                        if slot.session_date == curr:
                            has_slot = True
                            break
                if has_slot:
                    working_days_set.add(curr)
                curr += timezone.timedelta(days=1)

            total_working_days = len(working_days_set)
            if total_working_days == 0:
                curr = date_from_parsed
                while curr <= date_to_parsed:
                    if curr.weekday() < 5:
                        total_working_days += 1
                    curr += timezone.timedelta(days=1)

            absent_count = max(0, total_working_days - present_days - leave_days)
            attendance_pct = round((present_days / total_working_days) * 100, 2) if total_working_days > 0 else 0.0

            faculty_list.append({
                'id': str(f.id),
                'faculty_details': {
                    'id': str(f.id),
                    'name': f.user.name,
                    'employee_id': f.employee_id,
                    'email': f.user.email,
                    'branch_name': f.branch.name if f.branch else None,
                },
                'present_count': present_days,
                'absent_count': absent_count,
                'leave_count': leave_days,
                'attendance_percentage': attendance_pct
            })

        # Pagination
        page = request.GET.get('page', 1)
        page_size = request.GET.get('page_size', 50)
        try:
            page = int(page)
            page_size = int(page_size)
        except ValueError:
            page = 1
            page_size = 50

        total_count = len(faculty_list)
        start = (page - 1) * page_size
        end = start + page_size
        paginated_data = faculty_list[start:end]

        return Response({
            'success': True,
            'count': total_count,
            'page_size': page_size,
            'data': paginated_data
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 7. GET /api/attendance/faculty/{faculty_id}/
# ═══════════════════════════════════════════════════════════════════════════════

class FacultyAttendanceDetailAPIView(SafeAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, faculty_id):
        user = request.user
        role = getattr(user, 'role', None)

        if role in ['student', 'parents']:
            return Response({'success': False, 'message': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

        from faculty.models import FacultyProfile, FacultyQRScanLog
        from leave.models import LeaveApplication

        try:
            f = FacultyProfile.objects.get(id=faculty_id)
        except FacultyProfile.DoesNotExist:
            return Response({'success': False, 'message': 'Faculty not found.'}, status=status.HTTP_404_NOT_FOUND)

        if getattr(user, 'organization', None) and f.branch and f.branch.organization != user.organization:
            return Response({'success': False, 'message': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

        if role == 'faculty' and f.user != user:
            return Response({'success': False, 'message': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

        date_to = timezone.now().date()
        date_from = date_to - timezone.timedelta(days=30)

        scans = FacultyQRScanLog.objects.filter(faculty=f, scanned_at__date__gte=date_from, scanned_at__date__lte=date_to)

        present_days = scans.filter(scan_type='check_in').values_list('scanned_at__date', flat=True).distinct().count()
        leave_days = LeaveApplication.objects.filter(applied_by=f.user, status='approved', from_date__lte=date_to, to_date__gte=date_from).count()

        from batches.models import TimetableSlot
        assigned_slots = TimetableSlot.objects.filter(faculty=f)
        working_days_set = set()
        curr = date_from
        while curr <= date_to:
            weekday = curr.weekday()
            has_slot = False
            for slot in assigned_slots:
                if slot.is_recurring:
                    if slot.day_of_week == weekday:
                        if (not slot.effective_from or slot.effective_from <= curr) and (not slot.effective_to or slot.effective_to >= curr):
                            has_slot = True
                            break
                else:
                    if slot.session_date == curr:
                        has_slot = True
                        break
            if has_slot:
                working_days_set.add(curr)
            curr += timezone.timedelta(days=1)

        total_working_days = len(working_days_set)
        if total_working_days == 0:
            curr = date_from
            while curr <= date_to:
                if curr.weekday() < 5:
                    total_working_days += 1
                curr += timezone.timedelta(days=1)

        absent_count = max(0, total_working_days - present_days - leave_days)
        attendance_pct = round((present_days / total_working_days) * 100, 2) if total_working_days > 0 else 0.0

        # Detailed logs
        check_in_logs = []
        check_out_logs = []
        daily_history = []
        
        scans_by_date = {}
        for s in scans.order_by('-scanned_at'):
            d_str = s.scanned_at.strftime('%Y-%m-%d')
            if d_str not in scans_by_date:
                scans_by_date[d_str] = {'check_in': None, 'check_out': None}
            if s.scan_type == 'check_in':
                scans_by_date[d_str]['check_in'] = s
                check_in_logs.append({'date': d_str, 'timestamp': s.scanned_at, 'is_late': s.is_late})
            elif s.scan_type == 'check_out':
                scans_by_date[d_str]['check_out'] = s
                check_out_logs.append({'date': d_str, 'timestamp': s.scanned_at})

        for d_str, data in scans_by_date.items():
            ci = data['check_in']
            co = data['check_out']
            working_hours = 0
            if ci and co:
                working_hours = round((co.scanned_at - ci.scanned_at).total_seconds() / 3600, 2)
            
            daily_history.append({
                'date': d_str,
                'check_in': ci.scanned_at if ci else None,
                'check_out': co.scanned_at if co else None,
                'working_hours': working_hours,
                'status': 'present' if ci else 'absent'
            })

        avg_working_hours = 0
        total_hours = sum(d['working_hours'] for d in daily_history)
        if len(daily_history) > 0:
            avg_working_hours = round(total_hours / len(daily_history), 2)

        monthly_trend = []
        today = timezone.now().date()
        for i in range(5, -1, -1):
            m = today.month - i
            y = today.year
            if m <= 0:
                m += 12
                y -= 1
            month_str = f"{y}-{m:02d}"
            
            m_scans = FacultyQRScanLog.objects.filter(faculty=f, scanned_at__date__year=y, scanned_at__date__month=m, scan_type='check_in')
            m_present = m_scans.values_list('scanned_at__date', flat=True).distinct().count()
            
            m_working = 22 
            m_pct = round((m_present / m_working) * 100, 2)

            monthly_trend.append({
                'month': month_str,
                'percentage': m_pct
            })

        return Response({
            'success': True,
            'data': {
                'faculty': {
                    'id': str(f.id),
                    'name': f.user.name,
                    'employee_id': f.employee_id,
                    'email': f.user.email,
                },
                'summary': {
                    'present_count': present_days,
                    'absent_count': absent_count,
                    'leave_count': leave_days,
                    'attendance_percentage': attendance_pct,
                },
                'daily_attendance_history': daily_history,
                'check_in_logs': check_in_logs,
                'check_out_logs': check_out_logs,
                'working_hours': {
                    'total_hours': total_hours,
                    'average_hours_per_day': avg_working_hours
                },
                'monthly_analytics': monthly_trend
            }
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 8. GET /api/attendance/analytics/
# ═══════════════════════════════════════════════════════════════════════════════

class AttendanceAnalyticsAPIView(SafeAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        role = getattr(user, 'role', None)

        if role in ['student', 'parents']:
            return Response({'success': False, 'message': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

        branch_id = request.GET.get('branch')
        batch_id = request.GET.get('batch')
        course_id = request.GET.get('course')
        faculty_id = request.GET.get('faculty')
        student_id = request.GET.get('student')
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')

        records = AttendanceRecord.objects.all()

        if getattr(user, 'organization', None):
            records = records.filter(branch__organization=user.organization)

        if role == 'faculty':
            batch_ids = list(user.faculty_profile.batch_assignments.values_list('batch_id', flat=True)) if hasattr(user, 'faculty_profile') else []
            records = records.filter(batch_id__in=batch_ids)

        if branch_id:
            records = records.filter(branch_id=branch_id)
        if batch_id:
            records = records.filter(batch_id=batch_id)
        if course_id:
            records = records.filter(batch__course_id=course_id)
        if faculty_id:
            from faculty.models import FacultyProfile
            faculty_batches = list(FacultyProfile.objects.filter(id=faculty_id).values_list('batch_assignments__batch_id', flat=True))
            records = records.filter(batch_id__in=faculty_batches)
        if student_id:
            records = records.filter(student_id=student_id)
        if date_from:
            records = records.filter(date__gte=date_from)
        if date_to:
            records = records.filter(date__lte=date_to)

        total_days = records.exclude(status='on_leave').count()
        present_count = records.filter(status__in=['present', 'late', 'half_day']).count()
        avg_attendance = round((present_count / total_days) * 100, 2) if total_days > 0 else 0.0

        daily_trend = []
        daily_records = records.exclude(status='on_leave').values('date').annotate(
            present=Count('id', filter=Q(status__in=['present', 'late', 'half_day'])),
            total=Count('id')
        ).order_by('date')
        for r in daily_records:
            daily_trend.append({
                'date': r['date'].strftime('%Y-%m-%d'),
                'percentage': round((r['present'] / r['total']) * 100, 2)
            })

        weekly_stats = {}
        for r in daily_records:
            year, week, weekday = r['date'].isocalendar()
            monday = r['date'] - timezone.timedelta(days=weekday - 1)
            monday_str = monday.strftime('%Y-%m-%d')
            if monday_str not in weekly_stats:
                weekly_stats[monday_str] = {'present': 0, 'total': 0}
            weekly_stats[monday_str]['present'] += r['present']
            weekly_stats[monday_str]['total'] += r['total']

        weekly_trend = []
        for week_start, stats in sorted(weekly_stats.items()):
            weekly_trend.append({
                'week_start_date': week_start,
                'percentage': round((stats['present'] / stats['total']) * 100, 2)
            })

        monthly_stats = {}
        for r in daily_records:
            month_str = r['date'].strftime('%Y-%m')
            if month_str not in monthly_stats:
                monthly_stats[month_str] = {'present': 0, 'total': 0}
            monthly_stats[month_str]['present'] += r['present']
            monthly_stats[month_str]['total'] += r['total']

        monthly_trend = []
        for month_str, stats in sorted(monthly_stats.items()):
            monthly_trend.append({
                'month': month_str,
                'percentage': round((stats['present'] / stats['total']) * 100, 2)
            })

        branch_comparison = []
        branch_records = records.exclude(status='on_leave').values('branch__name').annotate(
            present=Count('id', filter=Q(status__in=['present', 'late', 'half_day'])),
            total=Count('id')
        )
        for r in branch_records:
            if r['branch__name']:
                branch_comparison.append({
                    'branch_name': r['branch__name'],
                    'percentage': round((r['present'] / r['total']) * 100, 2)
                })

        batch_comparison = []
        batch_records = records.exclude(status='on_leave').values('batch__name', 'batch__batch_code').annotate(
            present=Count('id', filter=Q(status__in=['present', 'late', 'half_day'])),
            total=Count('id')
        )
        for r in batch_records:
            if r['batch__name']:
                batch_comparison.append({
                    'batch_name': r['batch__name'],
                    'batch_code': r['batch__batch_code'],
                    'percentage': round((r['present'] / r['total']) * 100, 2)
                })

        faculty_comparison = []
        from faculty.models import FacultyProfile
        faculties = FacultyProfile.objects.all().select_related('user')
        for f in faculties:
            f_batches = list(f.batch_assignments.values_list('batch_id', flat=True))
            if len(f_batches) > 0:
                f_records = records.filter(batch_id__in=f_batches).exclude(status='on_leave')
                f_total = f_records.count()
                f_present = f_records.filter(status__in=['present', 'late', 'half_day']).count()
                if f_total > 0:
                    faculty_comparison.append({
                        'faculty_name': f.user.name,
                        'percentage': round((f_present / f_total) * 100, 2)
                    })

        return Response({
            'success': True,
            'data': {
                'average_attendance': avg_attendance,
                'attendance_trends': {
                    'daily_trend': daily_trend,
                    'weekly_trend': weekly_trend,
                    'monthly_trend': monthly_trend
                },
                'branch_comparison': branch_comparison,
                'batch_comparison': batch_comparison,
                'faculty_comparison': faculty_comparison
            }
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 9. GET /api/attendance/defaulters/
# ═══════════════════════════════════════════════════════════════════════════════

class DefaulterStudentsAPIView(SafeAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        role = getattr(user, 'role', None)

        if role in ['student', 'parents']:
            return Response({'success': False, 'message': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

        threshold = request.GET.get('attendance_threshold', 75.0)
        try:
            threshold = float(threshold)
        except ValueError:
            threshold = 75.0

        branch_id = request.GET.get('branch')
        batch_id = request.GET.get('batch')
        course_id = request.GET.get('course')

        from students.models import Student
        student_qs = Student.objects.filter(is_active=True).select_related('user', 'branch', 'batch')

        if getattr(user, 'organization', None):
            student_qs = student_qs.filter(branch__organization=user.organization)

        if role == 'faculty':
            batch_ids = list(user.faculty_profile.batch_assignments.values_list('batch_id', flat=True)) if hasattr(user, 'faculty_profile') else []
            student_qs = student_qs.filter(batch_id__in=batch_ids)

        if branch_id:
            student_qs = student_qs.filter(branch_id=branch_id)
        if batch_id:
            student_qs = student_qs.filter(batch_id=batch_id)
        if course_id:
            student_qs = student_qs.filter(batch__course_id=course_id)

        defaulter_list = []
        for s in student_qs:
            records = AttendanceRecord.objects.filter(student=s).exclude(status='on_leave')
            total = records.count()
            present = records.filter(status__in=['present', 'late', 'half_day']).count()
            pct = round((present / total) * 100, 2) if total > 0 else 0.0

            if pct < threshold:
                active_violations = ViolationRecord.objects.filter(student=s, is_resolved=False).count()
                defaulter_list.append({
                    'id': str(s.id),
                    'student_profile': {
                        'id': str(s.id),
                        'name': f"{s.first_name} {s.surname}",
                        'roll_number': s.roll_number,
                        'admission_number': s.admission_number,
                        'branch_name': s.branch.name if s.branch else None,
                        'batch_name': s.batch.name if s.batch else None,
                    },
                    'attendance_percentage': pct,
                    'active_violations': active_violations
                })

        return Response({
            'success': True,
            'count': len(defaulter_list),
            'data': defaulter_list
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 10. GET & POST /api/attendance/violations/
# ═══════════════════════════════════════════════════════════════════════════════

class ViolationsAPIView(SafeAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        role = getattr(user, 'role', None)

        from students.models import Student

        violation_qs = ViolationRecord.objects.all().select_related('student', 'student__user', 'resolved_by', 'created_by')

        if getattr(user, 'organization', None):
            violation_qs = violation_qs.filter(student__branch__organization=user.organization)

        if role == 'student':
            violation_qs = violation_qs.filter(student__user=user)
        elif role == 'parents':
            if user.linked_student:
                violation_qs = violation_qs.filter(student__user=user.linked_student)
            else:
                violation_qs = violation_qs.none()
        elif role == 'faculty':
            batch_ids = list(user.faculty_profile.batch_assignments.values_list('batch_id', flat=True)) if hasattr(user, 'faculty_profile') else []
            violation_qs = violation_qs.filter(student__batch_id__in=batch_ids)

        student_id = request.GET.get('student')
        branch_id = request.GET.get('branch')
        batch_id = request.GET.get('batch')
        violation_type = request.GET.get('violation_type')
        resolved = request.GET.get('resolved')
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')

        if student_id and role not in ['student', 'parents']:
            violation_qs = violation_qs.filter(student_id=student_id)
        if branch_id:
            violation_qs = violation_qs.filter(student__branch_id=branch_id)
        if batch_id:
            violation_qs = violation_qs.filter(student__batch_id=batch_id)
        if violation_type:
            violation_qs = violation_qs.filter(violation_type=violation_type)
        if resolved:
            violation_qs = violation_qs.filter(is_resolved=resolved.lower() == 'true')
        if date_from:
            violation_qs = violation_qs.filter(date__gte=date_from)
        if date_to:
            violation_qs = violation_qs.filter(date__lte=date_to)

        violation_qs = violation_qs.order_by('-date')

        return paginate_queryset(violation_qs, request, ViolationRecordSerializer)

    def post(self, request):
        """POST /api/v1/attendance/violations/ — admin manual violation (FRD §4.4.3)."""
        user = request.user
        role = getattr(user, 'role', None)

        VIOLATION_ROLES = ['super_admin', 'branch_manager', 'admin_senior_executive']
        if role not in VIOLATION_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        ser = ViolationCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        d = ser.validated_data
        v = ViolationRecord.objects.create(
            student_id=d['student_id'],
            violation_type=d['violation_type'],
            date=d['date'],
            description=d.get('description', ''),
            logged_by_admin=True,
            created_by=request.user,
        )

        from .models import AlertLog
        count = get_active_violations_count(d['student_id'])
        if count >= 3:
            try:
                from django.apps import apps
                SP = apps.get_model('students', 'Student')
                SP.objects.filter(id=d['student_id']).update(qr_blocked=True)
            except Exception:
                pass
            AlertLog.objects.create(
                student_id=d['student_id'], alert_type='violation',
                message=f'{count} active violations. QR access blocked.',
                notified_admin=True,
            )

        return Response({'success': True, 'message': 'Violation logged.', 'data': ViolationRecordSerializer(v).data}, status=status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. PATCH & DELETE /api/attendance/violations/{violation_id}/
# ═══════════════════════════════════════════════════════════════════════════════

class ViolationDetailAPIView(SafeAPIView):
    permission_classes = [IsAuthenticated]

    def _get_violation(self, request, violation_id):
        user = request.user
        role = getattr(user, 'role', None)
        VIOLATION_ROLES = ['super_admin', 'branch_manager', 'admin_senior_executive']
        if role not in VIOLATION_ROLES:
            return None, Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            v = ViolationRecord.objects.get(id=violation_id)
        except ViolationRecord.DoesNotExist:
            return None, Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return v, None

    def patch(self, request, violation_id):
        v, err = self._get_violation(request, violation_id)
        if err:
            return err

        ser = ViolationResolveSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        v.is_resolved = ser.validated_data['is_resolved']
        v.resolved_by = request.user
        v.resolved_at = timezone.now()
        v.save()

        if not should_block_qr(v.student_id):
            try:
                from django.apps import apps
                SP = apps.get_model('students', 'Student')
                SP.objects.filter(id=v.student_id).update(qr_blocked=False)
            except Exception:
                pass

        return Response({'success': True, 'message': 'Violation resolved.', 'data': ViolationRecordSerializer(v).data})

    def delete(self, request, violation_id):
        v, err = self._get_violation(request, violation_id)
        if err:
            return err

        student_id = v.student_id
        v.delete()

        if not should_block_qr(student_id):
            try:
                from django.apps import apps
                SP = apps.get_model('students', 'Student')
                SP.objects.filter(id=student_id).update(qr_blocked=False)
            except Exception:
                pass

        return Response({'success': True, 'message': 'Violation deleted.'}, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. GET /api/attendance/export/
# ═══════════════════════════════════════════════════════════════════════════════

class AttendanceExportAPIView(SafeAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        role = getattr(user, 'role', None)

        if role in ['student', 'parents']:
            return Response({'success': False, 'message': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

        branch_id = request.GET.get('branch')
        batch_id = request.GET.get('batch')
        student_id = request.GET.get('student')
        faculty_id = request.GET.get('faculty')
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')

        records = AttendanceRecord.objects.all().select_related('student', 'student__user', 'batch', 'branch')

        if getattr(user, 'organization', None):
            records = records.filter(branch__organization=user.organization)

        if role == 'faculty':
            batch_ids = list(user.faculty_profile.batch_assignments.values_list('batch_id', flat=True)) if hasattr(user, 'faculty_profile') else []
            records = records.filter(batch_id__in=batch_ids)

        if branch_id:
            records = records.filter(branch_id=branch_id)
        if batch_id:
            records = records.filter(batch_id=batch_id)
        if student_id:
            records = records.filter(student_id=student_id)
        if faculty_id:
            from faculty.models import FacultyProfile
            faculty_batches = list(FacultyProfile.objects.filter(id=faculty_id).values_list('batch_assignments__batch_id', flat=True))
            records = records.filter(batch_id__in=faculty_batches)
        if date_from:
            records = records.filter(date__gte=date_from)
        if date_to:
            records = records.filter(date__lte=date_to)

        # Optimize queries using pre-fetched maps
        student_ids = list(records.values_list('student_id', flat=True).distinct())
        scan_logs = QRScanLog.objects.filter(
            student_id__in=student_ids,
            scan_type='check_in'
        ).select_related('timetable_slot')
        
        scan_map = {}
        for s_log in scan_logs:
            scan_map[(s_log.student_id, s_log.scanned_at.date())] = s_log.timetable_slot.slot_code if s_log.timetable_slot else None

        batch_ids = list(records.values_list('batch_id', flat=True).distinct())
        from batches.models import TimetableSlot
        slots = TimetableSlot.objects.filter(batch_id__in=batch_ids)
        batch_slots = {}
        for slot in slots:
            batch_slots.setdefault(slot.batch_id, []).append(slot)

        def get_record_session(r):
            sess_code = scan_map.get((r.student_id, r.date))
            if sess_code:
                return sess_code
            if r.batch_id and r.batch_id in batch_slots:
                for slot in batch_slots[r.batch_id]:
                    if slot.is_recurring:
                        if slot.day_of_week == r.date.weekday():
                            if (not slot.effective_from or slot.effective_from <= r.date) and \
                               (not slot.effective_to or slot.effective_to >= r.date):
                                return slot.slot_code or "General"
                    else:
                        if slot.session_date == r.date:
                            return slot.slot_code or "General"
            return "General"

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="attendance_report.csv"'

        writer = csv.writer(response)
        writer.writerow(['Student Name', 'Roll Number', 'Branch', 'Batch', 'Date', 'Session', 'Status', 'Checked In At', 'Checked Out At'])

        for r in records.order_by('-date'):
            writer.writerow([
                f"{r.student.first_name} {r.student.surname}",
                r.student.roll_number,
                r.branch.name if r.branch else 'N/A',
                r.batch.name if r.batch else 'N/A',
                r.date.strftime('%Y-%m-%d'),
                get_record_session(r),
                r.status,
                r.checked_in_at.strftime('%Y-%m-%d %H:%M') if r.checked_in_at else '',
                r.checked_out_at.strftime('%Y-%m-%d %H:%M') if r.checked_out_at else ''
            ])

        return response


# ═══════════════════════════════════════════════════════════════════════════════
# 13. GET /api/attendance/audit-logs/
# ═══════════════════════════════════════════════════════════════════════════════

class AttendanceAuditAPIView(SafeAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        role = getattr(user, 'role', None)

        if role in ['student', 'parents']:
            return Response({'success': False, 'message': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

        records = AttendanceRecord.objects.filter(is_corrected=True).select_related('student', 'student__user', 'corrected_by', 'batch')

        if getattr(user, 'organization', None):
            records = records.filter(branch__organization=user.organization)

        if role == 'faculty':
            batch_ids = list(user.faculty_profile.batch_assignments.values_list('batch_id', flat=True)) if hasattr(user, 'faculty_profile') else []
            records = records.filter(batch_id__in=batch_ids)

        # Optimize queries using pre-fetched maps
        student_ids = list(records.values_list('student_id', flat=True).distinct())
        scan_logs = QRScanLog.objects.filter(
            student_id__in=student_ids,
            scan_type='check_in'
        ).select_related('timetable_slot')
        
        scan_map = {}
        for s_log in scan_logs:
            scan_map[(s_log.student_id, s_log.scanned_at.date())] = s_log.timetable_slot.slot_code if s_log.timetable_slot else None

        batch_ids = list(records.values_list('batch_id', flat=True).distinct())
        from batches.models import TimetableSlot
        slots = TimetableSlot.objects.filter(batch_id__in=batch_ids)
        batch_slots = {}
        for slot in slots:
            batch_slots.setdefault(slot.batch_id, []).append(slot)

        def get_record_session(r):
            sess_code = scan_map.get((r.student_id, r.date))
            if sess_code:
                return sess_code
            if r.batch_id and r.batch_id in batch_slots:
                for slot in batch_slots[r.batch_id]:
                    if slot.is_recurring:
                        if slot.day_of_week == r.date.weekday():
                            if (not slot.effective_from or slot.effective_from <= r.date) and \
                               (not slot.effective_to or slot.effective_to >= r.date):
                                return slot.slot_code or "General"
                    else:
                        if slot.session_date == r.date:
                            return slot.slot_code or "General"
            return "General"

        audit_logs = []
        for r in records.order_by('-marked_at'):
            audit_logs.append({
                'attendance_record': {
                    'id': str(r.id),
                    'date': r.date,
                    'student_name': f"{r.student.first_name} {r.student.surname}",
                    'roll_number': r.student.roll_number,
                    'session': get_record_session(r)
                },
                'old_value': 'absent', 
                'new_value': r.status,
                'updated_by': r.corrected_by.name if r.corrected_by else 'Unknown',
                'updated_date': r.marked_at,
                'correction_reason': r.correction_note
            })

        return Response({
            'success': True,
            'count': len(audit_logs),
            'data': audit_logs
        })
