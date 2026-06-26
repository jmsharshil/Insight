"""
Service for writing audit log files to Azure Blob Storage.

File structure in the container:
  audit_logs/{organization_name}/{user_name}/{YYYY-MM-DD}.log

Each file contains plain text log entries in a structured format.
The upload function *appends* new entries to any existing content
so that the blob always represents the complete cumulative log
for that organization/user/date (immediate middleware + periodic
catch-up both contribute without data loss).

Format per line:
  [YYYY-MM-DD HH:MM:SS] ACTION METHOD PATH STATUS IP "user@email.com" user_name
"""


import logging
from datetime import date
from django.conf import settings

logger = logging.getLogger(__name__)


# ── Custom formatters ─────────────────────────────────────────────

def format_log_entry(entry: dict) -> str:
    """
    Convert a log entry dict into a human-readable log line.

    Format: [timestamp] ACTION METHOD PATH STATUS IP "user_email" user_name
    """
    user_name = entry.get("user_name", "system")
    timestamp = entry.get("timestamp", "")
    action = entry.get("action", "UNKNOWN")
    method = entry.get("method", "")
    path = entry.get("path", "")
    status_code = entry.get("status_code", "-")
    ip_address = entry.get("ip_address", "-")
    user_email = entry.get("user_email", "anonymous")
    user_name = entry.get("user_name", "")

    # Build the log line
    log_line = f"[{timestamp}] {action} {method} {path} {status_code} {ip_address}"

    if user_email:
        log_line += f' "{user_email}"'

    if user_name:
        log_line += f" {user_name}"

    return log_line


def format_log_entries(entries: list) -> str:
    """
    Convert a list of log entry dicts into a multi-line log string.
    Each entry is on a separate line.
    """
    lines = []
    for entry in entries:
        try:
            lines.append(format_log_entry(entry))
        except Exception as e:
            logger.warning("[AUDIT BLOB] Failed to format entry: %s", str(e))
            lines.append(f"[ERROR] Failed to format log entry: {str(e)}")
    
    return "\n".join(lines) + "\n" if lines else ""


# ── Blob path builder ──────────────────────────────────────────────

def _blob_path(organization_name, user_name, log_date: date) -> str:
    """Return the blob path: audit_logs/{organization_name}/{user_name}/{date}.log"""
    # Sanitize names to be filesystem-safe (replace spaces and special chars)
    safe_organization = organization_name.replace(" ", "_").replace("/", "-").replace("\\", "-")
    safe_user = user_name.replace(" ", "_").replace("/", "-").replace("\\", "-")
    return f"audit_logs/{safe_organization}/{safe_user}/{log_date.isoformat()}.log"


# ── Core upload function ──────────────────────────────────────────

def upload_log_file(organization_name, user_name, log_date: date, log_entries: list) -> bool:
    """
    Append a list of serialised log entry dicts to the existing log file
    (or create new). The blob always contains the cumulative logs for that
    organization/user/date. Uses overwrite=True after merging with existing content.

    Returns True on success, False on failure.
    """
    blob_name = _blob_path(organization_name, user_name, log_date)

    try:
        from azure.storage.blob import BlobServiceClient

        account_name = settings.AZURE_ACCOUNT_NAME
        account_key = settings.AZURE_ACCOUNT_KEY
        container = getattr(settings, "AUDIT_LOG_CONTAINER", "auditlogs")

        connect_str = (
            f"DefaultEndpointsProtocol=https;"
            f"AccountName={account_name};"
            f"AccountKey={account_key};"
            f"EndpointSuffix=core.windows.net"
        )

        blob_service_client = BlobServiceClient.from_connection_string(connect_str)

        # Ensure container exists
        container_client = blob_service_client.get_container_client(container)
        try:
            container_client.get_container_properties()
        except Exception:
            container_client.create_container()
            logger.info("[AUDIT BLOB] Created container '%s'", container)

        # Write (append semantics via merge) log file to blob
        blob_client = blob_service_client.get_blob_client(
            container=container, blob=blob_name
        )
        existing = download_log_file(organization_name, user_name, log_date) or ""
        log_content = format_log_entries(log_entries)
        full_content = existing + log_content
        blob_client.upload_blob(full_content, overwrite=True)

        logger.info(
            "[AUDIT BLOB] Appended %d entries → %s (total ~%d chars)",
            len(log_entries),
            blob_name,
            len(full_content),
        )
        return True

    except Exception:
        logger.exception(
            "[AUDIT BLOB] Failed to upload %s", blob_name
        )
        return False


# ── Download helper (useful for API endpoints) ─────────────────────

def download_log_file(organization_name, user_name, log_date: date) -> str | None:
    """
    Download a log file from blob storage.

    Returns the log file content as a string, or None if the blob 
    does not exist / on error.
    """
    blob_name = _blob_path(organization_name, user_name, log_date)

    try:
        from azure.storage.blob import BlobServiceClient

        account_name = settings.AZURE_ACCOUNT_NAME
        account_key = settings.AZURE_ACCOUNT_KEY
        container = getattr(settings, "AUDIT_LOG_CONTAINER", "auditlogs")

        connect_str = (
            f"DefaultEndpointsProtocol=https;"
            f"AccountName={account_name};"
            f"AccountKey={account_key};"
            f"EndpointSuffix=core.windows.net"
        )

        blob_service_client = BlobServiceClient.from_connection_string(connect_str)
        blob_client = blob_service_client.get_blob_client(
            container=container, blob=blob_name
        )

        download_stream = blob_client.download_blob()
        content = download_stream.readall().decode('utf-8')
        return content

    except Exception:
        logger.exception(
            "[AUDIT BLOB] Failed to download %s", blob_name
        )
        return None
