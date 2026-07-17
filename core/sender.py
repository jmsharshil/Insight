from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
import logging

logger = logging.getLogger(__name__)

def send_email(to, subject, cc=None, text="", template=None, attachments=None, template_context=None, organization=None, from_email=None):
    """
    Send email supporting plain-text + HTML fallback.
    - `template`: if ends with ".html" renders Django template (with org context if provided);
      otherwise treated as raw HTML string for attach_alternative("text/html").
    - `attachments`: list of str (file paths) or tuples (filename, content_bytes, mimetype).
    - Auto-deduplicates to/cc lists. Uses DEFAULT_FROM_EMAIL by default.
    """
    if cc is None:
        cc = []
    if from_email is None:
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'iips.insightinstitute@gmail.com')
    
    # Ensure to/cc are always lists and deduplicate while preserving order
    if isinstance(to, str):
        to_list = [to]
    else:
        to_list = list(to) if to else []
    if isinstance(cc, str):
        cc = [cc]
    elif not isinstance(cc, list):
        cc = list(cc) if cc else []
    
    # Deduplicate preserving first occurrence order
    to_list = list(dict.fromkeys([email for email in to_list if email]))
    cc = list(dict.fromkeys([email for email in cc if email]))
    
    msg = EmailMultiAlternatives(subject, text, from_email, to=to_list, cc=cc)

    html_body = template
    if template and template.endswith(".html"):
        ctx = {**(template_context or {})}
        if organization:
            ctx.update({
                'org_name': getattr(organization, 'name', ''),
                'logo_url': getattr(organization, 'logo_url', ''),
                'footer_text': getattr(organization, 'footer_text', ''),
                'primary_color': getattr(organization, 'primary_color', ''),
                'website_url': getattr(organization, 'website_url', ''),
            })
        else:
            ctx.setdefault('org_name', 'Insight ERP')
            ctx.setdefault('logo_url', '')
            ctx.setdefault('footer_text', '')
            ctx.setdefault('primary_color', '#2563EB')
            ctx.setdefault('website_url', '')
            
        html_body = render_to_string(template, ctx)

    if html_body:
        msg.attach_alternative(html_body, "text/html")
        
    if attachments:
        for attachment in attachments:
            try:
                if isinstance(attachment, str):
                    # attachment is a file path
                    filename = attachment.split("/")[-1]
                    with open(attachment, "rb") as f:
                        msg.attach(filename, f.read(), "application/pdf")
                else:
                    # attachment is a tuple (filename, content_bytes, mimetype)
                    msg.attach(*attachment)
            except Exception as e:
                logger.error("Error attaching document: %s", e)
                print("Error Attaching Documents:", e)

    try:
        msg.send()
        logger.info("Email sent successfully to %s with subject: %s", to_list, subject)
        return True
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to_list, str(e))
        print(f"Email send failed: {e}")
        return False

"""
whatsapp_sender.py
Production-grade WhatsApp Cloud API (Meta) sender.

Supports: plain text, template messages (header/body/button params, media headers),
media (link or uploaded media_id), location, contacts, interactive (buttons/list/cta_url),
reactions, read receipts.

Design notes:
- Single pooled requests.Session reused across all calls (critical under Django/Celery
  workers where a new session per call would exhaust sockets under load).
- urllib3 Retry with exponential backoff on 429/5xx, respects Retry-After header.
- All errors normalized into WhatsAppAPIError with the raw Meta error payload attached,
  so callers can branch on error_code (e.g. 131056 = rate limit, 131047 = re-engagement
  window expired) without parsing strings.
- Stateless / thread-safe for read use; instantiate once per process (e.g. module-level
  singleton or Django app config) rather than per-request.
"""

import logging
import mimetypes
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("whatsapp_sender")
logger.addHandler(logging.NullHandler())


