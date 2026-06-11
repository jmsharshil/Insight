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
    validate_qr_scan,
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
    if hasattr(user, 'branch_id'):
        return user.branch_id
    if hasattr(user, 'profile') and hasattr(user.profile, 'branch_id'):
        return user.profile.branch_id
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
    filterset_fields = ['date', 'batch_id', 'student_id', 'status', 'session']
    search_fields = ['student__first_name', 'student__surname']
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

        for param, field in [('date','date'), ('batch_id','batch_id'), ('student_id','student_id'), ('status','status'), ('session','session')]:
            val = request.GET.get(param)
            if val:
                qs = qs.filter(**{field: val})

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
        batch_id, att_date, session, records = data['batch_id'], data['date'], data['session'], data['records']

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

        if AttendanceRecord.objects.filter(batch_id=batch_id, date=att_date, session=session).exists():
            return Response({'success': False, 'message': 'Already marked. Use PATCH to correct.'}, status=status.HTTP_409_CONFLICT)

        created, errors = [], []
        from students.models import Student
        from django.contrib.auth import get_user_model
        User = get_user_model()

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
                    date=att_date, session=session, status=entry['status'], marked_by=user,
                )
                created.append(str(r.id))
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
        
        # In a Class-wise QR system, only the student scans the Class QR from their own app.
        if role != 'student':
            return Response({'success': False, 'message': 'Only students can scan the Class QR code to mark attendance.'}, status=status.HTTP_403_FORBIDDEN)

        ser = QRScanInputSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        qr_data = ser.validated_data['qr_data']
        scan_type = ser.validated_data['scan_type']
        device_id = ser.validated_data['device_id']

        # 1. Resolve Class/Batch from QR data
        from batches.models import Batch
        from uuid import UUID
        
        batch = None
        try:
            UUID(str(qr_data))
            batch = Batch.objects.filter(id=qr_data).first()
        except ValueError:
            pass
            
        if not batch:
            batch = Batch.objects.filter(batch_code=qr_data).first()

        if not batch:
            return Response({'success': False, 'message': 'Invalid Class/Batch QR code.'}, status=status.HTTP_404_NOT_FOUND)

        # 2. Identify the student from the authenticated user
        try:
            from django.apps import apps
            SP = apps.get_model('students', 'Student')
            student = SP.objects.get(user=user)
        except Exception:
            return Response({'success': False, 'message': 'Student profile not found.'}, status=status.HTTP_404_NOT_FOUND)

        # 3. Verify if the student is actually in the scanned class/batch
        student_batch_id = getattr(student, 'current_batch_id', None) or getattr(student, 'batch_id', None)
        from batches.models import BatchStudent
        is_enrolled = BatchStudent.objects.filter(student=student, batch=batch).exists()
        
        if str(student_batch_id) != str(batch.id) and not is_enrolled:
            return Response({'success': False, 'message': 'You are not enrolled in this class/batch.'}, status=status.HTTP_403_FORBIDDEN)

        # Check QR block (3+ violations)
        if should_block_qr(student.id):
            return Response({'success': False, 'message': 'QR blocked due to unresolved violations. Contact admin.'}, status=status.HTTP_403_FORBIDDEN)

        student_branch_id = getattr(student, 'branch_id', None) or getattr(batch, 'branch_id', None) or _user_branch_id(user)

        # Geofencing check for students (if lat/long provided and branch has coords)
        student_lat = ser.validated_data.get('latitude')
        student_lon = ser.validated_data.get('longitude')
        timetable_slot_id = ser.validated_data.get('timetable_slot')

        # Resolve timetable slot (optional)
        timetable_slot_obj = None
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

        # E3: run validate_qr_scan — never block on failure, just log results
        scan_now = timezone.now()
        validation_result = validate_qr_scan(
            scan_lat=student_lat,
            scan_lng=student_lon,
            branch=branch_obj_for_validation,
            timetable_slot=timetable_slot_obj,
            scan_time=scan_now,
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

        now = timezone.now()
        attendance_status = None
        checked_in_at = None
        checked_out_at = None

        # Determine session from time
        hour = now.hour
        session = 'morning' if hour < 12 else ('afternoon' if hour < 17 else 'evening')

        if scan_type == 'check_in':
            record, created = AttendanceRecord.objects.get_or_create(
                student=student, batch_id=batch.id, date=now.date(), session=session,
                defaults={'branch_id': student_branch_id, 'status': 'present', 'marked_by': user, 'checked_in_at': now},
            )
            if not created and not record.checked_in_at:
                record.checked_in_at = now
                record.status = 'present'
                record.save(update_fields=['checked_in_at', 'status'])
            attendance_status = 'already_scanned' if (not created and record.checked_in_at and record.checked_in_at != now) else record.status
            checked_in_at = record.checked_in_at
            checked_out_at = record.checked_out_at

            # Stub: notify parent "✓ <Name> checked in at <time>"
            # from notifications.utils import send_notification(...)

        elif scan_type == 'check_out':
            try:
                record = AttendanceRecord.objects.get(
                    student=student, batch_id=batch.id, date=now.date(), session=session,
                )
                record.checked_out_at = now
                record.save(update_fields=['checked_out_at'])
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

                # Stub: notify parent "✓ <Name> checked out at <time>"
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
            'scan_time': scan_log.scanned_at, 'scan_type': scan_type,
            'device_id': device_id, 'is_valid': True,
            'attendance_status': attendance_status,
            'checked_in_at': checked_in_at, 'checked_out_at': checked_out_at,
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

    # def patch(self, request, record_id):
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
    #     if 'status' in ser.validated_data:
    #         record.status = ser.validated_data['status']
    #     if 'checked_in_at' in ser.validated_data:
    #         record.checked_in_at = ser.validated_data['checked_in_at']
    #     if 'checked_out_at' in ser.validated_data:
    #         record.checked_out_at = ser.validated_data['checked_out_at']
    # 
    #         record.is_corrected = True
    #         record.corrected_by = request.user
    #         record.correction_note = ser.validated_data.get('correction_note', '')
    #         record.save()
    # 
    #         return Response({'success': True, 'message': 'Corrected.', 'data': AttendanceRecordListSerializer(record).data})
    # 
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

        if role == 'student':
            try:
                from django.apps import apps
                SP = apps.get_model('students', 'Student')
                if str(SP.objects.get(user=user).id) != str(student_id):
                    return Response({'success': False, 'message': 'Own attendance only.'}, status=status.HTTP_403_FORBIDDEN)
            except Exception:
                return Response({'success': False, 'message': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        elif role == 'parents':
            linked = getattr(user, 'linked_student', None)
            if not linked:
                return Response({'success': False, 'message': 'No linked student.'}, status=status.HTTP_404_NOT_FOUND)
            try:
                from django.apps import apps
                SP = apps.get_model('students', 'Student')
                if str(SP.objects.get(user=linked).id) != str(student_id):
                    return Response({'success': False, 'message': 'Not your linked child.'}, status=status.HTTP_403_FORBIDDEN)
            except Exception:
                return Response({'success': False, 'message': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        elif role == 'faculty':
            bids = _user_batch_ids(user)
            if bids and not AttendanceRecord.objects.filter(student_id=student_id, batch_id__in=bids).exists():
                return Response({'success': False, 'message': 'Not in your batches.'}, status=status.HTTP_403_FORBIDDEN)
        elif role not in ADMIN_ROLES:
            return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        qs = AttendanceRecord.objects.filter(student_id=student_id).select_related('marked_by').order_by('-date', 'session')
        
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

        records_data = [{
            'date': r.date, 'session': r.session, 'status': r.status,
            'checked_in_at': r.checked_in_at, 'checked_out_at': r.checked_out_at,
            'marked_by_name': r.marked_by.name if r.marked_by else None,
        } for r in qs]

        present, total, pct = compute_attendance_percentage(student_id, month=month, batch_id=batch_id)

        # v3 FRD §4.4.3: violations visible on student profile
        violations_qs = ViolationRecord.objects.filter(student_id=student_id).order_by('-created_at')
        violations_data = [{
            'id': str(v.id), 'violation_type': v.violation_type, 'date': v.date,
            'description': v.description, 'logged_by_admin': v.logged_by_admin,
            'is_resolved': v.is_resolved, 'created_at': v.created_at,
        } for v in violations_qs]

        return Response({
            'success': True, 'data': records_data,
            'summary': {'present': present, 'absent': qs.filter(status='absent').count(), 'total': total, 'percentage': pct},
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
                             'session': r.session, 'status': r.status,
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
                # Stub: notify parent

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
