import logging
from core.pagination import paginate_queryset

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError

from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from core.utils import (
    apply_filters, has_user_branch_access,
    notify_users_by_role, get_user_branch_ids,
)
from core.sender import send_email
from django.conf import settings

from .serializers import (
    get_lead_serializer, LeadStageUpdateSerializer, LeadListSerializer,
    LeadDetailSerializer, LeadUpdateSerializer, LeadReassignSerializer,
    SalesDailyPlanSerializer, SalesDailyActivitySerializer, SalesActivityPhotoSerializer,
    OdometerReadingSerializer, OdometerApproveSerializer, OdometerRejectSerializer,
)
from .utils import LeadService
from .models import (
    Lead, LeadStage, LeadAssignmentLog, SalesDailyPlan, SalesDailyActivity, SalesActivityPhoto,
    OdometerReading, FORM_TYPE_CHOICES, STAGE_CHOICES, COURSE_TYPE_CHOICES,
    GROUP_MODULE_CHOICES, ATTEMPT_TYPE_CHOICES,
)
from django.db.models import Q
import re
from rest_framework.permissions import AllowAny
from datetime import datetime
from django.utils import timezone
from chat.notifications import send_whatsapp_with_fallback, send_system_notification

FORM_TYPE_DISPLAY = dict(FORM_TYPE_CHOICES)
STAGE_DISPLAY = dict(STAGE_CHOICES)
COURSE_DISPLAY = dict(COURSE_TYPE_CHOICES)
GROUP_MODULE_DISPLAY = dict(GROUP_MODULE_CHOICES)
ATTEMPT_DISPLAY = dict(ATTEMPT_TYPE_CHOICES)

logger = logging.getLogger(__name__)

# ── Roles ────────────────────────────────────────────────────────────────────────

# Roles that can only see leads explicitly assigned to them
RESTRICTED_ROLES = {'counsellor', 'tele_caller', 'sales_executive'}

# Roles that can see all leads and reassign them
SENIOR_ROLES = {'sales_senior_executive', 'branch_manager', 'super_admin'}
SALES_ROLES = {
    'sales_senior_executive', 'sales_executive', 'counsellor',
    'tele_caller', 'senior_tele_caller', 'telecaller',
    'associate_bdm', 'cmo', 'front_desk', 'receptionist', 'sales',
}

ODOMETER_APPROVER_ROLES = {'super_admin', 'admin_senior_executive', 'accountant', 'branch_manager'}

def _sales_activity_access(user, activity=None):
    user_role = getattr(user, 'role', None)
    if user_role not in SALES_ROLES | ODOMETER_APPROVER_ROLES:
        return False
    return activity is None or activity.user_id == user.id or user_role in ODOMETER_APPROVER_ROLES

