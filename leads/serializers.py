from rest_framework import serializers
from .models import (
    Lead,FORM_TYPE_CHOICES,COURSE_TYPE_CHOICES,GROUP_MODULE_CHOICES,ATTEMPT_TYPE_CHOICES,STAGE_CHOICES,QUALIFICATION_TYPE_CHOICES,BOARD_TYPE_CHOICES,CATEGORY_TYPE_CHOICES,REFERENCE_TYPE_CHOICES,)


# ── Helpers ───────────────────────────────────────────────────────────────────

def validate_phone(value):
    """Basic phone validation — digits only, 10 digits."""
    digits = value.replace('+', '').replace(' ', '').replace('-', '')
    if not digits.isdigit():
        raise serializers.ValidationError("Phone number must contain only digits.")
    if len(digits) < 10 or len(digits) > 15:
        raise serializers.ValidationError("Phone number must be between 10 and 15 digits.")
    return value


def validate_percentage(value):
    """Percentage must be between 0 and 100."""
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


# ── Base Serializer (Contact Us Form) ─────────────────────────────────────────
#
#   Fields: first_name, email, course, phone_student, consent
#   Used directly for: Contact Us page form
#   Extended by: InquirySerializer, RegistrationSerializer

class ContactSerializer(serializers.Serializer):

    # form_type is hardcoded in each serializer's save(),
    # but also accepted from request for routing purposes
    form_type     = serializers.ChoiceField(choices=FORM_TYPE_CHOICES)

    first_name    = serializers.CharField(max_length=100)
    email         = serializers.EmailField()
    phone_student = serializers.CharField(max_length=15)
    course        = serializers.ChoiceField(choices=COURSE_TYPE_CHOICES)
    consent       = serializers.BooleanField()

    def validate_phone_student(self, value):
        return validate_phone(value)

    def validate_consent(self, value):
        if not value:
            raise serializers.ValidationError("You must agree to the consent to proceed.")
        return value


# ── Inquiry Serializer (Full Inquiry Form) ─────────────────────────────────────
#
#   Extends ContactSerializer
#   Adds: group_module, batch_attempt, personal info, education, reference, location
#   Used for: /inquiry-form/

class InquirySerializer(ContactSerializer):

    # Override email — not required in full inquiry form
    email = serializers.EmailField(required=False, allow_blank=True)

    # ── Course Details ─────────────────────────────────────────────────────
    group_module  = serializers.ChoiceField(choices=GROUP_MODULE_CHOICES)
    batch_attempt = serializers.ChoiceField(choices=ATTEMPT_TYPE_CHOICES)

    # ── Personal Info ──────────────────────────────────────────────────────
    surname      = serializers.CharField(max_length=100)
    father_name  = serializers.CharField(max_length=100)
    street       = serializers.CharField()
    apartment = serializers.CharField(max_length=100, required=False, allow_blank=True)
    city         = serializers.CharField(max_length=100)
    state        = serializers.CharField(max_length=100)
    phone_father = serializers.CharField(max_length=15)
    qualification = serializers.ChoiceField(choices=QUALIFICATION_TYPE_CHOICES)
    reference    = serializers.ChoiceField(choices=REFERENCE_TYPE_CHOICES)
    location     = serializers.CharField(max_length=100)

    # ── 10th Education ─────────────────────────────────────────────────────
    tenth_medium     = serializers.ChoiceField(choices=BOARD_TYPE_CHOICES)
    tenth_school     = serializers.CharField(max_length=200)
    tenth_coaching   = serializers.CharField(max_length=200, required=False, allow_blank=True)
    tenth_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    tenth_percentile = serializers.DecimalField(max_digits=5, decimal_places=2)

    # ── 12th Education ─────────────────────────────────────────────────────
    # Optional — student may be appearing in 12th
    twelfth_medium     = serializers.ChoiceField(choices=BOARD_TYPE_CHOICES, required=False)
    twelfth_school     = serializers.CharField(max_length=200, required=False, allow_blank=True)
    twelfth_coaching   = serializers.CharField(max_length=200, required=False, allow_blank=True)
    twelfth_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    twelfth_percentile = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    inquiry_date = serializers.DateField()

    # ── Graduation ─────────────────────────────────────────────────────────
    # Optional — only if qualification is Graduate/PG
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

        # ── Course combination check ───────────────────────────────────────────
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

        # ── appearing_12: only 10th required ──────────────────────────────────
        if qualification == 'appearing_12':
            return data

        # ── All others: 12th is required ──────────────────────────────────────
        errors = {}
        TWELFTH_REQUIRED_FIELDS = {
            'twelfth_medium':     '12th medium is required.',
            'twelfth_school':     '12th school name is required.',
            'twelfth_percentage': '12th percentage is required.',
            'twelfth_percentile': '12th percentile is required.',
        }
        for field, message in TWELFTH_REQUIRED_FIELDS.items():
            if not data.get(field):
                errors[field] = message

        if errors:
            raise serializers.ValidationError(errors)

        # ── Only these qualifications need graduation ──────────────────────────
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


# ── Registration Serializer (Registration Form) ───────────────────────────────
#
#   Extends InquirySerializer
#   Adds: mother_name, dob, category, pincode, extra contacts, documents
#   Used for: /registration-form/