class WhatsAppAPIError(Exception):
    def __init__(self, message, status_code=None, error_code=None, error_data=None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.error_data = error_data or {}

    def __str__(self):
        return f"[{self.status_code}/{self.error_code}] {super().__str__()}"


class MessageType(str, Enum):
    TEXT = "text"
    TEMPLATE = "template"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    STICKER = "sticker"
    LOCATION = "location"
    CONTACTS = "contacts"
    INTERACTIVE = "interactive"
    REACTION = "reaction"


@dataclass
class WhatsAppConfig:
    phone_number_id: str
    access_token: str
    api_version: str = "v20.0"
    base_url: str = "https://graph.facebook.com"
    timeout: int = 15
    max_retries: int = 3
    backoff_factor: float = 0.5


class WhatsAppSender:
    """Connection-pooled sender for the WhatsApp Business Cloud API."""

    _RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
    _MEDIA_MIME_HINT = {"image", "video", "audio", "document", "sticker"}

    def __init__(self, config: WhatsAppConfig):
        self.config = config
        self.url = f"{config.base_url}/{config.api_version}/{config.phone_number_id}/messages"
        self.media_url = f"{config.base_url}/{config.api_version}/{config.phone_number_id}/media"
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.backoff_factor,
            status_forcelist=self._RETRY_STATUS_CODES,
            allowed_methods=["POST", "GET"],
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
        session.mount("https://", adapter)
        session.headers.update({"Authorization": f"Bearer {self.config.access_token}"})
        return session

    # ---------- core transport ----------

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            resp = self.session.post(
                self.url, json=payload, timeout=self.config.timeout,
                headers={"Content-Type": "application/json"},
            )
        except requests.exceptions.RequestException as exc:
            logger.error("WhatsApp request failed: %s", exc)
            raise WhatsAppAPIError(f"Network error: {exc}") from exc

        if resp.status_code >= 400:
            self._raise_for_error(resp)
        return resp.json()

    def _raise_for_error(self, resp: requests.Response):
        try:
            data = resp.json()
        except ValueError:
            data = {}
        err = data.get("error", {})
        message = err.get("message", resp.text)
        logger.error("WhatsApp API error [%s] code=%s: %s", resp.status_code, err.get("code"), message)
        raise WhatsAppAPIError(
            message=message,
            status_code=resp.status_code,
            error_code=err.get("code"),
            error_data=data,
        )

    @staticmethod
    def _base_payload(to: str, msg_type: str, reply_to: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": msg_type,
        }
        if reply_to:
            payload["context"] = {"message_id": reply_to}
        return payload

    # ---------- plain text ----------

    def send_text(self, to: str, body: str, preview_url: bool = False,
                  reply_to: Optional[str] = None) -> Dict[str, Any]:
        payload = self._base_payload(to, "text", reply_to)
        payload["text"] = {"body": body, "preview_url": preview_url}
        return self._post(payload)

    # ---------- templates ----------

    def send_template(self, to: str, template_name: str, language_code: str = "en_US",
                       components: Optional[List[Dict[str, Any]]] = None,
                       reply_to: Optional[str] = None) -> Dict[str, Any]:
        payload = self._base_payload(to, "template", reply_to)
        template: Dict[str, Any] = {"name": template_name, "language": {"code": language_code}}
        if components:
            template["components"] = components
        payload["template"] = template
        return self._post(payload)

    @staticmethod
    def build_template_components(
        header_params: Optional[List[Dict]] = None,
        header_media: Optional[Dict[str, str]] = None,  # {"type": "image", "link" or "id": "..."}
        body_params: Optional[List[Union[str, Dict]]] = None,
        button_params: Optional[List[Dict]] = None,       # [{"sub_type": "url", "index": 0, "param": "abc"}]
    ) -> List[Dict[str, Any]]:
        """Assembles the `components` array Meta expects for a template send."""
        components: List[Dict[str, Any]] = []

        if header_media:
            media_type = header_media["type"]
            media_payload = {k: v for k, v in header_media.items() if k != "type"}
            components.append({
                "type": "header",
                "parameters": [{"type": media_type, media_type: media_payload}],
            })
        elif header_params:
            components.append({"type": "header", "parameters": header_params})

        if body_params:
            params = [{"type": "text", "text": p} if isinstance(p, str) else p for p in body_params]
            components.append({"type": "body", "parameters": params})

        if button_params:
            for btn in button_params:
                sub_type = btn.get("sub_type", "quick_reply")
                default_param = (
                    {"type": "payload", "payload": btn.get("param", "")}
                    if sub_type == "quick_reply"
                    else {"type": "text", "text": btn.get("param", "")}
                )
                components.append({
                    "type": "button",
                    "sub_type": sub_type,
                    "index": str(btn.get("index", 0)),
                    "parameters": btn.get("parameters", [default_param]),
                })

        return components

    # ---------- media ----------

    def send_media(self, to: str, media_type: str, link: Optional[str] = None,
                    media_id: Optional[str] = None, caption: Optional[str] = None,
                    filename: Optional[str] = None, reply_to: Optional[str] = None) -> Dict[str, Any]:
        if media_type not in self._MEDIA_MIME_HINT:
            raise ValueError(f"Unsupported media_type: {media_type}")
        if not link and not media_id:
            raise ValueError("Provide either link or media_id")

        payload = self._base_payload(to, media_type, reply_to)
        media_obj: Dict[str, Any] = {"link": link} if link else {"id": media_id}
        if caption and media_type in {"image", "video", "document"}:
            media_obj["caption"] = caption
        if filename and media_type == "document":
            media_obj["filename"] = filename

        payload[media_type] = media_obj
        return self._post(payload)

    def upload_media(self, file_path: str, mime_type: Optional[str] = None) -> str:
        """Uploads a local file to Meta's media store, returns a reusable media_id.
        Prefer this over `link=` when sending the same asset to many recipients —
        avoids Meta re-fetching the URL on every send."""
        mime_type = mime_type or mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        with open(file_path, "rb") as f:
            files = {"file": (file_path, f, mime_type)}
            data = {"messaging_product": "whatsapp", "type": mime_type}
            resp = self.session.post(self.media_url, files=files, data=data, timeout=self.config.timeout)
        if resp.status_code >= 400:
            self._raise_for_error(resp)
        return resp.json()["id"]

    # ---------- location ----------

    def send_location(self, to: str, latitude: float, longitude: float,
                       name: Optional[str] = None, address: Optional[str] = None,
                       reply_to: Optional[str] = None) -> Dict[str, Any]:
        payload = self._base_payload(to, "location", reply_to)
        loc: Dict[str, Any] = {"latitude": latitude, "longitude": longitude}
        if name:
            loc["name"] = name
        if address:
            loc["address"] = address
        payload["location"] = loc
        return self._post(payload)

    # ---------- contacts ----------

    def send_contacts(self, to: str, contacts: List[Dict[str, Any]],
                       reply_to: Optional[str] = None) -> Dict[str, Any]:
        payload = self._base_payload(to, "contacts", reply_to)
        payload["contacts"] = contacts
        return self._post(payload)

    # ---------- interactive ----------

    def send_interactive_buttons(self, to: str, body_text: str, buttons: List[Dict[str, str]],
                                  header: Optional[Dict[str, Any]] = None,
                                  footer_text: Optional[str] = None,
                                  reply_to: Optional[str] = None) -> Dict[str, Any]:
        """buttons: up to 3 dicts like {"id": "confirm", "title": "Confirm"}."""
        if len(buttons) > 3:
            raise ValueError("Reply buttons support a maximum of 3 options")

        payload = self._base_payload(to, "interactive", reply_to)
        interactive: Dict[str, Any] = {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}} for b in buttons
            ]},
        }
        if header:
            interactive["header"] = header
        if footer_text:
            interactive["footer"] = {"text": footer_text}
        payload["interactive"] = interactive
        return self._post(payload)

    def send_interactive_list(self, to: str, body_text: str, button_text: str,
                               sections: List[Dict[str, Any]],
                               header_text: Optional[str] = None,
                               footer_text: Optional[str] = None,
                               reply_to: Optional[str] = None) -> Dict[str, Any]:
        payload = self._base_payload(to, "interactive", reply_to)
        interactive: Dict[str, Any] = {
            "type": "list",
            "body": {"text": body_text},
            "action": {"button": button_text, "sections": sections},
        }
        if header_text:
            interactive["header"] = {"type": "text", "text": header_text}
        if footer_text:
            interactive["footer"] = {"text": footer_text}
        payload["interactive"] = interactive
        return self._post(payload)

    def send_interactive_cta_url(self, to: str, body_text: str, button_text: str, url: str,
                                  header_text: Optional[str] = None,
                                  footer_text: Optional[str] = None,
                                  reply_to: Optional[str] = None) -> Dict[str, Any]:
        payload = self._base_payload(to, "interactive", reply_to)
        interactive: Dict[str, Any] = {
            "type": "cta_url",
            "body": {"text": body_text},
            "action": {"name": "cta_url", "parameters": {"display_text": button_text, "url": url}},
        }
        if header_text:
            interactive["header"] = {"type": "text", "text": header_text}
        if footer_text:
            interactive["footer"] = {"text": footer_text}
        payload["interactive"] = interactive
        return self._post(payload)

    # ---------- reaction / read receipts ----------

    def send_reaction(self, to: str, message_id: str, emoji: str) -> Dict[str, Any]:
        payload = self._base_payload(to, "reaction")
        payload["reaction"] = {"message_id": message_id, "emoji": emoji}
        return self._post(payload)

    def mark_as_read(self, message_id: str) -> Dict[str, Any]:
        payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
        return self._post(payload)

    # ---------- lifecycle ----------

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ---------------- usage examples ----------------

