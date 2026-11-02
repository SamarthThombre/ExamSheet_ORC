"""
tests_v2.test_lookalikes: Unit tests verifying that printed words and headers
are never converted to digits and always return a flagged null across all parsers:
- Question mark cells (parse_question_cell_m7 and legacy parse_question_cell)
- Grand total (parse_grand_total_m7 and fix_total_marks)
- Enrollment number (fix_enrollment_no and legacy_fix_enrollment_no)
- Subject code (parse_subject_code_shape_grammar)
"""

import pytest
from ocr_v2.cell_reader import parse_question_cell_m7, parse_question_cell
from ocr_v2.reader import parse_grand_total_m7, parse_subject_code_shape_grammar
from ocr.postprocessing.cleaning import (
    fix_enrollment_no,
    legacy_fix_enrollment_no,
    fix_total_marks,
)

PRINTED_WORDS_AND_HEADERS = [
    "instructions",
    "on",
    "BTECH EXAMINATION",
    "TOTAL 28 PAGES",
    "SGSITS",
    "Subject Nomenclature",
]


@pytest.mark.parametrize("text", PRINTED_WORDS_AND_HEADERS)
def test_question_cell_parsers_reject_printed_words(text):
    # M7 parser
    val_m7, conf_m7, flags_m7, _ = parse_question_cell_m7(text)
    assert val_m7 is None, f"Expected None for {text!r}, got {val_m7}"
    assert "needs_review" in flags_m7, f"Expected 'needs_review' in flags for {text!r}, got {flags_m7}"

    # Legacy parser
    val_leg, conf_leg, flags_leg = parse_question_cell(text)
    assert val_leg is None, f"Expected None for {text!r}, got {val_leg}"
    assert "needs_review" in flags_leg, f"Expected 'needs_review' in flags for {text!r}, got {flags_leg}"


@pytest.mark.parametrize("text", PRINTED_WORDS_AND_HEADERS)
def test_grand_total_parsers_reject_printed_words(text):
    # M7 parser
    res_m7 = parse_grand_total_m7(text)
    assert res_m7["value"] is None, f"Expected None for {text!r}, got {res_m7['value']}"
    assert "needs_review" in res_m7["flags"], f"Expected 'needs_review' in flags for {text!r}, got {res_m7['flags']}"

    # Cleaning helper
    val_clean = fix_total_marks(text)
    assert val_clean is None, f"Expected None for {text!r}, got {val_clean}"


@pytest.mark.parametrize("text", PRINTED_WORDS_AND_HEADERS)
def test_enrollment_parsers_reject_printed_words(text):
    res_fix = fix_enrollment_no(text)
    assert res_fix is None, f"Expected None for {text!r}, got {res_fix}"

    res_leg = legacy_fix_enrollment_no(text)
    assert res_leg is None, f"Expected None for {text!r}, got {res_leg}"


@pytest.mark.parametrize("text", PRINTED_WORDS_AND_HEADERS)
def test_subject_code_parser_rejects_printed_words(text):
    code, valid = parse_subject_code_shape_grammar(text)
    assert code is None, f"Expected code None for {text!r}, got {code}"
    assert valid is False, f"Expected valid=False for {text!r}, got {valid}"
