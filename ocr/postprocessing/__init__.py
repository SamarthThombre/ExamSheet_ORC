"""
Postprocessing module: Strategy B cleaning, number-in-words parser, and dual-source score fusion.
"""

from ocr.postprocessing.cleaning import (
    fix_enrollment_no,
    fix_total_marks,
    clean_single_subject_code,
    parse_tightened_gt,
    round_half_up,
)
from ocr.postprocessing.word_parser import parse_marks_in_words
from ocr.postprocessing.fusion import (
    combine_grand_total_and_words,
    has_leading_zero_single_digit,
)

__all__ = [
    "fix_enrollment_no",
    "fix_total_marks",
    "clean_single_subject_code",
    "parse_tightened_gt",
    "round_half_up",
    "parse_marks_in_words",
    "combine_grand_total_and_words",
    "has_leading_zero_single_digit",
]
