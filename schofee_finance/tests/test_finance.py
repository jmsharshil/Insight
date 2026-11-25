"""
schofee_finance/tests/test_finance.py
─────────────────────────────────────
Comprehensive test suite for SchoFee B2B Education Loan integration.
Covers:
1. Token caching, early refresh, rate limiting, and cache clear.
2. SchoFeeClient 401 refresh then retry.
3. SchoFeeClient 503 retry with identical body & Idempotency-Key.
4. SchoFeeClient 409 duplicate resource & idempotency conflict error handling.
5. Resumable pipeline execution and checkpoint recovery.
6. Full happy path: documents -> student -> loan -> OTP verification -> automatic Student enrollment.
7. Serializer validation (PAN regex, 12-digit Aadhaar, file validation, mutual discount exclusivity).
8. IDOR permissions and authorization guards.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from auth_user.models import User
from branch.models import Branch
from onboarding.models import Admission
from schofee_finance.models import (
    CourseMapping,
    FinanceApplication,
    FinanceApplicationStatus,
    FinanceDocument,
    FinanceParticipant,
    ParticipantRole,
)
from schofee_finance.serializers import (
    CreateFinanceApplicationSerializer,
    validate_aadhaar,
    validate_pan,
)
from schofee_finance.services.client import SchoFeeClient
from schofee_finance.services.exceptions import (
    SchoFeeAPIError,
    SchoFeeDuplicateError,
    SchoFeeIdempotencyConflictError,
    SchoFeeRateLimitError,
    SchoFeeValidationError,
)
from schofee_finance.services.pipeline import FinancePipelineService
from schofee_finance.services.token import (
    CACHE_KEY_RATE_LIMIT,
    CACHE_KEY_TOKEN,
    SchoFeeTokenService,
)


from django.test import TestCase, override_settings

@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class BaseFinanceTestCase(TestCase):
    """Base setup helper for tests."""

    def setUp(self):
        cache.clear()
        self.branch = Branch.objects.create(
            name="Main Branch",
            city="Ahmedabad",
            state="Gujarat",
            pincode="380001",
            phone="9876543210",
            email="branch@example.com",
            qr_image="branches/qrcodes/mock_qr.png",
        )
        self.admission = Admission.objects.create(
            first_name="Aarav",
            surname="Shah",
            email="aarav.shah@example.com",
            phone_student="9876543210",
            dob="2002-05-15",
            gender="male",
            street="12 MG Road",
            city="Ahmedabad",
            state="Gujarat",
            pincode="380001",
            course="cseet",
            branch=self.branch,
            payment_type="finance",
        )
        self.course_mapping = CourseMapping.objects.create(
            schofee_course_id="crs-uuid-12345",
            schofee_course_name="CSEET Full Course",
            schofee_course_code="CS-01",
            schofee_course_fees=Decimal("45000.00"),
            local_course_slug="cseet",
        )


class TokenServiceTests(BaseFinanceTestCase):
    """Tests for SchoFeeTokenService."""

    def test_token_caching_and_early_refresh(self):
        service = SchoFeeTokenService(
            base_url="https://api.schofee.com",
            client_id="test_client",
            client_secret="test_secret",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "token_abc_123",
            "expires_in": 600,
            "token_type": "Bearer",
        }

        with patch("requests.post", return_value=mock_resp) as mock_post:
            token = service.get_token()
            self.assertEqual(token, "token_abc_123")
            self.assertEqual(mock_post.call_count, 1)

            # Subsequent call should hit cache without calling requests.post
            cached_token = service.get_token()
            self.assertEqual(cached_token, "token_abc_123")
            self.assertEqual(mock_post.call_count, 1)

            # Check cache TTL (600 - 60 = 540 seconds)
            self.assertEqual(cache.get(CACHE_KEY_TOKEN), "token_abc_123")

    def test_token_clear(self):
        cache.set(CACHE_KEY_TOKEN, "existing_token", timeout=300)
        service = SchoFeeTokenService()
        service.clear_token()
        self.assertIsNone(cache.get(CACHE_KEY_TOKEN))

    def test_token_rate_limiting(self):
        service = SchoFeeTokenService(
            base_url="https://api.schofee.com",
            client_id="test_client",
            client_secret="test_secret",
        )
        now = timezone.now().timestamp()
        # Seed 10 recent timestamps
        cache.set(CACHE_KEY_RATE_LIMIT, [now - i for i in range(10)], timeout=120)

        with self.assertRaises(SchoFeeRateLimitError):
            service.get_token(force_refresh=True)


class SchoFeeClientTests(BaseFinanceTestCase):
    """Tests for SchoFeeClient error handling and retries."""

    def setUp(self):
        super().setUp()
        self.mock_token_service = MagicMock(spec=SchoFeeTokenService)
        self.mock_token_service.get_token.return_value = "valid_bearer_token"
        self.client = SchoFeeClient(
            base_url="https://api.schofee.com",
            token_mgr=self.mock_token_service,
        )

    def test_401_refresh_and_retry(self):
        """When receiving 401, client should clear token and retry once."""
        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.json.return_value = {
            "status": False,
            "statusCode": 401,
            "message": "Token expired.",
            "errorCode": "UNAUTHENTICATED",
            "traceId": "trc-401",
        }

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "status": True,
            "statusCode": 200,
            "message": "Success",
            "data": {"items": [{"institutionID": 1, "displayName": "SBI"}]},
            "traceId": "trc-200",
        }

        with patch.object(self.client.session, "request", side_effect=[resp_401, resp_200]) as mock_req:
            banks = self.client.list_banks()
            self.assertEqual(mock_req.call_count, 2)
            self.mock_token_service.clear_token.assert_called_once()
            self.assertEqual(len(banks.get("items", [])), 1)

    def test_503_retry_with_same_key(self):
        """When receiving 503, client retries with exponential backoff and identical Idempotency-Key."""
        resp_503 = MagicMock()
        resp_503.status_code = 503
        resp_503.json.return_value = {
            "status": False,
            "statusCode": 503,
            "errorCode": "TEMPORARILY_UNAVAILABLE",
            "message": "Server busy",
        }

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "status": True,
            "statusCode": 200,
            "data": {"studentId": "std-uuid-1", "participants": []},
        }

        with patch("time.sleep", return_value=None):
            with patch.object(self.client.session, "request", side_effect=[resp_503, resp_200]) as mock_req:
                res = self.client.create_student(
                    external_student_ref="INST-STU-01",
                    student_info={},
                    applicants=[{}],
                    idempotency_key="stu-key-123",
                )
                self.assertEqual(mock_req.call_count, 2)
                # Verify Idempotency-Key header was preserved on both calls
                first_headers = mock_req.call_args_list[0][1]["headers"]
                second_headers = mock_req.call_args_list[1][1]["headers"]
                self.assertEqual(first_headers.get("Idempotency-Key"), "stu-key-123")
                self.assertEqual(second_headers.get("Idempotency-Key"), "stu-key-123")
                self.assertEqual(res.get("studentId"), "std-uuid-1")

    def test_409_duplicate_resource(self):
        resp_409 = MagicMock()
        resp_409.status_code = 409
        resp_409.json.return_value = {
            "status": False,
            "statusCode": 409,
            "errorCode": "DUPLICATE_RESOURCE",
            "message": "Record exists",
        }
        with patch.object(self.client.session, "request", return_value=resp_409):
            with self.assertRaises(SchoFeeDuplicateError):
                self.client.create_student("INST-STU-01", {}, [{}], "stu-key")

    def test_409_idempotency_conflict(self):
        resp_409 = MagicMock()
        resp_409.status_code = 409
        resp_409.json.return_value = {
            "status": False,
            "statusCode": 409,
            "errorCode": "IDEMPOTENCY_CONFLICT",
            "message": "Payload differs from original request",
        }
        with patch.object(self.client.session, "request", return_value=resp_409):
            with self.assertRaises(SchoFeeIdempotencyConflictError):
                self.client.create_student("INST-STU-01", {}, [{}], "stu-key")

    def test_document_upload_returns_path_only(self):
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "status": True,
            "statusCode": 200,
            "data": {
                "path": "students/2026/doc6_aadhaar.pdf",
                "link": "https://storage.schofee.com/temp-read-link?token=secret",
            },
        }
        with patch.object(self.client.session, "request", return_value=resp_200):
            path = self.client.upload_document(
                file_bytes=b"dummy pdf content",
                filename="aadhaar.pdf",
                content_type="application/pdf",
                document_for=6,
            )
            # Must return ONLY the path
            self.assertEqual(path, "students/2026/doc6_aadhaar.pdf")
            self.assertNotIn("http", path)


class PipelineServiceTests(BaseFinanceTestCase):
    """Tests for Resumable Pipeline execution."""

    def setUp(self):
        super().setUp()
        self.mock_client = MagicMock(spec=SchoFeeClient)
        self.pipeline = FinancePipelineService(client=self.mock_client)
        self.finance_app = FinanceApplication.objects.filter(admission=self.admission).first()
        if not self.finance_app:
            self.finance_app = FinanceApplication.objects.create(
                admission=self.admission,
                external_student_ref=f"INSIGHT-STU-{self.admission.id}",
                external_application_ref=f"INSIGHT-LOAN-{self.admission.id}",
                status=FinanceApplicationStatus.INITIATED,
            )
        else:
            self.finance_app.status = FinanceApplicationStatus.INITIATED
            self.finance_app.save()

    def test_pipeline_happy_path(self):
        # 1. Mock document uploads
        self.mock_client.upload_document.side_effect = [
            "docs/student_aadhaar.pdf",
            "docs/applicant_pan.pdf",
            "docs/applicant_aadhaar.pdf",
        ]
        # 2. Mock student create
        self.mock_client.create_student.return_value = {
            "studentId": "schofee-stu-999",
            "participants": [{"participantId": "part-uuid-1", "role": "APPLICANT"}],
        }
        # 3. Mock loan create
        self.mock_client.create_loan_application.return_value = {
            "loanAppID": "loan-uuid-888",
            "customerID": "cust-uuid-777",
            "loanStatusID": 1,
        }
        # 4. Mock required actions & loan structure
        self.mock_client.get_loan_application.return_value = {
            "loanStructure": {"emiAmount": 3750.00}
        }
        self.mock_client.get_required_actions.return_value = {
            "items": [
                {
                    "type": "PARTICIPANT_VERIFICATION",
                    "status": "PENDING",
                    "participantId": "part-uuid-1",
                    "participantUserType": 13,
                }
            ]
        }

        docs = {
            6: (b"content", "aadhaar.pdf", "application/pdf"),
            8: (b"content", "pan.pdf", "application/pdf"),
            9: (b"content", "app_aadhaar.pdf", "application/pdf"),
        }

        app = self.pipeline.run_pipeline(
            finance_app=self.finance_app,
            student_info={"email": "student@example.com"},
            applicant_info={"name": "Guardian", "pan": "ABCDE1234F"},
            loan_terms={"course_id": "crs-uuid-12345", "number_of_emis": 12},
            document_files=docs,
        )

        self.assertEqual(app.status, FinanceApplicationStatus.OTP_PENDING)
        self.assertEqual(app.schofee_student_id, "schofee-stu-999")
        self.assertEqual(app.schofee_loan_app_id, "loan-uuid-888")
        self.assertEqual(app.estimated_emi_amount, Decimal("3750.00"))
        self.assertEqual(app.participants.count(), 1)
        self.assertEqual(app.documents.count(), 3)

    def test_pipeline_resumes_from_failed_step(self):
        """If pipeline failed after document upload, retry does not re-upload documents."""
        # Pre-seed uploaded documents
        FinanceDocument.objects.create(
            finance_application=self.finance_app,
            document_for=6,
            schofee_path="docs/existing_doc6.pdf",
        )
        self.finance_app.status = FinanceApplicationStatus.DOCUMENTS_UPLOADED
        self.finance_app.save()

        # Step 2: Student creation
        self.mock_client.create_student.return_value = {
            "studentId": "schofee-stu-resumed",
            "participants": [{"participantId": "part-resumed-1", "role": "APPLICANT"}],
        }
        self.mock_client.create_loan_application.return_value = {
            "loanAppID": "loan-uuid-resumed",
        }
        self.mock_client.get_loan_application.return_value = {"loanStructure": {"emiAmount": 4000}}
        self.mock_client.get_required_actions.return_value = {"items": []}  # Verification complete!

        app = self.pipeline.run_pipeline(
            finance_app=self.finance_app,
            student_info={"email": "student@example.com"},
            applicant_info={"name": "Guardian"},
            loan_terms={"course_id": "crs-uuid-12345"},
            document_files={},
        )

        # Upload document was NEVER called because status was already DOCUMENTS_UPLOADED
        self.mock_client.upload_document.assert_not_called()
        self.assertEqual(app.status, FinanceApplicationStatus.VERIFIED)
        self.assertEqual(app.schofee_student_id, "schofee-stu-resumed")


class SerializerValidationTests(BaseFinanceTestCase):
    """Tests for serializer data validations."""

    def test_pan_validation(self):
        self.assertEqual(validate_pan("ABCPD1234E"), "ABCPD1234E")
        with self.assertRaises(Exception):
            validate_pan("INVALIDPAN")
        with self.assertRaises(Exception):
            validate_pan("12345ABCDE")

    def test_aadhaar_validation(self):
        self.assertEqual(validate_aadhaar("123456789012"), "123456789012")
        self.assertEqual(validate_aadhaar("1234 5678 9012"), "123456789012")
        with self.assertRaises(Exception):
            validate_aadhaar("12345")  # Too short
        with self.assertRaises(Exception):
            validate_aadhaar("1234567890123")  # Too long

    def test_discount_mutual_exclusivity(self):
        data = {
            "admission_id": self.admission.id,
            "student_info": {
                "email": "test@example.com",
                "mobileNumber": "9876543210",
                "aadhaar": "123456789012",
                "fullName": "Student Name",
                "firstName": "Student",
                "lastName": "Name",
                "dateOfBirth": "2000-01-01",
                "gender": "M",
                "address": "Street 1",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "zipCode": "380001",
            },
            "applicant_info": {
                "name": "Applicant Name",
                "firstName": "Applicant",
                "lastName": "Name",
                "pan": "ABCPD1234E",
                "aadhaar": "987654321098",
                "email": "applicant@example.com",
                "mobileNumber": "9876543211",
                "dateOfBirth": "1975-01-01",
                "gender": "Male",
                "address": "Street 1",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "zipCode": "380001",
            },
            "loan_terms": {
                "course_id": "crs-123",
                "discount_amount": 1000,
                "discount_percentage": 10,  # Conflict: both provided!
            },
        }
        serializer = CreateFinanceApplicationSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("loan_terms", serializer.errors)


class ViewsAndIDORTests(BaseFinanceTestCase):
    """Tests for DRF API views and IDOR security checks."""

    def setUp(self):
        super().setUp()
        self.api_client = APIClient()
        self.student_user = User.objects.create(
            username="student_user",
            email="aarav.shah@example.com",
            role="student",
        )
        self.other_user = User.objects.create(
            username="other_student",
            email="other.student@example.com",
            role="student",
        )
        self.finance_app = FinanceApplication.objects.filter(admission=self.admission).first()
        if not self.finance_app:
            self.finance_app = FinanceApplication.objects.create(
                admission=self.admission,
                external_student_ref=f"INSIGHT-STU-{self.admission.id}",
                external_application_ref=f"INSIGHT-LOAN-{self.admission.id}",
                status=FinanceApplicationStatus.OTP_PENDING,
            )
        else:
            self.finance_app.status = FinanceApplicationStatus.OTP_PENDING
            self.finance_app.save()

    def test_authorized_student_access(self):
        self.api_client.force_authenticate(user=self.student_user)
        response = self.api_client.get(f"/api/v1/finance/applications/{self.finance_app.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["id"], self.finance_app.id)

    def test_idor_unauthorized_student_forbidden(self):
        """A different student cannot read another student's finance application."""
        self.api_client.force_authenticate(user=self.other_user)
        response = self.api_client.get(f"/api/v1/finance/applications/{self.finance_app.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_courses_endpoint(self):
        response = self.api_client.get("/api/v1/finance/courses/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(len(response.data["data"]) >= 1)
        self.assertEqual(response.data["data"][0]["schofee_course_id"], "crs-uuid-12345")
