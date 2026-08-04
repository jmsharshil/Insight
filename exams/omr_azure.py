"""
exams/omr_azure.py
===================
Azure OpenAI vision-based OMR reader — drop-in alternative to the
OpenCV/pytesseract pipeline in omr.py.

Env vars required:
  AZURE_OPENAI_ENDPOINT     e.g. https://your-resource.openai.azure.com
  AZURE_OPENAI_KEY
  AZURE_OPENAI_DEPLOYMENT   name of a vision-capable deployment (e.g. "gpt-4o")
  AZURE_OPENAI_API_VERSION  optional, defaults below
"""

import base64
import json
import logging
import os
import re
from typing import Dict, Optional
from django.conf import settings
import requests

logger = logging.getLogger(__name__)

AZURE_OPENAI_ENDPOINT = settings.get("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = settings.get("AZURE_OPENAI_KEY")
AZURE_OPENAI_DEPLOYMENT = settings.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_API_VERSION = settings.get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")


def _encode_image_to_data_url(path: str) -> str:
    ext = os.path.splitext(path)[1].lower().lstrip('.') or 'jpeg'
    mime = 'jpeg' if ext in ('jpg', 'jpeg') else ext
    with open(path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('utf-8')
    return f"data:image/{mime};base64,{b64}"


def _call_azure_vision(image_data_url: str, system_prompt: str, user_prompt: str, max_tokens: int = 2000) -> str:
    if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY):
        raise RuntimeError("AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_KEY not configured.")

    url = (
        f"{AZURE_OPENAI_ENDPOINT.rstrip('/')}/openai/deployments/"
        f"{AZURE_OPENAI_DEPLOYMENT}/chat/completions?api-version={AZURE_OPENAI_API_VERSION}"
    )
    headers = {"Content-Type": "application/json", "api-key": AZURE_OPENAI_KEY}
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            },
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict:
    cleaned = re.sub(r'^```(?:json)?|```$', '', text.strip(), flags=re.MULTILINE).strip()
    return json.loads(cleaned)


# ---------------------------------------------------------------------------
# Drop-in replacements matching omr.py's public interface
# ---------------------------------------------------------------------------

def extract_answer_key_from_file_azure(file_path: str, n_questions: int = 0, n_options: int = 4) -> Dict[int, str]:
    image_url = _encode_image_to_data_url(file_path)
    labels = ", ".join(chr(65 + i) for i in range(n_options))
    system_prompt = (
        "You are an OMR/answer-key reading assistant. Read the answer key image carefully "
        "(it may be filled bubbles or printed text) and return ONLY a JSON object mapping "
        "question number (as string) to the selected option letter."
    )
    user_prompt = (
        f"This image contains an answer key with {n_questions or 'an unknown number of'} questions, "
        f"each with options {labels}. Return JSON like {{\"1\": \"A\", \"2\": \"C\", ...}}. "
        "If a question's answer is unclear or missing, omit it. No commentary, JSON only."
    )
    raw = _call_azure_vision(image_url, system_prompt, user_prompt)
    try:
        parsed = _extract_json(raw)
    except json.JSONDecodeError as exc:
        logger.error("Azure OMR key parse failed, raw=%s", raw[:300])
        raise ValueError(f"Could not parse answer key JSON from Azure OpenAI: {exc}")

    return {int(k): str(v).upper() for k, v in parsed.items() if str(v).strip()}


def detect_student_answers_azure(file_path: str, n_questions: int, n_options: int = 4) -> Dict[int, Optional[str]]:
    image_url = _encode_image_to_data_url(file_path)
    labels = ", ".join(chr(65 + i) for i in range(n_options))
    system_prompt = (
        "You are an OMR bubble-sheet reading assistant. Carefully identify which bubble is "
        "filled/shaded for each question row. Return ONLY a JSON object."
    )
    user_prompt = (
        f"This is a student's answer sheet with {n_questions} questions, each with options {labels}. "
        f"For each question 1 to {n_questions}, return the filled option letter, or null if blank/unclear "
        f"or if multiple bubbles are filled. Return JSON like {{\"1\": \"B\", \"2\": null, ...}}. "
        "JSON only, no commentary."
    )
    raw = _call_azure_vision(image_url, system_prompt, user_prompt)
    try:
        parsed = _extract_json(raw)
    except json.JSONDecodeError as exc:
        logger.error("Azure OMR student parse failed, raw=%s", raw[:300])
        raise ValueError(f"Could not parse student answers JSON from Azure OpenAI: {exc}")

    result: Dict[int, Optional[str]] = {}
    for q in range(1, n_questions + 1):
        val = parsed.get(str(q))
        result[q] = str(val).upper() if val else None
    return result


def parse_student_identity_from_sheet_azure(file_path: str) -> dict:
    image_url = _encode_image_to_data_url(file_path)
    system_prompt = (
        "You extract student identity fields (name, roll number, admission number) from the "
        "header area of a scanned exam answer sheet. Return ONLY a JSON object."
    )
    user_prompt = (
        "Return JSON like {\"student_name\": \"...\", \"roll_number\": \"...\", "
        "\"admission_number\": \"...\"}. Omit any field you cannot find. JSON only."
    )
    raw = _call_azure_vision(image_url, system_prompt, user_prompt, max_tokens=500)
    try:
        parsed = _extract_json(raw)
    except json.JSONDecodeError:
        return {}
    return {k: v for k, v in parsed.items() if v}