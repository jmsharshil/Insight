"""
exams/omr.py
============
OMR (Optical Mark Recognition) engine for offline MCQ exams.

Core functions:
  - extract_answer_key_from_file(path, n_questions=0, n_options=4) → {1: 'A', 2: 'B', ...}
    Supports: (1) filled OMR bubble sheet (OpenCV contour detection + circularity),
              (2) printed/text answer key via pytesseract OCR + robust regex.

  - parse_student_identity_from_sheet(source) → {'student_name': , 'roll_number': , 'admission_number': }
    Uses OCR on header area to auto-resolve student in bulk uploads.

  - detect_student_answers(source, n_questions, n_options=4) → {1: 'A', 2: None, ...}
    Returns detected option or None for blank rows.

  - grade_omr(student_answers, answer_key, marks_per_question=1.0, negative_per_question=0.0)
    → (total_score, per_question_breakdown_list)

**Improved in this update:**
  - Better adaptive thresholding + morphology in bubble detection.
  - Dynamic row tolerance using median spacing.
  - Grayscale + PSM=6 config for OCR (much higher accuracy on printed OMRs).
  - Robust error messages, logging, and fallback for missing questions.
  - Uses math.pi for accurate circularity.

Dependencies (add to requirements.txt / environment):
  - opencv-python-headless
  - numpy
  - pytesseract + Tesseract binary (apt install tesseract-ocr or Windows installer)
  - pdf2image + Poppler (for PDF support)
  - Pillow
"""

import re
import logging
import os
import math
from io import BytesIO
from typing import Optional, Dict, List, Any

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


def _parse_text_answer_key(text: str) -> Dict[int, str]:
    """
    Robust regex parser for printed answer keys in many formats:
        1. A   2. B   3-C   4) D
        Q1: A, 2 B
        1)A 2)B
        Answer 5 : C
    Returns dict like {1: 'A', 2: 'B', ...}. Ignores duplicates (keeps first).
    """
    if not text or not text.strip():
        return {}

    # Multiple patterns for different common formats
    patterns = [
        # Standard: 1. A | Q1: B | 3 - C | 4) D
        re.compile(r'(?:Q|Question|Ans|Answer)?[\s\.]?(\d{1,3})[\s.\-:\)]+\s*([A-Ea-e])\b', re.IGNORECASE),
        # Number followed by option with optional parentheses: (1) A or 5.B
        re.compile(r'\(?(\d{1,3})\)?[\s.\-:]+\s*([A-Ea-e])\b', re.IGNORECASE),
        # Colon separated at start of line
        re.compile(r'^[\s]*(\d{1,3})[\s:]+([A-Ea-e])\b', re.IGNORECASE | re.MULTILINE),
    ]

    key: Dict[int, str] = {}
    for pattern in patterns:
        for m in pattern.finditer(text):
            qnum = int(m.group(1))
            opt = m.group(2).upper()
            if qnum not in key:  # keep first match
                key[qnum] = opt

    if not key:
        logger.warning("No answers parsed from text. Sample text: %s...", text.strip()[:100])
    else:
        logger.debug("Parsed answer key: %s", dict(sorted(key.items())))

    return key


