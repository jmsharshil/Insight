"""
exams/omr_azure.py
===================
Azure OpenAI (GPT-4o-vision) based OMR reader using the official `openai` SDK (v1.65+).

Provides drop-in replacements for the local OpenCV/pytesseract functions in omr.py:

  - extract_answer_key_from_file_azure(...) → {1: 'A', 2: 'B', ...}
  - detect_student_answers_azure(...) → {1: 'A', 2: None, ...}
  - parse_student_identity_from_sheet_azure(...) → {'student_name': ..., 'roll_number': ...}

Advantages: No local CV/OCR deps (pdf2image+Poppler optional for PDF support), robust to poor scans,
handles printed keys, handwritten bubbles, varied layouts. Uses official SDK with JSON mode (temp=0)
for reliable structured output. Enhanced _encode_image_to_data_url with magic-byte MIME detection
and full BytesIO/PDF support. _extract_json has graceful fallback + stricter validation in callers.

Required Django settings (add to your settings.py):
  AZURE_OPENAI_ENDPOINT     e.g. "https://your-resource.openai.azure.com/"
  AZURE_OPENAI_KEY          your API key
  AZURE_OPENAI_DEPLOYMENT   model deployment name (must support vision, e.g. "gpt-4o")
  AZURE_OPENAI_API_VERSION  optional (defaults to "2024-08-06")

PDF support (for .pdf paths/bytes/BytesIO): requires `pdf2image==1.16.0` (in requirements.txt)
**and** Poppler (apt install poppler-utils). See omr.py for shared helper. Clear errors on missing deps.

Note: Base64 data URLs sent to vision model. Monitor cost (~$0.01–0.05 per call) and latency (1–4s).
"""

import base64
import io
import json
import logging
import os
import re
from typing import Any, Dict, Optional

from django.conf import settings
from openai import AzureOpenAI

logger = logging.getLogger(__name__)

# Lazy-initialized Azure OpenAI client + deployment name (official SDK instead of raw requests)
_client = None
_deployment = None


def _get_azure_config():
    """Return cached (AzureOpenAI client, deployment_name). Fetches settings dynamically
    (in case module imported before Django settings ready). Raises RuntimeError if
    required settings missing.
    """
    global _client, _deployment
    if _client is None:
        endpoint = getattr(settings, "AZURE_OPENAI_ENDPOINT", None)
        key = getattr(settings, "AZURE_OPENAI_KEY", None)
        deployment = getattr(settings, "AZURE_OPENAI_DEPLOYMENT", None)
        api_version = getattr(settings, "AZURE_OPENAI_API_VERSION", None)

        if not (endpoint and key and deployment):
            raise RuntimeError(
                "AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY and AZURE_OPENAI_DEPLOYMENT "
                "must be configured in Django settings. See omr_azure.py docstring."
            )
        _client = AzureOpenAI(
            azure_endpoint=endpoint.rstrip("/"),
            api_key=key,
            api_version=api_version or "2024-08-06",
        )
        _deployment = deployment
    return _client, _deployment


def _get_mime_type(data: bytes, fallback: str = "jpeg") -> str:
    """Detect MIME type from magic bytes for robust image/PDF handling."""
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"RIFF") and b"WEBP" in data[:12]:
        return "webp"
    return fallback


