from .omr import (
    extract_answer_key_from_file,
    detect_student_answers,
    parse_student_identity_from_sheet,
    grade_omr,
)
from .omr_azure import (
    extract_answer_key_from_file_azure,
    detect_student_answers_azure,
    parse_student_identity_from_sheet_azure,
)

__all__ = [
    "extract_answer_key_from_file",
    "detect_student_answers",
    "parse_student_identity_from_sheet",
    "grade_omr",
    "extract_answer_key_from_file_azure",
    "detect_student_answers_azure",
    "parse_student_identity_from_sheet_azure",
]

