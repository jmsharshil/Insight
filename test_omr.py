"""
test_omr.py
===========
Standalone test for the OMR engine (exams/omr.py).

Does NOT require Django to be running.
Creates synthetic OMR sheets (answer key + student sheet) using numpy/opencv,
then runs the full detect → grade pipeline and prints a pass/fail summary.
"""

import sys
import os

# ── Make sure the project root is on sys.path ─────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import tempfile
import traceback

try:
    import cv2
    import numpy as np
except ImportError:
    print("FAIL: opencv-python-headless is not installed. Run: pip install opencv-python-headless numpy")
    sys.exit(1)

from exams.omr import _detect_bubbles_from_image, grade_omr, _parse_text_answer_key

# ─────────────────────────────────────────────────────────────────────────────
# Helper: draw a synthetic OMR sheet
# ─────────────────────────────────────────────────────────────────────────────

def make_omr_image(answers: dict, n_questions: int = 10, n_options: int = 4,
                   width: int = 400, height: int = 600) -> np.ndarray:
    """
    Draw a clean OMR grid image.
    answers = {1: 0, 2: 2, ...}  (0-indexed option column to fill)
    Returns a BGR numpy array.
    """
    img = np.ones((height, width, 3), dtype=np.uint8) * 255  # white bg

    row_h = height // (n_questions + 2)
    col_w = width // (n_options + 2)
    radius = min(row_h, col_w) // 3

    for q in range(1, n_questions + 1):
        cy = row_h * q + row_h // 2
        for opt in range(n_options):
            cx = col_w * (opt + 1) + col_w // 2
            # Draw all bubbles as hollow circles
            cv2.circle(img, (cx, cy), radius, (0, 0, 0), 2)

        # Fill the selected bubble
        filled_opt = answers.get(q)
        if filled_opt is not None:
            cx_fill = col_w * (filled_opt + 1) + col_w // 2
            cv2.circle(img, (cx_fill, cy), radius, (0, 0, 0), -1)  # solid black

    return img


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — bubble detection on a clean synthetic image
# ─────────────────────────────────────────────────────────────────────────────

def test_bubble_detection():
    print("\n── Test 1: Bubble detection on synthetic OMR image ──")
    N = 10
    OPTS = 4
    # Known answers: q1→A(0), q2→B(1), q3→C(2), q4→D(3), q5→A(0), ...
    ground_truth_col = {1: 0, 2: 1, 3: 2, 4: 3, 5: 0, 6: 1, 7: 2, 8: 3, 9: 0, 10: 1}
    OPTION_LABELS = ['A', 'B', 'C', 'D']
    expected = {q: OPTION_LABELS[c] for q, c in ground_truth_col.items()}

    img = make_omr_image(ground_truth_col, n_questions=N, n_options=OPTS)

    detected = _detect_bubbles_from_image(img, n_questions=N, n_options=OPTS)

    correct = sum(1 for q in range(1, N + 1) if detected.get(q) == expected.get(q))
    print(f"  Expected : {expected}")
    print(f"  Detected : {detected}")
    print(f"  Accuracy : {correct}/{N} ({correct/N*100:.0f}%)")

    if correct >= N * 0.8:
        print("  PASS ✓")
        return True
    else:
        print("  FAIL ✗ — detection accuracy below 80%")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — text answer key parsing
# ─────────────────────────────────────────────────────────────────────────────

def test_text_key_parsing():
    print("\n── Test 2: Text answer key parsing ──")
    sample_texts = [
        "1. A  2. B  3. C  4. D  5. A",
        "Q1: B\nQ2: C\nQ3: A\nQ4: D",
        "1-A 2-B 3-C 4-D 5-A",
        "1) A\n2) B\n3) C\n4) D",
    ]
    all_pass = True
    for text in sample_texts:
        parsed = _parse_text_answer_key(text)
        ok = len(parsed) >= 4 and all(v in 'ABCDE' for v in parsed.values())
        status = "PASS ✓" if ok else "FAIL ✗"
        print(f"  {status}  Input: {repr(text[:40])} → {parsed}")
        if not ok:
            all_pass = False
    return all_pass


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — full grade_omr pipeline
# ─────────────────────────────────────────────────────────────────────────────