def _encode_image_to_data_url(source) -> str:
    """Convert image source (path str, bytes, BytesIO, or PDF) to data URL.
    Now with full magic-byte detection for JPEG/PNG/GIF/WEBP/PDF.
    - PDF path/bytes → rendered to PNG via pdf2image or omr helper (requires Poppler).
    - BytesIO now fully supports PDF magic too.
    - Raises clear Poppler-missing errors. MIME defaults to jpeg for unknown images.
    """
    if isinstance(source, io.BytesIO):
        source.seek(0)
        source = source.read()  # convert to bytes for unified handling

    if isinstance(source, str):
        ext = os.path.splitext(source)[1].lower()
        if ext == ".pdf":
            try:
                from .omr import _pdf_page_to_image_bytes
                img_bytes = _pdf_page_to_image_bytes(source, page=0)
                if not img_bytes:
                    raise ValueError("PDF rendering returned no data")
                data = img_bytes
                mime = "png"
            except Exception as e:
                logger.error("PDF support in azure OMR failed: %s", e)
                raise ValueError(
                    "PDF processing requires pdf2image (pip install pdf2image) "
                    "AND the Poppler runtime library (system dep). "
                    "Ubuntu/Debian: sudo apt-get install poppler-utils. "
                    "See https://pdf2image.readthedocs.io/en/latest/installation.html "
                    "(also check omr.py _pdf_page_to_image_bytes)."
                ) from e
        else:
            with open(source, "rb") as f:
                data = f.read()
            mime = _get_mime_type(data, "jpeg" if ext in (".jpg", ".jpeg") else ext.lstrip("."))
    elif isinstance(source, (bytes, bytearray)):
        data = bytes(source)
        mime = _get_mime_type(data)
        if mime == "pdf":
            try:
                from pdf2image import convert_from_bytes
                pages = convert_from_bytes(data, dpi=200, first_page=1, last_page=1)
                if not pages:
                    raise ValueError("No pages in PDF bytes")
                buf = io.BytesIO()
                pages[0].save(buf, format="PNG")
                data = buf.getvalue()
                mime = "png"
            except Exception as e:
                logger.error("PDF bytes rendering failed: %s", e)
                raise ValueError(
                    "PDF bytes processing failed. Requires pdf2image + Poppler runtime. "
                    "See detailed install instructions in the PDF path error or "
                    "https://pdf2image.readthedocs.io/en/latest/installation.html"
                ) from e
    else:
        raise ValueError(f"Unsupported source type for image: {type(source)}")

    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:image/{mime};base64,{b64}"


def _call_azure_vision(image_data_url: str, system_prompt: str, user_prompt: str, max_tokens: int = 2000) -> str:
    """Call Azure OpenAI vision model (GPT-4o) using the official SDK.
    Uses structured JSON mode (temperature=0) for reliable parsing.
    """
    client, deployment = _get_azure_config()

    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                },
            ],
            max_tokens=max_tokens,
            temperature=0,
            response_format={"type": "json_object"},
        )
        if not response.choices or not response.choices[0].message.content:
            raise ValueError("Empty response from Azure OpenAI")
        return response.choices[0].message.content
    except Exception as exc:  # openai.APIError, RateLimitError, etc.
        logger.error("Azure OpenAI API call failed: %s", exc)
        raise RuntimeError(f"Azure Vision API error: {exc}") from exc


def _extract_json(text: str) -> Dict[str, Any]:
    """Robustly extract and parse JSON from LLM response.
    - Strips ```json markdown fences
    - Extracts first embedded JSON object if extra text present
    - Fixes common trailing commas
    - Graceful fallback to {} on parse failure (with detailed logging)
    """
    if not text or not text.strip():
        logger.warning("Empty response from Azure OpenAI")
        return {}

    cleaned = text.strip()

    # Strip common markdown code blocks
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.MULTILINE | re.IGNORECASE)
    cleaned = re.sub(r'\s*```$', '', cleaned, flags=re.MULTILINE | re.IGNORECASE)

    # Extract the first JSON-like object if there is surrounding text (non-greedy but sufficient for LLM output)
    json_match = re.search(r'(\{[\s\S]*?\})', cleaned)
    if json_match:
        cleaned = json_match.group(1)

    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("JSON parse failed, attempting trailing-comma fix. Snippet: %s", cleaned[:150])
        try:
            # Remove trailing commas before } or ]
            cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error("JSON parse failed even after cleanup. Raw response snippet: %s", text[:300])
            return {}


# ---------------------------------------------------------------------------
# Drop-in replacements matching omr.py's public interface
# ---------------------------------------------------------------------------


