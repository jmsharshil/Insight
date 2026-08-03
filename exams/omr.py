"""
exams/omr.py
============
OMR (Optical Mark Recognition) engine for offline MCQ exams.

Two responsibilities:
  1. extract_answer_key_from_file(path)  → dict[int, str]
     Reads the admin-uploaded answer key (image or PDF) and extracts
     correct answers.  Supports two formats:
       a) A filled OMR sheet (bubbles) — OpenCV bubble detection
       b) A plain text / printed list  — pytesseract OCR + regex

  2. detect_student_answers(image_bytes, n_questions, n_options) → dict[int, str]
     Reads a student-uploaded OMR sheet image and returns the filled
     option for each question row.

  3. grade_omr(student, key, marks_per_q, negative_per_q) → (score, breakdown)
     Compares detected answers against the answer key and returns the
     final score + per-question result list.

Dependencies (add to requirements.txt if not present):
  opencv-python-headless
  numpy
  pytesseract   (required for OCR metadata extraction and text fallback)
  Pillow
"""

import re
import logging
import os
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)


def _configure_tesseract_cmd():
    """Try to configure pytesseract with a known tesseract executable path."""
    try:
        import pytesseract
    except ImportError:
        return

    tesseract_cmd = getattr(pytesseract.pytesseract, 'tesseract_cmd', 'tesseract')
    if tesseract_cmd and tesseract_cmd != 'tesseract' and os.path.exists(tesseract_cmd):
        return

    if os.name == 'nt':
        candidate_paths = [
            os.environ.get('TESSERACT_CMD', ''),
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for candidate in candidate_paths:
            if candidate and os.path.exists(candidate):
                pytesseract.pytesseract.tesseract_cmd = candidate
                return
    else:
        import shutil
        which_path = os.environ.get('TESSERACT_CMD') or shutil.which('tesseract')
        if which_path:
            pytesseract.pytesseract.tesseract_cmd = which_path
            return

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_image_as_array(source):
    """Accept file path (str), bytes, or BytesIO and return a numpy BGR array."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        raise RuntimeError("opencv-python-headless is required for OMR processing.")

    if isinstance(source, (bytes, bytearray)):
        arr = np.frombuffer(source, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    elif isinstance(source, BytesIO):
        source.seek(0)
        arr = np.frombuffer(source.read(), dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    elif isinstance(source, str):
        img = cv2.imread(source)
    else:
        raise ValueError(f"Unsupported image source type: {type(source)}")

    if img is None:
        raise ValueError("Could not decode image — ensure it is a valid JPEG/PNG/BMP.")
    return img


def _pdf_page_to_image_bytes(pdf_path: str, page: int = 0) -> Optional[bytes]:
    """Convert one PDF page to PNG bytes using pdf2image (poppler) if available."""
    try:
        from pdf2image import convert_from_path
        pages = convert_from_path(pdf_path, dpi=200, first_page=page + 1, last_page=page + 1)
        if not pages:
            return None
        buf = BytesIO()
        pages[0].save(buf, format='PNG')
        return buf.getvalue()
    except ImportError:
        raise ImportError(
            "pdf2image is required to render PDF OMR sheets. Install pdf2image into your Python environment "
            "and install the Poppler runtime on the server."
        )
    except Exception as exc:
        logger.error("PDF→image conversion failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Answer key parsing
# ---------------------------------------------------------------------------

OPTION_LABELS = ['A', 'B', 'C', 'D', 'E']


def _parse_text_answer_key(text: str) -> dict:
    """
    Parse a text like:
        1. A   2. B   3-C   4) D   ...
        1 A
        Q1: A
    Returns {1: 'A', 2: 'B', ...}
    """
    pattern = re.compile(
        r'(?:Q\.?\s*)?(\d{1,3})'        # question number
        r'[\s.\-:)]+\s*'                 # separator
        r'([A-Ea-e])\b',                 # single letter option
        re.IGNORECASE,
    )
    key = {}
    for m in pattern.finditer(text):
        qnum = int(m.group(1))
        opt = m.group(2).upper()
        key[qnum] = opt
    return key


def _detect_bubbles_from_image(img_arr, n_questions: int, n_options: int) -> dict:
    """
    Detect filled bubbles from a preprocessed OMR image.
    Assumes a standard vertical OMR layout: rows = questions, cols = options.
    Returns {1: 'A', 2: 'B', ...}  (1-indexed)
    """
    import cv2
    import numpy as np

    gray = cv2.cvtColor(img_arr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Find contours of bubble candidates
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Filter circular-ish contours of reasonable size
    h, w = thresh.shape
    min_area = (h * w) / (n_questions * n_options * 20)
    max_area = (h * w) / (n_questions * n_options * 2)

    bubbles = []
    for c in contours:
        area = cv2.contourArea(c)
        if not (min_area < area < max_area):
            continue
        perimeter = cv2.arcLength(c, True)
        if perimeter == 0:
            continue
        circularity = 4 * 3.14159 * area / (perimeter * perimeter)
        if circularity < 0.55:  # loose threshold for printed/scanned sheets
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        cx = x + bw // 2
        cy = y + bh // 2
        bubbles.append((cy, cx, c))  # sort by (row, col)

    if not bubbles:
        raise ValueError("No bubble contours detected — check image quality / orientation.")

    # Sort bubbles by row then column
    bubbles.sort(key=lambda b: (b[0], b[1]))

    # Group into rows (questions)
    row_tolerance = h / (n_questions * 2.5)
    rows = []
    current_row = [bubbles[0]]
    for b in bubbles[1:]:
        if abs(b[0] - current_row[0][0]) <= row_tolerance:
            current_row.append(b)
        else:
            rows.append(sorted(current_row, key=lambda x: x[1]))  # sort cols left→right
            current_row = [b]
    rows.append(sorted(current_row, key=lambda x: x[1]))

    # Keep only the first n_questions rows with at least 1 bubble
    rows = [r for r in rows if len(r) >= 1][:n_questions]

    results = {}
    for row_idx, row_bubbles in enumerate(rows):
        qnum = row_idx + 1
        best_filled = None
        best_count = -1

        # Take up to n_options bubbles in this row
        row_bubbles = row_bubbles[:n_options]

        for col_idx, (cy, cx, contour) in enumerate(row_bubbles):
            # Create a mask for this bubble and count non-zero pixels in thresh
            mask = np.zeros(thresh.shape, dtype=np.uint8)
            cv2.drawContours(mask, [contour], -1, 255, -1)
            filled_pixels = cv2.countNonZero(cv2.bitwise_and(thresh, thresh, mask=mask))
            total_pixels = cv2.countNonZero(mask)
            fill_ratio = filled_pixels / total_pixels if total_pixels else 0

            if fill_ratio > 0.45 and filled_pixels > best_count:
                best_count = filled_pixels
                best_filled = col_idx

        if best_filled is not None and best_filled < len(OPTION_LABELS):
            results[qnum] = OPTION_LABELS[best_filled]
        else:
            results[qnum] = None  # blank / unanswered

    return results


def extract_answer_key_from_file(file_path: str, n_questions: int = 0, n_options: int = 4) -> dict:
    """
    Parse the admin-uploaded answer key file (image or PDF).
    Strategy:
      1. If image → try bubble detection (OMR sheet)
      2. If PDF  → convert first page to image and try bubble detection;
                   if that yields < 50 % of expected answers, fall back to OCR text parse
      3. If text file (txt/csv) → direct text parse

    Returns {1: 'A', 2: 'B', ...} (1-indexed, uppercase options).
    """
    ext = os.path.splitext(file_path)[1].lower()

    # ── Text / CSV path ────────────────────────────────────────────────────
    if ext in ('.txt', '.csv'):
        with open(file_path, 'r', errors='ignore') as f:
            text = f.read()
        key = _parse_text_answer_key(text)
        if key:
            return key
        raise ValueError("Could not parse any answers from text file.")

    # ── PDF path ───────────────────────────────────────────────────────────
    if ext == '.pdf':
        img_bytes = _pdf_page_to_image_bytes(file_path)
        if img_bytes and n_questions > 0:
            try:
                img = _load_image_as_array(img_bytes)
                key = _detect_bubbles_from_image(img, n_questions, n_options)
                if len([v for v in key.values() if v]) >= max(1, n_questions // 2):
                    return key
            except Exception as exc:
                logger.warning("Bubble detection on PDF failed, trying OCR: %s", exc)

        # OCR fallback
        try:
            import pytesseract
            from PIL import Image as PILImage
            if img_bytes:
                pil_img = PILImage.open(BytesIO(img_bytes))
            else:
                pil_img = PILImage.open(file_path)
            text = pytesseract.image_to_string(pil_img)
            key = _parse_text_answer_key(text)
            if key:
                return key
        except ImportError:
            logger.warning("pytesseract not installed — cannot OCR PDF answer key.")
        except Exception as exc:
            logger.error("OCR fallback failed: %s", exc)

        raise ValueError("Could not extract answer key from PDF — ensure it is a readable OMR sheet or text-based PDF.")

    # ── Image path (JPEG, PNG, BMP, TIFF) ─────────────────────────────────
    img_arr = _load_image_as_array(file_path)

    if n_questions > 0:
        try:
            key = _detect_bubbles_from_image(img_arr, n_questions, n_options)
            if len([v for v in key.values() if v]) >= max(1, n_questions // 2):
                return key
        except Exception as exc:
            logger.warning("Bubble detection on image failed, trying OCR: %s", exc)

    # OCR fallback for image
    try:
        import pytesseract
        from PIL import Image as PILImage
        import cv2
        gray = cv2.cvtColor(img_arr, cv2.COLOR_BGR2GRAY)
        pil_img = PILImage.fromarray(gray)
        text = pytesseract.image_to_string(pil_img)
        key = _parse_text_answer_key(text)
        if key:
            return key
    except ImportError:
        pass
    except Exception as exc:
        logger.error("OCR on image failed: %s", exc)

    raise ValueError("Could not extract answer key from image.")


def _extract_text_from_image(img_arr):
    try:
        import pytesseract
        from PIL import Image as PILImage
    except ImportError:
        raise ImportError("pytesseract is required to extract student metadata from the OMR sheet.")

    _configure_tesseract_cmd()

    if getattr(img_arr, 'ndim', None) is not None:
        from PIL import Image as PILImage
        pil_img = PILImage.fromarray(img_arr)
    else:
        raise ValueError("Unsupported image type for OCR metadata extraction.")

    try:
        return pytesseract.image_to_string(pil_img)
    except pytesseract.pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError(
            "Tesseract OCR binary not found. Install Tesseract and ensure it is on PATH "
            "or set pytesseract.pytesseract.tesseract_cmd to the executable path. "
            "On Windows, install it at C:\\Program Files\\Tesseract-OCR\\tesseract.exe."
        ) from exc


def _normalize_text_for_match(value: str) -> str:
    if not value:
        return ''
    value = re.sub(r'[\s\u00A0]+', ' ', value).strip()
    return value


def parse_student_identity_from_sheet(source) -> dict:
    """Parse student metadata like name, roll number, or admission number from the OMR sheet."""
    if isinstance(source, str) and source.lower().endswith('.pdf'):
        img_bytes = _pdf_page_to_image_bytes(source)
        if not img_bytes:
            raise ValueError("Could not render PDF answer sheet for metadata extraction.")
        img = _load_image_as_array(img_bytes)
    else:
        img = _load_image_as_array(source)

    text = _extract_text_from_image(img)
    text = text.replace('\r', '\n')
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    def extract_field(regex_list):
        for regex in regex_list:
            for line in lines:
                match = regex.search(line)
                if match:
                    return _normalize_text_for_match(match.group(1))
        return None

    metadata = {
        'student_name': extract_field([
            re.compile(r'(?:student\s*name|name)\s*[:\-]\s*(.+)', re.IGNORECASE),
            re.compile(r'^[Nn]ame\s*[:\-]\s*(.+)$'),
        ]),
        'roll_number': extract_field([
            re.compile(r'(?:roll(?:\s*(?:no|number)\b)|r\b)\s*[:\-]?\s*(\S+)', re.IGNORECASE),
            re.compile(r'^(?:roll|r)\s*(?:no|number)?\s*(?:[:\-])\s*(\S+)$', re.IGNORECASE),
        ]),
        'admission_number': extract_field([
            re.compile(r'(?:admission(?:\s*(?:no|number)|\s*)|enrollment(?:\s*(?:no|number)|\s*)|adm)\s*[:\-]?\s*(\S+)', re.IGNORECASE),
            re.compile(r'^(?:admission|admn|enrollment)\s*(?:no|number)?\s*(?:[:\-])\s*(\S+)$', re.IGNORECASE),
        ]),
    }

    if not metadata['student_name']:
        for index, line in enumerate(lines):
            if re.search(r'\b(student\s*name|name)\b', line, re.IGNORECASE):
                if ':' in line:
                    candidate = line.split(':', 1)[1].strip()
                    if candidate:
                        metadata['student_name'] = _normalize_text_for_match(candidate)
                        break
                elif index + 1 < len(lines):
                    metadata['student_name'] = _normalize_text_for_match(lines[index + 1])
                    break

    if not metadata['student_name'] and lines:
        for line in lines:
            if len(line) > 2 and all(ch.isalpha() or ch.isspace() or ch in '.-' for ch in line):
                if 'roll' not in line.lower() and 'admission' not in line.lower() and 'enroll' not in line.lower():
                    metadata['student_name'] = _normalize_text_for_match(line)
                    break

    return {k: v for k, v in metadata.items() if v}


# ---------------------------------------------------------------------------
# Student answer detection
# ---------------------------------------------------------------------------

def detect_student_answers(source, n_questions: int, n_options: int = 4) -> dict:
    """
    Detect filled bubbles from a student-uploaded OMR sheet.

    Args:
        source: file path (str), bytes, or BytesIO of the OMR image.
                If a PDF, only the first page is used.
        n_questions: total number of questions on the sheet.
        n_options:   number of options per question (default 4 = A/B/C/D).

    Returns:
        {1: 'A', 2: None, 3: 'C', ...}  — None means unanswered.
    """
    # Convert PDF first page if needed
    if isinstance(source, str) and source.lower().endswith('.pdf'):
        img_bytes = _pdf_page_to_image_bytes(source)
        if not img_bytes:
            raise ValueError("Could not render PDF answer sheet.")
        img = _load_image_as_array(img_bytes)
    else:
        img = _load_image_as_array(source)

    return _detect_bubbles_from_image(img, n_questions, n_options)


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

def grade_omr(
    student_answers: dict,
    answer_key: dict,
    marks_per_question: float = 1.0,
    negative_per_question: float = 0.0,
) -> tuple:
    """
    Compare student_answers against answer_key and compute the score.

    Args:
        student_answers:     {1: 'A', 2: None, ...}
        answer_key:          {1: 'C', 2: 'B', ...}
        marks_per_question:  marks awarded for a correct answer.
        negative_per_question: marks deducted for a wrong answer (pass positive value).

    Returns:
        (total_score: float, breakdown: list[dict])
        breakdown item: {
            "question": int,
            "correct_answer": str | None,
            "student_answer": str | None,
            "result": "correct" | "wrong" | "unanswered",
            "marks": float,
        }
    """
    breakdown = []
    total = 0.0

    all_questions = sorted(set(list(answer_key.keys()) + list(student_answers.keys())))

    for qnum in all_questions:
        correct = answer_key.get(qnum)
        given = student_answers.get(qnum)

        if given is None or correct is None:
            result = 'unanswered'
            marks = 0.0
        elif given.upper() == correct.upper():
            result = 'correct'
            marks = float(marks_per_question)
        else:
            result = 'wrong'
            marks = -float(negative_per_question)

        total += marks
        breakdown.append({
            'question': qnum,
            'correct_answer': correct,
            'student_answer': given,
            'result': result,
            'marks': marks,
        })

    return max(0.0, total), breakdown
