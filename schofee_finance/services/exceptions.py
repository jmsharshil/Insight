"""
schofee_finance/services/exceptions.py
──────────────────────────────────────
Custom exceptions for SchoFee B2B API v3.0 integration.
Branching is based on HTTP status and SchoFee error_code, never on message text.
Sensitive details (Aadhaar, PAN, OTP, tokens, paths) are NEVER included in messages.
"""

from typing import Any, Dict, List, Optional


class SchoFeeAPIError(Exception):
    """Base exception for all SchoFee API errors."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_code: Optional[str] = None,
        trace_id: Optional[str] = None,
        errors: Optional[List[Any]] = None,
        raw_response: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code or "INTERNAL_ERROR"
        self.trace_id = trace_id or ""
        self.errors = errors or []
        self.raw_response = raw_response or {}

    def __str__(self) -> str:
        parts = [f"[{self.status_code}] {self.error_code}: {self.message}"]
        if self.trace_id:
            parts.append(f"(traceId: {self.trace_id})")
        return " ".join(parts)


class SchoFeeAuthError(SchoFeeAPIError):
    """401 UNAUTHENTICATED or 403 INSUFFICIENT_SCOPE."""
    pass


class SchoFeeValidationError(SchoFeeAPIError):
    """400 VALIDATION_ERROR or OAuth invalid_scope / unsupported_grant_type."""
    pass


class SchoFeeNotFoundError(SchoFeeAPIError):
    """404 RESOURCE_NOT_FOUND (invalid or inaccessible student, course, loan or participant)."""
    pass


class SchoFeeConflictError(SchoFeeAPIError):
    """409 Conflict base class."""
    pass


class SchoFeeDuplicateError(SchoFeeConflictError):
    """409 DUPLICATE_RESOURCE (externalStudentRef or externalApplicationRef already exists)."""
    pass


class SchoFeeIdempotencyConflictError(SchoFeeConflictError):
    """409 IDEMPOTENCY_CONFLICT (same key with a different body). Bug: never auto-retry."""
    pass


class SchoFeeStateConflictError(SchoFeeConflictError):
    """409 STATE_CONFLICT (e.g. active loan already exists for the course)."""
    pass


class SchoFeeDownPaymentRequiredError(SchoFeeAPIError):
    """422 Course requires a down payment."""
    pass


class SchoFeeRateLimitError(SchoFeeAPIError):
    """429 Too Many Requests (Token endpoint or API rate limit exceeded)."""

    def __init__(
        self,
        message: str,
        retry_after: Optional[int] = None,
        trace_id: Optional[str] = None,
        error_code: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            status_code=429,
            error_code=error_code or "RATE_LIMIT_EXCEEDED",
            trace_id=trace_id,
        )
        self.retry_after = retry_after or 60


class SchoFeeServiceUnavailableError(SchoFeeAPIError):
    """503 TEMPORARILY_UNAVAILABLE or network connection timeout."""
    pass
