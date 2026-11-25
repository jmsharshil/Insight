"""
schofee_finance/models.py
─────────────────────────
Models for SchoFee B2B Education Loan integration.
Tracks finance applications, participants, uploaded documents, and course mappings.
SECURITY:
- No plaintext Aadhaar, PAN, or OTPs are stored at rest.
- schofee_path is stored strictly for internal submission to POST /v1/students and is never exposed in user API responses.
"""

from django.db import models


class FinanceApplicationStatus(models.TextChoices):
    INITIATED = "INITIATED", "Initiated"
    DOCUMENTS_UPLOADED = "DOCUMENTS_UPLOADED", "Documents Uploaded"
    STUDENT_CREATED = "STUDENT_CREATED", "Student Created"
    LOAN_CREATED = "LOAN_CREATED", "Loan Created"
    OTP_PENDING = "OTP_PENDING", "OTP Verification Pending"
    VERIFIED = "VERIFIED", "Verified / Complete"
    FAILED = "FAILED", "Failed"


class ParticipantRole(models.TextChoices):
    APPLICANT = "APPLICANT", "Applicant"
    CO_APPLICANT = "CO_APPLICANT", "Co-Applicant"


class DocumentOwnerType(models.TextChoices):
    STUDENT = "STUDENT", "Student"
    APPLICANT = "APPLICANT", "Applicant"
    CO_APPLICANT = "CO_APPLICANT", "Co-Applicant"


class FinanceApplication(models.Model):
    """
    Tracks the lifecycle of a SchoFee Education Loan application linked to an Admission.
    """
    admission = models.ForeignKey(
        "onboarding.Admission",
        on_delete=models.CASCADE,
        related_name="finance_applications",
        help_text="The admission record associated with this finance application.",
    )
    schofee_student_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        help_text="UUID returned by SchoFee POST /v1/students.",
    )
    schofee_loan_app_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        help_text="UUID returned by SchoFee POST /v1/loan-applications.",
    )
    schofee_customer_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text="Customer ID returned by SchoFee loan application.",
    )
    schofee_course_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text="SchoFee course UUID.",
    )
    external_student_ref = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Deterministic reference sent to SchoFee (e.g. INSIGHT-STU-{admission_id}).",
    )
    external_application_ref = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Deterministic reference sent to SchoFee (e.g. INSIGHT-LOAN-{admission_id}).",
    )
    status = models.CharField(
        max_length=30,
        choices=FinanceApplicationStatus.choices,
        default=FinanceApplicationStatus.INITIATED,
        db_index=True,
    )
    number_of_emis = models.PositiveSmallIntegerField(default=12)
    number_of_advance_emi = models.PositiveSmallIntegerField(default=0)
    downpayment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    estimated_emi_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Estimated monthly EMI amount returned by SchoFee loanStructure.",
    )

    last_error_code = models.CharField(max_length=100, blank=True, null=True)
    last_error_message = models.TextField(blank=True, null=True)
    last_trace_id = models.CharField(max_length=100, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "schofee_finance_applications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["admission", "status"]),
            models.Index(fields=["external_student_ref"]),
            models.Index(fields=["external_application_ref"]),
        ]

    def __str__(self) -> str:
        return f"FinanceApp #{self.id} (Admission: {self.admission_id}, Status: {self.status})"


class FinanceParticipant(models.Model):
    """
    Participants (Applicant or Co-Applicant) belonging to a FinanceApplication.
    """
    finance_application = models.ForeignKey(
        FinanceApplication,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    schofee_participant_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="UUID returned by SchoFee in participants array.",
    )
    role = models.CharField(
        max_length=20,
        choices=ParticipantRole.choices,
        default=ParticipantRole.APPLICANT,
    )
    participant_user_type = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="13 for Applicant, 5 for Co-Applicant per SchoFee spec.",
    )
    full_name = models.CharField(max_length=150, blank=True)
    mobile_number = models.CharField(max_length=20, blank=True)
    verification_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Latest verificationId from OTP request.",
    )
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "schofee_finance_participants"
        ordering = ["role", "created_at"]
        unique_together = ("finance_application", "schofee_participant_id")

    def __str__(self) -> str:
        return f"{self.role} - {self.full_name or self.schofee_participant_id} (Verified: {self.is_verified})"


class FinanceDocument(models.Model):
    """
    Records SchoFee blob paths obtained from POST /v1/students/documents.
    SECURITY: schofee_path is never exposed via public/user APIs.
    """
    DOCUMENT_FOR_CHOICES = (
        (4, "Student Photo"),
        (5, "Student PAN"),
        (6, "Student Aadhaar"),
        (7, "Applicant Photo"),
        (8, "Applicant PAN"),
        (9, "Applicant Aadhaar"),
        (10, "Co-Applicant Photo"),
        (11, "Co-Applicant PAN"),
        (12, "Co-Applicant Aadhaar"),
    )

    finance_application = models.ForeignKey(
        FinanceApplication,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    owner_type = models.CharField(
        max_length=20,
        choices=DocumentOwnerType.choices,
        default=DocumentOwnerType.STUDENT,
    )
    document_for = models.PositiveSmallIntegerField(choices=DOCUMENT_FOR_CHOICES)
    schofee_path = models.CharField(
        max_length=500,
        help_text="SchoFee internal document path. Never expose to client.",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "schofee_finance_documents"
        ordering = ["uploaded_at"]

    def __str__(self) -> str:
        return f"Doc {self.document_for} ({self.get_document_for_display()}) for App #{self.finance_application_id}"


class CourseMapping(models.Model):
    """
    Maps SchoFee catalog courses to local batches.Course or course slug.
    """
    local_course = models.ForeignKey(
        "batches.Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schofee_mappings",
    )
    local_course_slug = models.CharField(
        max_length=50,
        blank=True,
        help_text="Matches admission course choice, e.g. cseet, cs_executive, cs_professional",
    )
    schofee_course_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="SchoFee Course UUID",
    )
    schofee_course_name = models.CharField(max_length=200)
    schofee_course_code = models.CharField(max_length=50, blank=True)
    schofee_course_fees = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    max_emi_months = models.PositiveSmallIntegerField(default=12)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "schofee_course_mappings"
        ordering = ["schofee_course_name"]

    def __str__(self) -> str:
        return f"{self.schofee_course_code} - {self.schofee_course_name} (ID: {self.schofee_course_id})"