class RegistrationSerializer(InquirySerializer):

    # ── Extra Personal Info ────────────────────────────────────────────────
    mother_name     = serializers.CharField(max_length=100)
    dob             = serializers.DateField()                         # format: YYYY-MM-DD
    category        = serializers.ChoiceField(choices=CATEGORY_TYPE_CHOICES)
    pincode         = serializers.CharField(max_length=10)
    country         = serializers.CharField(max_length=100, default='India')

    # ── Extra Contacts ─────────────────────────────────────────────────────
    phone_student_2 = serializers.CharField(max_length=15, required=False, allow_blank=True)
    phone_father_2  = serializers.CharField(max_length=15, required=False, allow_blank=True)
    email_parent    = serializers.EmailField()

    # ── 12th becomes required for registration ─────────────────────────────
    twelfth_medium     = serializers.ChoiceField(choices=BOARD_TYPE_CHOICES)
    twelfth_school     = serializers.CharField(max_length=200)
    twelfth_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    twelfth_percentile = serializers.DecimalField(max_digits=5, decimal_places=2)

    # ── Documents (Required) ───────────────────────────────────────────────
    doc_signature       = serializers.FileField()
    doc_photo           = serializers.FileField()
    doc_dob_certificate = serializers.FileField()
    doc_id_card         = serializers.FileField()

    # ── Documents (Optional) ──────────────────────────────────────────────
    doc_twelfth_receipt   = serializers.FileField(required=False, allow_null=True)
    doc_twelfth_marksheet = serializers.FileField(required=False, allow_null=True)
    doc_category_cert     = serializers.FileField(required=False, allow_null=True)
    

    def validate_phone_student_2(self, value):
        if value:
            return validate_phone(value)
        return value

    def validate_phone_father_2(self, value):
        if value:
            return validate_phone(value)
        return value

    def validate_doc_signature(self, value):
        return _validate_file(value, allowed_types=['image/jpeg', 'image/png', 'application/pdf'])

    def validate_doc_photo(self, value):
        return _validate_file(value, allowed_types=['image/jpeg', 'image/png'])

    def validate_doc_dob_certificate(self, value):
        return _validate_file(value, allowed_types=['image/jpeg', 'image/png', 'application/pdf'])

    def validate_doc_id_card(self, value):
        return _validate_file(value, allowed_types=['image/jpeg', 'image/png', 'application/pdf'])


# ── File Validator Helper ─────────────────────────────────────────────────────

def _validate_file(file, allowed_types, max_size_mb=5):
    """
    Validates file type and size.
    allowed_types: list of MIME types e.g. ['image/jpeg', 'application/pdf']
    max_size_mb: max allowed file size in MB
    """
    if file.content_type not in allowed_types:
        raise serializers.ValidationError(
            f"Unsupported file type '{file.content_type}'. "
            f"Allowed: {', '.join(allowed_types)}"
        )
    max_size_bytes = max_size_mb * 1024 * 1024
    if file.size > max_size_bytes:
        raise serializers.ValidationError(
            f"File size must be under {max_size_mb}MB. "
            f"Uploaded file is {file.size / (1024*1024):.1f}MB."
        )
    return file


# ── Serializer Dispatcher ─────────────────────────────────────────────────────

SERIALIZER_MAP = {
    'contact': ContactSerializer,
    'inquiry': InquirySerializer,
    'registration': RegistrationSerializer,
}


# def get_lead_serializer(form_type: str, data: dict, files: dict = None):
#     """
#     Returns the correct serializer instance based on form_type.

#     Usage in view:
#         serializer = get_lead_serializer(
#             form_type=request.data.get('form_type'),
#             data=request.data,
#             files=request.FILES
#         )
#     """
#     serializer_class = SERIALIZER_MAP.get(form_type)

#     if not serializer_class:
#         raise serializers.ValidationError({
#             'form_type': f"Invalid form_type '{form_type}'. "
#                         f"Must be one of: {list(SERIALIZER_MAP.keys())}"
#         })

#     if files:
#         return serializer_class(data={**data, **files})

#     return serializer_class(data=data)


def get_lead_serializer(form_type: str, data, files=None):
    serializer_class = SERIALIZER_MAP.get(form_type)

    if not serializer_class:
        raise serializers.ValidationError({
            'form_type': f"Invalid form_type '{form_type}'. "
                        f"Must be one of: {list(SERIALIZER_MAP.keys())}"
        })

    if files:
        merged = data.dict() if hasattr(data, 'dict') else dict(data)
        # merged.update(files)
        merged.update({k: v for k, v in files.items()})
        return serializer_class(data=merged)

    return serializer_class(data=data)


class LeadStageUpdateSerializer(serializers.Serializer):
    stage = serializers.ChoiceField(choices=STAGE_CHOICES)
    note = serializers.CharField(required=False,allow_blank=True)


class LeadListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = [ "id","form_type", "first_name", "surname", "email", "phone_student", "course", "current_stage", "location", "created_at",]


class LeadDetailSerializer(serializers.ModelSerializer):
    """Full read serializer — returns every field on a Lead."""
    class Meta:
        model = Lead
        fields = "__all__"


class LeadUpdateSerializer(serializers.ModelSerializer):
    """
    Partial-update serializer for PUT / PATCH.
    Every field is optional so callers can send only what they want to change.
    form_type is read-only after creation.
    """
    class Meta:
        model = Lead
        exclude = ["created_at", "updated_at"]
        read_only_fields = ["id", "form_type"]

    def __init__(self, *args, **kwargs):
        # Make every non-read-only field optional
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False