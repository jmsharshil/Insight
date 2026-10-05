# leads/serializers.py

from decimal import Decimal
from rest_framework import serializers
from .models import (Lead, LeadAssignmentLog, LeadTransferRequest, SalesDailyPlan, SalesDailyActivity, SalesActivityPhoto, OdometerReading, SalesPlanReminder, SalesDailyActivityTiming, FORM_TYPE_CHOICES, COURSE_TYPE_CHOICES, GROUP_MODULE_CHOICES,
                     ATTEMPT_TYPE_CHOICES, STAGE_CHOICES, QUALIFICATION_TYPE_CHOICES,
                     BOARD_TYPE_CHOICES, REFERENCE_TYPE_CHOICES,)
from auth_user.models import User
from dateutil import parser
from django.utils import timezone

# ── Helpers ───────────────────────────────────────────────────────────────────

def validate_phone(value):
    digits = value.replace('+', '').replace(' ', '').replace('-', '')
    if not digits.isdigit():
        raise serializers.ValidationError("Phone number must contain only digits.")
    if not (10 <= len(digits) <= 15):
        raise serializers.ValidationError("Phone number must be between 10 and 15 digits.")
    return value


def validate_percentage(value):
    if value is not None and not (0 <= value <= 100):
        raise serializers.ValidationError("Percentage must be between 0 and 100.")
    return value


VALID_COMBINATIONS = {
    'cseet': {
        'group_module':  ['full'],
        'batch_attempt': ['june', 'oct', 'feb'],
    },
    'cs_executive': {
        'group_module':  ['both', 'module_1', 'module_2'],
        'batch_attempt': ['june', 'dec'],
    },
    'cs_professional': {
        'group_module':  ['both', 'module_1', 'module_2', 'module_3'],
        'batch_attempt': ['june', 'dec'],
    },
}

class FlexibleDateTimeField(serializers.DateTimeField):
    """
    Accepts multiple datetime formats automatically.
    """

    def to_internal_value(self, value):
        if value in (None, ''):
            return None

        try:
            # Unix timestamp support
            if isinstance(value, (int, float)):
                dt = timezone.datetime.fromtimestamp(value)

            elif str(value).isdigit():
                dt = timezone.datetime.fromtimestamp(int(value))

            else:
                dt = parser.parse(str(value))

            if timezone.is_naive(dt):
                dt = timezone.make_aware(
                    dt,
                    timezone.get_current_timezone()
                )

            return dt

        except Exception:
            raise serializers.ValidationError(
                "Invalid datetime format."
            )

class SalesDailyActivityTimingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesDailyActivityTiming
        fields = ['id', 'date', 'start_time', 'end_time']
        read_only_fields = ['id']

class SalesActivityPhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesActivityPhoto
        fields = [
            'id', 'activity', 'photo_type', 'name', 'photo',
            'latitude', 'longitude', 'odometer_kms', 'captured_at', 'created_at',
        ]
        read_only_fields = ['id', 'activity', 'created_at']

    def validate(self, attrs):
        photo_type = attrs.get('photo_type')
        odometer_kms = attrs.get('odometer_kms')
        if photo_type in {'start_odometer', 'end_odometer'} and odometer_kms is None:
            raise serializers.ValidationError({'odometer_kms': 'Required for odometer photos.'})
        if photo_type not in {'start_odometer', 'end_odometer'} and odometer_kms is not None:
            raise serializers.ValidationError({'odometer_kms': 'Only valid for odometer photos.'})
        return attrs

class OdometerReadingSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    activity_date = serializers.DateField(source='activity.activity_date', read_only=True)
    vehicle_type_display = serializers.CharField(source='get_vehicle_type_display', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.name', read_only=True, default=None)
    rejected_by_name = serializers.CharField(source='rejected_by.name', read_only=True, default=None)
    start_odometer_photo = serializers.SerializerMethodField()
    end_odometer_photo = serializers.SerializerMethodField()

    class Meta:
        model = OdometerReading
        fields = [
            'id', 'activity', 'activity_date', 'user', 'user_name', 'user_email',
            'vehicle_type', 'vehicle_type_display',
            'start_kms', 'end_kms', 'total_kms', 'expense_per_km', 'total_expense',
            'status', 'approved_by', 'approved_by_name', 'approved_at',
            'rejected_by', 'rejected_by_name', 'rejected_at', 'rejection_reason',
            'payroll_run', 'payslip', 'is_paid',
            'start_odometer_photo', 'end_odometer_photo',
            'created_at', 'updated_at'
        ]
        read_only_fields = fields

    def get_start_odometer_photo(self, obj):
        photo = obj.activity.photos.filter(photo_type='start_odometer').first()
        if photo and photo.photo:
            request = self.context.get('request')
            return request.build_absolute_uri(photo.photo.url) if request else photo.photo.url
        return None

    def get_end_odometer_photo(self, obj):
        photo = obj.activity.photos.filter(photo_type='end_odometer').first()
        if photo and photo.photo:
            request = self.context.get('request')
            return request.build_absolute_uri(photo.photo.url) if request else photo.photo.url
        return None


class OdometerApproveSerializer(serializers.Serializer):
    expense_per_km = serializers.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal('0.00'), required=False, allow_null=True,
        help_text="Optional reimbursement rate override per kilometer (defaults to vehicle_type rate: ₹5/km for bike, ₹12/km for car)."
    )
    total_kms = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal('0.00'), required=False, allow_null=True,
        help_text="Optional override for the total kilometers traveled."
    )


class OdometerRejectSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(
        required=False, allow_blank=True, default="",
        help_text="Reason for rejecting the odometer reading."
    )


class MonthlyOdometerApproveSerializer(serializers.Serializer):
    """Serializer for approving ALL pending odometer readings for a user in a given month."""
    user_id = serializers.UUIDField(required=True, help_text="UUID of the sales user")
    month = serializers.IntegerField(min_value=1, max_value=12, required=True)
    year = serializers.IntegerField(min_value=2020, max_value=2100, required=True)
    expense_per_km = serializers.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal('0.00'), required=False, allow_null=True,
        help_text="Optional reimbursement rate override per kilometer for ALL daily readings in the month (defaults to vehicle_type rate)."
    )
    total_kms = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal('0.00'), required=False, allow_null=True,
        help_text="Optional override for the total kilometers traveled for ALL daily readings in the month."
    )


class MonthlyOdometerRejectSerializer(serializers.Serializer):
    """Serializer for rejecting ALL pending odometer readings for a user in a given month."""
    user_id = serializers.UUIDField(required=True, help_text="UUID of the sales user")
    month = serializers.IntegerField(min_value=1, max_value=12, required=True)
    year = serializers.IntegerField(min_value=2020, max_value=2100, required=True)
    rejection_reason = serializers.CharField(
        required=False, allow_blank=True, default="",
        help_text="Reason for rejecting the monthly odometer claim."
    )


