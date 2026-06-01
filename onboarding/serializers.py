from rest_framework import serializers
from .models import Admission, ADMISSION_STATUS_CHOICES

from leads.models import (COURSE_TYPE_CHOICES,GROUP_MODULE_CHOICES,ATTEMPT_TYPE_CHOICES,QUALIFICATION_TYPE_CHOICES,BOARD_TYPE_CHOICES,CATEGORY_TYPE_CHOICES,REFERENCE_TYPE_CHOICES,)
from leads.serializers import VALID_COMBINATIONS

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


def _validate_file(file, allowed_types, max_size_mb=5):
    if file.content_type not in allowed_types:
        raise serializers.ValidationError(
            f"Unsupported file type '{file.content_type}'. "
            f"Allowed: {', '.join(allowed_types)}"
        )
    if file.size > max_size_mb * 1024 * 1024:
        raise serializers.ValidationError(
            f"File size must be under {max_size_mb}MB. "
            f"Uploaded: {file.size / (1024 * 1024):.1f}MB."
        )
    return file


# ── Admission Create Serializer ───────────────────────────────────────────────

class AdmissionSerializer(serializers.Serializer):

    # ── Optional lead link ────────────────────────────────────────────────────
    lead_id = serializers.IntegerField(required=False, allow_null=True)

    branch = serializers.UUIDField(required=False, allow_null=True)

    assigned_counsellor = serializers.UUIDField(required=False, allow_null=True)

    # ── Personal Info ─────────────────────────────────────────────────────────
    first_name   = serializers.CharField(max_length=100)
    surname      = serializers.CharField(max_length=100)
    father_name  = serializers.CharField(max_length=100)
    mother_name  = serializers.CharField(max_length=100)
    dob          = serializers.DateField()
    category     = serializers.ChoiceField(choices=CATEGORY_TYPE_CHOICES)

    # ── Contact ───────────────────────────────────────────────────────────────
    email           = serializers.EmailField()
    email_parent    = serializers.EmailField()
    phone_student   = serializers.CharField(max_length=15)
    phone_student_2 = serializers.CharField(max_length=15, required=False, allow_blank=True)
    phone_father    = serializers.CharField(max_length=15)
    phone_father_2  = serializers.CharField(max_length=15, required=False, allow_blank=True)

    # ── Address ───────────────────────────────────────────────────────────────
    street    = serializers.CharField()
    apartment = serializers.CharField(max_length=100, required=False, allow_blank=True)
    city      = serializers.CharField(max_length=100)
    state     = serializers.CharField(max_length=100)
    pincode   = serializers.CharField(max_length=10)
    country   = serializers.CharField(max_length=100, default='India')

    # ── Course Details ────────────────────────────────────────────────────────
    course        = serializers.ChoiceField(choices=COURSE_TYPE_CHOICES)
    group_module  = serializers.ChoiceField(choices=GROUP_MODULE_CHOICES)
    batch_attempt = serializers.ChoiceField(choices=ATTEMPT_TYPE_CHOICES)
    location      = serializers.CharField(max_length=100)

    # ── Qualification & Reference ─────────────────────────────────────────────
    qualification = serializers.ChoiceField(choices=QUALIFICATION_TYPE_CHOICES)
    reference     = serializers.ChoiceField(choices=REFERENCE_TYPE_CHOICES)
    consent       = serializers.BooleanField()

    # ── 10th Education ────────────────────────────────────────────────────────
    tenth_medium     = serializers.ChoiceField(choices=BOARD_TYPE_CHOICES)
    tenth_school     = serializers.CharField(max_length=200)
    tenth_coaching   = serializers.CharField(max_length=200, required=False, allow_blank=True)
    tenth_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    tenth_percentile = serializers.DecimalField(max_digits=5, decimal_places=2)

    # ── 12th Education (always required for admission) ────────────────────────
    twelfth_medium     = serializers.ChoiceField(choices=BOARD_TYPE_CHOICES)
    twelfth_school     = serializers.CharField(max_length=200)
    twelfth_coaching   = serializers.CharField(max_length=200, required=False, allow_blank=True)
    twelfth_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    twelfth_percentile = serializers.DecimalField(max_digits=5, decimal_places=2)

    # ── Graduation ────────────────────────────────────────────────────────────
    grad_university = serializers.CharField(max_length=200, required=False, allow_blank=True)
    grad_college    = serializers.CharField(max_length=200, required=False, allow_blank=True)
    grad_last_sem   = serializers.CharField(max_length=200, required=False, allow_blank=True)

    # ── Documents (Required) ──────────────────────────────────────────────────
    doc_signature       = serializers.FileField()
    doc_photo           = serializers.FileField()
    doc_dob_certificate = serializers.FileField()
    doc_id_card         = serializers.FileField()

    # ── Documents (Optional) ──────────────────────────────────────────────────
    doc_twelfth_receipt   = serializers.FileField(required=False, allow_null=True)
    doc_twelfth_marksheet = serializers.FileField(required=False, allow_null=True)
    doc_category_cert     = serializers.FileField(required=False, allow_null=True)

    # ── Field-level validators ────────────────────────────────────────────────

    def validate_consent(self, value):
        if not value:
            raise serializers.ValidationError("You must agree to the consent to proceed.")
        return value

    def validate_branch(self, value):
        if not value:
            return value

        from branch.models import Branch

        try:
            return Branch.objects.get(id=value)
        except Branch.DoesNotExist:
            raise serializers.ValidationError("Branch not found.")

    def validate_phone_student(self, value):
        return validate_phone(value)

    def validate_phone_student_2(self, value):
        return validate_phone(value) if value else value

    def validate_phone_father(self, value):
        return validate_phone(value)

    def validate_phone_father_2(self, value):
        return validate_phone(value) if value else value

    def validate_tenth_percentage(self, value):
        return validate_percentage(value)

    def validate_twelfth_percentage(self, value):
        return validate_percentage(value)

    def validate_doc_signature(self, value):
        return _validate_file(value, allowed_types=['image/jpeg', 'image/png', 'application/pdf'])

    def validate_doc_photo(self, value):
        return _validate_file(value, allowed_types=['image/jpeg', 'image/png'])

    def validate_doc_dob_certificate(self, value):
        return _validate_file(value, allowed_types=['image/jpeg', 'image/png', 'application/pdf'])

    def validate_doc_id_card(self, value):
        return _validate_file(value, allowed_types=['image/jpeg', 'image/png', 'application/pdf'])

    # ── Cross-field validation ────────────────────────────────────────────────

    def validate(self, data):
        course        = data.get('course')
        group_module  = data.get('group_module')
        batch_attempt = data.get('batch_attempt')
        qualification = data.get('qualification')

        # Course + group_module + batch_attempt combination check
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

        # Graduation required for these qualifications
        GRADUATION_REQUIRED = ['graduate', 'post_graduate', 'cseet_pass']
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

        # Validate lead_id exists if provided
        lead_id = data.get('lead_id')
        if lead_id:
            from leads.models import Lead
            if not Lead.objects.filter(id=lead_id).exists():
                raise serializers.ValidationError({'lead_id': 'No lead found with this ID.'})

        # Validate and resolve assigned_counsellor UUID
        counsellor_id = data.get('assigned_counsellor')
        if counsellor_id:
            from auth_user.models import User
            try:
                counsellor = User.objects.get(id=counsellor_id, role='counsellor')
                data['assigned_counsellor'] = counsellor
            except User.DoesNotExist:
                raise serializers.ValidationError({
                    'assigned_counsellor': 'No counsellor found with this ID.'
                })

        return data


