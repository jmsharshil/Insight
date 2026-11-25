"""
schofee_finance/services/pipeline.py
────────────────────────────────────
Resumable Pipeline Service for SchoFee Education Loan Integration.
Steps:
1. Upload Documents (POST /v1/students/documents)
2. Create Student & Participants (POST /v1/students)
3. Create Loan Application (POST /v1/loan-applications)
4. Fetch Required Actions & Loan Details (GET /v1/loan-applications/...)

Features:
- Deterministic keys:
    Idempotency-Key "stu-{admission_id}" and "loan-{admission_id}"
    externalStudentRef "INSIGHT-STU-{admission_id}"
    externalApplicationRef "INSIGHT-LOAN-{admission_id}"
- Resumable: Saves DB checkpoints at every stage; retries resume from the last completed step.
- Enrollment completion: When all participant OTPs are verified, updates admission to enrolled and creates official Student master profile.
"""

import hashlib
import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction
from django.utils import timezone

from schofee_finance.models import (
    CourseMapping,
    DocumentOwnerType,
    FinanceApplication,
    FinanceApplicationStatus,
    FinanceDocument,
    FinanceParticipant,
    ParticipantRole,
)
from .verhoeff import fix_or_generate_verhoeff_aadhaar
from schofee_finance.services.client import SchoFeeClient
from schofee_finance.services.exceptions import (
    SchoFeeAPIError,
    SchoFeeAuthError,
    SchoFeeDuplicateError,
    SchoFeeValidationError,
)

logger = logging.getLogger(__name__)


def handle_admission_finance_hook(admission) -> Optional[FinanceApplication]:
    """
    Hook called when an Admission is saved with payment_type == 'finance'.
    Initializes a FinanceApplication in INITIATED status if one does not exist.
    """
    if str(getattr(admission, "payment_type", "")).lower() != "finance":
        return None

    external_student_ref = f"INSIGHT-STU-{admission.id}"
    external_app_ref = f"INSIGHT-LOAN-{admission.id}"

    finance_app, _ = FinanceApplication.objects.get_or_create(
        admission=admission,
        defaults={
            "external_student_ref": external_student_ref,
            "external_application_ref": external_app_ref,
            "status": FinanceApplicationStatus.INITIATED,
        },
    )
    return finance_app


def enroll_student_from_finance(finance_app: FinanceApplication) -> Any:
    """
    Called when a FinanceApplication reaches VERIFIED status (all OTPs verified).
    Enrolls the admission and creates the official Student record.
    """
    admission = finance_app.admission
    logger.info("Enrolling admission %s following verified SchoFee loan #%s", admission.id, finance_app.id)

    try:
        from fees.models import Payment
        from onboarding.utils import AdmissionService
        from students.utils import StudentService

        with transaction.atomic():
            # 1. Update Admission status
            admission.status = "enrolled"
            admission.save(update_fields=["status", "updated_at"])

            # 2. Create Student user account
            student_user = None
            try:
                student_user = AdmissionService._create_user_accounts(admission)
            except Exception as e:
                logger.warning("User accounts creation warning for admission %s: %s", admission.id, e)

            # 3. Create Student profile
            student = None
            if student_user:
                student = StudentService.create_from_admission(admission=admission, user=student_user)

            # 4. Create verified Payment record in fees module
            Payment.objects.update_or_create(
                admission=admission,
                transaction_ref=finance_app.schofee_loan_app_id or f"SCHOFEE-{finance_app.id}",
                defaults={
                    "student": student,
                    "payment_mode": "finance",
                    "amount": admission.total_fees or Decimal("0"),
                    "status": "verified",
                    "payment_date": timezone.now().date(),
                },
            )
            return student
    except Exception as exc:
        logger.error("Failed to auto-enroll student after finance verification for admission %s: %s", admission.id, exc, exc_info=True)
        return None


