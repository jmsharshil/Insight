"""
Middleware that captures every API request/response and creates an AuditLog entry.

Design goals:
  - Zero impact on existing view code (fully decoupled).
  - Lightweight: only creates a DB row; blob upload is deferred to a background task.
  - Sanitises sensitive fields (passwords, tokens, pins) from request bodies.
"""

import json
import logging
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)

# Paths that should NOT be audited (health checks, static, admin, etc.)
EXCLUDED_PATH_PREFIXES = (
    "/admin/",
    "/static/",
    "/favicon.ico",
    "/api/accounts/set-pin/",
)

# HTTP method → action mapping
METHOD_ACTION_MAP = {
    "GET": "READ",
    "HEAD": "READ",
    "OPTIONS": "READ",
    "POST": "CREATE",
    "PUT": "UPDATE",
    "PATCH": "UPDATE",
    "DELETE": "DELETE",
}

# Keys whose values should be redacted from the stored request body
SENSITIVE_KEYS = {
    "password", "pin", "token", "refresh", "access",
    "authorization", "secret", "api_key", "credit_card",
}


def _sanitise_body(raw_body: str, max_len: int = 4000) -> str:
    """Remove sensitive values and truncate the request body."""
    if not raw_body:
        return ""
    try:
        data = json.loads(raw_body)
        if isinstance(data, dict):
            for key in list(data.keys()):
                if key.lower() in SENSITIVE_KEYS:
                    data[key] = "***REDACTED***"
        sanitised = json.dumps(data, default=str)
    except (json.JSONDecodeError, TypeError):
        sanitised = raw_body

    return sanitised[:max_len]


def _determine_action(method: str, path: str, status_code: int) -> str:
    """Determine the action type, with special cases for login/logout."""
    if "/login/" in path:
        return "LOGIN"
    if "/logout/" in path:
        return "LOGOUT"
    if method == "POST" and status_code in (200, 201):
        return "CREATE"
    return METHOD_ACTION_MAP.get(method, "OTHER")


