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
  pytesseract   (optional — used as fallback for text-based answer keys)
  Pillow
"""

import re
import logging
import os
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)

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
        logger.warning("pdf2image not installed — cannot render PDF pages. Install pdf2image + poppler.")
        return None
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
