"""
tests_v2.test_review: Unit tests for ocr_v2.review and batch review layer.
Tests duplicate detection, roster validation, missing from batch,
and rescan_recommended vs needs_review classification.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from ocr_v2.review import BatchReviewManager, classify_flags, BatchReviewResult


def test_classify_flags_rescan():
    """Verify that physical scan failures trigger rescan_recommended."""
    # Comb touches edge
    rescan, review, reasons = classify_flags(["COMB_TOUCHES_PAGE_EDGE"])
    assert rescan is True
    assert review is True
    assert "COMB_TOUCHES_PAGE_EDGE" in reasons

    # Comb detection failed
    rescan, review, reasons = classify_flags(["COMB_DETECTION_FAILED"])
    assert rescan is True
    assert review is True

    # Extreme skew > 15 deg
    rescan, review, reasons = classify_flags(["EXCESSIVE_SKEW_18.2_DEG"])
    assert rescan is True
    assert review is True


def test_classify_flags_advisory():
    """Verify that advisory review flags trigger needs_review but NOT rescan_recommended."""
    # Low comb quality
    rescan, review, reasons = classify_flags(["LOW_COMB_QUALITY_0.42"])
    assert rescan is False
    assert review is True

    # Comb not fully detected
    rescan, review, reasons = classify_flags(["COMB_NOT_FULLY_DETECTED"])
    assert rescan is False
    assert review is True

    # Moderate skew (e.g. 5.1 deg)
    rescan, review, reasons = classify_flags(["EXCESSIVE_SKEW_5.1_DEG"])
    assert rescan is False
    assert review is True

    # Low confidence
    rescan, review, reasons = classify_flags(["LOW_CONFIDENCE_0.78"])
    assert rescan is False
    assert review is True

    # Business validation flags
    rescan, review, reasons = classify_flags(["INVALID_PREFIX", "ROLL_OUT_OF_RANGE"])
    assert rescan is False
    assert review is True


def test_classify_flags_clean():
    """Verify that clean scans have both flags False."""
    rescan, review, reasons = classify_flags([])
    assert rescan is False
    assert review is False
    assert reasons == []


def test_batch_duplicate_enrolment():
    """Verify duplicate enrolments flag all participating sheets."""
    mgr = BatchReviewManager()
    sheets = [
        {"filename": "s1.jpg", "pred_enrol": "0801CA251001", "review_reasons": []},
        {"filename": "s2.jpg", "pred_enrol": "0801CA251002", "review_reasons": []},
        {"filename": "s3.jpg", "pred_enrol": "0801CA251001", "review_reasons": []},
    ]

    res = mgr.evaluate_batch(sheets)
    assert res.total_sheets == 3
    assert res.flagged_sheets == 2
    assert "0801CA251001" in res.duplicate_enrolments
    assert len(res.duplicate_enrolments["0801CA251001"]) == 2

    # Both s1 and s3 must carry DUPLICATE_ENROLMENT
    assert "DUPLICATE_ENROLMENT" in res.sheets[0]["review_reasons"]
    assert res.sheets[0]["needs_review"] is True
    assert res.sheets[0]["rescan_recommended"] is False

    assert "DUPLICATE_ENROLMENT" in res.sheets[2]["review_reasons"]
    assert res.sheets[2]["needs_review"] is True

    # s2 must not be flagged
    assert "DUPLICATE_ENROLMENT" not in res.sheets[1]["review_reasons"]
    assert res.sheets[1]["needs_review"] is False


def test_batch_roster_and_missing():
    """Verify optional roster validation and missing_from_batch reporting."""
    mgr = BatchReviewManager()
    sheets = [
        {"filename": "s1.jpg", "pred_enrol": "0801CA251001", "review_reasons": []},
        {"filename": "s2.jpg", "pred_enrol": "0801CA251999", "review_reasons": []},  # not in roster
    ]
    roster = ["0801CA251001", "0801CA251002", "0801CA251003"]

    res = mgr.evaluate_batch(sheets, roster=roster)
    assert res.roster_provided is True
    # s2 not in roster
    assert "READ_NOT_IN_ROSTER" in res.sheets[1]["review_reasons"]
    assert res.sheets[1]["needs_review"] is True

    # Missing from batch: 1002 and 1003
    assert res.missing_from_batch == ["0801CA251002", "0801CA251003"]


def test_batch_without_roster_only_duplicates():
    """Without roster, only duplicates are evaluated."""
    mgr = BatchReviewManager()
    sheets = [
        {"filename": "s1.jpg", "pred_enrol": "0801CA251999", "review_reasons": []},
    ]
    res = mgr.evaluate_batch(sheets, roster=None)
    assert res.roster_provided is False
    assert res.missing_from_batch == []
    assert "READ_NOT_IN_ROSTER" not in res.sheets[0]["review_reasons"]
    assert res.flagged_sheets == 0