# if __name__ == "__main__":
#     logging.basicConfig(level=logging.INFO)

#     config = WhatsAppConfig(
#         phone_number_id="YOUR_PHONE_NUMBER_ID",
#         access_token="YOUR_ACCESS_TOKEN",
#     )

#     with WhatsAppSender(config) as wa:
#         # 1. Plain text (only works inside the 24h customer-service window)
#         wa.send_text(to="919999999999", body="Hello from RecruitSmart!")

#         # 2. Template with body params + a dynamic URL button
#         components = wa.build_template_components(
#             body_params=["Anand", "your interview is on July 20"],
#             button_params=[{"sub_type": "url", "index": 0, "param": "abc123"}],
#         )
#         wa.send_template(
#             to="919999999999",
#             template_name="interview_reminder",
#             language_code="en_US",
#             components=components,
#         )

#         # 3. Media by link
#         wa.send_media(
#             to="919999999999", media_type="document",
#             link="https://example.com/offer_letter.pdf",
#             filename="Offer_Letter.pdf", caption="Your offer letter",
#         )

#         # 4. Upload once, send by media_id (skip re-fetching the URL each time)
#         media_id = wa.upload_media("/path/to/resume.pdf")
#         wa.send_media(to="919999999999", media_type="document", media_id=media_id)

#         # 5. Interactive quick-reply buttons
#         wa.send_interactive_buttons(
#             to="919999999999",
#             body_text="Confirm your interview slot?",
#             buttons=[{"id": "confirm", "title": "Confirm"}, {"id": "reschedule", "title": "Reschedule"}],
#         )