# ---------------------------------------------------------------------------
# Human-readable event map
# Each entry: (url_fragment, http_method or None) → event description
# Rules are checked in order; first match wins. More specific paths first.
# ---------------------------------------------------------------------------
_EVENT_RULES = [
    # Auth
    ("/login/",                   "POST",   "User logged in"),
    ("/logout/",                  "POST",   "User logged out"),
    ("/register/",                "POST",   "New user registered"),
    ("/set-pin/",                 "POST",   "User set PIN"),
    ("/change-password/",         "POST",   "User changed password"),
    ("/reset-password/",          "POST",   "Password reset requested"),

    # Exams — more specific paths before generic /exams/
    ("/start/",                   "POST",   "Student started exam"),
    ("/submit/",                  "POST",   "Student submitted exam"),
    ("/autosave/",                "POST",   "Exam answer autosaved"),
    ("/geo-check/",               "POST",   "Geo-check performed"),
    ("/screen-event/",            "POST",   "Screen event logged"),
    ("/answer-key/distribute/",   "POST",   "Answer key distributed to checkers"),
    ("/answer-key/",              "GET",    "Answer key viewed"),
    ("/malpractice/",             "POST",   "Malpractice report created"),
    ("/malpractice/",             "GET",    "Malpractice reports fetched"),
    ("/malpractice/",             "PATCH",  "Malpractice report updated"),
    ("/malpractice/",             "DELETE", "Malpractice report deleted"),
    ("/papers/",                  "POST",   "Exam paper uploaded"),
    ("/papers/",                  "GET",    "Exam papers fetched"),
    ("/papers/",                  "DELETE", "Exam paper deleted"),
    ("/questions/",               "POST",   "Questions added to exam"),
    ("/questions/",               "GET",    "Exam questions fetched"),
    ("/questions/",               "PATCH",  "Question updated"),
    ("/questions/",               "DELETE", "Question deleted"),
    ("/seating/",                 "POST",   "Seating arrangement set"),
    ("/seating/",                 "GET",    "Seating arrangement fetched"),
    ("/seating/",                 "PATCH",  "Seat updated"),
    ("/seating/",                 "DELETE", "Seat removed"),
    ("/schedule/",                "GET",    "Exam schedule fetched"),
    ("/schedule/",                "POST",   "Exam scheduled"),
    ("/exams/",                   "POST",   "Exam created"),
    ("/exams/",                   "GET",    "Exam list fetched"),
    ("/exams/",                   "PATCH",  "Exam updated"),
    ("/exams/",                   "DELETE", "Exam deleted"),

    # Students
    ("/students/",                "POST",   "Student created"),
    ("/students/",                "GET",    "Students list fetched"),
    ("/students/",                "PATCH",  "Student updated"),
    ("/students/",                "DELETE", "Student deleted"),

    # Faculty
    ("/faculty/",                 "POST",   "Faculty member created"),
    ("/faculty/",                 "GET",    "Faculty list fetched"),
    ("/faculty/",                 "PATCH",  "Faculty member updated"),
    ("/faculty/",                 "DELETE", "Faculty member deleted"),

    # Batches
    ("/batches/",                 "POST",   "Batch created"),
    ("/batches/",                 "GET",    "Batches list fetched"),
    ("/batches/",                 "PATCH",  "Batch updated"),
    ("/batches/",                 "DELETE", "Batch deleted"),

    # Fees
    ("/fees/",                    "POST",   "Fee record created"),
    ("/fees/",                    "GET",    "Fee records fetched"),
    ("/fees/",                    "PATCH",  "Fee record updated"),

    # Attendance
    ("/attendance/",              "POST",   "Attendance marked"),
    ("/attendance/",              "GET",    "Attendance fetched"),
    ("/attendance/",              "PATCH",  "Attendance updated"),

    # Results
    ("/results/",                 "POST",   "Result recorded"),
    ("/results/",                 "GET",    "Results fetched"),

    # Payroll
    ("/payroll/",                 "POST",   "Payroll entry created"),
    ("/payroll/",                 "GET",    "Payroll fetched"),
    ("/payroll/",                 "PATCH",  "Payroll entry updated"),

    # Leave
    ("/leave/",                   "POST",   "Leave request submitted"),
    ("/leave/",                   "GET",    "Leave records fetched"),
    ("/leave/",                   "PATCH",  "Leave request updated"),

    # Inventory
    ("/inventory/",               "POST",   "Inventory item created"),
    ("/inventory/",               "GET",    "Inventory fetched"),
    ("/inventory/",               "PATCH",  "Inventory item updated"),
    ("/inventory/",               "DELETE", "Inventory item deleted"),

    # Chat
    ("/chat/",                    "POST",   "Message sent"),
    ("/chat/",                    "GET",    "Chat history fetched"),

    # Leads / Admissions
    ("/leads/",                   "POST",   "Lead created"),
    ("/leads/",                   "GET",    "Leads fetched"),
    ("/leads/",                   "PATCH",  "Lead updated"),
    ("/admissions/",              "POST",   "Admission created"),
    ("/admissions/",              "GET",    "Admissions fetched"),

    # Reports
    ("/reports/",                 "GET",    "Report generated"),

    # Generic fallback by method
    (None,                        "POST",   "Resource created"),
    (None,                        "GET",    "Resource fetched"),
    (None,                        "PATCH",  "Resource updated"),
    (None,                        "PUT",    "Resource replaced"),
    (None,                        "DELETE", "Resource deleted"),
]


def _resolve_event(path: str, method: str) -> str:
    """Return a human-readable event string for the given path + method."""
    for fragment, rule_method, description in _EVENT_RULES:
        method_match = rule_method is None or rule_method == method
        path_match = fragment is None or fragment in path
        if method_match and path_match:
            return description
    return "Other API call"