# ── Admission Status Update Serializer ───────────────────────────────────────

class AdmissionStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ADMISSION_STATUS_CHOICES)
    note   = serializers.CharField(required=False, allow_blank=True)


# ── Admission Read Serializers ────────────────────────────────────────────────

class CounsellorInfoSerializer(serializers.Serializer):
    """Nested read-only serializer to display assigned counsellor details."""
    id    = serializers.UUIDField()
    name  = serializers.CharField()
    email = serializers.EmailField()
    phone = serializers.CharField()


class BranchInfoSerializer(serializers.Serializer):
    """Nested read-only serializer to display branch details."""
    id   = serializers.UUIDField()
    name = serializers.CharField()
    code = serializers.CharField()
    city = serializers.CharField()


class AdmissionListSerializer(serializers.ModelSerializer):
    branch = BranchInfoSerializer(read_only=True)
    assigned_counsellor = CounsellorInfoSerializer(read_only=True)

    class Meta:
        model = Admission
        fields = [
            'id', 'branch', 'first_name', 'surname', 'email', 'phone_student',
            'course', 'batch_attempt', 'status', 'location',
            'assigned_counsellor', 'note', 'submitted_at',
        ]


class AdmissionDetailSerializer(serializers.ModelSerializer):
    branch = BranchInfoSerializer(read_only=True)
    assigned_counsellor = CounsellorInfoSerializer(read_only=True)

    class Meta:
        model = Admission
        fields = '__all__'


class AdmissionUpdateSerializer(serializers.ModelSerializer):
    """Partial-update serializer for PUT / PATCH."""
    class Meta:
        model = Admission
        exclude = ['submitted_at', 'updated_at']
        read_only_fields = ['id', 'lead']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False

# ── Admission Document Upload Serializer ──────────────────────────────────────

ADMISSION_DOCUMENT_FIELDS = ['doc_signature','doc_photo','doc_dob_certificate','doc_id_card','doc_twelfth_receipt','doc_twelfth_marksheet','doc_category_cert',]

class AdmissionDocumentUploadSerializer(serializers.Serializer):
    field_name = serializers.ChoiceField(
        choices=[(f, f) for f in ADMISSION_DOCUMENT_FIELDS],
        error_messages={
            'invalid_choice': (
                "'{input}' is not a valid document field. "
                f"Allowed: {ADMISSION_DOCUMENT_FIELDS}"
            )
        },
    )
    file = serializers.FileField()

    def validate_file(self, value):
        # doc_photo only allows images; all other fields also allow PDF
        if self.initial_data.get('field_name') == 'doc_photo':
            return _validate_file(value, allowed_types=['image/jpeg', 'image/png'])
        return _validate_file(value, allowed_types=['image/jpeg', 'image/png', 'application/pdf'])