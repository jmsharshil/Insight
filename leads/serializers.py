# leads/serializers.py

from rest_framework import serializers
from .models import (Lead, LeadAssignmentLog, FORM_TYPE_CHOICES, COURSE_TYPE_CHOICES, GROUP_MODULE_CHOICES,
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