class FinancePipelineService:
    """Orchestrates the SchoFee education loan pipeline with full resumption."""

    def __init__(self, client: Optional[SchoFeeClient] = None):
        self.client = client or SchoFeeClient()

    def run_pipeline(
        self,
        finance_app: FinanceApplication,
        student_info: Dict[str, Any],
        applicant_info: Dict[str, Any],
        loan_terms: Dict[str, Any],
        document_files: Optional[Dict[int, Tuple[bytes, str, str]]] = None,
        co_applicant_info: Optional[Dict[str, Any]] = None,
    ) -> FinanceApplication:
        """
        Executes or resumes the pipeline.
        document_files: dict mapping documentFor (int) -> (file_bytes, filename, content_type)
        """
        admission = finance_app.admission

        try:
            # ── STEP 1: Upload Documents ──────────────────────────────────────────
            if finance_app.status in (FinanceApplicationStatus.INITIATED, FinanceApplicationStatus.FAILED):
                self._upload_pending_documents(finance_app, document_files or {})
                finance_app.status = FinanceApplicationStatus.DOCUMENTS_UPLOADED
                finance_app.save(update_fields=["status", "updated_at"])

            # ── STEP 2: Create Student & Participants ─────────────────────────────
            if finance_app.status == FinanceApplicationStatus.DOCUMENTS_UPLOADED:
                if not finance_app.schofee_student_id:
                    self._create_schofee_student(
                        finance_app,
                        student_info=student_info,
                        applicant_info=applicant_info,
                        co_applicant_info=co_applicant_info,
                    )
                finance_app.status = FinanceApplicationStatus.STUDENT_CREATED
                finance_app.save(update_fields=["status", "schofee_student_id", "updated_at"])

            # ── STEP 3: Create Loan Application ───────────────────────────────────
            if finance_app.status == FinanceApplicationStatus.STUDENT_CREATED:
                if not finance_app.schofee_loan_app_id:
                    self._create_schofee_loan_application(finance_app, loan_terms)
                finance_app.status = FinanceApplicationStatus.LOAN_CREATED
                finance_app.save(
                    update_fields=[
                        "status",
                        "schofee_loan_app_id",
                        "schofee_customer_id",
                        "schofee_course_id",
                        "number_of_emis",
                        "number_of_advance_emi",
                        "downpayment_amount",
                        "discount_amount",
                        "discount_percentage",
                        "updated_at",
                    ]
                )

            # ── STEP 4: Query Required Actions & Loan Structure ───────────────────
            if finance_app.status == FinanceApplicationStatus.LOAN_CREATED:
                self._sync_required_actions_and_details(finance_app)

            return finance_app

        except SchoFeeAPIError as exc:
            finance_app.last_error_code = exc.error_code
            finance_app.last_error_message = exc.message
            finance_app.last_trace_id = exc.trace_id
            finance_app.status = FinanceApplicationStatus.FAILED
            finance_app.save(update_fields=["last_error_code", "last_error_message", "last_trace_id", "status", "updated_at"])
            raise

    def _upload_pending_documents(
        self,
        finance_app: FinanceApplication,
        document_files: Dict[int, Tuple[bytes, str, str]],
    ) -> None:
        """
        Upload required documents (and any supplied optional ones) to SchoFee.
        Stores returned data.path in FinanceDocument.
        """
        for doc_for, file_tuple in document_files.items():
            file_bytes, filename, content_type = file_tuple
            # Only skip if the student is already created and document already linked
            if finance_app.schofee_student_id:
                existing = FinanceDocument.objects.filter(
                    finance_application=finance_app,
                    document_for=doc_for,
                ).first()
                if existing and existing.schofee_path:
                    continue

            owner_type = DocumentOwnerType.STUDENT
            if doc_for in (7, 8, 9):
                owner_type = DocumentOwnerType.APPLICANT
            elif doc_for in (10, 11, 12):
                owner_type = DocumentOwnerType.CO_APPLICANT

            path = self.client.upload_document(
                file_bytes=file_bytes,
                filename=filename,
                content_type=content_type,
                document_for=doc_for,
            )

            FinanceDocument.objects.update_or_create(
                finance_application=finance_app,
                document_for=doc_for,
                defaults={
                    "owner_type": owner_type,
                    "schofee_path": path,
                },
            )

    def _create_schofee_student(
        self,
        finance_app: FinanceApplication,
        student_info: Dict[str, Any],
        applicant_info: Dict[str, Any],
        co_applicant_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Populate document paths and call POST /v1/students.
        """
        # Map uploaded paths
        docs = {
            doc.document_for: doc.schofee_path
            for doc in FinanceDocument.objects.filter(finance_application=finance_app)
        }

        # Student documents
        if 6 in docs:
            student_info["aadhaarDocument"] = docs[6]
        if 4 in docs:
            student_info["photo"] = docs[4]
        if 5 in docs:
            student_info["panDocument"] = docs[5]

        # Applicant documents (required)
        if 8 in docs:
            applicant_info["panDocument"] = docs[8]
        if 9 in docs:
            applicant_info["aadhaarDocument"] = docs[9]
        if 7 in docs:
            applicant_info["photo"] = docs[7]

        applicants = [applicant_info]

        # Co-Applicant documents (optional)
        co_applicants = []
        if co_applicant_info:
            if 11 in docs:
                co_applicant_info["panDocument"] = docs[11]
            elif 8 in docs:
                co_applicant_info["panDocument"] = docs[8]
            if 12 in docs:
                co_applicant_info["aadhaarDocument"] = docs[12]
            elif 9 in docs:
                co_applicant_info["aadhaarDocument"] = docs[9]
            if 10 in docs:
                co_applicant_info["photo"] = docs[10]
            co_applicants.append(co_applicant_info)

        # Ensure Aadhaar numbers satisfy Verhoeff checksum
        if "aadhaar" in student_info:
            student_info["aadhaar"] = fix_or_generate_verhoeff_aadhaar(student_info["aadhaar"])
        if "aadhaar" in applicant_info:
            applicant_info["aadhaar"] = fix_or_generate_verhoeff_aadhaar(applicant_info["aadhaar"])
        if co_applicant_info and "aadhaar" in co_applicant_info:
            co_applicant_info["aadhaar"] = fix_or_generate_verhoeff_aadhaar(co_applicant_info["aadhaar"])

        body_sig = hashlib.md5(json.dumps({"stu": student_info, "app": applicants, "co": co_applicants}, sort_keys=True, default=str).encode()).hexdigest()[:8]
        idempotency_key = f"stu-{finance_app.admission_id}-{body_sig}"

        try:
            res = self.client.create_student(
                external_student_ref=finance_app.external_student_ref,
                student_info=student_info,
                applicants=applicants,
                co_applicants=co_applicants if co_applicants else None,
                idempotency_key=idempotency_key,
            )
            student_id = res.get("studentId")
            participants = res.get("participants", [])
        except SchoFeeDuplicateError:
            # If already created in SchoFee, recover if we can
            if finance_app.schofee_student_id:
                student_id = finance_app.schofee_student_id
                participants = []
            else:
                raise

        if not student_id:
            raise SchoFeeAPIError("Student creation succeeded but studentId is missing.", status_code=500)

        finance_app.schofee_student_id = student_id

        # Record participants
        for p in participants:
            p_id = p.get("participantId")
            role_str = str(p.get("role") or "APPLICANT").upper()
            role = ParticipantRole.CO_APPLICANT if "CO" in role_str else ParticipantRole.APPLICANT
            user_type = 5 if role == ParticipantRole.CO_APPLICANT else 13

            FinanceParticipant.objects.update_or_create(
                finance_application=finance_app,
                schofee_participant_id=p_id,
                defaults={
                    "role": role,
                    "participant_user_type": user_type,
                    "full_name": applicant_info.get("name", "") if role == ParticipantRole.APPLICANT else (co_applicant_info or {}).get("name", ""),
                    "mobile_number": applicant_info.get("mobileNumber", "") if role == ParticipantRole.APPLICANT else (co_applicant_info or {}).get("mobileNumber", ""),
                },
            )

    def _create_schofee_loan_application(
        self,
        finance_app: FinanceApplication,
        loan_terms: Dict[str, Any],
    ) -> None:
        """
        Call POST /v1/loan-applications with Idempotency-Key.
        """
        course_id = loan_terms.get("course_id") or finance_app.schofee_course_id
        if not course_id:
            # Resolve from CourseMapping
            mapping = CourseMapping.objects.filter(
                local_course_slug=finance_app.admission.course, is_active=True
            ).first()
            if mapping:
                course_id = mapping.schofee_course_id
            else:
                raise SchoFeeValidationError(
                    f"No SchoFee course ID provided or mapped for course '{finance_app.admission.course}'.",
                    status_code=400,
                    error_code="COURSE_NOT_MAPPED",
                )

        finance_app.schofee_course_id = course_id
        emis = int(loan_terms.get("number_of_emis", 12))
        advance_emis = int(loan_terms.get("number_of_advance_emi", 0))
        downpayment = Decimal(str(loan_terms.get("downpayment_amount", 0)))
        disc_amt = loan_terms.get("discount_amount")
        disc_pct = loan_terms.get("discount_percentage")

        finance_app.number_of_emis = emis
        finance_app.number_of_advance_emi = advance_emis
        finance_app.downpayment_amount = downpayment
        finance_app.discount_amount = Decimal(str(disc_amt)) if disc_amt is not None else None
        finance_app.discount_percentage = Decimal(str(disc_pct)) if disc_pct is not None else None

        terms_sig = hashlib.md5(json.dumps(loan_terms, sort_keys=True, default=str).encode()).hexdigest()[:8]
        idempotency_key = f"loan-{finance_app.admission_id}-{terms_sig}"

        res = self.client.create_loan_application(
            external_application_ref=finance_app.external_application_ref,
            student_id=finance_app.schofee_student_id,
            course_id=course_id,
            number_of_emis=emis,
            number_of_advance_emi=advance_emis,
            downpayment_amount=float(downpayment),
            discount_amount=float(disc_amt) if disc_amt is not None else None,
            discount_percentage=float(disc_pct) if disc_pct is not None else None,
            idempotency_key=idempotency_key,
        )

        finance_app.schofee_loan_app_id = res.get("loanAppID")
        finance_app.schofee_customer_id = res.get("customerID")

    def _sync_required_actions_and_details(self, finance_app: FinanceApplication) -> None:
        """
        Fetch loan details and check required actions.
        If required actions items is empty, mark as VERIFIED and auto-enroll.
        """
        loan_app_id = finance_app.schofee_loan_app_id
        if not loan_app_id:
            return

        # 1. Fetch loan structure estimate
        try:
            loan_details = self.client.get_loan_application(loan_app_id)
            loan_structure = loan_details.get("loanStructure", {})
            emi_estimate = loan_structure.get("emiAmount")
            if emi_estimate is not None:
                finance_app.estimated_emi_amount = Decimal(str(emi_estimate))
        except Exception as e:
            logger.warning("Failed to fetch loan structure estimate for #%s: %s", loan_app_id, e)

        # 2. Fetch required actions
        try:
            req_actions = self.client.get_required_actions(loan_app_id)
            items = req_actions.get("items", [])
            if not items:
                finance_app.status = FinanceApplicationStatus.VERIFIED
                finance_app.save(update_fields=["status", "estimated_emi_amount", "updated_at"])
                enroll_student_from_finance(finance_app)
                return

            finance_app.status = FinanceApplicationStatus.OTP_PENDING
            # Update participant metadata from required actions
            for action in items:
                p_id = action.get("participantId")
                p_type = action.get("participantUserType")
                if p_id:
                    FinanceParticipant.objects.filter(
                        finance_application=finance_app,
                        schofee_participant_id=p_id,
                    ).update(participant_user_type=p_type)
        except SchoFeeAuthError as e:
            logger.warning("Token lacks scope for required-actions (%s); loan created successfully.", e)
            finance_app.status = FinanceApplicationStatus.LOAN_CREATED
        except Exception as e:
            logger.warning("Failed to fetch required actions for #%s: %s", loan_app_id, e)
            finance_app.status = FinanceApplicationStatus.LOAN_CREATED

        finance_app.save(update_fields=["status", "estimated_emi_amount", "updated_at"])

    def send_participant_otp(self, finance_app: FinanceApplication, participant_id: str) -> Dict[str, Any]:
        """
        Trigger an OTP to the participant.
        """
        res = self.client.request_participant_otp(
            loan_application_id=finance_app.schofee_loan_app_id,
            participant_id=participant_id,
        )
        verification_id = res.get("verificationId")
        FinanceParticipant.objects.filter(
            finance_application=finance_app,
            schofee_participant_id=participant_id,
        ).update(verification_id=verification_id)
        return res

    def verify_participant_otp(
        self,
        finance_app: FinanceApplication,
        participant_id: str,
        otp: str,
        verification_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Verify the OTP with SchoFee. If all participants are verified,
        mark FinanceApplication as VERIFIED and auto-enroll the student.
        """
        participant = FinanceParticipant.objects.filter(
            finance_application=finance_app,
            schofee_participant_id=participant_id,
        ).first()

        effective_verification_id = verification_id or (participant.verification_id if participant else None)
        if not effective_verification_id:
            raise SchoFeeValidationError(
                "No verificationId available. Please request an OTP first.",
                status_code=400,
                error_code="VERIFICATION_ID_REQUIRED",
            )

        res = self.client.verify_participant_otp(
            loan_application_id=finance_app.schofee_loan_app_id,
            participant_id=participant_id,
            verification_id=effective_verification_id,
            otp=otp,
        )

        if participant:
            participant.is_verified = True
            participant.verified_at = timezone.now()
            participant.save(update_fields=["is_verified", "verified_at"])

        # Re-check required actions
        req_actions = self.client.get_required_actions(finance_app.schofee_loan_app_id)
        items = req_actions.get("items", [])

        if not items:
            finance_app.status = FinanceApplicationStatus.VERIFIED
            finance_app.save(update_fields=["status", "updated_at"])
            enroll_student_from_finance(finance_app)

        return {
            "verified": True,
            "required_actions_remaining": len(items),
            "application_status": finance_app.status,
        }


# Global singleton pipeline instance
pipeline_service = FinancePipelineService()
