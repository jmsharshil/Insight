"""
schofee_finance/services/token.py
─────────────────────────────────
SchoFee B2B OAuth2 Token Service.
Handles machine token exchange via HTTP Basic client credentials,
thread-safe caching in Django cache, early refresh (60s before expiry),
and rate-limit protection (<= 10 requests/min).
Never logs client secrets or access tokens.
"""

import base64
import logging
import threading
import time
from typing import Optional
import requests
from django.conf import settings
from django.core.cache import cache

from .exceptions import (
    SchoFeeAuthError,
    SchoFeeRateLimitError,
    SchoFeeServiceUnavailableError,
    SchoFeeValidationError,
)

logger = logging.getLogger(__name__)

CACHE_KEY_TOKEN = "schofee_b2b_access_token"
CACHE_KEY_RATE_LIMIT = "schofee_token_req_timestamps"
MAX_TOKEN_REQUESTS_PER_MINUTE = 10
EARLY_REFRESH_SECONDS = 60
DEFAULT_TIMEOUT_SECONDS = 30


class SchoFeeTokenService:
    """Thread-safe token manager for SchoFee B2B API."""

    _lock = threading.Lock()

    def __init__(
        self,
        base_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        scopes: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        self.base_url = (base_url or getattr(settings, "SCHOFEE_BASE_URL", "")).rstrip("/")
        self.client_id = client_id or getattr(settings, "SCHOFEE_CLIENT_ID", "")
        self.client_secret = client_secret or getattr(settings, "SCHOFEE_CLIENT_SECRET", "")
        self.scopes = scopes or getattr(settings, "SCHOFEE_SCOPES", "")
        self.timeout = timeout or getattr(settings, "SCHOFEE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)

    def _check_rate_limit(self) -> None:
        """Ensure we do not exceed the 10 requests/minute fixed/sliding window on /oauth/token."""
        now = time.time()
        timestamps = cache.get(CACHE_KEY_RATE_LIMIT, [])
        # Keep timestamps from the last 60 seconds
        recent = [t for t in timestamps if now - t < 60.0]
        if len(recent) >= MAX_TOKEN_REQUESTS_PER_MINUTE:
            wait_time = int(60.0 - (now - recent[0])) + 1
            logger.warning(
                "SchoFee token rate limit reached (%d req/min). Backing off for %ds.",
                len(recent),
                wait_time,
            )
            raise SchoFeeRateLimitError(
                f"SchoFee token rate limit reached. Retry after {wait_time} seconds.",
                retry_after=wait_time,
                error_code="RATE_LIMIT_EXCEEDED",
            )
        recent.append(now)
        cache.set(CACHE_KEY_RATE_LIMIT, recent, timeout=120)

    def get_token(self, force_refresh: bool = False) -> str:
        """
        Return a valid access token.
        Retrieves from cache if available and not expiring within 60s,
        otherwise acquires the lock, checks cache again (double-checked locking),
        and fetches a fresh token from SchoFee.
        """
        if not force_refresh:
            cached_token = cache.get(CACHE_KEY_TOKEN)
            if cached_token:
                return cached_token

        with self._lock:
            # Double-check cache inside lock
            if not force_refresh:
                cached_token = cache.get(CACHE_KEY_TOKEN)
                if cached_token:
                    return cached_token

            return self._fetch_new_token()

    def clear_token(self) -> None:
        """Clear cached access token (called when an API request returns 401)."""
        cache.delete(CACHE_KEY_TOKEN)

    def _fetch_new_token(self) -> str:
        """Perform POST /v1/oauth/token call with HTTP Basic Auth."""
        if not self.base_url:
            raise SchoFeeAuthError("SCHOFEE_BASE_URL is not configured in settings.", status_code=500)
        if not self.client_id or not self.client_secret:
            raise SchoFeeAuthError("SCHOFEE_CLIENT_ID or SCHOFEE_CLIENT_SECRET is missing.", status_code=500)

        self._check_rate_limit()

        token_url = f"{self.base_url}/v1/oauth/token"
        payload = {"grant_type": "client_credentials"}
        # Scope is optional per SchoFee v3.0 spec. When omitted, all granted scopes are returned.
        if self.scopes and self.scopes.strip():
            payload["scope"] = self.scopes.strip()

        try:
            logger.info("Requesting new SchoFee OAuth machine token from %s", "/v1/oauth/token")
            response = requests.post(
                token_url,
                data=payload,
                auth=(self.client_id, self.client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            logger.error("Timeout fetching SchoFee OAuth token: %s", exc)
            raise SchoFeeServiceUnavailableError(
                "SchoFee token request timed out.",
                status_code=503,
                error_code="TEMPORARILY_UNAVAILABLE",
            ) from exc
        except requests.RequestException as exc:
            logger.error("Connection error fetching SchoFee OAuth token: %s", exc)
            raise SchoFeeServiceUnavailableError(
                "Network error connecting to SchoFee token endpoint.",
                status_code=503,
                error_code="CONNECTION_ERROR",
            ) from exc

        # Parse response
        try:
            data = response.json()
        except ValueError:
            data = {}

        # If invalid_scope error occurs, automatically retry once with scope omitted
        if response.status_code == 400 and data.get("error") == "invalid_scope" and "scope" in payload:
            logger.warning("SchoFee returned invalid_scope. Retrying token request with scope omitted to request all granted scopes.")
            payload.pop("scope", None)
            try:
                response = requests.post(
                    token_url,
                    data=payload,
                    auth=(self.client_id, self.client_secret),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=self.timeout,
                )
                try:
                    data = response.json()
                except ValueError:
                    data = {}
            except Exception as exc:
                logger.error("Retry without scope failed: %s", exc)

        if response.status_code == 200:
            access_token = data.get("access_token")
            expires_in = int(data.get("expires_in", 600))
            if not access_token:
                raise SchoFeeAuthError(
                    "Invalid token response from SchoFee: access_token missing.",
                    status_code=500,
                )

            # Refresh 60 seconds before expiry; ensure minimum cache time of 30s
            cache_ttl = max(30, expires_in - EARLY_REFRESH_SECONDS)
            cache.set(CACHE_KEY_TOKEN, access_token, timeout=cache_ttl)
            logger.info(
                "SchoFee OAuth token successfully acquired. Expires in %ds (cached for %ds).",
                expires_in,
                cache_ttl,
            )
            return access_token

        # Handle OAuth errors
        error_type = data.get("error", "oauth_error")
        error_desc = data.get("error_description", str(data))

        if response.status_code == 401:
            logger.error("SchoFee OAuth 401: Invalid client credentials.")
            raise SchoFeeAuthError(
                f"SchoFee authentication failed: {error_type}",
                status_code=401,
                error_code="INVALID_CLIENT",
                raw_response=data,
            )
        elif response.status_code == 400:
            logger.error("SchoFee OAuth 400: %s (%s)", error_type, error_desc)
            raise SchoFeeValidationError(
                f"SchoFee token request invalid: {error_type}",
                status_code=400,
                error_code=error_type.upper(),
                raw_response=data,
            )
        elif response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            logger.warning("SchoFee OAuth 429: Rate limit exceeded. Retry after %ds", retry_after)
            raise SchoFeeRateLimitError(
                "SchoFee token endpoint rate limit exceeded.",
                retry_after=retry_after,
                error_code="RATE_LIMIT_EXCEEDED",
            )
        else:
            logger.error("SchoFee OAuth unexpected status %d: %s", response.status_code, error_type)
            raise SchoFeeServiceUnavailableError(
                f"Failed to obtain SchoFee token (status {response.status_code}).",
                status_code=response.status_code,
                error_code="TOKEN_EXCHANGE_FAILED",
                raw_response=data,
            )


# Global singleton instance
token_service = SchoFeeTokenService()