class SalesDailyActivitySerializer(serializers.ModelSerializer):
    photos = SalesActivityPhotoSerializer(many=True, read_only=True)
    user_name = serializers.CharField(source='user.name', read_only=True)
    odometer_reading = OdometerReadingSerializer(read_only=True)
    timings = SalesDailyActivityTimingSerializer(many=True, required=False)
    event_photo_slots = serializers.SerializerMethodField()
    inventory_items = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False,
        help_text="List of items to allocate: [{'item_id': '<uuid>', 'quantity': 1}]"
    )
    allocations = serializers.SerializerMethodField()
    violations = serializers.SerializerMethodField()

    class Meta:
        model = SalesDailyActivity
        fields = [
            'id', 'name', 'user', 'user_name', 'plan',
            'activity_date', 'status', 'notes', 'students_expected', 'students_attended',
            'standard', 'board', 'medium',
            'seminar_reference_by', 'seminar_given_by',
            'target_name', 'target_number',
            'location_link', 'from_date', 'to_date',
            'photos', 'odometer_reading', 'timings', 'event_photo_slots', 'inventory_items', 'allocations', 'violations',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user', 'user_name', 'photos', 'odometer_reading', 'event_photo_slots', 'violations', 'created_at', 'updated_at']

    def get_allocations(self, obj):
        from inventory.serializers import ItemAllocationSerializer
        return ItemAllocationSerializer(obj.inventory_allocations.all(), many=True).data

    def get_violations(self, obj):
        from datetime import datetime, timedelta, time
        from django.utils import timezone
        
        violations = []
        
        last_date = None
        end_time = None
        
        if obj.plan:
            last_timing = obj.timings.order_by('-date').first()
            if last_timing:
                last_date = last_timing.date
                end_time = last_timing.end_time
            else:
                last_date = obj.to_date or obj.activity_date or obj.plan.plan_date
                end_time = obj.plan.end_time
        elif obj.name == "Daily Field Operations":
            last_date = obj.activity_date
            end_time = time(23, 59, 59)
            
        if not (last_date and end_time):
            return violations
            
        end_datetime = datetime.combine(last_date, end_time)
        if timezone.is_naive(end_datetime):
            end_datetime = timezone.make_aware(end_datetime)
            
        grace_period_end = end_datetime + timedelta(minutes=30)
        
        if timezone.now() > grace_period_end:
            photos = list(obj.photos.all())
            photo_types = [p.photo_type for p in photos]
            
            if obj.name == "Daily Field Operations":
                start_selfie_photo = next((p for p in photos if p.photo_type == 'start_selfie'), None)
                if start_selfie_photo:
                    from attendance.models import EmployeeAttendanceRecord
                    # If they checked in via QR, the attendance record's checked_in_at will be BEFORE the selfie capture time
                    is_qr_checkin = EmployeeAttendanceRecord.objects.filter(
                        user=obj.user,
                        date=last_date,
                        checked_in_at__lt=start_selfie_photo.captured_at
                    ).exists()
                    
                    if not is_qr_checkin:
                        violations.append({'type': 'sales_check_in_selfie', 'description': 'Checked in with start selfie instead of QR code.'})
                else:
                    violations.append({'type': 'sales_missing_photo', 'description': 'Missing start_selfie photo.'})
                    
                if 'end_selfie' not in photo_types:
                    violations.append({'type': 'sales_missing_photo', 'description': 'Missing end_selfie photo (did not check out).'})
            elif obj.plan:
                slots_by_date = self.get_event_photo_slots(obj)
                for day_slots in slots_by_date:
                    for slot in day_slots["slots"]:
                        if not slot["is_filled"]:
                            violations.append({'type': 'sales_missing_photo', 'description': f'Missing {slot["type"]} photo for slot {slot["slot"]} on {day_slots["date"]}.'})
                    
        return violations

    def create(self, validated_data):
        inventory_items_data = validated_data.pop('inventory_items', [])
        activity = super().create(validated_data)
        self._handle_inventory_allocations(activity, inventory_items_data)
        return activity
        
    def update(self, instance, validated_data):
        inventory_items_data = validated_data.pop('inventory_items', None)
        activity = super().update(instance, validated_data)
        if inventory_items_data is not None:
            self._handle_inventory_allocations(activity, inventory_items_data)
        return activity
        
    def _handle_inventory_allocations(self, activity, inventory_items_data):
        from inventory.models import Item, ItemAllocation, StockTransaction
        from rest_framework.exceptions import ValidationError
        for inv_data in inventory_items_data:
            item_id = inv_data.get('item_id')
            quantity = int(inv_data.get('quantity', 1))
            try:
                item = Item.objects.get(id=item_id)
                allocation = ItemAllocation.objects.create(
                    item=item,
                    sales_user=activity.user,
                    quantity=quantity,
                    status='issued',
                    issued_by=activity.user
                )
                activity.inventory_allocations.add(allocation)
                StockTransaction.objects.create(
                    item=item,
                    transaction_type='allocation',
                    quantity=-quantity,
                    reference=f"Allocated to {activity.user.name} for activity",
                    created_by=activity.user
                )
            except Item.DoesNotExist:
                pass
            except Exception as e:
                raise ValidationError({"inventory_items": str(e)})

    def get_event_photo_slots(self, obj):
        from datetime import datetime
        from django.utils import timezone
        
        from datetime import timedelta
        
        start_date = obj.from_date or obj.activity_date or timezone.localdate()
        end_date = obj.to_date or obj.activity_date or timezone.localdate()
        
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            
        if end_date < start_date:
            end_date = start_date
            
        num_days = (end_date - start_date).days + 1
        
        all_photos = list(obj.photos.all())
        exhibition_photos = sorted([p for p in all_photos if p.photo_type == 'exhibition'], key=lambda x: x.captured_at)
        
        all_slots_by_date = []
        request = self.context.get('request')
        
        for d in range(num_days):
            current_date = start_date + timedelta(days=d)
            
            duration_hours = 0
            start_dt = None
            end_dt = None
            
            timing = obj.timings.filter(date=current_date).first()
            if timing and timing.start_time and timing.end_time:
                start_dt = datetime.combine(current_date, timing.start_time)
                end_dt = datetime.combine(current_date, timing.end_time)
                duration_hours = (end_dt - start_dt).total_seconds() / 3600
            elif obj.plan and hasattr(obj.plan, 'start_time') and obj.plan.start_time and obj.plan.end_time:
                start_dt = datetime.combine(current_date, obj.plan.start_time)
                end_dt = datetime.combine(current_date, obj.plan.end_time)
                duration_hours = (end_dt - start_dt).total_seconds() / 3600
                
            total_slots = max(2, int(duration_hours)) if duration_hours > 0 else 8
            
            start_selfie = next((p for p in all_photos if p.photo_type == 'event_start_selfie' and timezone.localtime(p.captured_at).date() == current_date), None)
            end_selfie = next((p for p in all_photos if p.photo_type == 'event_end_selfie' and timezone.localtime(p.captured_at).date() == current_date), None)
            
            slots = []
            for i in range(total_slots):
                if i == 0:
                    slot_type = "event_start_selfie"
                    photo = start_selfie
                elif i == total_slots - 1 and total_slots > 1:
                    slot_type = "event_end_selfie"
                    photo = end_selfie
                else:
                    slot_type = "exhibition"
                    date_exhibition_photos = [p for p in exhibition_photos if timezone.localtime(p.captured_at).date() == current_date]
                    if date_exhibition_photos:
                        photo = date_exhibition_photos[0]
                        exhibition_photos.remove(photo)
                    else:
                        photo = None
                    
                slot_timing_str = None
                if start_dt and end_dt:
                    if i == total_slots - 1 and total_slots > 1:
                        slot_end = end_dt
                        slot_start = max(start_dt, end_dt - timedelta(hours=1))
                    else:
                        slot_start = start_dt + timedelta(hours=i)
                        slot_end = min(slot_start + timedelta(hours=1), end_dt)
                        
                    slot_timing_str = f"{slot_start.strftime('%I:%M %p').lstrip('0')} to {slot_end.strftime('%I:%M %p').lstrip('0')}"
                    
                slot_data = {
                    "slot": i + 1,
                    "type": slot_type,
                    "photo_id": photo.id if photo else None,
                    "photo_url": None,
                    "is_filled": bool(photo),
                    "timing": slot_timing_str
                }
                if photo and photo.photo:
                    slot_data['photo_url'] = request.build_absolute_uri(photo.photo.url) if request else photo.photo.url
                slots.append(slot_data)
                
            all_slots_by_date.append({
                "date": current_date.strftime("%Y-%m-%d"),
                "slots": slots
            })
            
        return all_slots_by_date


class SalesPlanReminderSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesPlanReminder
        fields = ['id', 'reminder_time', 'purpose', 'is_sent']
        read_only_fields = ['id', 'is_sent']


class SalesDailyPlanSerializer(serializers.ModelSerializer):
    """
    Parent serializer — daily plan / scheduled event.
    Activities for the day are nested inside.
    Validates that new/updated events do not time-conflict with existing events
    for the same user on the same date.
    """
    user_name = serializers.CharField(source='user.name', read_only=True)
    activities = SalesDailyActivitySerializer(many=True, read_only=True)
    date = serializers.DateField(source='plan_date', required=False)
    photos = serializers.SerializerMethodField()
    custom_reminders = SalesPlanReminderSerializer(many=True, required=False)

    class Meta:
        model = SalesDailyPlan
        fields = [
            'id', 'user', 'user_name', 'plan_date', 'date', 'type',
            'start_time', 'end_time', 'place', 'description', 'status',
            'photos','reminder_two_days_before_sent',
            'reminder_one_day_before_sent', 'reminder_day_of_event_sent',
            'activities', 'custom_reminders', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'user', 'user_name', 'photos', 'activities',
            'reminder_two_days_before_sent',
            'reminder_one_day_before_sent', 'reminder_day_of_event_sent',
            'created_at', 'updated_at'
        ]

    def get_photos(self, obj):
        try:
            general_activity = SalesDailyActivity.objects.get(
                user=obj.user,
                activity_date=obj.plan_date,
                name="Daily Field Operations"
            )
            # Filter for general check-in/out selfies
            photos = general_activity.photos.filter(photo_type__in=['start_selfie', 'end_selfie'])
            return SalesActivityPhotoSerializer(photos, many=True, context=self.context).data
        except SalesDailyActivity.DoesNotExist:
            return []

    def to_internal_value(self, data):
        mutable_data = data.copy() if hasattr(data, 'copy') else dict(data)
        if 'date' in mutable_data and 'plan_date' not in mutable_data:
            mutable_data['plan_date'] = mutable_data['date']
        return super().to_internal_value(mutable_data)

    def create(self, validated_data):
        reminders_data = validated_data.pop('custom_reminders', [])
        plan = super().create(validated_data)
        
        # Auto-create the linked SalesDailyActivity container
        SalesDailyActivity.objects.create(
            user=plan.user,
            plan=plan,
            activity_date=plan.plan_date,
            status='pending',
            name=plan.type if plan.type else 'Sales Activity'
        )
        
        for reminder_data in reminders_data:
            SalesPlanReminder.objects.create(
                plan=plan, 
                reminder_time=reminder_data['reminder_time'],
                purpose=reminder_data.get('purpose', '')
            )
        return plan

    def update(self, instance, validated_data):
        reminders_data = validated_data.pop('custom_reminders', None)
        
        old_date = instance.plan_date
        plan = super().update(instance, validated_data)
        
        # Sync updates to linked pending activities
        if old_date != plan.plan_date or 'type' in validated_data:
            pending_activities = plan.activities.filter(status='pending')
            for act in pending_activities:
                if old_date != plan.plan_date:
                    act.activity_date = plan.plan_date
                if 'type' in validated_data:
                    act.name = plan.type if plan.type else 'Sales Activity'
                act.save(update_fields=['activity_date', 'name'])
                
        if reminders_data is not None:
            # Delete existing unsent reminders and recreate them
            instance.custom_reminders.filter(is_sent=False).delete()
            for reminder_data in reminders_data:
                SalesPlanReminder.objects.create(
                    plan=plan, 
                    reminder_time=reminder_data['reminder_time'],
                    purpose=reminder_data.get('purpose', '')
                )
                
        return plan

    def validate(self, attrs):
        """
        Run model-level time-conflict validation via model.clean().
        Builds a temporary (unsaved) model instance populated with the
        validated data merged over any existing instance fields.
        """
        from django.core.exceptions import ValidationError as DjangoValidationError

        instance = self.instance  # None on create, existing plan on update
        request = self.context.get('request')

        # Build a scratch instance to run clean() against
        if instance:
            # Merge incoming attrs over existing fields
            user = instance.user
            plan_date = attrs.get('plan_date', instance.plan_date)
            start_time = attrs.get('start_time', instance.start_time)
            end_time = attrs.get('end_time', instance.end_time)
            scratch_pk = instance.pk
        else:
            user = request.user if request else getattr(instance, 'user', None)
            plan_date = attrs.get('plan_date')
            start_time = attrs.get('start_time')
            end_time = attrs.get('end_time')
            scratch_pk = None

        scratch = SalesDailyPlan(
            pk=scratch_pk,
            user=user,
            plan_date=plan_date,
            start_time=start_time,
            end_time=end_time,
        )
        try:
            scratch.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'non_field_errors': exc.messages})

        return attrs