class AuditLogMiddleware:
    """
    Intercepts every request and, after the response is generated,
    persists an AuditLog entry in the database.

    We intentionally do *not* wrap the view call itself (no try/except
    around get_response) so that any exception propagates normally and
    Django's error handling is unaffected.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ---------- pre-processing (before view) ----------
        # Save a reference to the request body *before* it may be consumed.
        request_body = ""
        content_type = getattr(request, "content_type", "") or ""
        if request.method in ("POST", "PUT", "PATCH") and "json" in content_type:
            try:
                request_body = request.body.decode("utf-8") if request.body else ""
            except Exception:
                request_body = ""

        # Let the view execute normally
        response = self.get_response(request)

        # ---------- post-processing (after view) ----------
        self._create_log_entry(request, response, request_body)
        return response

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_log_entry(self, request, response, request_body: str):
        """Build and save a single AuditLog row."""
        path = request.path

        # Skip excluded paths
        for prefix in EXCLUDED_PATH_PREFIXES:
            if path.startswith(prefix):
                return

        # Only audit /api/ paths
        if not path.startswith("/api/"):
            return

        # Resolve user
        user = getattr(request, "user", None)
        user_name = "system" if user is None or not getattr(user, "is_authenticated", False) else user.name
        if user is None or not getattr(user, "is_authenticated", False):
            user = None

        # HTTP method & status
        method = request.method
        status_code = getattr(response, "status_code", None)

        # For login requests, try to resolve user from response or email in body
        if user is None and "/login/" in path and status_code == 200:
            try:
                body_data = json.loads(request_body) if request_body else {}
                login_email = body_data.get("email", "")
                if login_email:
                    from auth_user.models import User
                    user = User.objects.filter(email=login_email).first()
            except Exception:
                pass

        # Resolve organization
        organization = getattr(user, "organization", None) if user else None

        # Determine action
        action = _determine_action(method, path, status_code)

        # Human-readable event
        event = _resolve_event(path, method)

        # Endpoint name (DRF sets this on the view)
        endpoint_name = ""
        view_func = getattr(request, "_audit_view_name", None)
        if not view_func:
            resolver_match = getattr(request, "resolver_match", None)
            if resolver_match:
                view_func = resolver_match.view_name
        endpoint_name = str(view_func or "")[:255]

        # Query params
        query_params = ""
        if request.META.get("QUERY_STRING"):
            query_params = request.META["QUERY_STRING"][:2000]

        # IP address - strip port if present (e.g., "122.170.55.74:59596" -> "122.170.55.74")
        ip_address = (
            request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            or request.META.get("HTTP_X_REAL_IP")
            or request.META.get("REMOTE_ADDR")
        )

        # Remove port number if present (PostgreSQL inet type doesn't accept ports)
        if ip_address and ":" in ip_address:
            if ip_address.startswith("["):
                # IPv6 format: [::1]:1234
                ip_address = ip_address.split("]")[0].lstrip("[")
            else:
                # IPv4 format: 1.2.3.4:1234
                ip_address = ip_address.split(":")[0]

        ip_address = ip_address or None

        # User-Agent
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:1000]

        # Sanitised request body
        sanitised_body = _sanitise_body(request_body)

        # Response summary (keep it small)
        response_summary = ""
        if hasattr(response, "data") and isinstance(response.data, dict):
            try:
                summary_keys = list(response.data.keys())[:10]
                response_summary = json.dumps(
                    {k: type(response.data[k]).__name__ for k in summary_keys},
                    default=str,
                )[:1500]
            except Exception:
                pass

        # Import here to avoid circular imports at module level
        from .models import AuditLog
        from .tasks import _serialise_log

        try:
            log_entry = AuditLog.objects.create(
                user=user,
                organization=organization,
                action=action,
                event=event,
                method=method,
                path=path,
                endpoint_name=endpoint_name,
                status_code=status_code,
                query_params=query_params,
                request_body=sanitised_body,
                response_summary=response_summary,
                ip_address=ip_address,
                user_agent=user_agent,
                target_model="",
                target_id="",
                timestamp=timezone.now(),
            )

            # Also upload to blob storage immediately as fallback (reliability)
            try:
                from .blob_service import upload_log_file

                organization_name = organization.name if organization else "Unknown_organization"
                user_name = user.name if user else "Anonymous"
                log_date = timezone.now().date()

                log_dict = _serialise_log(log_entry)

                # Upload immediately (appends to day's log file)
                upload_log_file(organization_name, user_name, log_date, [log_dict])

                # Mark as flushed since we already uploaded
                log_entry.flushed_to_blob = True
                log_entry.save(update_fields=["flushed_to_blob"])

            except Exception as blob_err:
                # Don't fail the request if blob upload fails
                logger.debug("Immediate blob upload failed (will retry later): %s", blob_err)

        except Exception:
            # Must never break the actual request/response cycle
            logger.exception("Failed to create AuditLog entry for %s %s", method, path)
