# leads/serializers.py

from rest_framework import serializers
from .models import (Lead,FORM_TYPE_CHOICES,COURSE_TYPE_CHOICES,GROUP_MODULE_CHOICES,ATTEMPT_TYPE_CHOICES,STAGE_CHOICES,QUALIFICATION_TYPE_CHOICES,BOARD_TYPE_CHOICES,REFERENCE_TYPE_CHOICES,)


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
        'group_module':  ['both', 'module_1', 'module_2'],
        'batch_attempt': ['june', 'dec'],
    },
}


# ── Contact Serializer ────────────────────────────────────────────────────────

class ContactSerializer(serializers.Serializer):
    branch        = serializers.UUIDField(required=False, allow_null=True)
    form_type     = serializers.ChoiceField(choices=FORM_TYPE_CHOICES)
    first_name    = serializers.CharField(max_length=100)
    email         = serializers.EmailField()
    phone_student = serializers.CharField(max_length=15)
    course        = serializers.ChoiceField(choices=COURSE_TYPE_CHOICES)
    consent       = serializers.BooleanField()

    def validate_branch(self, value):
        if value:
            from branch.models import Branch
            try:
                return Branch.objects.get(id=value)
            except Branch.DoesNotExist:
                raise serializers.ValidationError("Branch not found.")
        return value

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
    note  = serializers.CharField(required=False, allow_blank=True)


class LeadListSerializer(serializers.ModelSerializer):
    current_stage_display = serializers.CharField(source='get_current_stage_display', read_only=True)
    form_type_display = serializers.CharField(source='get_form_type_display', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = Lead
        fields = [
            'id', 'branch', 'branch_name', 'form_type', 'form_type_display', 'first_name', 'surname', 'email',
            'phone_student', 'course', 'current_stage', 'current_stage_display', 'location', 'note', 'created_at',
        ]


class LeadDetailSerializer(serializers.ModelSerializer):
    form_type_display = serializers.CharField(source='get_form_type_display', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = Lead
        fields = '__all__'


class LeadUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        exclude = ['created_at', 'updated_at']
        read_only_fields = ['id', 'form_type']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False