class SalesDailyActivityView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        if not _sales_activity_access(request.user):
            return Response({'detail': 'Only sales staff and managers can access sales activities.'}, status=status.HTTP_403_FORBIDDEN)
        queryset = SalesDailyActivity.objects.prefetch_related('photos').select_related('user', 'odometer_reading')
        if request.user.role not in ODOMETER_APPROVER_ROLES:
            queryset = queryset.filter(user=request.user)
        elif request.user.role == 'branch_manager':
            branch_ids = get_user_branch_ids(request.user)
            if branch_ids:
                queryset = queryset.filter(user__branch_id__in=branch_ids)

        # ── Filters ──
        # 1. Search by user name, email, phone
        search = request.query_params.get('search') or request.query_params.get('name')
        if search:
            queryset = queryset.filter(
                Q(user__name__icontains=search) |
                Q(user__email__icontains=search) |
                Q(user__phone__icontains=search)
            )

        # 2. Filter by date (supports YYYY-MM-DD or 'today')
        date_param = request.query_params.get('date')
        if date_param:
            if date_param.lower() == 'today':
                queryset = queryset.filter(activity_date=timezone.localdate())
            else:
                try:
                    parsed_date = datetime.strptime(date_param, '%Y-%m-%d').date()
                    queryset = queryset.filter(activity_date=parsed_date)
                except ValueError:
                    return Response({'detail': 'Invalid date format. Use YYYY-MM-DD or "today".'}, status=status.HTTP_400_BAD_REQUEST)

        # 3. Date range filter
        from_date = request.query_params.get('from_date')
        if from_date:
            try:
                parsed_from = datetime.strptime(from_date, '%Y-%m-%d').date()
                queryset = queryset.filter(activity_date__gte=parsed_from)
            except ValueError:
                return Response({'detail': 'Invalid from_date format. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

        to_date = request.query_params.get('to_date')
        if to_date:
            try:
                parsed_to = datetime.strptime(to_date, '%Y-%m-%d').date()
                queryset = queryset.filter(activity_date__lte=parsed_to)
            except ValueError:
                return Response({'detail': 'Invalid to_date format. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

        # 4. Filter by specific user_id
        user_id = request.query_params.get('user_id')
        if user_id:
            if request.user.role in ODOMETER_APPROVER_ROLES or str(request.user.id) == str(user_id):
                queryset = queryset.filter(user_id=user_id)
            else:
                return Response({'detail': 'You can only view your own sales activities.'}, status=status.HTTP_403_FORBIDDEN)

        queryset = queryset.order_by('-activity_date', '-created_at')
        serializer = SalesDailyActivitySerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    def post(self, request):
        if not _sales_activity_access(request.user):
            return Response({'detail': 'Only sales staff can upload sales activities.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = SalesDailyActivitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        activity_date = serializer.validated_data.get('activity_date') or timezone.localdate()

        # Auto-link to the day's plan if one exists
        plan = SalesDailyPlan.objects.filter(user=request.user, plan_date=activity_date).first()

        activity, _ = SalesDailyActivity.objects.get_or_create(
            user=request.user,
            activity_date=activity_date,
            defaults={
                'notes': serializer.validated_data.get('notes', ''),
                'plan': plan,
            },
        )
        if 'notes' in serializer.validated_data:
            activity.notes = serializer.validated_data['notes']
            activity.save(update_fields=['notes', 'updated_at'])

        # If plan was created after activity, link it now
        if plan and activity.plan_id != plan.id:
            activity.plan = plan
            activity.save(update_fields=['plan', 'updated_at'])

        return Response(
            SalesDailyActivitySerializer(activity, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class SalesDailyPlanView(APIView):
    """
    GET  /api/v1/sales/plans/        — List daily plans (with nested activities).
    POST /api/v1/sales/plans/        — Create or update today's plan (description).
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request):
        if not _sales_activity_access(request.user):
            return Response({'detail': 'Only sales staff and managers can access sales plans.'}, status=status.HTTP_403_FORBIDDEN)

        queryset = SalesDailyPlan.objects.prefetch_related(
            'activities', 'activities__photos', 'activities__odometer_reading',
        ).select_related('user')

        if request.user.role not in ODOMETER_APPROVER_ROLES:
            queryset = queryset.filter(user=request.user)
        elif request.user.role == 'branch_manager':
            branch_ids = get_user_branch_ids(request.user)
            if branch_ids:
                queryset = queryset.filter(user__branch_id__in=branch_ids)

        # ── Filters ──
        search = request.query_params.get('search') or request.query_params.get('name')
        if search:
            queryset = queryset.filter(
                Q(user__name__icontains=search) |
                Q(user__email__icontains=search) |
                Q(user__phone__icontains=search)
            )

        date_param = request.query_params.get('date')
        if date_param:
            if date_param.lower() == 'today':
                queryset = queryset.filter(plan_date=timezone.localdate())
            else:
                try:
                    parsed_date = datetime.strptime(date_param, '%Y-%m-%d').date()
                    queryset = queryset.filter(plan_date=parsed_date)
                except ValueError:
                    return Response({'detail': 'Invalid date format. Use YYYY-MM-DD or "today".'}, status=status.HTTP_400_BAD_REQUEST)

        from_date = request.query_params.get('from_date')
        if from_date:
            try:
                parsed_from = datetime.strptime(from_date, '%Y-%m-%d').date()
                queryset = queryset.filter(plan_date__gte=parsed_from)
            except ValueError:
                return Response({'detail': 'Invalid from_date format. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

        to_date = request.query_params.get('to_date')
        if to_date:
            try:
                parsed_to = datetime.strptime(to_date, '%Y-%m-%d').date()
                queryset = queryset.filter(plan_date__lte=parsed_to)
            except ValueError:
                return Response({'detail': 'Invalid to_date format. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

        user_id = request.query_params.get('user_id')
        if user_id:
            if request.user.role in ODOMETER_APPROVER_ROLES or str(request.user.id) == str(user_id):
                queryset = queryset.filter(user_id=user_id)
            else:
                return Response({'detail': 'You can only view your own sales plans.'}, status=status.HTTP_403_FORBIDDEN)

        queryset = queryset.order_by('-plan_date', '-created_at')
        serializer = SalesDailyPlanSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    def post(self, request):
        if not _sales_activity_access(request.user):
            return Response({'detail': 'Only sales staff can create sales plans.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = SalesDailyPlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan_date = serializer.validated_data.get('plan_date') or timezone.localdate()
        description = serializer.validated_data.get('description', '')
        event_type = serializer.validated_data.get('type', '')
        start_time = serializer.validated_data.get('start_time')
        end_time = serializer.validated_data.get('end_time')
        place = serializer.validated_data.get('place', '')

        plan_id = request.data.get('id') or request.data.get('plan_id')
        if plan_id:
            try:
                plan = SalesDailyPlan.objects.get(id=plan_id, user=request.user)
                plan.plan_date = plan_date
                plan.description = description
                plan.type = event_type
                plan.start_time = start_time
                plan.end_time = end_time
                plan.place = place
                plan.save()
                created = False
            except SalesDailyPlan.DoesNotExist:
                return Response({'detail': 'Plan with specified ID not found.'}, status=status.HTTP_404_NOT_FOUND)
        else:
            plan = SalesDailyPlan.objects.create(
                user=request.user,
                plan_date=plan_date,
                description=description,
                type=event_type,
                start_time=start_time,
                end_time=end_time,
                place=place,
            )
            created = True

        # Link day's activity container to the plan
        activity, act_created = SalesDailyActivity.objects.get_or_create(
            user=request.user,
            activity_date=plan_date,
            defaults={'plan': plan, 'notes': ''},
        )
        if not act_created and not activity.plan:
            activity.plan = plan
            activity.save(update_fields=['plan', 'updated_at'])

        return Response(
            SalesDailyPlanSerializer(plan, context={'request': request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class SalesDailyPlanDetailView(APIView):
    """
    GET    /api/v1/sales/plans/<uuid:pk>/ — View a specific sales plan / scheduled event.
    PUT    /api/v1/sales/plans/<uuid:pk>/ — Update a specific sales plan / scheduled event.
    PATCH  /api/v1/sales/plans/<uuid:pk>/ — Partial update of a sales plan / scheduled event.
    DELETE /api/v1/sales/plans/<uuid:pk>/ — Delete a sales plan / scheduled event.
    """
    permission_classes = [IsAuthenticated]

    def get_object(self, pk, user):
        try:
            plan = SalesDailyPlan.objects.select_related('user').prefetch_related(
                'activities', 'activities__photos', 'activities__odometer_reading',
            ).get(pk=pk)
        except SalesDailyPlan.DoesNotExist:
            return None

        if user.role not in ODOMETER_APPROVER_ROLES and plan.user_id != user.id:
            return None
        return plan

    def get(self, request, pk):
        plan = self.get_object(pk, request.user)
        if not plan:
            return Response({'detail': 'Sales plan not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = SalesDailyPlanSerializer(plan, context={'request': request})
        return Response(serializer.data)

    def patch(self, request, pk):
        plan = self.get_object(pk, request.user)
        if not plan:
            return Response({'detail': 'Sales plan not found or permission denied.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = SalesDailyPlanSerializer(plan, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        updated_plan = serializer.save()
        return Response(SalesDailyPlanSerializer(updated_plan, context={'request': request}).data)

    def put(self, request, pk):
        return self.patch(request, pk)

    def delete(self, request, pk):
        plan = self.get_object(pk, request.user)
        if not plan:
            return Response({'detail': 'Sales plan not found or permission denied.'}, status=status.HTTP_404_NOT_FOUND)
        plan.delete()
        return Response({'success': True, 'message': 'Sales plan deleted successfully.'}, status=status.HTTP_200_OK)


class SalesActivityPhotoView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, activity_id):
        try:
            activity = SalesDailyActivity.objects.select_related('user').get(id=activity_id)
        except SalesDailyActivity.DoesNotExist:
            return Response({'detail': 'Sales activity not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not _sales_activity_access(request.user, activity):
            return Response({'detail': 'You cannot upload photos for this activity.'}, status=status.HTTP_403_FORBIDDEN)

        photo_type = request.data.get('photo_type')
        if photo_type == 'exhibition' and activity.photos.filter(photo_type='exhibition').count() >= 6:
            return Response({'detail': 'A maximum of 6 exhibition photos is allowed.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = SalesActivityPhotoSerializer(data={
            'photo_type': photo_type,
            'photo': request.FILES.get('photo'),
            'latitude': request.data.get('latitude'),
            'longitude': request.data.get('longitude'),
            'odometer_kms': request.data.get('odometer_kms') or None,
            'captured_at': request.data.get('captured_at') or timezone.now(),
        })
        serializer.is_valid(raise_exception=True)
        photo = serializer.save(activity=activity)

        # ── Attendance Check-in / Check-out on Start and End Selfies ──
        attendance_info = None
        if photo_type == 'start_selfie':
            try:
                from attendance.models import EmployeeAttendanceRecord
                from core.utils import get_user_branch_id
                today = activity.activity_date

                # Check if user already checked in today (e.g. via QR or selfie)
                already_checked_in = EmployeeAttendanceRecord.objects.filter(
                    user=activity.user,
                    date=today,
                    checked_in_at__isnull=False,
                ).exists()

                if not already_checked_in:
                    bid = get_user_branch_id(activity.user) or getattr(activity.user, 'branch_id', None)
                    if not bid:
                        from branch.models import Branch
                        first_branch = Branch.objects.filter(organization=activity.user.organization).first() or Branch.objects.first()
                        bid = first_branch.id if first_branch else None

                    if bid:
                        # Clear stale absent record
                        EmployeeAttendanceRecord.objects.filter(
                            user=activity.user, date=today, status='absent'
                        ).delete()

                        checkin_time = photo.captured_at or timezone.now()
                        rec = EmployeeAttendanceRecord.objects.create(
                            user=activity.user,
                            branch_id=bid,
                            date=today,
                            status='checkout_pending',
                            checked_in_at=checkin_time,
                            latitude=photo.latitude,
                            longitude=photo.longitude,
                            location_verified=False,
                            marked_by=activity.user,
                        )
                        attendance_info = {
                            'action': 'check_in',
                            'record_id': str(rec.id),
                            'status': 'checkout_pending',
                            'checked_in_at': rec.checked_in_at.isoformat(),
                        }
                    else:
                        logger.warning(f"Could not auto check-in user {activity.user.id}: no branch found")
                else:
                    attendance_info = {'action': 'none', 'message': 'Already checked in for today'}
            except Exception as e:
                logger.error(f"Auto check-in on start_selfie failed: {e}", exc_info=True)

        elif photo_type == 'end_selfie':
            try:
                from attendance.models import EmployeeAttendanceRecord
                from core.utils import get_user_branch_id
                today = activity.activity_date

                # Check if user already checked out today (e.g. via QR or selfie)
                already_checked_out = EmployeeAttendanceRecord.objects.filter(
                    user=activity.user,
                    date=today,
                    checked_out_at__isnull=False,
                ).exists()

                if not already_checked_out:
                    checkout_time = photo.captured_at or timezone.now()
                    open_rec = EmployeeAttendanceRecord.objects.filter(
                        user=activity.user,
                        date=today,
                        checked_in_at__isnull=False,
                        checked_out_at__isnull=True,
                    ).order_by('-checked_in_at').first()

                    if open_rec:
                        open_rec.checked_out_at = checkout_time
                        open_rec.status = 'present'
                        role = getattr(activity.user, 'role', '')
                        if role not in {'faculty', 'sweeper', 'maid', 'driver'} and open_rec.checked_in_at:
                            duration_mins = int((checkout_time - open_rec.checked_in_at).total_seconds() / 60)
                            shortfall = max(0, 540 - duration_mins)
                            open_rec.shortfall_minutes = shortfall
                        open_rec.save()
                        attendance_info = {
                            'action': 'check_out',
                            'record_id': str(open_rec.id),
                            'status': open_rec.status,
                            'checked_out_at': open_rec.checked_out_at.isoformat(),
                        }
                    else:
                        bid = get_user_branch_id(activity.user) or getattr(activity.user, 'branch_id', None)
                        if not bid:
                            from branch.models import Branch
                            first_branch = Branch.objects.filter(organization=activity.user.organization).first() or Branch.objects.first()
                            bid = first_branch.id if first_branch else None

                        if bid:
                            EmployeeAttendanceRecord.objects.filter(
                                user=activity.user, date=today, status='absent'
                            ).delete()
                            rec = EmployeeAttendanceRecord.objects.create(
                                user=activity.user,
                                branch_id=bid,
                                date=today,
                                status='present',
                                checked_in_at=checkout_time,
                                checked_out_at=checkout_time,
                                latitude=photo.latitude,
                                longitude=photo.longitude,
                                location_verified=False,
                                marked_by=activity.user,
                            )
                            attendance_info = {
                                'action': 'check_out',
                                'record_id': str(rec.id),
                                'status': 'present',
                                'checked_out_at': rec.checked_out_at.isoformat(),
                            }
                else:
                    attendance_info = {'action': 'none', 'message': 'Already checked out for today'}
            except Exception as e:
                logger.error(f"Auto check-out on end_selfie failed: {e}", exc_info=True)

        # ── Auto-sync Odometer Reading ──
        if photo_type in {'start_odometer', 'end_odometer'}:
            start_photo = activity.photos.filter(photo_type='start_odometer').first()
            end_photo = activity.photos.filter(photo_type='end_odometer').first()

            start_kms = start_photo.odometer_kms if start_photo else None
            end_kms = end_photo.odometer_kms if end_photo else None
            vehicle_type = request.data.get('vehicle_type')

            reading_defaults = {
                'user': activity.user,
                'start_kms': start_kms,
                'end_kms': end_kms,
            }
            if vehicle_type:
                reading_defaults['vehicle_type'] = vehicle_type

            reading, created = OdometerReading.objects.get_or_create(
                activity=activity,
                defaults=reading_defaults
            )
            if not created:
                if vehicle_type:
                    reading.vehicle_type = vehicle_type
                if start_kms is not None:
                    reading.start_kms = start_kms
                if end_kms is not None:
                    reading.end_kms = end_kms
                reading.save()
            else:
                reading.save()

            # If both start and end odometer photos exist, notify approvers
            if start_photo and end_photo and start_photo.odometer_kms is not None and end_photo.odometer_kms is not None:
                try:
                    staff_name = activity.user.name or activity.user.email
                    vtype_label = reading.get_vehicle_type_display()
                    notify_users_by_role(
                        roles=['super_admin', 'admin_senior_executive', 'accountant'],
                        title='New Odometer Reading for Approval',
                        body=f"{staff_name} submitted an odometer reading for {activity.activity_date} ({reading.total_kms} km, {vtype_label} @ ₹{reading.expense_per_km}/km = ₹{reading.total_expense}).",
                        metadata={
                            'odometer_reading_id': str(reading.id),
                            'sales_activity_id': str(activity.id),
                            'type': 'odometer_submitted',
                        },
                        notification_type='sales',
                    )
                    if activity.user.branch:
                        notify_users_by_role(
                            roles=['branch_manager'],
                            branch=activity.user.branch,
                            title='New Odometer Reading for Approval',
                            body=f"{staff_name} submitted an odometer reading for {activity.activity_date} ({reading.total_kms} km, {vtype_label} @ ₹{reading.expense_per_km}/km = ₹{reading.total_expense}).",
                            metadata={
                                'odometer_reading_id': str(reading.id),
                                'sales_activity_id': str(activity.id),
                                'type': 'odometer_submitted',
                            },
                            notification_type='sales',
                        )
                except Exception as e:
                    logger.error(f"Failed to notify approvers for odometer reading {reading.id}: {e}")

        resp_data = SalesActivityPhotoSerializer(photo, context={'request': request}).data
        if attendance_info:
            resp_data['attendance'] = attendance_info
        return Response(resp_data, status=status.HTTP_201_CREATED)


class OdometerReadingListView(APIView):
    """
    GET /api/sales/odometer-readings/
    List odometer readings.
    - Admins/managers see all (or branch-scoped).
    - Sales staff see only their own.
    Supports query params:
    - ?status=pending|approved|rejected
    - ?user_id=<uuid>
    - ?search=<name/email/phone>
    - ?date=YYYY-MM-DD|today
    - ?from_date=YYYY-MM-DD
    - ?to_date=YYYY-MM-DD
    - ?is_paid=true|false
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        role = getattr(user, 'role', None)
        is_approver = role in ODOMETER_APPROVER_ROLES

        if not is_approver and role not in SALES_ROLES:
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        queryset = OdometerReading.objects.select_related(
            'activity', 'user', 'approved_by', 'rejected_by', 'payroll_run', 'payslip'
        ).prefetch_related('activity__photos')

        if not is_approver:
            queryset = queryset.filter(user=user)
        elif role == 'branch_manager':
            branch_ids = get_user_branch_ids(user)
            if branch_ids:
                queryset = queryset.filter(user__branch_id__in=branch_ids)

        # Filters
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        user_id = request.query_params.get('user_id')
        if user_id:
            if is_approver or str(user.id) == str(user_id):
                queryset = queryset.filter(user_id=user_id)
            else:
                return Response({'detail': 'You can only view your own odometer readings.'}, status=status.HTTP_403_FORBIDDEN)

        search = request.query_params.get('search') or request.query_params.get('name')
        if search:
            queryset = queryset.filter(
                Q(user__name__icontains=search) |
                Q(user__email__icontains=search) |
                Q(user__phone__icontains=search)
            )

        date_param = request.query_params.get('date')
        if date_param:
            if date_param.lower() == 'today':
                queryset = queryset.filter(activity__activity_date=timezone.localdate())
            else:
                try:
                    parsed_date = datetime.strptime(date_param, '%Y-%m-%d').date()
                    queryset = queryset.filter(activity__activity_date=parsed_date)
                except ValueError:
                    return Response({'detail': 'Invalid date format. Use YYYY-MM-DD or "today".'}, status=status.HTTP_400_BAD_REQUEST)

        from_date = request.query_params.get('from_date')
        if from_date:
            try:
                parsed_from = datetime.strptime(from_date, '%Y-%m-%d').date()
                queryset = queryset.filter(activity__activity_date__gte=parsed_from)
            except ValueError:
                return Response({'detail': 'Invalid from_date format. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

        to_date = request.query_params.get('to_date')
        if to_date:
            try:
                parsed_to = datetime.strptime(to_date, '%Y-%m-%d').date()
                queryset = queryset.filter(activity__activity_date__lte=parsed_to)
            except ValueError:
                return Response({'detail': 'Invalid to_date format. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

        is_paid = request.query_params.get('is_paid')
        if is_paid is not None:
            queryset = queryset.filter(is_paid=is_paid.lower() in ('true', '1'))

        queryset = queryset.order_by('-activity__activity_date', '-created_at')
        serializer = OdometerReadingSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)


class OdometerReadingDetailView(APIView):
    """
    GET /api/sales/odometer-readings/<uuid:pk>/
    Fetch a single odometer reading.
    PATCH /api/sales/odometer-readings/<uuid:pk>/
    Update vehicle_type or details on a pending odometer reading.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            reading = OdometerReading.objects.select_related(
                'activity', 'user', 'approved_by', 'rejected_by', 'payroll_run', 'payslip'
            ).prefetch_related('activity__photos').get(pk=pk)
        except OdometerReading.DoesNotExist:
            return Response({'detail': 'Odometer reading not found.'}, status=status.HTTP_404_NOT_FOUND)

        role = getattr(request.user, 'role', None)
        is_approver = role in ODOMETER_APPROVER_ROLES

        if not is_approver and reading.user_id != request.user.id:
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = OdometerReadingSerializer(reading, context={'request': request})
        return Response(serializer.data)

    def patch(self, request, pk):
        try:
            reading = OdometerReading.objects.select_related('activity', 'user').get(pk=pk)
        except OdometerReading.DoesNotExist:
            return Response({'detail': 'Odometer reading not found.'}, status=status.HTTP_404_NOT_FOUND)

        role = getattr(request.user, 'role', None)
        is_approver = role in ODOMETER_APPROVER_ROLES

        if not is_approver and reading.user_id != request.user.id:
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        if reading.is_paid:
            return Response({'detail': 'Cannot modify an odometer reading that has already been paid.'}, status=status.HTTP_400_BAD_REQUEST)

        if reading.status != 'pending' and not is_approver:
            return Response({'detail': 'Cannot modify an approved or rejected odometer reading.'}, status=status.HTTP_400_BAD_REQUEST)

        vehicle_type = request.data.get('vehicle_type')
        if vehicle_type:
            reading.vehicle_type = vehicle_type
            reading.calculate_totals()
            reading.save()

        serializer = OdometerReadingSerializer(reading, context={'request': request})
        return Response(serializer.data)


class OdometerReadingApproveView(APIView):
    """
    POST /api/sales/odometer-readings/<uuid:pk>/approve/
    Body: {"expense_per_km": 5.00} (Optional)
    Approves the reading, calculates total_expense using vehicle_type rate if omitted, and sends a 'sales' notification.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        role = getattr(request.user, 'role', None)
        if role not in ODOMETER_APPROVER_ROLES:
            return Response({'detail': 'Permission denied. Only managers/admins can approve odometer readings.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            reading = OdometerReading.objects.select_related('activity', 'user').get(pk=pk)
        except OdometerReading.DoesNotExist:
            return Response({'detail': 'Odometer reading not found.'}, status=status.HTTP_404_NOT_FOUND)

        if role == 'branch_manager' and reading.user.branch_id:
            if not has_user_branch_access(request.user, reading.user.branch_id):
                return Response({'detail': 'Permission denied. Branch managers can only approve readings for their branch.'}, status=status.HTTP_403_FORBIDDEN)

        if reading.is_paid:
            return Response({'detail': 'Cannot modify an odometer reading that has already been paid in payroll.'}, status=status.HTTP_400_BAD_REQUEST)

        if reading.start_kms is None or reading.end_kms is None:
            return Response({'detail': 'Cannot approve odometer reading: both start and end odometer readings are required.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = OdometerApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        expense_per_km = serializer.validated_data.get('expense_per_km')
        from decimal import Decimal
        if expense_per_km is not None:
            reading.expense_per_km = expense_per_km
            reading.total_expense = (reading.total_kms * Decimal(str(expense_per_km))).quantize(Decimal('0.01'))
        else:
            # Pre-calculated automatically based on vehicle_type: 5/km for 2-wheeler, 12/km for 4-wheeler
            reading.calculate_totals()

        reading.status = 'approved'
        reading.approved_by = request.user
        reading.approved_at = timezone.now()
        reading.rejected_by = None
        reading.rejected_at = None
        reading.rejection_reason = ''
        reading.save()

        # Send in-app notification to employee
        try:
            send_system_notification(
                user_id=str(reading.user.id),
                title='Odometer Reading Approved',
                body=f"Your odometer reading for {reading.activity.activity_date} ({reading.total_kms} km @ ₹{reading.expense_per_km}/km = ₹{reading.total_expense}) has been approved.",
                metadata={
                    'odometer_reading_id': str(reading.id),
                    'sales_activity_id': str(reading.activity_id),
                    'type': 'odometer_approved',
                    'route': f"/sales/odometer-readings/{reading.id}",
                },
                notification_type='sales',
            )
        except Exception as e:
            logger.error(f"Failed to notify user for approved odometer reading {reading.id}: {e}")

        return Response({
            'success': True,
            'message': f"Odometer reading approved ({reading.total_kms} km @ ₹{reading.expense_per_km}/km = ₹{reading.total_expense}). Added to upcoming payslip.",
            'data': OdometerReadingSerializer(reading, context={'request': request}).data
        }, status=status.HTTP_200_OK)


class OdometerReadingRejectView(APIView):
    """
    POST /api/sales/odometer-readings/<uuid:pk>/reject/
    Body: {"rejection_reason": "Distance does not match logs"}
    Rejects the reading and sends a 'sales' notification.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        role = getattr(request.user, 'role', None)
        if role not in ODOMETER_APPROVER_ROLES:
            return Response({'detail': 'Permission denied. Only managers/admins can reject odometer readings.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            reading = OdometerReading.objects.select_related('activity', 'user').get(pk=pk)
        except OdometerReading.DoesNotExist:
            return Response({'detail': 'Odometer reading not found.'}, status=status.HTTP_404_NOT_FOUND)

        if role == 'branch_manager' and reading.user.branch_id:
            if not has_user_branch_access(request.user, reading.user.branch_id):
                return Response({'detail': 'Permission denied. Branch managers can only reject readings for their branch.'}, status=status.HTTP_403_FORBIDDEN)

        if reading.is_paid:
            return Response({'detail': 'Cannot modify an odometer reading that has already been paid in payroll.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = OdometerRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data.get('rejection_reason', '')
        reading.status = 'rejected'
        reading.rejected_by = request.user
        reading.rejected_at = timezone.now()
        reading.rejection_reason = reason
        reading.approved_by = None
        reading.approved_at = None
        reading.save()

        # Send in-app notification to employee
        try:
            send_system_notification(
                user_id=str(reading.user.id),
                title='Odometer Reading Rejected',
                body=f"Your odometer reading for {reading.activity.activity_date} has been rejected." + (f" Reason: {reason}" if reason else ""),
                metadata={
                    'odometer_reading_id': str(reading.id),
                    'sales_activity_id': str(reading.activity_id),
                    'type': 'odometer_rejected',
                    'route': f"/sales/odometer-readings/{reading.id}",
                },
                notification_type='sales',
            )
        except Exception as e:
            logger.error(f"Failed to notify user for rejected odometer reading {reading.id}: {e}")

        return Response({
            'success': True,
            'message': 'Odometer reading rejected.',
            'data': OdometerReadingSerializer(reading, context={'request': request}).data
        }, status=status.HTTP_200_OK)


class TriggerSalesRemindersView(APIView):
    """
    POST /api/v1/sales/plans/send-reminders/
    Manually evaluate and trigger sales event reminders (1 day before and day of event).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _sales_activity_access(request.user):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        from .tasks import send_sales_plan_reminders
        stats = send_sales_plan_reminders()
        return Response({
            'success': True,
            'message': 'Sales plan reminders evaluated and sent successfully.',
            'data': stats,
        }, status=status.HTTP_200_OK)


def get_lead_queryset(request):
    """
    Returns a Lead queryset scoped to the requesting user's role.

    - Counsellor / Tele Caller / Sales Executive  → only their assigned leads.
    - All other authenticated roles (Senior / Manager / Admin / Front Desk)
      → all leads within their organisation.
    - Unauthenticated (AllowAny endpoints)  → all leads (no personal data risk
      here since POST is public form submission and GET requires authentication).
    """
    queryset = Lead.objects.all().order_by("-created_at")

    # Scope by organisation when available
    if getattr(request.user, 'organization', None):
        queryset = queryset.filter(branch__organization=request.user.organization)

    user = request.user
    if user.is_authenticated:
        role = getattr(user, 'role', None)
        if role in RESTRICTED_ROLES:
            # These roles can ONLY see leads assigned to them
            queryset = queryset.filter(assigned_to=user)

    return queryset


class LeadListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['current_stage', 'course', 'form_type']
    search_fields = ['first_name', 'surname', 'email', 'phone_student']
    ordering_fields = '__all__'

    def get_permissions(self):
        if self.request.method == 'POST':
            return [AllowAny()]
        return [IsAuthenticated()]

    permission_classes=[AllowAny]

    def post(self, request):

        form_type = request.data.get('form_type')

        if not form_type:
            return Response(
                {
                    "success": False,
                    "message": "form_type is required.",
                    "errors": {"form_type": ["This field is required."]}
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            serializer = get_lead_serializer(
                form_type=form_type,
                data=request.data,
                files=request.FILES or None
            )
        except ValidationError as e:
            return Response(
                {
                    "success": False,
                    "message": "Invalid form type.",
                    "form_type": form_type,
                    "form_type_display": FORM_TYPE_DISPLAY.get(form_type),
                    "valid_form_types": [
                        {"value": key, "display": label}
                        for key, label in FORM_TYPE_CHOICES
                    ],
                    "errors": e.detail
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if not serializer.is_valid():
            logger.warning(
                f"Lead validation failed — form_type: {form_type} | "
                f"errors: {serializer.errors}"
            )
            return Response(
                {
                    "success": False,
                    "message": "Please fix the errors below.",
                    "errors": serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        validated_data = serializer.validated_data

        first_name = validated_data.get("first_name", "").strip()
        surname = validated_data.get("surname", "").strip()

        email = validated_data.get("email", "")
        email = email.strip().lower() if email else ""

        phone_student = validated_data.get("phone_student", "")
        phone_student = re.sub(r"\D", "", phone_student)

        course = validated_data.get("course")

        duplicate_lead = Lead.objects.filter(
            first_name__iexact=first_name,
            surname__iexact=surname,
            course=course
        ).filter(
            Q(email__iexact=email) |
            Q(phone_student=phone_student)
        ).first()

        try:
            lead = LeadService.create_lead(
                validated_data=validated_data,
                user=request.user if request.user.is_authenticated else None,
            )
        except Exception as e:
            logger.error(f"Lead creation error — {str(e)}")
            return Response(
                {
                    "success": False,
                    "message": "Something went wrong. Please try again.",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        tag = "duplicate" if duplicate_lead else "new"

        # Send notification to admins
        from core.utils import notify_users_by_role
        notify_users_by_role(
            roles=['super_admin', 'branch_manager', 'front_desk', 'admin_executive'],
            title='New Lead Received',
            body=f"A new lead ({lead.first_name} {lead.surname or ''}) has submitted a {FORM_TYPE_DISPLAY.get(lead.form_type, lead.form_type)} form.",
            organization=lead.branch.organization if getattr(lead, 'branch', None) else None,
            branch=lead.branch if getattr(lead, 'branch', None) else None,
        )

        return Response(
            {
                "success": True,
                "message": "Thank you! Your inquiry has been received. We will contact you shortly.",
                "tag": tag,
                "data": {
                    "lead_id":             lead.id,
                    "form_type":           lead.form_type,
                    "form_type_display":   FORM_TYPE_DISPLAY.get(lead.form_type),
                    "course":              lead.course,
                    "course_display":      COURSE_DISPLAY.get(lead.course),
                    "group_module":        lead.group_module,
                    "group_module_display": GROUP_MODULE_DISPLAY.get(lead.group_module),
                    "batch_attempt":       lead.batch_attempt,
                    "batch_attempt_display": ATTEMPT_DISPLAY.get(lead.batch_attempt),
                    "name":                lead.first_name,
                    "stage":               lead.current_stage,
                    "stage_display":       STAGE_DISPLAY.get(lead.current_stage),
                    "assigned_to_id":      str(lead.assigned_to.id) if lead.assigned_to else None,
                    "assigned_to_name":    lead.assigned_to.name if lead.assigned_to else None,
                }
            },
            status=status.HTTP_201_CREATED
        )

    def get(self, request):

        queryset = get_lead_queryset(request)

        # Optional filters
        stage = request.GET.get("stage")
        course = request.GET.get("course")
        form_type = request.GET.get("form_type")

        if stage:
            queryset = queryset.filter(current_stage=stage)

        if course:
            queryset = queryset.filter(course=course)

        if form_type:
            queryset = queryset.filter(form_type=form_type)

        queryset = apply_filters(self, request, queryset)

        return paginate_queryset(queryset, request, LeadListSerializer)


class LeadStatusUpdateView(APIView):
    permission_classes=[AllowAny]
    def patch(self, request, lead_id):
        # Find lead
        try:
            queryset = Lead.objects.all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(branch__organization=request.user.organization)
            lead = queryset.get(id=lead_id)
        except Lead.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "message": "Lead not found."
                },
                status=status.HTTP_404_NOT_FOUND
            )
        # Validate input
        serializer = LeadStageUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "errors": serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        new_stage = serializer.validated_data["stage"]
        note = serializer.validated_data.get("note", "")

        old_stage = lead.current_stage

        # ── Handle conversion: auto-create Admission record ──────────────────
        admission_created = False
        if new_stage == 'converted' and old_stage != 'converted':
            try:
                from onboarding.models import Admission
                from onboarding.utils import AdmissionService

                # Check if an admission already exists for this lead
                if not Admission.objects.filter(lead=lead).exists():
                    # Build admission data from lead fields
                    admission_data = {
                        'lead_id':          lead.id,
                        'first_name':       lead.first_name,
                        'surname':          lead.surname or '',
                        'father_name':      lead.father_name or '',
                        'mother_name':      '',
                        'dob':              None,
                        'category':         'gen',
                        'email':            lead.email or '',
                        'email_parent':     '',
                        'phone_student':    lead.phone_student or '',
                        'phone_student_2':  '',
                        'phone_father':     lead.phone_father or '',
                        'phone_father_2':   '',
                        'street':           lead.street or '',
                        'apartment':        lead.apartment or '',
                        'city':             lead.city or '',
                        'state':            lead.state or '',
                        'pincode':          '',
                        'country':          lead.country or 'India',
                        'course':           lead.course or 'cseet',
                        'group_module':     lead.group_module or 'full',
                        'batch_attempt':    lead.batch_attempt or 'june',
                        'location':         lead.location or '',
                        'qualification':    lead.qualification or 'appearing_12',
                        'reference':        lead.reference or 'none',
                        'consent':          True,
                        'tenth_medium':     lead.tenth_medium or 'cbse',
                        'tenth_school':     lead.tenth_school or '',
                        'tenth_coaching':   lead.tenth_coaching or '',
                        'tenth_percentage': lead.tenth_percentage or 0,
                        'tenth_percentile': lead.tenth_percentile or 0,
                        'twelfth_medium':   lead.twelfth_medium or 'cbse',
                        'twelfth_school':   lead.twelfth_school or '',
                        'twelfth_coaching': lead.twelfth_coaching or '',
                        'twelfth_percentage': lead.twelfth_percentage or 0,
                        'twelfth_percentile': lead.twelfth_percentile or 0,
                        'grad_university':  lead.grad_university or '',
                        'grad_college':     lead.grad_college or '',
                        'grad_last_sem':    lead.grad_last_sem or '',
                    }

                    # ── AUTO-ASSIGN COUNSELLOR VIA ROUND-ROBIN (commented out: now manual) ──
                    # The block below previously auto-assigned a counsellor to the Admission
                    # record when a lead was converted. This has been replaced by manual
                    # assignment on the Lead itself (Lead.assigned_to). The Admission is now
                    # created with assigned_counsellor=None and must be set manually.
                    #
                    # assigned_counsellor = AdmissionService.get_next_counsellor()
                    assigned_counsellor = lead.assigned_to
 

                    # Create Admission with status='form_pending' (no credentials yet)
                    counsellor_name = assigned_counsellor.name if assigned_counsellor else 'Unassigned'
                    auto_note = f'Auto-created from converted lead #{lead.id}. Waiting for student to submit the admission form.'
                    
                    admission = Admission(
                        id=lead.id,
                        lead=lead,
                        branch=lead.branch,
                        status='form_pending',
                        note=auto_note,
                        assigned_counsellor=assigned_counsellor,
                        **{k: v for k, v in admission_data.items() if k != 'lead_id'},
                    )
                    admission.save()

                    from onboarding.models import AdmissionStatusHistory
                    AdmissionStatusHistory.objects.create(
                        admission=admission,
                        status='form_pending',
                        changed_by=request.user if request.user.is_authenticated else None,
                        note=auto_note,
                    )

                    admission_created = True
                    logger.info(
                        f"Admission {admission.id} auto-created from converted lead {lead.id}, "
                        f"assigned to counsellor: {counsellor_name}"
                    )
                    
                    if admission.email:
                        try:
                            admission_link = f"{settings.FRONTEND_BASE_URL}/insight/student/admission-form?id={lead.id}"
                            subject = "Complete Your Admission Process"
                            text_content = f"Hello {admission.first_name},\n\nWe are thrilled to welcome you! Your lead has been converted, and we are ready to proceed with your admission.\n\nPlease click the link below to complete your admission form and upload the necessary documents:\n\n{admission_link}\n\nIf you have any questions, feel free to reach out.\n\nBest Regards,\nInsight Institute Team"
                            
                            template_context = {
                                'student_name': admission.first_name,
                                'admission_link': admission_link,
                                'primary_color': '#ed7c31',
                                'org_name': getattr(admission.branch.organization, 'name', 'Insight Institute of Professional Studies') if getattr(admission, 'branch', None) and getattr(admission.branch, 'organization', None) else 'Insight Institute of Professional Studies',
                            }
                            
                            send_email(
                                to=admission.email,
                                subject=subject,
                                text=text_content,
                                template="emails/admission_process.html",
                                template_context=template_context,
                                organization=admission.branch.organization if getattr(admission, 'branch', None) else None,
                            )
                            
                            try:
                                send_whatsapp_with_fallback(
                                    to=admission.phone_student,
                                    template_name="admission_process_",
                                    language_code="en",
                                    components=[{"type": "body", "parameters": [{"type": "text", "text": admission.first_name}]}],
                                    fallback_body=text_content,
                                )
                            except Exception as e:
                                print(e)
                            logger.info(f"Admission form email sent to {admission.email}")
                        except Exception as e:
                            logger.error(f"Failed to send admission form email to {admission.email}: {e}")

            except Exception as e:
                logger.error(f"Error creating admission for lead {lead.id}: {str(e)}")
                return Response(
                    {
                        "success": False,
                        "message": f"Error creating admission record: {str(e)}"
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        # Update lead current stage and note
        lead.current_stage = new_stage
        lead.note = note
        today = timezone.now().date()

        print(serializer.validated_data)
        
        if new_stage == "contacted":
            lead.contacted_at = today

        elif new_stage == "interested":
            lead.interested_at = today

        elif new_stage == "follow_up":
            lead.followup_set_at = today
            lead.followup_date = serializer.validated_data.get("followup_date")

        elif new_stage == "converted":
            lead.converted_at = today

        elif new_stage == "lost":
            lead.lost_at = today

        elif new_stage == "visit":
            lead.visit_set_at = today
            lead.visit_date = serializer.validated_data.get("visit_date")

        elif new_stage == "visited":
            lead.is_visited = True

        if "is_visited" in serializer.validated_data:
            lead.is_visited = serializer.validated_data["is_visited"]

        lead.updated_by = request.user

        lead.save()

        # Create stage history
        LeadStage.objects.create(
            lead=lead,
            stage=new_stage,
            changed_by=request.user if request.user.is_authenticated else None,
            note=note
        )

        message = "Lead status updated successfully."
        response_data = {
            "lead_id": lead.id,
            "current_stage": lead.current_stage,
            "note": lead.note,
        }

        if admission_created:
            message += " Admission record created and assigned for counsellor review."
            counsellor_info = None
            if assigned_counsellor:
                counsellor_info = {
                    "id":    str(assigned_counsellor.id),
                    "name":  assigned_counsellor.name,
                    "email": assigned_counsellor.email,
                }
            response_data["admission"] = {
                "admission_id": admission.id,
                "status": admission.status,
                "assigned_counsellor": counsellor_info,
            }

        return Response(
            {
                "success": True,
                "message": message,
                "data": response_data,
            },
            status=status.HTTP_200_OK
        )



class LeadDetailView(APIView):
    permission_classes=[AllowAny]

    """
    GET    /leads/<id>/   — retrieve a single lead (full detail)
    PUT    /leads/<id>/   — full update
    PATCH  /leads/<id>/   — partial update
    DELETE /leads/<id>/   — soft-delete / hard-delete
    """

    def _get_lead(self, request, lead_id):
        try:
            return get_lead_queryset(request).get(id=lead_id)
        except Lead.DoesNotExist:
            return None

    # ── GET ────────────────────────────────────────────────────────────
    def get(self, request, lead_id):
        lead = self._get_lead(request, lead_id)
        if lead is None:
            return Response(
                {"success": False, "message": "Lead not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = LeadDetailSerializer(lead)
        return Response(
            {"success": True, "data": serializer.data},
            status=status.HTTP_200_OK
        )

    # ── PUT / PATCH ───────────────────────────────────────────────
    def _update(self, request, lead_id, partial: bool):
        lead = self._get_lead(request, lead_id)
        if lead is None:
            return Response(
                {"success": False, "message": "Lead not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = LeadUpdateSerializer(lead, data=request.data, partial=partial)
        if not serializer.is_valid():
            logger.warning(
                f"Lead update validation failed — lead_id: {lead_id} | "
                f"errors: {serializer.errors}"
            )
            return Response(
                {
                    "success": False,
                    "message": "Please fix the errors below.",
                    "errors": serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer.save()
        return Response(
            {
                "success": True,
                "message": "Lead updated successfully.",
                "data": LeadDetailSerializer(lead).data
            },
            status=status.HTTP_200_OK
        )

    def put(self, request, lead_id):
        return self._update(request, lead_id, partial=False)

    def patch(self, request, lead_id):
        return self._update(request, lead_id, partial=True)

    # ── DELETE ───────────────────────────────────────────────────
    def delete(self, request, lead_id):
        lead = self._get_lead(request, lead_id)
        if lead is None:
            return Response(
                {"success": False, "message": "Lead not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        lead.delete()
        return Response(
            {"success": True, "message": f"Lead {lead_id} deleted successfully."},
            status=status.HTTP_200_OK
        )


# ── Lead Reassign View ──────────────────────────────────────────────────────

class LeadReassignView(APIView):
    """
    PATCH /leads/<lead_id>/reassign/

    Manually reassign a lead to a different Counsellor / Sales Executive.
    Restricted to: Sales Senior Executive, Branch Manager, Super Admin.

    Request body:
        {
            "assigned_to": "<user-uuid>",   # required; pass null to unassign
            "note": "Reason for reassignment"  # optional
        }
    """
    permission_classes = [AllowAny]

    # Roles permitted to reassign leads
    ALLOWED_ROLES = {'sales_senior_executive', 'branch_manager', 'super_admin'}

    def patch(self, request, lead_id):
        # ── Role check (soft — returns 403 without changing permission_classes) ──
        user = request.user
        if not user.is_authenticated:
            return Response(
                {"success": False, "message": "Authentication required to reassign leads."},
                status=status.HTTP_403_FORBIDDEN,
            )
        user_role = getattr(user, 'role', None)
        if user_role not in self.ALLOWED_ROLES:
            return Response(
                {
                    "success": False,
                    "message": (
                        "Only Sales Senior Executives, Branch Managers, and "
                        "Super Admins can reassign leads."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── Fetch lead (all leads visible to senior roles) ──────────────────
        try:
            queryset = Lead.objects.all()
            if getattr(user, 'organization', None):
                queryset = queryset.filter(branch__organization=user.organization)
            lead = queryset.get(id=lead_id)
        except Lead.DoesNotExist:
            return Response(
                {"success": False, "message": "Lead not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Validate input ─────────────────────────────────────────────
        serializer = LeadReassignSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_assignee = serializer.validated_data['assigned_to']  # User instance or None
        note = serializer.validated_data.get('note', '')

        # ── Audit log ──────────────────────────────────────────────────
        previous_assignee = lead.assigned_to  # capture before update

        LeadAssignmentLog.objects.create(
            lead=lead,
            assigned_from=previous_assignee,
            assigned_to=new_assignee,
            changed_by=user,
            note=note or (
                f"Reassigned from "
                f"{'Unassigned' if not previous_assignee else previous_assignee.name} "
                f"to "
                f"{'Unassigned' if not new_assignee else new_assignee.name} "
                f"by {user.name}."
            ),
        )

        # ── Apply reassignment ───────────────────────────────────────────
        lead.assigned_to = new_assignee
        lead.updated_by = user
        lead.save(update_fields=['assigned_to', 'updated_by', 'updated_at'])

        logger.info(
            f"Lead {lead.id} reassigned: "
            f"{previous_assignee} → {new_assignee} by {user}"
        )

        if new_assignee:
            from chat.notifications import send_system_notification
            send_system_notification(
                user_id=str(new_assignee.id),
                title='Lead Assigned',
                body=f"You have been assigned a lead: {lead.first_name} {lead.surname or ''}.",
                metadata={'lead_id': str(lead.id)},
            )

        # ── Response ───────────────────────────────────────────────────
        return Response(
            {
                "success": True,
                "message": "Lead reassigned successfully.",
                "data": {
                    "lead_id":            lead.id,
                    "assigned_from_id":   str(previous_assignee.id)   if previous_assignee else None,
                    "assigned_from_name": previous_assignee.name       if previous_assignee else None,
                    "assigned_to_id":     str(new_assignee.id)         if new_assignee       else None,
                    "assigned_to_name":   new_assignee.name            if new_assignee       else None,
                    "reassigned_by":      user.name,
                    "note":               note,
                },
            },
            status=status.HTTP_200_OK,
        )


# ── Lead Assign View ────────────────────────────────────────────────────────

class LeadAssignView(APIView):
    """
    PATCH /leads/<lead_id>/assign/

    Assign an UNASSIGNED lead to a Counsellor / Sales Executive.
    Use this when a lead was created without an assignee and you want to
    assign it for the first time.

    Allowed roles: front_desk, sales_senior_executive, branch_manager, super_admin.

    To CHANGE an existing assignment use /leads/<id>/reassign/ instead
    (restricted to senior roles only).

    Request body:
        {
            "assigned_to": "<user-uuid>",       # required — cannot be null
            "note": "Assigning to Jane Smith"   # optional
        }
    """
    permission_classes = [AllowAny]

    # Roles permitted to do the initial assignment
    ALLOWED_ROLES = {'front_desk', 'sales_senior_executive', 'branch_manager', 'super_admin'}

    def patch(self, request, lead_id):
        # ── Auth + role check ────────────────────────────────────────────────
        user = request.user
        if not user.is_authenticated:
            return Response(
                {"success": False, "message": "Authentication required to assign leads."},
                status=status.HTTP_403_FORBIDDEN,
            )

        user_role = getattr(user, 'role', None)
        if user_role not in self.ALLOWED_ROLES:
            return Response(
                {
                    "success": False,
                    "message": (
                        "Only Front Desk Executives, Sales Senior Executives, "
                        "Branch Managers, and Super Admins can assign leads."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── Fetch lead ───────────────────────────────────────────────────────
        try:
            queryset = Lead.objects.all()
            if getattr(user, 'organization', None):
                queryset = queryset.filter(branch__organization=user.organization)
            lead = queryset.get(id=lead_id)
        except Lead.DoesNotExist:
            return Response(
                {"success": False, "message": "Lead not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Guard: already assigned — use /reassign/ instead ─────────────────
        if lead.assigned_to is not None:
            return Response(
                {
                    "success": False,
                    "message": (
                        f"This lead is already assigned to {lead.assigned_to.name}. "
                        "Use PATCH /leads/{id}/reassign/ to change the assignment "
                        "(requires Senior Executive / Manager role)."
                    ),
                    "current_assignee_id":   str(lead.assigned_to.id),
                    "current_assignee_name": lead.assigned_to.name,
                },
                status=status.HTTP_409_CONFLICT,
            )

        # ── Validate input ───────────────────────────────────────────────────
        # Re-use LeadReassignSerializer but override assigned_to to be non-nullable
        serializer = LeadReassignSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_assignee = serializer.validated_data['assigned_to']  # User instance
        note = serializer.validated_data.get('note', '')

        if new_assignee is None:
            return Response(
                {
                    "success": False,
                    "message": "assigned_to cannot be null for initial assignment. "
                               "Provide a valid user UUID.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Audit log ────────────────────────────────────────────────────────
        LeadAssignmentLog.objects.create(
            lead=lead,
            assigned_from=None,   # was unassigned
            assigned_to=new_assignee,
            changed_by=user,
            note=note or f"Assigned to {new_assignee.name} by {user.name}.",
        )

        # ── Apply assignment ─────────────────────────────────────────────────
        lead.assigned_to = new_assignee
        lead.updated_by = user
        lead.save(update_fields=['assigned_to', 'updated_by', 'updated_at'])

        logger.info(
            f"Lead {lead.id} assigned to {new_assignee} by {user}"
        )

        if new_assignee:
            from chat.notifications import send_system_notification
            send_system_notification(
                user_id=str(new_assignee.id),
                title='Lead Assigned',
                body=f"You have been assigned a new lead: {lead.first_name} {lead.surname or ''}.",
                metadata={'lead_id': str(lead.id)},
            )

        # ── Response ─────────────────────────────────────────────────────────
        return Response(
            {
                "success": True,
                "message": f"Lead successfully assigned to {new_assignee.name}.",
                "data": {
                    "lead_id":          lead.id,
                    "assigned_to_id":   str(new_assignee.id),
                    "assigned_to_name": new_assignee.name,
                    "assigned_by":      user.name,
                    "note":             note,
                },
            },
            status=status.HTTP_200_OK,
        )


from .serializers import LeadTransferRequestSerializer, LeadTransferApprovalSerializer
from .models import LeadTransferRequest
from auth_user.models import User

class LeadTransferRequestListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in SENIOR_ROLES:
            return Response({"error": "Permission denied. Only senior roles can view transfer requests."}, status=status.HTTP_403_FORBIDDEN)
        
        status_filter = request.query_params.get('status')
        queryset = LeadTransferRequest.objects.all()
        if status_filter:
            queryset = queryset.filter(status=status_filter)
            
        return paginate_queryset(queryset, request, LeadTransferRequestSerializer)

    def post(self, request):
        lead_id = request.data.get('lead_id')
        try:
            lead = Lead.objects.get(id=lead_id)
        except Lead.DoesNotExist:
            return Response({"error": "Lead not found."}, status=status.HTTP_404_NOT_FOUND)
        
        if lead.assigned_to != request.user:
            return Response({"error": "You can only request transfer for leads assigned to you."}, status=status.HTTP_403_FORBIDDEN)
            
        reason = request.data.get('reason', '')
        
        transfer_request = LeadTransferRequest.objects.create(
            lead=lead,
            requested_by=request.user,
            reason=reason
        )
        
        serializer = LeadTransferRequestSerializer(transfer_request)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class LeadTransferRequestReviewView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if request.user.role not in SENIOR_ROLES:
            return Response({"error": "Permission denied. Only senior roles can review transfer requests."}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            transfer_request = LeadTransferRequest.objects.get(id=pk)
        except LeadTransferRequest.DoesNotExist:
            return Response({"error": "Request not found."}, status=status.HTTP_404_NOT_FOUND)
            
        if transfer_request.status != 'pending':
            return Response({"error": "Only pending requests can be reviewed."}, status=status.HTTP_400_BAD_REQUEST)
            
        serializer = LeadTransferApprovalSerializer(data=request.data)
        if serializer.is_valid():
            status_decision = serializer.validated_data['status']
            assigned_to_id = serializer.validated_data.get('assigned_to')
            
            transfer_request.status = status_decision
            transfer_request.reviewed_by = request.user
            
            if status_decision == 'approved':
                lead = transfer_request.lead
                old_assignee = lead.assigned_to
                try:
                    new_assignee = User.objects.get(id=assigned_to_id)
                except User.DoesNotExist:
                    return Response({"error": "Counsellor not found."}, status=status.HTTP_404_NOT_FOUND)
                    
                lead.assigned_to = new_assignee
                lead.save()
                
                LeadAssignmentLog.objects.create(
                    lead=lead,
                    assigned_from=old_assignee,
                    assigned_to=new_assignee,
                    changed_by=request.user,
                    note=f"Approved transfer request #{transfer_request.id}"
                )
                
                transfer_request.assigned_to = new_assignee
                
                from chat.notifications import send_system_notification
                try:
                    send_system_notification(
                        user_id=str(new_assignee.id),
                        title='Lead Transferred',
                        body=f"A lead transfer has been approved. You are now assigned to: {lead.first_name} {lead.surname or ''}.",
                        metadata={'type': 'lead_transferred', 'lead_id': str(lead.id)},
                    )
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Failed to notify new assignee on transfer for lead {lead.id}: {e}")
            
            transfer_request.save()
            return Response(LeadTransferRequestSerializer(transfer_request).data)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