# ── Contact Serializer ────────────────────────────────────────────────────────

class ContactSerializer(serializers.Serializer):
    branch        = serializers.UUIDField(required=False, allow_null=True)
    form_type     = serializers.ChoiceField(choices=FORM_TYPE_CHOICES)
    first_name    = serializers.CharField(max_length=100)
    email         = serializers.EmailField()
    phone_student = serializers.CharField(max_length=15)
    course        = serializers.ChoiceField(choices=COURSE_TYPE_CHOICES)
    consent       = serializers.BooleanField()

    # ── Manual assignment (optional at creation; only honoured for authenticated users) ─
    assigned_to   = serializers.UUIDField(
        required=False, allow_null=True,
        help_text="UUID of the User (Counsellor/Sales Executive) to assign this lead to."
    )

    def validate_branch(self, value):
        if value:
            from branch.models import Branch
            try:
                return Branch.objects.get(id=value)
            except Branch.DoesNotExist:
                raise serializers.ValidationError("Branch not found.")
        return value

    def validate_assigned_to(self, value):
        """Resolve UUID → User instance, or return None."""
        if value is None:
            return None
        try:
            return User.objects.get(id=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found for the given assigned_to UUID.")

    def validate_phone_student(self, value):
        return validate_phone(value)

    def validate_consent(self, value):
        if not value:
            raise serializers.ValidationError("You must agree to the consent to proceed.")
        return value


# ── Inquiry Serializer ────────────────────────────────────────────────────────

class InquirySerializer(ContactSerializer):

    email = serializers.EmailField(required=False, allow_blank=True)

    group_module  = serializers.ChoiceField(choices=GROUP_MODULE_CHOICES)
    batch_attempt = serializers.ChoiceField(choices=ATTEMPT_TYPE_CHOICES)

    surname      = serializers.CharField(max_length=100)
    father_name  = serializers.CharField(max_length=100)
    street       = serializers.CharField()
    apartment    = serializers.CharField(max_length=100, required=False, allow_blank=True)
    city         = serializers.CharField(max_length=100)
    state        = serializers.CharField(max_length=100)
    phone_father = serializers.CharField(max_length=15)
    qualification = serializers.ChoiceField(choices=QUALIFICATION_TYPE_CHOICES)
    reference    = serializers.ChoiceField(choices=REFERENCE_TYPE_CHOICES)
    location     = serializers.CharField(max_length=100)
    inquiry_date = serializers.DateField()
    reference_name = serializers.CharField(max_length=100,required=False,allow_blank=True)

    tenth_medium     = serializers.ChoiceField(choices=BOARD_TYPE_CHOICES)
    tenth_school     = serializers.CharField(max_length=200)
    tenth_coaching   = serializers.CharField(max_length=200, required=False, allow_blank=True)
    tenth_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    tenth_percentile = serializers.DecimalField(max_digits=5, decimal_places=2)

    twelfth_medium     = serializers.ChoiceField(choices=BOARD_TYPE_CHOICES, required=False)
    twelfth_school     = serializers.CharField(max_length=200, required=False, allow_blank=True)
    twelfth_coaching   = serializers.CharField(max_length=200, required=False, allow_blank=True)
    twelfth_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    twelfth_percentile = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)

    grad_university = serializers.CharField(max_length=200, required=False, allow_blank=True)
    grad_college    = serializers.CharField(max_length=200, required=False, allow_blank=True)
    grad_last_sem   = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_phone_father(self, value):
        return validate_phone(value)

    def validate_tenth_percentage(self, value):
        return validate_percentage(value)

    def validate_twelfth_percentage(self, value):
        return validate_percentage(value)

    def validate(self, data):
        course        = data.get('course')
        group_module  = data.get('group_module')
        batch_attempt = data.get('batch_attempt')
        qualification = data.get('qualification')

        if course in VALID_COMBINATIONS:
            valid = VALID_COMBINATIONS[course]
            if group_module not in valid['group_module']:
                raise serializers.ValidationError({
                    'group_module': (
                        f"'{group_module}' is not valid for {course}. "
                        f"Valid options: {valid['group_module']}"
                    )
                })
            if batch_attempt not in valid['batch_attempt']:
                raise serializers.ValidationError({
                    'batch_attempt': (
                        f"'{batch_attempt}' is not valid for {course}. "
                        f"Valid options: {valid['batch_attempt']}"
                    )
                })

        if qualification == 'appearing_12':
            return data

        errors = {}
        TWELFTH_REQUIRED = {
            'twelfth_medium':     '12th medium is required.',
            'twelfth_school':     '12th school name is required.',
            'twelfth_percentage': '12th percentage is required.',
            'twelfth_percentile': '12th percentile is required.',
        }
        for field, message in TWELFTH_REQUIRED.items():
            if not data.get(field):
                errors[field] = message
        if errors:
            raise serializers.ValidationError(errors)

        GRADUATION_REQUIRED = ['pass_12', 'cseet_pass', 'post_graduate']
        if qualification in GRADUATION_REQUIRED:
            grad_errors = {}
            if not data.get('grad_university'):
                grad_errors['grad_university'] = 'University name is required.'
            if not data.get('grad_college'):
                grad_errors['grad_college'] = 'College name is required.'
            if not data.get('grad_last_sem'):
                grad_errors['grad_last_sem'] = 'Last semester detail is required.'
            if grad_errors:
                raise serializers.ValidationError(grad_errors)

        return data