def test_grading():
    print("\n── Test 3: grade_omr function ──")
    answer_key = {1: 'A', 2: 'B', 3: 'C', 4: 'D', 5: 'A'}
    student_answers = {
        1: 'A',    # correct
        2: 'C',    # wrong
        3: 'C',    # correct
        4: None,   # unanswered
        5: 'B',    # wrong
    }

    score, breakdown = grade_omr(
        student_answers=student_answers,
        answer_key=answer_key,
        marks_per_question=2.0,
        negative_per_question=0.5,
    )

    expected_score = 2.0 + 0 - 0.5 + 2.0 + 0 - 0.5  # q1 correct, q2 wrong, q3 correct, q4 unans, q5 wrong
    # = 2 - 0.5 + 2 - 0.5 = 3.0
    print(f"  Score    : {score} (expected {expected_score})")
    print(f"  Breakdown: {breakdown}")

    ok = abs(score - expected_score) < 0.01
    print("  PASS ✓" if ok else "  FAIL ✗")
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — end-to-end: write OMR image to temp file, extract key, grade
# ─────────────────────────────────────────────────────────────────────────────

def test_end_to_end():
    from exams.omr import extract_answer_key_from_file, detect_student_answers, grade_omr

    print("\n── Test 4: End-to-end (temp file → extract key → detect student → grade) ──")
    N = 10
    OPTS = 4

    key_cols   = {1: 0, 2: 1, 3: 2, 4: 3, 5: 0, 6: 1, 7: 2, 8: 3, 9: 0, 10: 1}
    stud_cols  = {1: 0, 2: 1, 3: 3, 4: 3, 5: 0, 6: 0, 7: 2, 8: 3, 9: 1, 10: 1}
    # q1✓ q2✓ q3✗ q4✓ q5✓ q6✗ q7✓ q8✓ q9✗ q10✓  → 7 correct, 3 wrong

    key_img   = make_omr_image(key_cols,  n_questions=N, n_options=OPTS)
    stud_img  = make_omr_image(stud_cols, n_questions=N, n_options=OPTS)

    try:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as kf:
            cv2.imwrite(kf.name, key_img)
            key_path = kf.name
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as sf:
            cv2.imwrite(sf.name, stud_img)
            stud_path = sf.name

        key_dict  = extract_answer_key_from_file(key_path, n_questions=N, n_options=OPTS)
        stud_dict = detect_student_answers(stud_path, n_questions=N, n_options=OPTS)
        score, breakdown = grade_omr(stud_dict, key_dict, marks_per_question=1.0)

        print(f"  Answer key detected : {key_dict}")
        print(f"  Student answers     : {stud_dict}")
        print(f"  Score               : {score}/{N}")
        correct_count = sum(1 for b in breakdown if b['result'] == 'correct')
        wrong_count   = sum(1 for b in breakdown if b['result'] == 'wrong')
        print(f"  Correct: {correct_count}  Wrong: {wrong_count}")

        ok = score >= 5  # At least 50% expected on synthetic data
        print("  PASS ✓" if ok else "  FAIL ✗ — score too low on synthetic data")
        return ok
    except Exception as e:
        print(f"  FAIL ✗ — exception: {e}")
        traceback.print_exc()
        return False
    finally:
        for p in [key_path, stud_path]:
            try:
                os.unlink(p)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Run all tests
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    results = {
        "Bubble detection"  : test_bubble_detection(),
        "Text key parsing"  : test_text_key_parsing(),
        "Grading logic"     : test_grading(),
        "End-to-end"        : test_end_to_end(),
    }

    print("\n" + "═" * 50)
    print("RESULTS SUMMARY")
    print("═" * 50)
    all_ok = True
    for name, passed in results.items():
        icon = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {icon}  {name}")
        if not passed:
            all_ok = False

    print("═" * 50)
    if all_ok:
        print("All tests passed! OMR engine is working correctly.")
        sys.exit(0)
    else:
        print("Some tests failed. Check output above.")
        sys.exit(1)
