"""
schofee_finance/services/client.py
──────────────────────────────────
SchoFee B2B API v3.0 Client.
Implements the 10 endpoints of the SchoFee v3.0 specification:
1. POST /v1/oauth/token (via SchoFeeTokenService)
2. GET /v1/courses
3. GET /v1/banks
4. POST /v1/students/documents
5. POST /v1/students
6. POST /v1/loan-applications
7. GET /v1/loan-applications/{loanApplicationId}
8. GET /v1/loan-applications/{loanApplicationId}/required-actions
9. POST /v1/loan-applications/{loanApplicationId}/participants/{participantId}/otp-requests
10. POST /v1/loan-applications/{loanApplicationId}/participants/{participantId}/otp-verifications

SECURITY RULES:
- Never log request bodies (which contain Aadhaar, PAN, OTP, addresses).
- Never log response bodies or document paths.
- Never log access tokens or credentials.
- Log only: traceId, endpoint, HTTP status, and errorCode.
- Return only path (never link) for document uploads.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import requests
from django.conf import settings

from .exceptions import (
    SchoFeeAPIError,
    SchoFeeAuthError,
    SchoFeeConflictError,
    SchoFeeDownPaymentRequiredError,
    SchoFeeDuplicateError,
    SchoFeeIdempotencyConflictError,
    SchoFeeNotFoundError,
    SchoFeeRateLimitError,
    SchoFeeServiceUnavailableError,
    SchoFeeStateConflictError,
    SchoFeeValidationError,
)
from .token import SchoFeeTokenService, token_service

logger = logging.getLogger(__name__)

MAX_RETRIES_503 = 3
INITIAL_BACKOFF_SECONDS = 1.0


class SchoFeeClient:
    """Official HTTP client for SchoFee B2B API v3.0."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
        token_mgr: Optional[SchoFeeTokenService] = None,
    ):
        self.base_url = (base_url or getattr(settings, "SCHOFEE_BASE_URL", "")).rstrip("/")
        # Ensure base_url does not end in /v1
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.timeout = timeout or getattr(settings, "SCHOFEE_TIMEOUT_SECONDS", 30)
        self.token_service = token_mgr or token_service
        self.session = requests.Session()

    def _build_url(self, endpoint: str) -> str:
        """Construct full URL with /v1 prefix."""
        endpoint = endpoint.lstrip("/")
        if not endpoint.startswith("v1/"):
            endpoint = f"v1/{endpoint}"
        return f"{self.base_url}/{endpoint}"

    def _parse_response(self, response: requests.Response) -> Tuple[Dict[str, Any], str, Optional[str]]:
        """
        Extract envelope data, traceId, and errorCode from response.
        Envelopes follow: {status, statusCode, message, data, traceId, errorCode, errors}
        """
        trace_id = ""
        error_code = None
        data = {}

        try:
            body = response.json()
            if isinstance(body, dict):
                trace_id = str(body.get("traceId") or "")
                error_code = body.get("errorCode")
                data = body
        except ValueError:
            data = {"raw_text": response.text}

        return data, trace_id, error_code

    def _raise_for_status(
        self,
        response: requests.Response,
        endpoint: str,
        envelope: Dict[str, Any],
        trace_id: str,
        error_code: Optional[str],
    ) -> None:
        """
        Translate HTTP status and errorCode into typed exceptions.
        Never logs request/response payloads.
        """
        status_code = response.status_code
        message = envelope.get("message") or f"HTTP {status_code} error from SchoFee"
        errors = envelope.get("errors") or []

        # Sanitized log: method, endpoint, status, errorCode, traceId
        logger.error(
            "SchoFee API error | endpoint=%s status=%d errorCode=%s traceId=%s message=%s",
            endpoint,
            status_code,
            error_code,
            trace_id,
            message,
        )

        if status_code == 400:
            raise SchoFeeValidationError(
                message=message,
                status_code=400,
                error_code=error_code or "VALIDATION_ERROR",
                trace_id=trace_id,
                errors=errors,
                raw_response=envelope,
            )
        elif status_code == 401:
            raise SchoFeeAuthError(
                message=message,
                status_code=401,
                error_code=error_code or "UNAUTHENTICATED",
                trace_id=trace_id,
                errors=errors,
                raw_response=envelope,
            )
        elif status_code == 403:
            raise SchoFeeAuthError(
                message="Token lacks required scope for this operation.",
                status_code=403,
                error_code=error_code or "INSUFFICIENT_SCOPE",
                trace_id=trace_id,
                errors=errors,
                raw_response=envelope,
            )
        elif status_code == 404:
            raise SchoFeeNotFoundError(
                message=message,
                status_code=404,
                error_code=error_code or "RESOURCE_NOT_FOUND",
                trace_id=trace_id,
                errors=errors,
                raw_response=envelope,
            )
        elif status_code == 409:
            ec = (error_code or "").upper()
            if "IDEMPOTENCY" in ec or ec == "IDEMPOTENCY_CONFLICT":
                raise SchoFeeIdempotencyConflictError(
                    message=message,
                    status_code=409,
                    error_code="IDEMPOTENCY_CONFLICT",
                    trace_id=trace_id,
                    errors=errors,
                    raw_response=envelope,
                )
            elif "DUPLICATE" in ec or ec == "DUPLICATE_RESOURCE":
                raise SchoFeeDuplicateError(
                    message=message,
                    status_code=409,
                    error_code="DUPLICATE_RESOURCE",
                    trace_id=trace_id,
                    errors=errors,
                    raw_response=envelope,
                )
            elif "STATE" in ec or ec == "STATE_CONFLICT":
                raise SchoFeeStateConflictError(
                    message=message,
                    status_code=409,
                    error_code="STATE_CONFLICT",
                    trace_id=trace_id,
                    errors=errors,
                    raw_response=envelope,
                )
            else:
                raise SchoFeeConflictError(
                    message=message,
                    status_code=409,
                    error_code=error_code or "CONFLICT",
                    trace_id=trace_id,
                    errors=errors,
                    raw_response=envelope,
                )
        elif status_code == 422:
            raise SchoFeeDownPaymentRequiredError(
                message=message,
                status_code=422,
                error_code=error_code or "DOWNPAYMENT_REQUIRED",
                trace_id=trace_id,
                errors=errors,
                raw_response=envelope,
            )
        elif status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            raise SchoFeeRateLimitError(
                message=message,
                retry_after=retry_after,
                trace_id=trace_id,
                error_code=error_code or "RATE_LIMIT_EXCEEDED",
            )
        elif status_code in (502, 503, 504):
            raise SchoFeeServiceUnavailableError(
                message=message,
                status_code=status_code,
                error_code=error_code or "TEMPORARILY_UNAVAILABLE",
                trace_id=trace_id,
                errors=errors,
                raw_response=envelope,
            )
        else:
            raise SchoFeeAPIError(
                message=message,
                status_code=status_code,
                error_code=error_code or "UNKNOWN_ERROR",
                trace_id=trace_id,
                errors=errors,
                raw_response=envelope,
            )

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute an authenticated request with retry policies:
        1. 401: Refresh token once and retry once.
        2. 503 or Network timeout: Retry with exponential backoff (max 3 times) with identical body & key.
        3. 429: Wait for Retry-After if small, else raise.
        """
        url = self._build_url(endpoint)
        request_headers = headers.copy() if headers else {}
        if idempotency_key:
            request_headers["Idempotency-Key"] = idempotency_key

        attempt = 0
        backoff = INITIAL_BACKOFF_SECONDS
        token_refreshed = False

        while attempt < MAX_RETRIES_503:
            attempt += 1
            token = self.token_service.get_token()
            request_headers["Authorization"] = f"Bearer {token}"

            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data,
                    data=data,
                    files=files,
                    headers=request_headers,
                    timeout=self.timeout,
                )
            except requests.Timeout as exc:
                logger.warning(
                    "SchoFee request timeout | attempt=%d/%d endpoint=%s",
                    attempt,
                    MAX_RETRIES_503,
                    endpoint,
                )
                if attempt >= MAX_RETRIES_503:
                    raise SchoFeeServiceUnavailableError(
                        f"Request to {endpoint} timed out after {MAX_RETRIES_503} attempts.",
                        status_code=503,
                        error_code="TIMEOUT",
                    ) from exc
                time.sleep(backoff)
                backoff *= 2
                continue
            except requests.RequestException as exc:
                logger.warning(
                    "SchoFee network error | attempt=%d/%d endpoint=%s: %s",
                    attempt,
                    MAX_RETRIES_503,
                    endpoint,
                    exc,
                )
                if attempt >= MAX_RETRIES_503:
                    raise SchoFeeServiceUnavailableError(
                        f"Network error connecting to {endpoint}.",
                        status_code=503,
                        error_code="CONNECTION_ERROR",
                    ) from exc
                time.sleep(backoff)
                backoff *= 2
                continue

            envelope, trace_id, error_code = self._parse_response(response)

            # Success
            if response.status_code == 200:
                logger.info(
                    "SchoFee API success | endpoint=%s status=200 traceId=%s",
                    endpoint,
                    trace_id,
                )
                return envelope.get("data", envelope)

            # Handle 401 UNAUTHENTICATED: refresh token once and retry
            if response.status_code == 401 and not token_refreshed:
                logger.info("SchoFee 401 received. Clearing token and retrying request once.")
                self.token_service.clear_token()
                token_refreshed = True
                continue

            # Handle 429 Rate Limit
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 5))
                if retry_after <= 10 and attempt < MAX_RETRIES_503:
                    logger.warning("SchoFee 429 rate limit. Waiting %ds before retry.", retry_after)
                    time.sleep(retry_after)
                    continue
                self._raise_for_status(response, endpoint, envelope, trace_id, error_code)

            # Handle 503 / 502 / 504: retry with identical body and idempotency key
            if response.status_code in (502, 503, 504) and attempt < MAX_RETRIES_503:
                logger.warning(
                    "SchoFee %d service unavailable | attempt=%d/%d endpoint=%s traceId=%s. Backing off %0.1fs.",
                    response.status_code,
                    attempt,
                    MAX_RETRIES_503,
                    endpoint,
                    trace_id,
                    backoff,
                )
                time.sleep(backoff)
                backoff *= 2
                continue

            # All other errors: raise typed exception
            self._raise_for_status(response, endpoint, envelope, trace_id, error_code)

        raise SchoFeeServiceUnavailableError(
            f"Failed request to {endpoint} after {MAX_RETRIES_503} attempts.",
            status_code=503,
            error_code="TEMPORARILY_UNAVAILABLE",
        )

    # ── 10 Endpoint Implementations (SchoFee v3.0 Specification) ───────────────

    def list_courses(
        self,
        page: int = 1,
        page_size: int = 10,
        course_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        GET /v1/courses?page={page}&pageSize={pageSize}&courseName={courseName}
        Returns: {page, pageSize, totalCount, items: [{id, courseName, courseCode, courseFees, maxEmiMonths}]}
        """
        params = {"page": max(1, page), "pageSize": min(100, max(1, page_size))}
        if course_name:
            params["courseName"] = course_name
        return self._request("GET", "courses", params=params)

    def list_banks(self) -> Dict[str, Any]:
        """
        GET /v1/banks
        Returns: {items: [{institutionID, displayName}]} (no pagination).
        """
        return self._request("GET", "banks")

    def upload_document(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        document_for: int,
    ) -> str:
        """
        POST /v1/students/documents
        Multipart upload of a single document.
        documentFor:
          4: student photo, 5: student PAN, 6: student Aadhaar
          7: applicant photo, 8: applicant PAN, 9: applicant Aadhaar
          10: co-applicant photo, 11: co-applicant PAN, 12: co-applicant Aadhaar
        SECURITY: Returns data.path ONLY. Never returns or stores temporary data.link.
        """
        if not (4 <= document_for <= 12):
            raise SchoFeeValidationError(
                f"Invalid documentFor: {document_for}. Must be between 4 and 12.",
                status_code=400,
                error_code="VALIDATION_ERROR",
            )
        if len(file_bytes) > 20 * 1024 * 1024:
            raise SchoFeeValidationError(
                "Document file exceeds 20 MiB limit.",
                status_code=400,
                error_code="VALIDATION_ERROR",
            )
        if len(file_bytes) == 0:
            raise SchoFeeValidationError(
                "Document file cannot be empty.",
                status_code=400,
                error_code="VALIDATION_ERROR",
            )

        files = {
            "documentFile": (filename, file_bytes, content_type),
        }
        data = {
            "documentFor": str(document_for),
        }

        # Idempotency-Key is disabled for document upload per v3.0 spec
        res = self._request("POST", "students/documents", files=files, data=data)
        path = res.get("path")
        if not path:
            raise SchoFeeAPIError(
                "Document upload succeeded but path is missing in response.",
                status_code=500,
                error_code="MISSING_PATH",
            )
        return path

    def create_student(
        self,
        external_student_ref: str,
        student_info: Dict[str, Any],
        applicants: List[Dict[str, Any]],
        idempotency_key: str,
        co_applicants: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        POST /v1/students
        Creates student and participants with document paths and Idempotency-Key.
        Returns: {studentId, externalStudentRef, participants: [{participantId, role}]}
        """
        payload: Dict[str, Any] = {
            "externalStudentRef": external_student_ref,
            "studentInfo": student_info,
            "applicants": applicants,
            "coApplicants": co_applicants if co_applicants is not None else [],
        }

        return self._request(
            "POST",
            "students",
            json_data=payload,
            idempotency_key=idempotency_key,
        )

    def create_loan_application(
        self,
        external_application_ref: str,
        student_id: str,
        course_id: str,
        number_of_emis: int,
        idempotency_key: str,
        number_of_advance_emi: int = 0,
        downpayment_amount: Union[int, float] = 0,
        discount_amount: Optional[Union[int, float]] = None,
        discount_percentage: Optional[Union[int, float]] = None,
    ) -> Dict[str, Any]:
        """
        POST /v1/loan-applications
        Creates loan application.
        NOTE: Do NOT send financedAmount (derived server-side).
        Send either discountAmount OR discountPercentage (never both; or omit both).
        Returns: {loanAppID, customerID, loanStatusID, createdDate}
        """
        payload: Dict[str, Any] = {
            "externalApplicationRef": external_application_ref,
            "studentId": student_id,
            "courseId": course_id,
            "numberOfEmis": number_of_emis,
            "numberOfAdvanceEmi": number_of_advance_emi,
            "downpaymentAmount": downpayment_amount,
        }
        if discount_amount is not None and discount_percentage is not None:
            raise SchoFeeValidationError(
                "Cannot provide both discountAmount and discountPercentage.",
                status_code=400,
                error_code="VALIDATION_ERROR",
            )
        if discount_amount is not None:
            payload["discountAmount"] = discount_amount
        elif discount_percentage is not None:
            payload["discountPercentage"] = discount_percentage

        return self._request(
            "POST",
            "loan-applications",
            json_data=payload,
            idempotency_key=idempotency_key,
        )

    def get_loan_application(self, loan_application_id: str) -> Dict[str, Any]:
        """
        GET /v1/loan-applications/{loanApplicationId}
        Returns full loan application details and loanStructure summary (estimated EMI).
        """
        return self._request("GET", f"loan-applications/{loan_application_id}")

    def get_required_actions(self, loan_application_id: str) -> Dict[str, Any]:
        """
        GET /v1/loan-applications/{loanApplicationId}/required-actions
        Returns: {items: [{type: 'PARTICIPANT_VERIFICATION', status: 'PENDING', participantId, participantUserType}]}
        When items is [] and message is 'No required actions.', participant verification is complete.
        """
        return self._request("GET", f"loan-applications/{loan_application_id}/required-actions")

    def request_participant_otp(
        self,
        loan_application_id: str,
        participant_id: str,
    ) -> Dict[str, Any]:
        """
        POST /v1/loan-applications/{loanApplicationId}/participants/{participantId}/otp-requests
        No body. SchoFee triggers OTP to participant's mobile.
        Returns: {verificationId, status: 'SENT'}
        """
        return self._request(
            "POST",
            f"loan-applications/{loan_application_id}/participants/{participant_id}/otp-requests",
        )

    def verify_participant_otp(
        self,
        loan_application_id: str,
        participant_id: str,
        verification_id: str,
        otp: str,
    ) -> Dict[str, Any]:
        """
        POST /v1/loan-applications/{loanApplicationId}/participants/{participantId}/otp-verifications
        Body: {verificationId, otp}
        Returns: {verified: True}
        """
        payload = {
            "verificationId": verification_id,
            "otp": otp,
        }
        return self._request(
            "POST",
            f"loan-applications/{loan_application_id}/participants/{participant_id}/otp-verifications",
            json_data=payload,
        )
