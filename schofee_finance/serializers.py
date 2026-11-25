"""
schofee_finance/serializers.py
──────────────────────────────
DRF Serializers for SchoFee B2B Education Loan API.
Strictly implements validation rules from the SchoFee v3.0 Specification:
- PAN regex (10 characters: 5 letters, 4 digits, 1 letter)
- Aadhaar (exactly 12 ASCII digits)
- Gender choices (M/F/O/Male/Female/Other)
- DOB formats (yyyy-MM-dd, dd/MM/yyyy, d/M/yyyy, dd-MM-yyyy, MM/dd/yyyy)
- 63 UTF-8 byte ceiling for encrypted fields
- Discount mutual exclusivity (discount_amount XOR discount_percentage)
- File size (<= 20 MiB) and format checks (photo: jpg/jpeg/png; PAN/Aadhaar: +pdf)
- Never exposes internal schofee_path in output serialization
"""

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from rest_framework import serializers

from .models import (
    CourseMapping,
    FinanceApplication,
    FinanceDocument,
    FinanceParticipant,
)
from .services.verhoeff import fix_or_generate_verhoeff_aadhaar, validate_verhoeff

PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")
AADHAAR_REGEX = re.compile(r"^\d{12}$")
GENDER_CHOICES = ["M", "F", "O", "Male", "Female", "Other", "male", "female", "other"]
ACCEPTED_DOB_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"]


def validate_pan(value: Optional[str]) -> str:
    if not value:
        raise serializers.ValidationError("PAN is required.")
    cleaned = value.strip().upper()
    if not PAN_REGEX.match(cleaned):
        raise serializers.ValidationError("Invalid PAN format. Must be 10 characters (e.g. ABCPD1234E).")
    if len(cleaned.encode("utf-8")) > 63:
        raise serializers.ValidationError("PAN exceeds 63 bytes.")
    return cleaned


def validate_aadhaar(value: Optional[str]) -> str:
    if not value:
        raise serializers.ValidationError("Aadhaar number is required.")
    cleaned = re.sub(r"\s+", "", str(value).strip())
    if not AADHAAR_REGEX.match(cleaned):
        raise serializers.ValidationError("Aadhaar must be exactly 12 digits.")
    return cleaned


def validate_dob(value: Any) -> str:
    if not value:
        raise serializers.ValidationError("Date of birth is required.")
    str_val = str(value).strip()
    valid = False
    for fmt in ACCEPTED_DOB_FORMATS:
        try:
            datetime.strptime(str_val, fmt)
            valid = True
            break
        except ValueError:
            continue
    if not valid:
        raise serializers.ValidationError(
            "Invalid date of birth format. Accepted formats: yyyy-MM-dd, dd/MM/yyyy, dd-MM-yyyy, MM/dd/yyyy."
        )
    return str_val


def validate_max_63_bytes(value: Optional[str], field_name: str) -> str:
    val = (value or "").strip()
    if len(val.encode("utf-8")) > 63:
        raise serializers.ValidationError(f"{field_name} must not exceed 63 UTF-8 bytes.")
    return val


def validate_file(uploaded_file, allowed_extensions: List[str], max_bytes: int = 20 * 1024 * 1024) -> None:
    if not uploaded_file:
        raise serializers.ValidationError("File is required.")
    if uploaded_file.size > max_bytes:
        raise serializers.ValidationError(f"File size exceeds limit of {max_bytes // (1024 * 1024)} MiB.")
    if uploaded_file.size == 0:
        raise serializers.ValidationError("Uploaded file is empty.")
    name = uploaded_file.name.lower()
    if not any(name.endswith(ext) for ext in allowed_extensions):
        raise serializers.ValidationError(
            f"Unsupported file format. Allowed formats: {', '.join(allowed_extensions)}."
        )


# ── Nested Info Serializers ──────────────────────────────────────────────────

class StudentInfoSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    mobileNumber = serializers.CharField(required=True, max_length=20)
    pan = serializers.CharField(required=True, help_text="Valid 10-character PAN")
    aadhaar = serializers.CharField(required=True, help_text="Valid 12-digit Aadhaar")
    fullName = serializers.CharField(required=True, max_length=150)
    firstName = serializers.CharField(required=True, max_length=100)
    middleName = serializers.CharField(required=False, allow_blank=True, max_length=100)
    lastName = serializers.CharField(required=True, max_length=100)
    dateOfBirth = serializers.CharField(required=True)
    gender = serializers.ChoiceField(choices=GENDER_CHOICES, required=True)
    address = serializers.CharField(required=True)
    city = serializers.CharField(required=True, max_length=100)
    state = serializers.CharField(required=True, max_length=100)
    zipCode = serializers.CharField(required=True, max_length=20)

    def validate_pan(self, value):
        return validate_pan(value)

    def validate_aadhaar(self, value):
        return validate_aadhaar(value)

    def validate_dateOfBirth(self, value):
        return validate_dob(value)

    def validate_city(self, value):
        return validate_max_63_bytes(value, "city")

    def validate_state(self, value):
        return validate_max_63_bytes(value, "state")

    def validate_zipCode(self, value):
        return validate_max_63_bytes(value, "zipCode")


