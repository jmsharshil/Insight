import uuid
import logging
from core.pagination import paginate_queryset
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from core.utils import apply_filters

from .models import AttendanceRecord, QRScanLog, AlertLog, ViolationRecord
from .serializers import (
    AttendanceRecordListSerializer, BatchAttendanceCreateSerializer,
    AttendanceCorrectionSerializer, QRScanInputSerializer,
    AlertTriggerSerializer, ViolationRecordSerializer, ViolationResolveSerializer,
    ViolationCreateSerializer,
)
from .utils import (
    compute_attendance_percentage, get_batch_attendance_sheet,
    resolve_qr_data, should_block_qr, get_active_violations_count,
    compute_avg_times, get_violations_breakdown, haversine_distance,
    validate_qr_scan, get_attendance_entry_status,
)

logger = logging.getLogger(__name__)

ADMIN_ROLES = ['super_admin', 'branch_manager', 'admin_senior_executive', 'admin_executive']
MARKING_ROLES = ['super_admin', 'faculty', 'admin_executive', 'admin_senior_executive']
CORRECTION_ROLES = ['super_admin', 'admin_senior_executive', 'branch_manager']
REPORT_ROLES = ['super_admin', 'branch_manager', 'admin_senior_executive']
QR_ROLES = ['super_admin', 'student', 'exam_supervisor', 'admin_executive']
VIOLATION_ROLES = ['super_admin', 'branch_manager', 'admin_senior_executive']


def _user_role(user):
    return getattr(user, 'role', None)


def _user_branch_id(user):
    if hasattr(user, 'branch_id') and user.branch_id:
        return user.branch_id
    if hasattr(user, 'profile') and hasattr(user.profile, 'branch_id'):
        return user.profile.branch_id
    try:
        from faculty.models import FacultyProfile
        fp = FacultyProfile.objects.only('branch_id').get(user=user)
        return fp.branch_id
    except Exception:
        pass
    return None


def _user_batch_ids(user):
    if hasattr(user, 'faculty_profile'):
        return list(user.faculty_profile.batch_assignments.values_list('batch_id', flat=True))
    return []


# ═══════════════════════════════════════════════════════════════════════════════
# 1. GET & POST  /api/v1/attendance/
# ═══════════════════════════════════════════════════════════════════════════════

