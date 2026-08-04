"""
exams/omr_azure.py
===================
Azure OpenAI (GPT-4o-vision) based OMR reader using the official `openai` SDK.

Provides drop-in replacements for the local OpenCV/pytesseract functions in omr.py:

  - extract_answer_key_from_file_azure(...) → {1: 'A', 2: 'B', ...}
  - detect_student_answers_azure(...) → {1: 'A', 2: None, ...}
  - parse_student_identity_from_sheet_azure(...) → {'student_name': ..., 'roll_number': ...}

Advantages: No local CV/OCR deps (except optional pdf2image for PDF paths), works on poor scans,
handles printed keys, handwritten bubbles, and varied layouts better in many cases.
Uses official SDK, structured JSON mode (temperature=0) for reliability.

Required Django settings (add to your settings.py):
  AZURE_OPENAI_ENDPOINT     e.g. "https://your-resource.openai.azure.com/"
  AZURE_OPENAI_KEY          your API key
  AZURE_OPENAI_DEPLOYMENT   model deployment name (must support vision, e.g. "gpt-4o")
  AZURE_OPENAI_API_VERSION  optional (defaults to "2024-08-06")

Note: Images are base64-encoded and sent in the prompt. For production, consider cost
(~$0.01–0.05 per call) and latency (1–4s). PDF support reuses omr._pdf_page_to_image_bytes.
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

# Lazy-initialized Azure OpenAI client (official SDK instead of raw requests)
_client = None


def _get_azure_client():
    """Return a cached AzureOpenAI client. Fetches settings dynamically (in case
    module imported before Django settings are fully configured). Raises RuntimeError
    if required settings missing.
    """
    global _client
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
    return _client


def _encode_image_to_data_url(source) -> str:
    """Convert image source (path, bytes, BytesIO, or PDF) to data URL for vision API.
    - PDF (path or bytes starting with %PDF) renders first page as PNG via pdf2image.
    - Reuses helper from omr.py for consistency.
    - MIME defaults to jpeg; PNG for rendered PDFs.
    """
    data: bytes
    mime: str = "jpeg"

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
                    "PDF processing requires pdf2image+Poppler (see omr.py)"
                ) from e
        else:
            with open(source, "rb") as f:
                data = f.read()
            mime = "jpeg" if ext in (".jpg", ".jpeg") else ext.lstrip(".")
    elif isinstance(source, (bytes, bytearray)):
        data = bytes(source)  # ensure bytes
        # Check for PDF magic bytes
        if data.startswith(b"%PDF"):
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
                raise ValueError("PDF bytes processing failed (pdf2image required)") from e
        # else keep as jpeg default
    elif isinstance(source, io.BytesIO):
        source.seek(0)
        data = source.read()
        # could check for PDF magic here too but omitted for simplicity
        mime = "jpeg"
    else:
        raise ValueError(f"Unsupported source type for image: {type(source)}")

    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:image/{mime};base64,{b64}"


def _call_azure_vision(image_data_url: str, system_prompt: str, user_prompt: str, max_tokens: int = 2000) -> str:
    """Call Azure OpenAI vision model using the official SDK (no requests library).
    Includes basic error handling for API issues.
    """
    client = _get_azure_client()

    try:
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
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
    - Graceful fallback to {} on parse failure (with logging)
    """
    if not text or not text.strip():
        raise ValueError("Empty response from Azure OpenAI")

    cleaned = text.strip()

    # Strip common markdown code blocks
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.MULTILINE | re.IGNORECASE)
    cleaned = re.sub(r'\s*```$', '', cleaned, flags=re.MULTILINE | re.IGNORECASE)

    # Extract the first JSON-like object if there is surrounding text
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
            raise ValueError(f"Could not parse JSON from Azure OpenAI response: {exc}") from exc


# ---------------------------------------------------------------------------
# Drop-in replacements matching omr.py's public interface
# ---------------------------------------------------------------------------