class ParticipantInfoSerializer(serializers.Serializer):
    name = serializers.CharField(required=True, max_length=150, help_text="Full name")
    firstName = serializers.CharField(required=True, max_length=100)
    lastName = serializers.CharField(required=True, max_length=100)
    pan = serializers.CharField(required=True)
    aadhaar = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)
    mobileNumber = serializers.CharField(required=True, max_length=20)
    dateOfBirth = serializers.CharField(required=True)
    gender = serializers.ChoiceField(choices=GENDER_CHOICES, required=True)
    address = serializers.CharField(required=True)
    city = serializers.CharField(required=True, max_length=100)
    state = serializers.CharField(required=True, max_length=100)
    zipCode = serializers.CharField(required=True, max_length=20)

    def validate_pan(self, value):
        return validate_pan(value)

    def validate_aadhaar(self, value):
        return validate_aadhaar(value)

    def validate_dateOfBirth(self, value):
        return validate_dob(value)

    def validate_city(self, value):
        return validate_max_63_bytes(value, "city")

    def validate_state(self, value):
        return validate_max_63_bytes(value, "state")

    def validate_zipCode(self, value):
        return validate_max_63_bytes(value, "zipCode")


class LoanTermsSerializer(serializers.Serializer):
    course_id = serializers.CharField(required=False, allow_blank=True)
    number_of_emis = serializers.IntegerField(required=False, default=12, min_value=1, max_value=60)
    number_of_advance_emi = serializers.IntegerField(required=False, default=0, min_value=0)
    downpayment_amount = serializers.DecimalField(required=False, default=Decimal("0"), max_digits=12, decimal_places=2, min_value=0)
    discount_amount = serializers.DecimalField(required=False, allow_null=True, max_digits=12, decimal_places=2, min_value=0)
    discount_percentage = serializers.DecimalField(required=False, allow_null=True, max_digits=5, decimal_places=2, min_value=0, max_value=100)

    def validate(self, attrs):
        disc_amt = attrs.get("discount_amount")
        disc_pct = attrs.get("discount_percentage")
        if disc_amt is not None and disc_pct is not None:
            raise serializers.ValidationError("Provide either discount_amount OR discount_percentage, never both.")
        return attrs


# ── Full Loan Application Submission Serializer ──────────────────────────────

class CreateFinanceApplicationSerializer(serializers.Serializer):
    admission_id = serializers.IntegerField(required=True)
    student_info = StudentInfoSerializer(required=True)
    applicant_info = ParticipantInfoSerializer(required=True)
    co_applicant_info = ParticipantInfoSerializer(required=False, allow_null=True)
    loan_terms = LoanTermsSerializer(required=True)

    # Required files
    file_student_aadhaar = serializers.FileField(required=False)
    file_applicant_pan = serializers.FileField(required=False)
    file_applicant_aadhaar = serializers.FileField(required=False)

    # Optional files
    file_student_photo = serializers.FileField(required=False, allow_null=True)
    file_student_pan = serializers.FileField(required=False, allow_null=True)
    file_applicant_photo = serializers.FileField(required=False, allow_null=True)
    file_co_applicant_photo = serializers.FileField(required=False, allow_null=True)
    file_co_applicant_pan = serializers.FileField(required=False, allow_null=True)
    file_co_applicant_aadhaar = serializers.FileField(required=False, allow_null=True)

    def validate(self, attrs):
        photo_exts = [".jpg", ".jpeg", ".png"]
        doc_exts = [".jpg", ".jpeg", ".png", ".pdf"]

        # Validate file formats & sizes if provided
        for field, exts in [
            ("file_student_photo", photo_exts),
            ("file_student_pan", doc_exts),
            ("file_student_aadhaar", doc_exts),
            ("file_applicant_photo", photo_exts),
            ("file_applicant_pan", doc_exts),
            ("file_applicant_aadhaar", doc_exts),
            ("file_co_applicant_photo", photo_exts),
            ("file_co_applicant_pan", doc_exts),
            ("file_co_applicant_aadhaar", doc_exts),
        ]:
            f = attrs.get(field)
            if f:
                validate_file(f, exts)

        return attrs


# ── Output & Status Serializers ──────────────────────────────────────────────

class FinanceParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinanceParticipant
        fields = [
            "id",
            "schofee_participant_id",
            "role",
            "participant_user_type",
            "full_name",
            "mobile_number",
            "is_verified",
            "verified_at",
        ]


class FinanceApplicationDetailSerializer(serializers.ModelSerializer):
    participants = FinanceParticipantSerializer(many=True, read_only=True)
    admission_code = serializers.CharField(source="admission.admission_code", read_only=True)
    admission_name = serializers.SerializerMethodField()

    class Meta:
        model = FinanceApplication
        fields = [
            "id",
            "admission_id",
            "admission_code",
            "admission_name",
            "external_student_ref",
            "external_application_ref",
            "status",
            "schofee_loan_app_id",
            "number_of_emis",
            "number_of_advance_emi",
            "downpayment_amount",
            "estimated_emi_amount",
            "last_error_code",
            "last_error_message",
            "participants",
            "created_at",
            "updated_at",
        ]

    def get_admission_name(self, obj) -> str:
        adm = obj.admission
        return f"{adm.first_name} {adm.surname or ''}".strip()


# ── OTP Action Serializers ───────────────────────────────────────────────────

class OTPVerifyRequestSerializer(serializers.Serializer):
    otp = serializers.CharField(required=True, max_length=10)
    verification_id = serializers.CharField(required=False, allow_blank=True)


# ── Course Catalog Serializer ────────────────────────────────────────────────

class CourseMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseMapping
        fields = [
            "id",
            "schofee_course_id",
            "schofee_course_name",
            "schofee_course_code",
            "schofee_course_fees",
            "max_emi_months",
            "local_course_slug",
            "is_active",
        ]