class AttendanceListCreateView(APIView):
    # permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['date', 'batch_id', 'student_id', 'status']
    search_fields = ['student__first_name', 'student__surname','student__fullname']
    ordering_fields = '__all__'

    def get(self, request):
        user = request.user
        role = _user_role(user)
        allowed = ADMIN_ROLES + ['faculty']
        if role not in allowed:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        qs = AttendanceRecord.objects.select_related('student', 'batch', 'branch', 'marked_by', 'corrected_by')

        if getattr(request.user, 'organization', None):
            qs = qs.filter(branch__organization=request.user.organization)

        if role in ('branch_manager', 'admin_senior_executive', 'admin_executive'):
            bid = _user_branch_id(user)
            if bid:
                qs = qs.filter(branch_id=bid)
        if role == 'faculty':
            bids = _user_batch_ids(user)
            qs = qs.filter(batch_id__in=bids) if bids else qs.none()

        for param, field in [('date','date'), ('batch_id','batch_id'), ('student_id','student_id'), ('status','status')]:
            val = request.GET.get(param)
            if val:
                qs = qs.filter(**{field: val})

        search_query = request.GET.get('search')
        if search_query:
            qs = qs.filter(
                Q(student__first_name__icontains=search_query) |
                Q(student__surname__icontains=search_query) |
                Q(student__roll_number__icontains=search_query) |
                Q(student__admission_number__icontains=search_query) |
                Q(student__fullname__icontains=search_query)
            )

        qs = apply_filters(self, request, qs)

        return paginate_queryset(qs, request, AttendanceRecordListSerializer)

    def post(self, request):
        user = request.user
        role = _user_role(user)
        if role not in MARKING_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        ser = BatchAttendanceCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        data = ser.validated_data
        batch_id, att_date, records = data['batch_id'], data['date'], data['records']

        # if role == 'faculty':
        #     bids = _user_batch_ids(user)
        #     if bids and batch_id not in bids:
        #         return Response({'success': False, 'message': 'Not your assigned batch.'}, status=status.HTTP_403_FORBIDDEN)

        # try:
        #     from django.apps import apps
        #     batch_obj = apps.get_model('batches', 'Batch').objects.get(id=batch_id)
        #     branch_id = batch_obj.branch_id
        # except Exception:
        #     branch_id = _user_branch_id(user)
        branch_id = data.get('branch_id')
        if not branch_id:
            return Response({'success': False, 'message': 'Branch ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

        from branch.models import Branch
        if not Branch.objects.filter(id=branch_id).exists():
            return Response({'success': False, 'message': 'Invalid Branch ID.'}, status=status.HTTP_400_BAD_REQUEST)

        from batches.models import Batch
        if not Batch.objects.filter(id=batch_id).exists():
            return Response({'success': False, 'message': 'Invalid Batch ID.'}, status=status.HTTP_400_BAD_REQUEST)

        timetable_slot_id = request.data.get('timetable_slot_id')

        if AttendanceRecord.objects.filter(batch_id=batch_id, date=att_date, timetable_slot_id=timetable_slot_id).exists():
            return Response({'success': False, 'message': 'Already marked for this slot. Use PATCH to correct.'}, status=status.HTTP_409_CONFLICT)

        created, errors = [], []
        from students.models import Student
        from django.contrib.auth import get_user_model
        User = get_user_model()
        from .notifications import notify_student_attendance_marked

        # Resolve batch name for notification body
        batch_name = None
        try:
            from batches.models import Batch
            batch_obj = Batch.objects.filter(id=batch_id).first()
            batch_name = batch_obj.name if batch_obj else None
        except Exception:
            pass

        for entry in records:
            try:
                sid = entry['student_id']
                # Check if it's a valid Student ID
                if not Student.objects.filter(id=sid).exists():
                    # Fallback: check if the frontend accidentally sent a User ID instead
                    student_profile = Student.objects.filter(user_id=sid).first()
                    if student_profile:
                        sid = student_profile.id
                    else:
                        raise Exception("Student ID does not exist in the database.")

                r = AttendanceRecord.objects.create(
                    student_id=sid, batch_id=batch_id, branch_id=branch_id,
                    date=att_date, status=entry['status'], marked_by=user,
                    timetable_slot_id=timetable_slot_id,
                )
                created.append(str(r.id))

                # Notify student + parent
                try:
                    student_obj = Student.objects.select_related('user').get(id=sid)
                    notify_student_attendance_marked(student_obj, att_date, entry['status'], batch_name)
                except Exception as ne:
                    logger.error(f"Attendance notification failed for student {sid}: {ne}")
            except Exception as e:
                errors.append({'student_id': str(entry['student_id']), 'error': str(e)})

        return Response({'success': True, 'message': f'{len(created)} records created.', 'created_ids': created, 'errors': errors}, status=status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. POST  /api/v1/attendance/qr-scan/
# ═══════════════════════════════════════════════════════════════════════════════

class QRScanView(APIView):
    """QR scan: check_in, check_out, exam_entry based on Class/Batch QR."""
    # permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        role = _user_role(user)
        
        # Removed student-only restriction so employees can also scan the global branch QR.

        ser = QRScanInputSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        qr_data = ser.validated_data['qr_data']
        scan_type = ser.validated_data['scan_type']
        device_id = ser.validated_data['device_id']

        # 2. Resolve Branch from QR data
        from branch.models import Branch
        from uuid import UUID
        
        branch = None
        try:
            UUID(str(qr_data))
            branch = Branch.objects.filter(id=qr_data).first()
        except ValueError:
            pass
            
        if not branch:
            # Fallback if QR data is branch name/code etc
            branch = Branch.objects.filter(name=qr_data).first()

        if not branch:
            return Response({'success': False, 'message': 'Invalid Institute/Branch QR code.'}, status=status.HTTP_404_NOT_FOUND)

        # Handle Employee Scan
        if role != 'student':
            user_branch_id = _user_branch_id(user)
            if str(branch.id) != str(user_branch_id):
                return Response({'success': False, 'message': 'You are not assigned to this branch.'}, status=status.HTTP_403_FORBIDDEN)
            
            # Record employee attendance
            from attendance.models import EmployeeAttendanceRecord
            from attendance.serializers import EmployeeAttendanceRecordSerializer
            from django.utils import timezone
            
            today = timezone.now().date()
            now = timezone.now()
            
            # Faculty specific tracking for payroll late/early logic
            if role == 'faculty':
                from faculty.models import FacultyQRScanLog, FacultyProfile
                faculty_profile = FacultyProfile.objects.filter(user=user).first()
                if faculty_profile:
                    late_mins = 0
                    if scan_type == 'check_in' and faculty_profile.work_start_time:
                        import datetime
                        s_dt = datetime.datetime.combine(today, faculty_profile.work_start_time)
                        diff = (now.replace(tzinfo=None) - s_dt).total_seconds() / 60
                        if diff > 0:
                            late_mins = int(diff)
                    
                    early_mins = 0
                    if scan_type == 'check_out' and faculty_profile.work_end_time:
                        import datetime
                        e_dt = datetime.datetime.combine(today, faculty_profile.work_end_time)
                        if faculty_profile.work_start_time and faculty_profile.work_end_time < faculty_profile.work_start_time:
                            e_dt += datetime.timedelta(days=1)
                        diff = (e_dt - now.replace(tzinfo=None)).total_seconds() / 60
                        if diff > 0:
                            early_mins = int(diff)

                    FacultyQRScanLog.objects.create(
                        faculty=faculty_profile,
                        branch=branch,
                        scan_type=scan_type,
                        is_late=(late_mins > 0),
                        late_minutes=late_mins,
                        is_early_checkout=(early_mins > 0),
                        early_minutes=early_mins
                    )

            if scan_type == 'check_in':
                open_record = EmployeeAttendanceRecord.objects.filter(
                    user=user,
                    date=today,
                    checked_in_at__isnull=False,
                    checked_out_at__isnull=True,
                ).order_by('-checked_in_at').first()
                if open_record:
                    return Response({
                        'success': False,
                        'message': 'You are already checked in. Please check out first.',
                        'data': EmployeeAttendanceRecordSerializer(open_record).data,
                    }, status=status.HTTP_400_BAD_REQUEST)
                # Create new record (allows multiple per day via different slots or null slots)
                record = EmployeeAttendanceRecord.objects.create(
                    user=user,
                    date=today,
                    branch_id=branch.id,
                    status='checkout_pending',
                    checked_in_at=now,
                    marked_by=user,
                )
                message = f'Employee {scan_type.replace("_", " ").title()} recorded successfully.'
            else:  # check_out
                record_qs = EmployeeAttendanceRecord.objects.filter(
                    user=user,
                    date=today,
                    checked_in_at__isnull=False,
                    checked_out_at__isnull=True,
                ).order_by('-checked_in_at')
                record = record_qs.first()
                if not record:
                    return Response({
                        'success': False,
                        'message': 'Must check in first before checking out.',
                    }, status=status.HTTP_400_BAD_REQUEST)
                record.checked_out_at = now
                record.status = 'present'
                record.save(update_fields=['checked_out_at', 'status'])
                message = f'Employee {scan_type.replace("_", " ").title()} recorded successfully.'
            
            return Response({
                'success': True,
                'message': message,
                'data': EmployeeAttendanceRecordSerializer(record).data,
            })

        # --- Student Logic ---
        try:
            from django.apps import apps
            SP = apps.get_model('students', 'Student')
            student = SP.objects.get(user=user)
        except Exception:
            return Response({'success': False, 'message': 'Student profile not found.'}, status=status.HTTP_404_NOT_FOUND)

        student_branch_id = getattr(student, 'branch_id', None) or _user_branch_id(user)

        if str(branch.id) != str(student_branch_id):
            return Response({'success': False, 'message': 'You are not assigned to this branch.'}, status=status.HTTP_403_FORBIDDEN)

        # Auto-detect Batch for the current time
        from batches.models import Batch, TimetableSlot, BatchStudent
        from django.utils import timezone
        from datetime import timedelta
        
        now_local = timezone.localtime()
        current_time = now_local.time()
        buffered_time = (now_local + timedelta(minutes=15)).time()
        current_dow = now_local.weekday() + 1 if now_local.weekday() != 6 else 7 # weekday() is 0-6 (Mon-Sun), day_of_week is 1-7 (Mon-Sun)

        enrolled_batch_ids = list(BatchStudent.objects.filter(student=student).values_list('batch_id', flat=True))
        primary_batch_id = getattr(student, 'current_batch_id', None) or getattr(student, 'batch_id', None)
        if primary_batch_id and primary_batch_id not in enrolled_batch_ids:
            enrolled_batch_ids.append(primary_batch_id)

        active_slot_qs = TimetableSlot.objects.filter(
            batch_id__in=enrolled_batch_ids,
            day_of_week=current_dow,
        )
        # Prefer slots where current time is between start and end, or within buffer after start
        active_slot = active_slot_qs.filter(
            start_time__lte=buffered_time,
            end_time__gte=(now_local - timedelta(minutes=30)).time()  # allow checking in up to 30min after nominal end
        ).order_by('start_time').first()

        if not active_slot:
            # Fallback: find the most recent slot that started today for this student
            active_slot = active_slot_qs.filter(
                start_time__lte=current_time
            ).order_by('-start_time').first()

        batch = None
        if active_slot and active_slot.batch:
            batch = active_slot.batch
        else:
            if primary_batch_id:
                batch = Batch.objects.filter(id=primary_batch_id).first()
            if not batch and enrolled_batch_ids:
                batch = Batch.objects.filter(id=enrolled_batch_ids[0]).first()

        if not batch:
             return Response({'success': False, 'message': 'No class/batch assigned to you could be detected.'}, status=status.HTTP_404_NOT_FOUND)

        # Check QR block (3+ violations)
        if should_block_qr(student.id):
            return Response({'success': False, 'message': 'QR blocked due to unresolved violations. Contact admin.'}, status=status.HTTP_403_FORBIDDEN)

        student_branch_id = getattr(student, 'branch_id', None) or getattr(batch, 'branch_id', None) or _user_branch_id(user)

        # Geofencing check for students (if lat/long provided and branch has coords)
        student_lat = ser.validated_data.get('latitude')
        student_lon = ser.validated_data.get('longitude')
        timetable_slot_id = ser.validated_data.get('timetable_slot')

        timetable_slot_obj = active_slot
        if timetable_slot_id:
            from batches.models import TimetableSlot
            timetable_slot_obj = TimetableSlot.objects.filter(id=timetable_slot_id).first()

        # Resolve branch object for validation
        branch_obj_for_validation = None
        from django.apps import apps
        BranchModel = apps.get_model('branch', 'Branch')
        try:
            branch_obj_for_validation = BranchModel.objects.get(id=student_branch_id)
        except BranchModel.DoesNotExist:
            pass

        now = timezone.now()

        # Check for open check-in (supports multiple sessions per day across different slots)
        has_prior_same_day_checkin = AttendanceRecord.objects.filter(
            student=student,
            batch_id=batch.id,
            date=now.date(),
            checked_in_at__lt=now,
        ).exists()

        if scan_type == 'check_in':
            existing_record = AttendanceRecord.objects.filter(
                student=student, timetable_slot=timetable_slot_obj, date=now.date()
            ).first()
            # Only block if currently checked in without checkout for this slot (allows re-scan after checkout)
            if existing_record and existing_record.checked_in_at and not getattr(existing_record, 'checked_out_at', None):
                return Response({'success': False, 'message': 'You are already checked in. Please check out first.'}, status=status.HTTP_400_BAD_REQUEST)
        elif scan_type == 'check_out':
            # Use broader query for checkout to support checking out any open session (not just current slot)
            open_record_qs = AttendanceRecord.objects.filter(
                student=student,
                date=now.date(),
                checked_in_at__isnull=False,
                checked_out_at__isnull=True,
            )
            if timetable_slot_obj and timetable_slot_obj.pk:
                open_record_qs = open_record_qs.filter(timetable_slot=timetable_slot_obj)
            existing_record = open_record_qs.order_by('-checked_in_at').first()
            if not existing_record:
                return Response({'success': False, 'message': 'You cannot check out without checking in first.'}, status=status.HTTP_400_BAD_REQUEST)
            if existing_record.checked_out_at:
                return Response({'success': False, 'message': 'You are already checked out for today.'}, status=status.HTTP_400_BAD_REQUEST)

        # E3: run validate_qr_scan — never block on failure, just log results
        validation_result = validate_qr_scan(
            scan_lat=student_lat,
            scan_lng=student_lon,
            branch=branch_obj_for_validation,
            timetable_slot=timetable_slot_obj,
            scan_time=now,
        )

        scan_log = QRScanLog.objects.create(
            student=student,
            branch_id=student_branch_id,
            scan_type=scan_type,
            device_id=device_id,
            scanned_by=None,
            is_valid=True,
            latitude=student_lat,
            longitude=student_lon,
            location_verified=validation_result['location_verified'],
            time_verified=validation_result['time_verified'],
            validation_reason=validation_result['reason'][:255],
            timetable_slot=timetable_slot_obj,
        )

        attendance_status = None
        checked_in_at = None
        checked_out_at = None


        if scan_type == 'check_in':
            record, created = AttendanceRecord.objects.get_or_create(
                student=student, timetable_slot=timetable_slot_obj, date=now.date(),
                defaults={'batch_id': batch.id, 'branch_id': student_branch_id, 'status': 'checkout_pending', 'marked_by': user, 'checked_in_at': now},
            )
            if not created and not record.checked_in_at:
                record.checked_in_at = now
                record.status = 'checkout_pending'
                record.save(update_fields=['checked_in_at', 'status'])

            entry_status = get_attendance_entry_status(
                timetable_slot_obj,
                now,
                is_first_class_of_day=not has_prior_same_day_checkin,
            )
            if entry_status == 'late_entry':
                record.status = 'late'
                slot_start_str = str(timetable_slot_obj.start_time) if timetable_slot_obj and timetable_slot_obj.start_time else 'N/A'
                checkin_str = now.strftime('%H:%M')
                ViolationRecord.objects.create(
                    student=student,
                    violation_type='late_entry',
                    date=now.date(),
                    description=f'Check-in at {checkin_str} (slot start was {slot_start_str}). Late entry beyond allowed buffer.',
                    created_by=user,
                )
                # Notify student + parent about violation
                try:
                    from .notifications import notify_student_violation
                    notify_student_violation(student, 'late_entry', now.date(), f'Checked in at {checkin_str} for {slot_start_str} slot.')
                except Exception as ne:
                    logger.error(f"Violation notification failed: {ne}")
            else:
                record.status = 'checkout_pending'
            record.checked_in_at = now
            record.save(update_fields=['checked_in_at', 'status'])

            attendance_status = 'already_scanned' if (not created and record.checked_in_at and record.checked_in_at != now) else record.status
            checked_in_at = record.checked_in_at
            checked_out_at = record.checked_out_at

            # Notify parent about check-in
            try:
                from .notifications import notify_student_qr_scan
                notify_student_qr_scan(student, 'check_in', now)
            except Exception as ne:
                logger.error(f"QR check-in notification failed: {ne}")

        elif scan_type == 'check_out':
            try:
                record_qs = AttendanceRecord.objects.filter(
                    student=student,
                    date=now.date(),
                    checked_in_at__isnull=False,
                    checked_out_at__isnull=True,
                )
                if timetable_slot_obj and timetable_slot_obj.pk:
                    record_qs = record_qs.filter(timetable_slot=timetable_slot_obj)
                record = record_qs.order_by('-checked_in_at').first()

                if not record:
                    attendance_status = 'no_checkin_found'
                    return Response({
                        'success': False, 
                        'message': 'Must check in first before checking out.',
                        'attendance_status': 'no_checkin_found'
                    }, status=status.HTTP_400_BAD_REQUEST)

                record.checked_out_at = now
                record.status = 'present'
                record.save(update_fields=['checked_out_at', 'status'])
                attendance_status = record.status
                checked_in_at = record.checked_in_at
                checked_out_at = record.checked_out_at

                # Check minimum session duration — log violation if too short
                if record.checked_in_at:
                    duration = (now - record.checked_in_at).total_seconds() / 60
                    if duration < 30:  # Less than 30 minutes
                        ViolationRecord.objects.create(
                            student=student, violation_type='missing_checkout', date=now.date(),
                            description=f'Session duration only {int(duration)} minutes (minimum 30).',
                        )
                        # Check if violations threshold reached
                        if should_block_qr(student.id):
                            AlertLog.objects.create(
                                student=student, alert_type='violation',
                                message=f'{get_active_violations_count(student.id)} active violations. QR blocked.',
                            )

                # Notify parent about check-out
                try:
                    from .notifications import notify_student_qr_scan
                    notify_student_qr_scan(student, 'check_out', now)
                except Exception as ne:
                    logger.error(f"QR check-out notification failed: {ne}")
            except AttendanceRecord.DoesNotExist:
                attendance_status = 'no_checkin_found'

        # exam_entry — just the scan log, no attendance change

        try:
            sname = student.user.name if hasattr(student, 'user') else str(student)
            roll = student.roll_number if hasattr(student, 'roll_number') else ''
        except Exception:
            sname, roll = str(student), ''

        return Response({
            'success': True, 'student_name': sname, 'roll_number': roll,
            'scan_time': timezone.localtime(scan_log.scanned_at).isoformat() if scan_log.scanned_at else None, 'scan_type': scan_type,
            'device_id': device_id, 'is_valid': True,
            'attendance_status': attendance_status,
            'checked_in_at': timezone.localtime(checked_in_at).isoformat() if checked_in_at else None, 
            'checked_out_at': timezone.localtime(checked_out_at).isoformat() if checked_out_at else None,
            'location_verified': validation_result['location_verified'],
            'time_verified': validation_result['time_verified'],
            'validation_reason': validation_result['reason'],
            'message': f'Class QR {scan_type} recorded successfully.',
        }, status=status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PATCH  /api/v1/attendance/{id}/
# ═══════════════════════════════════════════════════════════════════════════════

class AttendanceCorrectionView(APIView):
    # permission_classes = [IsAuthenticated]

    def _get_record(self, request, record_id):
        user = request.user
        role = _user_role(user)
        if role not in CORRECTION_ROLES + ADMIN_ROLES + ['faculty', 'student']:
            return None, Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            record = AttendanceRecord.objects.select_related(
                'student', 'batch', 'branch', 'marked_by', 'corrected_by'
            ).get(id=record_id)
        except AttendanceRecord.DoesNotExist:
            return None, Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if role == 'branch_manager':
            ub = _user_branch_id(user)
            if ub and str(record.branch_id) != str(ub):
                return None, Response({'success': False, 'message': 'Not your branch.'}, status=status.HTTP_403_FORBIDDEN)
        return record, None

    def get(self, request, record_id):
        """GET /api/v1/attendance/{id}/ — fetch a single attendance record by ID."""
        record, err = self._get_record(request, record_id)
        if err:
            return err
        return Response({'success': True, 'data': AttendanceRecordListSerializer(record).data})

    def patch(self, request, record_id):
        role = _user_role(request.user)
        if role not in CORRECTION_ROLES:
            return Response({'success': False, 'message': 'Only ASE or BM can correct.'}, status=status.HTTP_403_FORBIDDEN)
        record, err = self._get_record(request, record_id)
        if err:
            return err
    
        ser = AttendanceCorrectionSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)
    
        if 'status' in ser.validated_data:
            record.status = ser.validated_data['status']
        if 'checked_in_at' in ser.validated_data:
            record.checked_in_at = ser.validated_data['checked_in_at']
        if 'checked_out_at' in ser.validated_data:
            record.checked_out_at = ser.validated_data['checked_out_at']
    
        record.is_corrected = True
        record.corrected_by = request.user
        record.correction_note = ser.validated_data.get('correction_note', '')
        record.save()

        # Notify student about correction
        try:
            from .notifications import notify_attendance_correction
            notify_attendance_correction(record.student, record.date, record.status)
        except Exception as ne:
            logger.error(f"Correction notification failed: {ne}")
    
        return Response({'success': True, 'message': 'Corrected.', 'data': AttendanceRecordListSerializer(record).data})
    
    # def put(self, request, record_id):
    #     """PUT /api/v1/attendance/{id}/ — full update of an attendance record."""
    #     role = _user_role(request.user)
    #     if role not in CORRECTION_ROLES:
    #         return Response({'success': False, 'message': 'Only ASE or BM can correct.'}, status=status.HTTP_403_FORBIDDEN)
    #     record, err = self._get_record(request, record_id)
    #     if err:
    #         return err
    # 
    #     ser = AttendanceCorrectionSerializer(data=request.data)
    #     if not ser.is_valid():
    #         return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)
    # 
    #     record.status = ser.validated_data.get('status', record.status)
    #     record.checked_in_at = ser.validated_data.get('checked_in_at')
    #     record.checked_out_at = ser.validated_data.get('checked_out_at')
    #     record.is_corrected = True
    #     record.corrected_by = request.user
    #     record.correction_note = ser.validated_data.get('correction_note', '')
    #     record.save()
    # 
    #     return Response({'success': True, 'message': 'Record fully updated.', 'data': AttendanceRecordListSerializer(record).data})
    # 
    # def delete(self, request, record_id):
    #     """DELETE /api/v1/attendance/{id}/ — remove an attendance record."""
    #     role = _user_role(request.user)
    #     if role not in CORRECTION_ROLES:
    #         return Response({'success': False, 'message': 'Only ASE or BM can delete.'}, status=status.HTTP_403_FORBIDDEN)
    #     record, err = self._get_record(request, record_id)
    #     if err:
    #         return err
    # 
    #     record.delete()
    #     return Response({'success': True, 'message': 'Attendance record deleted.'}, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. GET  /api/v1/attendance/student/{student_id}/
# ═══════════════════════════════════════════════════════════════════════════════

class StudentAttendanceView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        user = request.user
        role = _user_role(user)

        from django.apps import apps
        SP = apps.get_model('students', 'Student')

        # Fallback: if student_id is a User ID instead of Student Profile ID
        if not SP.objects.filter(id=student_id).exists():
            student_profile = SP.objects.filter(user_id=student_id).first()
            if student_profile:
                student_id = student_profile.id

        if role == 'student':
            try:
                if str(SP.objects.get(user=user).id) != str(student_id):
                    return Response({'success': False, 'message': 'Own attendance only.'}, status=status.HTTP_403_FORBIDDEN)
            except Exception:
                return Response({'success': False, 'message': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        elif role == 'parents':
            # Prefer ParentLink as source of truth
            from students.models import ParentLink
            linked_ids = list(ParentLink.objects.filter(parent=user).values_list('student_id', flat=True))
            if linked_ids:
                if str(student_id) not in [str(lid) for lid in linked_ids]:
                    return Response({'success': False, 'message': 'Not your linked child.'}, status=status.HTTP_403_FORBIDDEN)
            elif getattr(user, 'linked_students', None) and user.linked_students.exists():
                try:
                    student_obj = SP.objects.filter(id=student_id).first()
                    if not student_obj or not student_obj.user or not user.linked_students.filter(id=student_obj.user.id).exists():
                        return Response({'success': False, 'message': 'Not your linked child.'}, status=status.HTTP_403_FORBIDDEN)
                except Exception:
                    return Response({'success': False, 'message': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)
            else:
                return Response({'success': False, 'message': 'No linked student.'}, status=status.HTTP_404_NOT_FOUND)
        elif role == 'faculty':
            bids = _user_batch_ids(user)
            if bids and not AttendanceRecord.objects.filter(student_id=student_id, batch_id__in=bids).exists():
                return Response({'success': False, 'message': 'Not in your batches.'}, status=status.HTTP_403_FORBIDDEN)
        elif role not in ADMIN_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        qs = AttendanceRecord.objects.filter(student_id=student_id).select_related('marked_by').order_by('-date')
        
        if getattr(request.user, 'organization', None):
            qs = qs.filter(branch__organization=request.user.organization)
            
        month = request.GET.get('month')
        batch_id = request.GET.get('batch_id')
        if month:
            try:
                y, m = map(int, month.split('-'))
                qs = qs.filter(date__year=y, date__month=m)
            except (ValueError, AttributeError):
                pass
        if batch_id:
            qs = qs.filter(batch_id=batch_id)

        present, total, pct = compute_attendance_percentage(student_id, month=month, batch_id=batch_id)

        # v3 FRD §4.4.3: violations visible on student profile
        violations_qs = ViolationRecord.objects.filter(student_id=student_id).order_by('-created_at')
        violations_data = [{
            'id': str(v.id), 'violation_type': v.violation_type, 'date': v.date,
            'description': v.description, 'logged_by_admin': v.logged_by_admin,
            'is_resolved': v.is_resolved, 'created_at': v.created_at,
        } for v in violations_qs]

        summary_data = {'present': present, 'absent': qs.filter(status='absent').count(), 'total': total, 'percentage': pct}

        from core.pagination import StandardPagination
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)

        if page is not None:
            records_data = [{
                'date': r.date, 'status': r.status,
                'checked_in_at': r.checked_in_at, 'checked_out_at': r.checked_out_at,
                'marked_by_name': r.marked_by.name if r.marked_by else None,
            } for r in page]
            return Response({
                'success': True, 
                'count': paginator.page.paginator.count,
                'next': paginator.get_next_link(),
                'previous': paginator.get_previous_link(),
                'page_size': paginator.get_page_size(request),
                'data': records_data,
                'summary': summary_data,
                'violations': violations_data,
            })

        records_data = [{
            'date': r.date, 'status': r.status,
            'checked_in_at': r.checked_in_at, 'checked_out_at': r.checked_out_at,
            'marked_by_name': r.marked_by.name if r.marked_by else None,
        } for r in qs]

        return Response({
            'success': True, 'data': records_data,
            'summary': summary_data,
            'violations': violations_data,
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 5. GET  /api/v1/attendance/batch/{batch_id}/
# ═══════════════════════════════════════════════════════════════════════════════

class BatchAttendanceSheetView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request, batch_id):
        user = request.user
        role = _user_role(user)
        allowed = ['faculty', 'admin_senior_executive', 'branch_manager', 'super_admin']
        if role not in allowed:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if role == 'faculty':
            bids = _user_batch_ids(user)
            if bids and batch_id not in bids:
                return Response({'success': False, 'message': 'Not your batch.'}, status=status.HTTP_403_FORBIDDEN)

        if getattr(request.user, 'organization', None):
            from django.apps import apps
            Batch = apps.get_model('batches', 'Batch')
            if not Batch.objects.filter(id=batch_id, organization=request.user.organization).exists():
                return Response({'success': False, 'message': 'Batch not found.'}, status=status.HTTP_404_NOT_FOUND)

        date_filter = request.GET.get('date')
        month_filter = request.GET.get('month')

        if date_filter:
            qs = AttendanceRecord.objects.filter(batch_id=batch_id, date=date_filter).select_related('student')
            data = []
            for r in qs:
                try:
                    name = r.student.user.name if hasattr(r.student, 'user') else str(r.student)
                    roll = r.student.roll_number if hasattr(r.student, 'roll_number') else ''
                except Exception:
                    name, roll = str(r.student_id), ''
                data.append({'student_id': str(r.student_id), 'name': name, 'roll_number': roll,
                             'status': r.status,
                             'checked_in_at': r.checked_in_at, 'checked_out_at': r.checked_out_at})
            return Response({'success': True, 'date': date_filter, 'data': data})

        if not month_filter:
            month_filter = timezone.now().strftime('%Y-%m')
        return Response({'success': True, 'month': month_filter, 'data': get_batch_attendance_sheet(batch_id, month_filter)})


# ═══════════════════════════════════════════════════════════════════════════════
# 6. GET  /api/v1/attendance/report/
# ═══════════════════════════════════════════════════════════════════════════════

class AttendanceReportView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        role = _user_role(user)
        if role not in REPORT_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        branch_id = request.GET.get('branch_id')
        batch_id = request.GET.get('batch_id')
        month = request.GET.get('month')
        threshold = float(request.GET.get('threshold', 75))

        if role != 'super_admin':
            ub = _user_branch_id(user)
            if ub:
                branch_id = str(ub)

        qs = AttendanceRecord.objects.all()
        if getattr(request.user, 'organization', None):
            qs = qs.filter(branch__organization=request.user.organization)

        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        if month:
            try:
                y, m = map(int, month.split('-'))
                qs = qs.filter(date__year=y, date__month=m)
            except (ValueError, AttributeError):
                pass

        student_ids = qs.values_list('student_id', flat=True).distinct()
        report = []

        for sid in student_ids:
            present, total, pct = compute_attendance_percentage(sid, month=month, batch_id=batch_id)
            avg_in, avg_out = compute_avg_times(sid, month=month, batch_id=batch_id)
            v_count = get_active_violations_count(sid)

            try:
                from django.apps import apps
                SP = apps.get_model('students', 'Student')
                s = SP.objects.get(id=sid)
                name = s.user.name if hasattr(s, 'user') else str(s)
                roll = s.roll_number if hasattr(s, 'roll_number') else ''
            except Exception:
                name, roll = str(sid), ''

            # v3 FRD §4.4.3: violations_breakdown per type
            v_breakdown = get_violations_breakdown(sid)

            report.append({
                'student_id': str(sid), 'roll_number': roll, 'name': name,
                'present_days': present, 'total_days': total, 'percentage': pct,
                'avg_checkin_time': avg_in, 'avg_checkout_time': avg_out,
                'violations_count': v_count,
                'violations_breakdown': v_breakdown,
                'status': 'below_threshold' if pct < threshold else 'ok',
            })

        report.sort(key=lambda r: r['percentage'])
        return Response({'success': True, 'threshold': threshold, 'count': len(report), 'data': report})


# ═══════════════════════════════════════════════════════════════════════════════
# 7. POST  /api/v1/attendance/alert/
# ═══════════════════════════════════════════════════════════════════════════════

class AttendanceAlertView(APIView):
    # permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        role = _user_role(user)
        if role not in ('admin_senior_executive', 'super_admin'):
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        ser = AlertTriggerSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        branch_id = ser.validated_data['branch_id']
        threshold = ser.validated_data['threshold']

        try:
            from django.apps import apps
            SP = apps.get_model('students', 'Student')
            students = SP.objects.filter(branch_id=branch_id)
            if hasattr(SP, 'is_active'):
                students = students.filter(is_active=True)
        except Exception as e:
            logger.error(f"Student model not available: {e}")
            return Response({'success': False, 'message': 'Students not available.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        alerts_created = 0
        for s in students:
            present, total, pct = compute_attendance_percentage(s.id)
            if total == 0:
                continue
            if pct < threshold:
                if AlertLog.objects.filter(student=s, alert_type='low_attendance', sent_at__date=timezone.now().date()).exists():
                    continue
                AlertLog.objects.create(
                    student=s, alert_type='low_attendance',
                    message=f'Attendance {pct}% below {threshold}% threshold.',
                    threshold=threshold, current_pct=pct,
                )
                alerts_created += 1
                # Notify student + parent
                try:
                    from .notifications import notify_student_low_attendance
                    notify_student_low_attendance(s, pct, threshold)
                except Exception as ne:
                    logger.error(f"Low attendance notification failed for student {s.id}: {ne}")

        return Response({'success': True, 'message': f'{alerts_created} alerts generated.', 'alerts_created': alerts_created}, status=status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. GET, POST & PATCH  /api/v1/attendance/violations/
#    v3: added POST for manual admin violation logging (FRD §4.4.3)
# ═══════════════════════════════════════════════════════════════════════════════

# class ViolationListCreateView(APIView):
#     """List violations + manually create violations (FRD §4.4.3)."""
#     # permission_classes = [IsAuthenticated]
#     filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
#     filterset_fields = ['student_id', 'date', 'violation_type', 'is_resolved', 'logged_by_admin']
#     search_fields = ['student__first_name', 'student__surname', 'description']
#     ordering_fields = '__all__'
# 
#     def get(self, request):
#         role = _user_role(request.user)
#         if role not in VIOLATION_ROLES:
#             return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
# 
#         qs = ViolationRecord.objects.select_related('student', 'resolved_by', 'created_by').all()
# 
#         if getattr(request.user, 'organization', None):
#             qs = qs.filter(student__branch__organization=request.user.organization)
# 
#         for param, field in [('student_id','student_id'), ('date','date'), ('violation_type','violation_type')]:
#             val = request.GET.get(param)
#             if val:
#                 qs = qs.filter(**{field: val})
# 
#         is_resolved = request.GET.get('is_resolved')
#         if is_resolved is not None:
#             qs = qs.filter(is_resolved=is_resolved.lower() == 'true')
# 
#         logged_by_admin = request.GET.get('logged_by_admin')
#         if logged_by_admin is not None:
#             qs = qs.filter(logged_by_admin=logged_by_admin.lower() == 'true')
# 
#         qs = apply_filters(self, request, qs)
# 
#         return Response({'success': True, 'count': qs.count(), 'data': ViolationRecordSerializer(qs, many=True).data})
# 
#     def post(self, request):
#         """POST /api/v1/attendance/violations/ — admin manual violation (FRD §4.4.3)."""
#         role = _user_role(request.user)
#         if role not in VIOLATION_ROLES:
#             return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
# 
#         ser = ViolationCreateSerializer(data=request.data)
#         if not ser.is_valid():
#             return Response({'success': False, 'message': 'Validation failed.', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)
# 
#         d = ser.validated_data
#         v = ViolationRecord.objects.create(
#             student_id=d['student_id'],
#             violation_type=d['violation_type'],
#             date=d['date'],
#             description=d.get('description', ''),
#             logged_by_admin=True,
#             created_by=request.user,
#         )
# 
#         # Check violation threshold — block QR if >= 3
#         count = get_active_violations_count(d['student_id'])
#         if count >= 3:
#             try:
#                 from django.apps import apps
#                 SP = apps.get_model('students', 'Student')
#                 SP.objects.filter(id=d['student_id']).update(qr_blocked=True)
#             except Exception:
#                 pass
#             AlertLog.objects.create(
#                 student_id=d['student_id'], alert_type='violation',
#                 message=f'{count} active violations. QR access blocked.',
#                 notified_admin=True,
#             )
# 
#         return Response({'success': True, 'message': 'Violation logged.', 'data': ViolationRecordSerializer(v).data}, status=status.HTTP_201_CREATED)
# 
# 
# class ViolationResolveView(APIView):
#     """Resolve or delete a violation."""
#     # permission_classes = [IsAuthenticated]
# 
#     def _get_violation(self, request, violation_id):
#         role = _user_role(request.user)
#         if role not in VIOLATION_ROLES:
#             return None, Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
#         try:
#             v = ViolationRecord.objects.get(id=violation_id)
#         except ViolationRecord.DoesNotExist:
#             return None, Response({'success': False, 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
#         return v, None
# 
#     def patch(self, request, violation_id):
#         v, err = self._get_violation(request, violation_id)
#         if err:
#             return err
# 
#         ser = ViolationResolveSerializer(data=request.data)
#         if not ser.is_valid():
#             return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)
# 
#         v.is_resolved = ser.validated_data['is_resolved']
#         v.resolved_by = request.user
#         v.resolved_at = timezone.now()
#         v.save()
# 
#         # Re-enable QR if violations drop below 3
#         if not should_block_qr(v.student_id):
#             try:
#                 from django.apps import apps
#                 SP = apps.get_model('students', 'Student')
#                 SP.objects.filter(id=v.student_id).update(qr_blocked=False)
#             except Exception:
#                 pass
# 
#         return Response({'success': True, 'message': 'Violation resolved.', 'data': ViolationRecordSerializer(v).data})
# 
#     def delete(self, request, violation_id):
#         """DELETE /api/v1/attendance/violations/{id}/ — remove a violation record."""
#         v, err = self._get_violation(request, violation_id)
#         if err:
#             return err
# 
#         student_id = v.student_id
#         v.delete()
# 
#         # Re-enable QR if violations drop below 3 after deletion
#         if not should_block_qr(student_id):
#             try:
#                 from django.apps import apps
#                 SP = apps.get_model('students', 'Student')
#                 SP.objects.filter(id=student_id).update(qr_blocked=False)
#             except Exception:
#                 pass
# 
#         return Response({'success': True, 'message': 'Violation deleted.'}, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════════════════════════════════════════
# Employee Attendance APIs — check-in/check-out for ALL staff (non-student) users
# POST   /api/v1/attendance/employee/           — bulk mark (admin)
# GET    /api/v1/attendance/employee/           — list (admin sees branch; staff sees own)
# POST   /api/v1/attendance/employee/scan/      — self check-in / check-out
# GET    /api/v1/attendance/employee/history/    — personal attendance history
# ═══════════════════════════════════════════════════════════════════════════════

from .models import EmployeeAttendanceRecord
from .serializers import (
    EmployeeAttendanceRecordSerializer,
    EmployeeAttendanceCreateSerializer,
    EmployeeCheckInOutSerializer,
)

EMPLOYEE_ATTENDANCE_ADMIN_ROLES = ['super_admin', 'branch_manager', 'admin_senior_executive', 'admin_executive']


class EmployeeAttendanceListCreateView(APIView):
    """
    GET  — list employee attendance records (admin: by branch; staff: own)
    POST — bulk mark attendance for employees (admin only)
    """
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'date']
    search_fields = ['user__name', 'user__email']
    ordering_fields = '__all__'

    def get(self, request):
        role = _user_role(request.user)

        if role in EMPLOYEE_ATTENDANCE_ADMIN_ROLES:
            qs = EmployeeAttendanceRecord.objects.select_related('user', 'branch', 'marked_by').all()
            if getattr(request.user, 'organization', None):
                qs = qs.filter(branch__organization=request.user.organization)
            bid = _user_branch_id(request.user)
            if role != 'super_admin' and bid:
                qs = qs.filter(branch_id=bid)
        else:
            # Non-admin staff see only their own records
            qs = EmployeeAttendanceRecord.objects.filter(user=request.user).select_related('branch', 'marked_by')

        # Optional filters
        date = request.GET.get('date')
        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')
        status_filter = request.GET.get('status')
        user_id = request.GET.get('user_id')

        if date:
            qs = qs.filter(date=date)
        if from_date:
            qs = qs.filter(date__gte=from_date)
        if to_date:
            qs = qs.filter(date__lte=to_date)
        if status_filter:
            qs = qs.filter(status=status_filter)
        # Search by employee name or email
        search_query = request.GET.get('search')
        if search_query:
            qs = qs.filter(
                Q(user__name__icontains=search_query) |
                Q(user__email__icontains=search_query)
            )
        if user_id and role in EMPLOYEE_ATTENDANCE_ADMIN_ROLES:
            qs = qs.filter(user_id=user_id)

        qs = apply_filters(self, request, qs)
        return paginate_queryset(qs, request, EmployeeAttendanceRecordSerializer)

    def post(self, request):
        """Bulk mark attendance for employees (admin only)."""
        role = _user_role(request.user)
        if role not in EMPLOYEE_ATTENDANCE_ADMIN_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        ser = EmployeeAttendanceCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        d = ser.validated_data
        from django.contrib.auth import get_user_model
        User = get_user_model()

        created_count = 0
        updated_count = 0
        errors = []

        for rec in d['records']:
            # Support multiple key names from frontend (user, user_id, id, employee_id)
            raw_id = rec.get('user') or rec.get('user_id') or rec.get('id') or rec.get('employee_id')
            rec_status = rec.get('status', 'present')

            if not raw_id:
                errors.append({'user_id': None, 'error': 'user_id (or user/id/employee_id) is required.'})
                continue

            emp_user = None
            try:
                # Primary: lookup by User ID (UUID or PK)
                emp_user = User.objects.get(id=raw_id)
            except (User.DoesNotExist, ValueError, TypeError):
                # Fallback 1: FacultyProfile lookup (common for employees)
                try:
                    from faculty.models import FacultyProfile
                    fp = None
                    # Try as UUID for FacultyProfile.id
                    try:
                        fp = FacultyProfile.objects.filter(id=raw_id).select_related('user').first()
                    except (ValueError, TypeError):
                        pass
                    if not fp:
                        # Try by employee_id string
                        fp = FacultyProfile.objects.filter(employee_id=str(raw_id)).select_related('user').first()
                    if not fp and isinstance(raw_id, (str, int)):
                        # Try if raw_id was actually a User ID for the profile
                        fp = FacultyProfile.objects.filter(user_id=raw_id).select_related('user').first()
                    if fp and fp.user:
                        emp_user = fp.user
                except Exception as fallback_err:
                    logger.warning(f"FacultyProfile fallback failed for ID {raw_id}: {fallback_err}")

            if not emp_user:
                errors.append({'user_id': str(raw_id), 'error': 'User not found.'})
                logger.info(f"Employee attendance bulk: User not found for ID {raw_id}")
                continue

            # Optional: ensure not a student (prevent accidental student records here)
            if hasattr(emp_user, 'role') and emp_user.role == 'student':
                errors.append({'user_id': str(raw_id), 'error': 'Student accounts should use student attendance endpoint.'})
                continue

            defaults = {
                'branch_id': d.get('branch_id') or _user_branch_id(request.user),
                'status': rec_status,
                'marked_by': request.user,
            }

            if 'checked_in_at' in rec:
                val = rec['checked_in_at']
                defaults['checked_in_at'] = None if val == "" else val
            if 'checked_out_at' in rec:
                val = rec['checked_out_at']
                defaults['checked_out_at'] = None if val == "" else val

            record, created = EmployeeAttendanceRecord.objects.update_or_create(
                user=emp_user, date=d['date'],
                defaults=defaults,
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

            # Notify the employee
            try:
                from .notifications import notify_employee_attendance_marked
                notify_employee_attendance_marked(emp_user, d['date'], rec_status)
            except Exception as ne:
                logger.error(f"Employee attendance notification failed for {emp_user.id}: {ne}")

        return Response({
            'success': True,
            'message': f'Created {created_count}, updated {updated_count} records.',
            'errors': errors,
        }, status=status.HTTP_201_CREATED)


class EmployeeCheckInOutView(APIView):
    """
    POST /api/v1/attendance/employee/scan/
    Self-service check-in / check-out for the authenticated employee.
    Creates or updates the EmployeeAttendanceRecord for today.
    """

    def post(self, request):
        ser = EmployeeCheckInOutSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        scan_type = ser.validated_data['scan_type']
        user = request.user
        today = timezone.now().date()

        bid = _user_branch_id(user)
        if not bid:
            return Response(
                {'success': False, 'message': 'No branch assigned to your account.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Resolve Timetable Slot for faculty (used for unique per-session records)
        timetable_slot_obj = None
        if getattr(user, 'role', '') == 'faculty':
            try:
                from batches.models import TimetableSlot
                from faculty.models import FacultyProfile
                from datetime import timedelta
                fp = FacultyProfile.objects.filter(user=user).first()
                if fp:
                    now_local = timezone.localtime()
                    current_dow = now_local.weekday() + 1 if now_local.weekday() != 6 else 7
                    current_time = now_local.time()
                    buffered_time = (now_local + timedelta(minutes=15)).time()
                    # Find active slot
                    active_slot = TimetableSlot.objects.filter(
                        faculty=fp,
                        day_of_week=current_dow,
                        start_time__lte=buffered_time,
                        end_time__gte=current_time
                    ).first()
                    timetable_slot_obj = active_slot
            except Exception as e:
                logger.error(f"Error resolving faculty slot: {e}")

        now = timezone.now()

        # Updated logic to support multiple check-in/out per day (one record per session)
        # This fixes the restriction for faculty and staff.
        if scan_type == 'check_in':
            # Check for any currently open session today
            open_record = EmployeeAttendanceRecord.objects.filter(
                user=user,
                date=today,
                checked_in_at__isnull=False,
                checked_out_at__isnull=True,
            ).order_by('-checked_in_at').first()
            if open_record:
                return Response({
                    'success': False,
                    'message': 'You are already checked in. Please check out first.',
                    'data': EmployeeAttendanceRecordSerializer(open_record).data,
                }, status=status.HTTP_400_BAD_REQUEST)
            # Create new record for this new session
            record = EmployeeAttendanceRecord.objects.create(
                user=user,
                date=today,
                timetable_slot=timetable_slot_obj,
                branch_id=bid,
                status='checkout_pending',
                checked_in_at=now,
                marked_by=user,
            )
            message = f'{scan_type.replace("_", " ").title()} recorded.'
        else:  # check_out
            # Find most recent open record (prefer matching slot if available)
            record_qs = EmployeeAttendanceRecord.objects.filter(
                user=user,
                date=today,
                checked_in_at__isnull=False,
                checked_out_at__isnull=True,
            )
            if timetable_slot_obj:
                record_qs = record_qs.filter(timetable_slot=timetable_slot_obj)
            record = record_qs.order_by('-checked_in_at').first()
            if not record:
                return Response({
                    'success': False,
                    'message': 'Must check in first before checking out.',
                }, status=status.HTTP_400_BAD_REQUEST)
            record.checked_out_at = now
            record.status = 'present'
            record.save(update_fields=['checked_out_at', 'status'])
            message = f'{scan_type.replace("_", " ").title()} recorded.'

        return Response({
            'success': True,
            'message': message,
            'data': EmployeeAttendanceRecordSerializer(record).data,
        })


class EmployeeAttendanceHistoryView(APIView):
    """
    GET /api/v1/attendance/employee/history/
    Personal attendance history for the authenticated employee.
    Supports ?month=6&year=2026 for filtering.
    """

    def get(self, request):
        user = request.user
        qs = EmployeeAttendanceRecord.objects.filter(user=user).select_related('branch')

        year = request.GET.get('year')
        month = request.GET.get('month')
        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')

        if year:
            qs = qs.filter(date__year=year)
        if month:
            qs = qs.filter(date__month=month)
        if from_date:
            qs = qs.filter(date__gte=from_date)
        if to_date:
            qs = qs.filter(date__lte=to_date)

        qs = qs.order_by('-date')

        # Compute summary
        total = qs.count()
        present = qs.filter(status__in=['present', 'late']).count()
        absent = qs.filter(status='absent').count()
        half_day = qs.filter(status='half_day').count()
        on_leave = qs.filter(status='on_leave').count()
        percentage = round((present / total) * 100, 1) if total > 0 else 0

        serialized = EmployeeAttendanceRecordSerializer(qs[:100], many=True).data

        return Response({
            'success': True,
            'summary': {
                'total_days': total,
                'present_days': present,
                'absent_days': absent,
                'half_days': half_day,
                'on_leave': on_leave,
                'attendance_percentage': percentage,
            },
            'records': serialized,
        })


# ═══════════════════════════════════════════════════════════════════════════════
# 9. GET  /api/v1/attendance/employees/dropdown/  — Lightweight list for UI dropdowns
# ═══════════════════════════════════════════════════════════════════════════════

class EmployeeDropdownView(APIView):
    """
    Returns a simple list of employees (Users + FacultyProfiles) for dropdowns.
    - Admins see all (filtered by branch if not super_admin).
    - Includes name, employee_id, role, branch for easy display.
    """
    # permission_classes = [IsAuthenticated]

    def get(self, request):
        role = _user_role(request.user)
        if role not in EMPLOYEE_ATTENDANCE_ADMIN_ROLES + ['faculty']:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        from django.contrib.auth import get_user_model
        User = get_user_model()
        from faculty.models import FacultyProfile

        qs = User.objects.filter(is_active=True).exclude(role='student').select_related('branch')

        # Branch scoping
        if role != 'super_admin':
            bid = _user_branch_id(request.user)
            if bid:
                qs = qs.filter(branch_id=bid)

        if getattr(request.user, 'organization', None):
            qs = qs.filter(branch__organization=request.user.organization)

        # Prefer FacultyProfile data when available
        employees = []
        for user in qs.only('id', 'name', 'role', 'branch', 'email'):
            emp_id = ''
            branch_name = ''
            try:
                if hasattr(user, 'faculty_profile') and user.faculty_profile:
                    emp_id = user.faculty_profile.employee_id
                    branch_name = user.faculty_profile.branch.name if user.faculty_profile.branch else ''
                elif user.branch:
                    branch_name = user.branch.name
            except Exception:
                pass

            employees.append({
                'id': str(user.id),
                'name': user.name or user.email,
                'employee_id': emp_id or f"EMP-{str(user.id)[:8]}",
                'role': getattr(user, 'role', 'staff'),
                'branch_name': branch_name,
                'email': user.email,
            })

        return Response({
            'success': True,
            'count': len(employees),
            'data': employees
        })