def extract_answer_key_from_file_azure(source, n_questions: int = 0, n_options: int = 4) -> Dict[int, str]:
    """Drop-in alternative to omr.extract_answer_key_from_file using Azure Vision (GPT-4o).
    Accepts: str (path to image/PDF), bytes, BytesIO. For PDF uses first page.
    Returns {1: 'A', 2: 'B', ...}. Raises on API or parse errors.
    """
    image_url = _encode_image_to_data_url(source)
    labels = ", ".join(chr(65 + i) for i in range(n_options))
    system_prompt = (
        "You are an expert OMR/answer-key extractor. Analyze the image (may contain "
        "filled bubbles, printed letters, or checkboxes) and return ONLY valid JSON."
    )
    user_prompt = (
        f"Image shows answer key for ~{n_questions or 'unknown'} questions with options {labels}. "
        f'Output JSON: {{"1": "A", "2": "B", ...}}. Use null or omit for unclear/missing. '
        "No explanations, no markdown — pure JSON only."
    )
    raw = _call_azure_vision(image_url, system_prompt, user_prompt, max_tokens=1500)
    try:
        parsed = _extract_json(raw)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.error("Failed to parse answer key from Azure. Raw response: %s", raw[:250])
        raise ValueError(f"Could not parse answer key JSON from Azure OpenAI: {exc}") from exc

    # Convert keys to int, values to uppercase letters, skip None/empty
    return {
        int(k): str(v).upper().strip()
        for k, v in parsed.items()
        if v and str(v).strip() in "ABCDE"
    }


def detect_student_answers_azure(source, n_questions: int, n_options: int = 4) -> Dict[int, Optional[str]]:
    """Drop-in alternative to omr.detect_student_answers using Azure Vision (GPT-4o).
    Accepts: str (path to image/PDF), bytes, BytesIO. For PDF uses first page.
    Returns {1: 'A', 2: None, ...} where None = blank or ambiguous.
    """
    if n_questions < 1:
        raise ValueError("n_questions must be > 0 for student answer detection")

    image_url = _encode_image_to_data_url(source)
    labels = ", ".join(chr(65 + i) for i in range(n_options))
    system_prompt = (
        "You are an expert OMR bubble-sheet reader. Examine each question row and "
        "identify the selected/filled option. Return ONLY a JSON dict."
    )
    user_prompt = (
        f"Student OMR sheet with {n_questions} questions, options {labels}. For each q, "
        f'return letter or null if blank/unclear/multiple. JSON example: {{"1": "B", "2": null, "3": "A"}}. '
        "Strictly JSON, no other text."
    )
    raw = _call_azure_vision(image_url, system_prompt, user_prompt, max_tokens=2000)
    try:
        parsed = _extract_json(raw)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.error("Failed to parse student answers from Azure. Raw: %s", raw[:250])
        raise ValueError(f"Could not parse student answers JSON from Azure OpenAI: {exc}") from exc

    result: Dict[int, Optional[str]] = {}
    for q in range(1, n_questions + 1):
        val = parsed.get(str(q)) or parsed.get(q)
        if val and str(val).strip().upper() in "ABCDE":
            result[q] = str(val).upper().strip()
        else:
            result[q] = None
    return result


def parse_student_identity_from_sheet_azure(source) -> Dict[str, Any]:
    """Drop-in alternative to omr.parse_student_identity_from_sheet using Azure Vision.
    More robust for poor scans/handwriting than local OCR. Returns {} on failure.
    Accepts str path (img/PDF), bytes, BytesIO.
    """
    image_url = _encode_image_to_data_url(source)
    system_prompt = (
        "You are an expert at extracting student information from exam answer sheet headers. "
        "Look for name, roll number, admission/enrollment ID. Return ONLY JSON."
    )
    user_prompt = (
        'From the image header, extract: {"student_name": "...", "roll_number": "...", '
        '"admission_number": "..."}. Use empty string for missing fields. JSON only.'
    )
    raw = _call_azure_vision(image_url, system_prompt, user_prompt, max_tokens=800)
    try:
        parsed = _extract_json(raw)
        if not isinstance(parsed, dict):
            logger.warning("Parsed identity is not a dict: %s", type(parsed))
            return {}
        return {k: str(v).strip() for k, v in parsed.items() if v and str(v).strip()}
    except (json.JSONDecodeError, ValueError, TypeError, RuntimeError) as exc:
        logger.warning("Azure identity extraction failed: %s. Raw snippet: %s", exc, raw[:150] if 'raw' in locals() else 'N/A')
        return {}