# ── Serializer Dispatcher ─────────────────────────────────────────────────────

SERIALIZER_MAP = {
    'contact': ContactSerializer,
    'inquiry': InquirySerializer,
}


def get_lead_serializer(form_type: str, data, files=None):
    serializer_class = SERIALIZER_MAP.get(form_type)

    if not serializer_class:
        raise serializers.ValidationError({
            'form_type': (
                f"Invalid form_type '{form_type}'. "
                f"Must be one of: {list(SERIALIZER_MAP.keys())}"
            )
        })

    if files:
        merged = data.dict() if hasattr(data, 'dict') else dict(data)
        merged.update({k: v for k, v in files.items()})
        return serializer_class(data=merged)

    return serializer_class(data=data)


# ── Stage / List / Detail / Update Serializers ───────────────────────────────

class LeadStageUpdateSerializer(serializers.Serializer):
    stage = serializers.ChoiceField(choices=STAGE_CHOICES)
    note = serializers.CharField(required=False, allow_blank=True)

    followup_date = FlexibleDateTimeField(
        required=False,
        allow_null=True
    )

    visit_date = FlexibleDateTimeField(
        required=False,
        allow_null=True
    )

    is_visited = serializers.BooleanField(
        required=False
    )

    def validate(self, attrs):
        stage = attrs.get("stage")

        if stage == "follow_up" and not attrs.get("followup_date"):
            print("followup validation error raised.")
            raise serializers.ValidationError({
                "followup_date": "Follow-up date is required for follow-up stage."
            })

        if stage == "visit" and not attrs.get("visit_date"):
            print("visit validation error raised.")
            raise serializers.ValidationError({
                "visit_date": "Visit date is required for visit stage."
            })
        
        return attrs