def extract_answer_key_from_file_azure(source, n_questions: int = 0, n_options: int = 4) -> Dict[int, str]:
    """Drop-in alternative to omr.extract_answer_key_from_file using Azure Vision (GPT-4o).
    Accepts: str (path to image/PDF), bytes, BytesIO. For PDF uses first page.
    Returns {1: 'A', 2: 'B', ...} with stricter int/ABCDE validation. Returns {} on failure.
    """
    image_url = _encode_image_to_data_url(source)
    labels = ", ".join(chr(65 + i) for i in range(n_options))
    system_prompt = (
        "You are an expert OMR/answer-key extractor. Analyze the image (may contain "
        "filled bubbles, printed letters, or checkboxes) and return ONLY valid JSON."
    )
    user_prompt = (
        f"Image shows answer key for ~{n_questions or 'unknown'} questions with options {labels}. "
        f'Output JSON object with integer keys and option letters (A-{labels[-1] if labels else "D"}): '
        f'{{"1": "A", "2": "B", ...}}. Use null for unclear. No extra text or markdown.'
    )
    raw = _call_azure_vision(image_url, system_prompt, user_prompt, max_tokens=1500)
    parsed = _extract_json(raw)
    if not isinstance(parsed, dict) or not parsed:
        logger.warning("No valid answer key parsed from Azure response. Raw snippet: %s", str(raw)[:200])
        return {}

    # Convert keys to int, values to uppercase letters; stricter validation for ABCDE
    result = {}
    for k, v in parsed.items():
        try:
            q = int(k)
            ans = str(v).upper().strip()
            if ans in "ABCDE":
                result[q] = ans
        except (ValueError, TypeError):
            continue  # skip invalid keys
    return result


def detect_student_answers_azure(source, n_questions: int, n_options: int = 4) -> Dict[int, Optional[str]]:
    """Drop-in alternative to omr.detect_student_answers using Azure Vision (GPT-4o).
    Accepts: str (path to image/PDF), bytes, BytesIO. For PDF uses first page.
    Returns {1: 'A', 2: None, ...} where None = blank or ambiguous. Always returns all questions.
    """
    if n_questions < 1:
        raise ValueError("n_questions must be > 0 for student answer detection")

    image_url = _encode_image_to_data_url(source)
    labels = ", ".join(chr(65 + i) for i in range(n_options))
    system_prompt = (
        "You are an expert OMR bubble-sheet reader. Examine each question row and "
        "identify the selected/filled option (A-E). Return ONLY a JSON dict with "
        "question numbers as keys."
    )
    user_prompt = (
        f"Analyze this student OMR sheet ({n_questions} questions, options {labels}). "
        f'For each question output the chosen letter or null if blank/ambiguous/multiple. '
        f'Example: {{"1": "B", "2": null, "3": "A", "4": "C"}}. Strictly valid JSON only.'
    )
    raw = _call_azure_vision(image_url, system_prompt, user_prompt, max_tokens=2000)
    parsed = _extract_json(raw)
    if not isinstance(parsed, dict):
        logger.warning("Invalid parsed type from Azure for student answers: %s", type(parsed))
        parsed = {}

    result: Dict[int, Optional[str]] = {}
    for q in range(1, n_questions + 1):
        val = parsed.get(str(q)) or parsed.get(q)
        if isinstance(val, str) and val.strip().upper() in "ABCDE":
            result[q] = val.strip().upper()
        else:
            result[q] = None
    return result


def parse_student_identity_from_sheet_azure(source) -> Dict[str, Any]:
    """Drop-in alternative to omr.parse_student_identity_from_sheet using Azure Vision.
    More robust for poor scans/handwriting than local OCR. Returns {} on failure.
    Accepts str path (img/PDF), bytes, BytesIO.
    """
    try:
        image_url = _encode_image_to_data_url(source)
        system_prompt = (
            "You are an expert at extracting student information from exam answer sheet headers. "
            "Look for name, roll number, admission/enrollment ID. Return ONLY valid JSON."
        )
        user_prompt = (
            'From the image header, extract: {"student_name": "...", "roll_number": "...", '
            '"admission_number": "..."}. Use empty string for missing fields. JSON only.'
        )
        raw = _call_azure_vision(image_url, system_prompt, user_prompt, max_tokens=800)
        parsed = _extract_json(raw)
        if not isinstance(parsed, dict):
            logger.warning("Parsed identity is not a dict: %s", type(parsed))
            return {}
        # Stricter filtering
        return {
            k: str(v).strip()
            for k, v in parsed.items()
            if v and str(v).strip() and str(v).strip().lower() not in ("null", "none", "n/a")
        }
    except Exception as exc:  # RuntimeError from API, ValueError from encoding, etc.
        raw_snippet = str(locals().get("raw", ""))[:150] if "raw" in locals() else "N/A"
        logger.warning("Azure identity extraction failed: %s. Raw snippet: %s", exc, raw_snippet)
        return {}