def _detect_bubbles_from_image(img_arr, n_questions: int, n_options: int = 4) -> Dict[int, Optional[str]]:
    """
    Detect filled bubbles from a preprocessed OMR image using OpenCV contours.
    Improved preprocessing, adaptive thresholds, and robust row grouping.
    Assumes standard vertical OMR layout (questions top to bottom, options left to right).
    Returns {1: 'A', 2: 'B', ...} or {qnum: None} for unanswered. Raises descriptive errors.
    """
    import cv2
    import numpy as np

    if n_questions < 1:
        n_questions = 50  # safe default
    if n_options < 2:
        n_options = 4

    # Enhanced preprocessing for scanned/printed OMR sheets
    if len(img_arr.shape) == 3:
        gray = cv2.cvtColor(img_arr, cv2.COLOR_BGR2GRAY)
    else:
        gray = img_arr

    # Noise reduction + contrast enhancement
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    # Adaptive thresholding works better for varying lighting/scans than global Otsu
    thresh = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 11, 2
    )

    # Light morphology to connect broken bubble edges
    kernel = np.ones((2, 2), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    # Find contours
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Calculate expected bubble area (robust against zero-division)
    h, w = thresh.shape[:2]
    expected_area = (h * w) / (n_questions * n_options * 25)  # slightly more conservative
    min_area = max(5, int(expected_area * 0.4))
    max_area = int(expected_area * 3.0)

    bubbles = []
    for c in contours:
        area = cv2.contourArea(c)
        if not (min_area < area < max_area):
            continue
        perimeter = cv2.arcLength(c, True)
        if perimeter == 0:
            continue
        # Improved circularity using math.pi
        circularity = 4 * math.pi * area / (perimeter * perimeter)
        if circularity < 0.6:  # tightened slightly for better filter
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        cx = x + bw // 2
        cy = y + bh // 2
        bubbles.append((cy, cx, c, area))  # include area for potential tie-breaking

    if not bubbles:
        # Provide more diagnostic info
        logger.warning(
            "No bubble contours detected. Image shape=%s, contours_found=%s, "
            "min_area=%s, max_area=%s. Check scan quality, contrast, or orientation.",
            img_arr.shape, len(contours), min_area, max_area
        )
        raise ValueError(
            "No bubble contours detected — ensure the image is a clear, well-lit, "
            "non-rotated OMR sheet with filled bubbles. Try re-scanning at 200+ DPI."
        )

    # Sort by vertical position (row) then horizontal (column)
    bubbles.sort(key=lambda b: (b[0], b[1]))

    # Improved row grouping using dynamic tolerance based on median spacing
    ys = [b[0] for b in bubbles]
    if len(ys) > 1:
        y_diffs = [ys[i+1] - ys[i] for i in range(len(ys)-1)]
        median_spacing = sorted(y_diffs)[len(y_diffs)//2] if y_diffs else h / n_questions
        row_tolerance = max(median_spacing * 1.5, h / (n_questions * 3))
    else:
        row_tolerance = h / (n_questions * 2.5)

    rows: List[List] = []
    current_row = [bubbles[0]]
    for b in bubbles[1:]:
        if abs(b[0] - current_row[0][0]) <= row_tolerance:
            current_row.append(b)
        else:
            rows.append(sorted(current_row, key=lambda x: x[1]))
            current_row = [b]
    rows.append(sorted(current_row, key=lambda x: x[1]))

    # Filter valid rows (must have at least one bubble) and limit to n_questions
    valid_rows = [r for r in rows if len(r) >= 1]
    rows = valid_rows[:n_questions]

    if len(rows) < n_questions // 2:
        logger.warning("Only detected %d question rows out of %d expected", len(rows), n_questions)

    results: Dict[int, Optional[str]] = {}
    for row_idx, row_bubbles in enumerate(rows):
        qnum = row_idx + 1
        best_filled = None
        best_count = -1
        best_ratio = 0.0

        # Limit to expected options per question
        row_bubbles = row_bubbles[:n_options]

        for col_idx, bubble_data in enumerate(row_bubbles):
            cy, cx, contour, _ = bubble_data
            # Mask and measure fill
            mask = np.zeros(thresh.shape, dtype=np.uint8)
            cv2.drawContours(mask, [contour], -1, 255, -1)
            filled_pixels = cv2.countNonZero(cv2.bitwise_and(thresh, thresh, mask=mask))
            total_pixels = cv2.countNonZero(mask)
            fill_ratio = filled_pixels / total_pixels if total_pixels > 0 else 0.0

            # Improved decision: use both ratio and absolute filled pixels
            if fill_ratio > 0.42 and filled_pixels > best_count:
                best_count = filled_pixels
                best_filled = col_idx
                best_ratio = fill_ratio

        if best_filled is not None and best_filled < len(OPTION_LABELS):
            results[qnum] = OPTION_LABELS[best_filled]
            logger.debug("Q%d: %s (fill_ratio=%.2f)", qnum, OPTION_LABELS[best_filled], best_ratio)
        else:
            results[qnum] = None  # unanswered/blank

    # Fill in any missing questions as unanswered
    for q in range(1, n_questions + 1):
        if q not in results:
            results[q] = None

    return results


def extract_answer_key_from_file(file_path: str, n_questions: int = 0, n_options: int = 4) -> Dict[int, str]:
    """
    Main entry point for parsing admin answer key (image/PDF/txt).
    Prioritizes bubble detection on OMR sheets; falls back to OCR+regex for printed keys.
    """
    ext = os.path.splitext(file_path)[1].lower()
    logger.info("Extracting answer key from %s (n_questions=%s, n_options=%s)", ext, n_questions, n_options)

    # ── Text / CSV path ────────────────────────────────────────────────────
    if ext in ('.txt', '.csv'):
        with open(file_path, 'r', errors='ignore') as f:
            text = f.read()
        key = _parse_text_answer_key(text)
        if key:
            logger.info("Parsed %d answers from text file via regex.", len(key))
            return key
        raise ValueError("Could not parse any answers from text file. Check format (e.g. '1. A  2. B').")

    # ── PDF path ───────────────────────────────────────────────────────────
    if ext == '.pdf':
        img_bytes = _pdf_page_to_image_bytes(file_path)
        if not img_bytes:
            raise ValueError("Failed to render PDF to image (check Poppler installation).")

        if n_questions > 0:
            try:
                img = _load_image_as_array(img_bytes)
                key = _detect_bubbles_from_image(img, n_questions, n_options)
                filled_count = len([v for v in key.values() if v is not None])
                if filled_count >= max(3, n_questions // 2):
                    logger.info("Successfully extracted %d answers via bubble detection on PDF.", filled_count)
                    return key
                logger.info("Bubble detection only found %d/%d answers; falling back to OCR.", filled_count, n_questions)
            except Exception as exc:
                logger.warning("Bubble detection on PDF failed (will try OCR): %s", exc)

        # OCR fallback for PDF (printed answer key)
        try:
            import pytesseract
            from PIL import Image as PILImage
            pil_img = PILImage.open(BytesIO(img_bytes))
            text = pytesseract.image_to_string(pil_img, config=r'--oem 3 --psm 6')
            key = _parse_text_answer_key(text)
            if key:
                logger.info("Parsed %d answers from PDF via OCR+regex.", len(key))
                return key
        except ImportError:
            logger.warning("pytesseract not installed — cannot OCR PDF answer key.")
        except Exception as exc:
            logger.error("OCR fallback on PDF failed: %s", exc)

        raise ValueError(
            "Could not extract answer key from PDF. The file should either be a scannable OMR sheet "
            "or contain clearly printed answers like '1 A, 2 B, 3 C'. Install Tesseract + Poppler."
        )

    # ── Image path (JPEG, PNG, BMP, TIFF) ─────────────────────────────────
    img_arr = _load_image_as_array(file_path)

    if n_questions > 0:
        try:
            key = _detect_bubbles_from_image(img_arr, n_questions, n_options)
            filled_count = len([v for v in key.values() if v is not None])
            if filled_count >= max(3, n_questions // 2):
                logger.info("Extracted %d answers via bubble detection on image.", filled_count)
                return key
            logger.info("Bubble detection yielded only %d answers; trying OCR fallback.", filled_count)
        except Exception as exc:
            logger.warning("Bubble detection failed on image, falling back to OCR: %s", exc)

    # OCR fallback for image-based answer keys
    try:
        import pytesseract
        from PIL import Image as PILImage
        import cv2
        gray = cv2.cvtColor(img_arr, cv2.COLOR_BGR2GRAY)
        pil_img = PILImage.fromarray(gray)
        text = pytesseract.image_to_string(pil_img, config=r'--oem 3 --psm 6')
        key = _parse_text_answer_key(text)
        if key:
            logger.info("Parsed %d answers from image via OCR fallback.", len(key))
            return key
    except ImportError:
        logger.warning("pytesseract unavailable for OCR fallback.")
    except Exception as exc:
        logger.error("OCR on image failed: %s", exc)

    raise ValueError(
        "Could not extract answer key from image. Try a clearer scan or a text-based answer key. "
        "Supported: bubble-filled OMR or text like 'Q1: A, 2 B, 3: C'."
    )


def _extract_text_from_image(img_arr):
    """Improved OCR with grayscale conversion and PSM config optimized for OMR sheets."""
    try:
        import pytesseract
        from PIL import Image as PILImage
        import cv2
        import numpy as np
    except ImportError:
        raise ImportError("pytesseract is required to extract student metadata from the OMR sheet.")

    _configure_tesseract_cmd()

    # Ensure we have a numpy array and convert BGR/color to grayscale for better OCR
    if getattr(img_arr, 'ndim', None) is not None:
        if len(img_arr.shape) == 3:  # color image (BGR from OpenCV)
            gray = cv2.cvtColor(img_arr, cv2.COLOR_BGR2GRAY)
        else:
            gray = img_arr
        # Optional: enhance contrast for OCR
        gray = cv2.convertScaleAbs(gray, alpha=1.5, beta=0)
        pil_img = PILImage.fromarray(gray)
    else:
        pil_img = PILImage.open(img_arr) if isinstance(img_arr, (str, BytesIO)) else img_arr

    try:
        # Use PSM 6 (uniform text block) or 3 (fully automatic) for OMR metadata/printed text
        custom_config = r'--oem 3 --psm 6'
        text = pytesseract.image_to_string(pil_img, config=custom_config)
        logger.debug("OCR extracted text (first 200 chars): %s...", text[:200])
        return text
    except pytesseract.pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError(
            "Tesseract OCR binary not found. Install Tesseract and ensure it is on PATH "
            "or set pytesseract.pytesseract.tesseract_cmd to the executable path. "
            "On Windows, install it at C:\\Program Files\\Tesseract-OCR\\tesseract.exe. "
            "On Linux: apt-get install tesseract-ocr"
        ) from exc
    except Exception as exc:
        logger.error("Tesseract OCR failed: %s", exc)
        # Fallback to default config
        return pytesseract.image_to_string(pil_img)


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