class LeadListSerializer(serializers.ModelSerializer):
    current_stage_display = serializers.CharField(source='get_current_stage_display', read_only=True)
    form_type_display = serializers.CharField(source='get_form_type_display', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    course_display = serializers.CharField(source="get_course_display", read_only=True)
    group_module_display = serializers.CharField(source="get_group_module_display", read_only=True)
    batch_attempt_display = serializers.CharField(source="get_batch_attempt_display", read_only=True)
    current_stage_display = serializers.CharField(source="get_current_stage_display", read_only=True)
    qualification_display = serializers.CharField(source="get_qualification_display", read_only=True)
    reference_display = serializers.CharField(source="get_reference_display", read_only=True)
    tenth_medium_display = serializers.CharField(source="get_tenth_medium_display", read_only=True)
    twelfth_medium_display = serializers.CharField(source="get_twelfth_medium_display", read_only=True)
    stage_display = serializers.CharField(source="get_stage_display", read_only=True)
    # ── Assignment display ───────────────────────────────────────────────
    assigned_to_id   = serializers.UUIDField(source='assigned_to.id',   read_only=True, allow_null=True)
    assigned_to_name = serializers.CharField(source='assigned_to.name', read_only=True, allow_null=True)

    class Meta:
        model = Lead
        fields = [
            'id', 'branch', 'branch_name', 'form_type', 'form_type_display', 'first_name', 'surname', 'email',
            'phone_student', 'course', 'current_stage', 'current_stage_display', 'location', 'note', 'created_at',
            'contacted_at', 'interested_at', 'followup_set_at', 'converted_at', 'lost_at', 'followup_date', 'visit_date', 'is_visited', 'visit_set_at',
            'course_display', 'group_module_display', 'batch_attempt_display', 'qualification_display', 'reference_display', 'tenth_medium_display', 'twelfth_medium_display', 'stage_display',
            'assigned_to_id', 'assigned_to_name',
        ]


class LeadAssignmentLogSerializer(serializers.ModelSerializer):
    assigned_from_name = serializers.CharField(source='assigned_from.name', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.name', read_only=True)
    changed_by_name = serializers.CharField(source='changed_by.name', read_only=True)

    class Meta:
        model = LeadAssignmentLog
        fields = '__all__'


class LeadDetailSerializer(serializers.ModelSerializer):
    form_type_display = serializers.CharField(source='get_form_type_display', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    course_display = serializers.CharField(source="get_course_display", read_only=True)
    group_module_display = serializers.CharField(source="get_group_module_display", read_only=True)
    batch_attempt_display = serializers.CharField(source="get_batch_attempt_display", read_only=True)
    current_stage_display = serializers.CharField(source="get_current_stage_display", read_only=True)
    qualification_display = serializers.CharField(source="get_qualification_display", read_only=True)
    reference_display = serializers.CharField(source="get_reference_display", read_only=True)
    tenth_medium_display = serializers.CharField(source="get_tenth_medium_display", read_only=True)
    twelfth_medium_display = serializers.CharField(source="get_twelfth_medium_display", read_only=True)
    stage_display = serializers.CharField(source="get_stage_display", read_only=True)
    # ── Assignment display ───────────────────────────────────────────────
    assigned_to_id   = serializers.UUIDField(source='assigned_to.id',   read_only=True, allow_null=True)
    assigned_to_name = serializers.CharField(source='assigned_to.name', read_only=True, allow_null=True)
    assignment_history = LeadAssignmentLogSerializer(source='assignment_logs', many=True, read_only=True)

    class Meta:
        model = Lead
        fields = '__all__'


class LeadUpdateSerializer(serializers.ModelSerializer):

    followup_date = FlexibleDateTimeField(
        required=False,
        allow_null=True
    )

    visit_date = FlexibleDateTimeField(
        required=False,
        allow_null=True
    )

    is_visited = serializers.BooleanField(
        required=False
    )
    
    class Meta:
        model = Lead
        exclude = ['created_at', 'updated_at']
        read_only_fields = ['id', 'form_type']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False


# ── Reassign Serializer (for PATCH /leads/<id>/reassign/) ──────────────────

class LeadReassignSerializer(serializers.Serializer):
    """
    Accepts a new assignee UUID and an optional reassignment note.
    Restricted to Sales Senior Executive / Branch Manager / Super Admin.
    """
    assigned_to = serializers.UUIDField(
        required=True,
        allow_null=True,
        help_text="UUID of the new assignee. Pass null to unassign the lead."
    )
    note = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_assigned_to(self, value):
        """Resolve UUID → User instance, or return None (unassign)."""
        if value is None:
            return None
        try:
            return User.objects.get(id=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found for the given assigned_to UUID.")


class LeadTransferRequestSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.CharField(source='requested_by.name', read_only=True)
    reviewed_by_name = serializers.CharField(source='reviewed_by.name', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.name', read_only=True)
    lead_name = serializers.CharField(source='lead.first_name', read_only=True)
    
    class Meta:
        model = LeadTransferRequest
        fields = '__all__'
        read_only_fields = ['requested_by', 'status', 'reviewed_by', 'assigned_to']


class LeadTransferApprovalSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[('approved', 'Approved'), ('rejected', 'Rejected')])
    assigned_to = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        status = attrs.get('status')
        assigned_to = attrs.get('assigned_to')
        if status == 'approved' and not assigned_to:
            raise serializers.ValidationError({"assigned_to": "assigned_to is required when approving a transfer request."})
        return attrs
