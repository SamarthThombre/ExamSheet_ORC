"""
Unit tests for ocr_v2.reader.
"""

import pytest
import numpy as np
from unittest.mock import MagicMock
from ocr_v2.reader import BatchedONNXReader, FieldRecognitionResult, PageRecognitionResult, levenshtein_distance


def test_levenshtein_distance():
    assert levenshtein_distance("CT10718", "CT10718") == 0
    assert levenshtein_distance("CT10718", "CT10715") == 1
    assert levenshtein_distance("CTIO18", "CT10718") == 3
    assert levenshtein_distance("CT1078", "CT10718") == 1


def test_reader_validation_flags():
    # Test validation logic by mocking ONNX predict output
    reader = BatchedONNXReader.__new__(BatchedONNXReader)
    mock_model = MagicMock()
    # Mock return: enrolment reads '0801CA251042', subject reads 'Subject Code CT10718'
    mock_model.predict.return_value = [
        {"rec_text": "0801CA251042", "rec_score": 0.98},
        {"rec_text": "Subject Code CT10718", "rec_score": 0.95},
    ]
    reader.model = mock_model

    cfg = {
        "fields": {
            "enrollment_no": {
                "expected_prefix": "0801CA25",
                "roll_range": [1000, 1157],
            },
            "subject_code": {
                "known_codes": ["CT10718", "CT10715"],
            },
        }
    }

    dummy_crop_e = np.zeros((60, 600, 3), dtype=np.uint8)
    dummy_crop_s = np.zeros((100, 500, 3), dtype=np.uint8)

    # Mock prepare methods to return dummy arrays directly
    reader.prepare_enrolment_strip = MagicMock(return_value=(dummy_crop_e, 1.0))
    reader.prepare_subject_strip = MagicMock(return_value=dummy_crop_s)

    page_res = reader.read_fields(
        enrol_crop=dummy_crop_e,
        subj_crop=dummy_crop_s,
        format_id="format_original",
        format_config=cfg,
    )

    assert not page_res.needs_review
    assert "enrollment_no" in page_res.fields
    assert "subject_code" in page_res.fields

    e_res = page_res.fields["enrollment_no"]
    assert e_res.parsed_value == "0801CA251042"
    assert e_res.validation_flags["prefix_valid"]
    assert e_res.validation_flags["roll_range_valid"]
    assert e_res.validation_flags["length_valid"]
    assert not e_res.needs_review

    s_res = page_res.fields["subject_code"]
    assert s_res.metadata["matched_code"] == "CT10718"
    assert s_res.metadata["edit_distance"] == 0
    assert not s_res.needs_review


def test_reader_optional_and_out_of_range_roll():
    reader = BatchedONNXReader.__new__(BatchedONNXReader)
    mock_model = MagicMock()
    mock_model.predict.return_value = [
        {"rec_text": "0801CA259999", "rec_score": 0.98},
    ]
    reader.model = mock_model
    dummy_crop_e = np.zeros((60, 600, 3), dtype=np.uint8)
    reader.prepare_enrolment_strip = MagicMock(return_value=(dummy_crop_e, 1.0))

    # Case 1: Config with roll_range [1000, 1157], 9999 is out of range
    cfg_with_range = {
        "fields": {
            "enrollment_no": {
                "expected_prefix": "0801CA25",
                "roll_range": [1000, 1157],
            }
        }
    }
    res1 = reader.read_fields(dummy_crop_e, None, "format_original", cfg_with_range)
    e1 = res1.fields["enrollment_no"]
    assert not e1.validation_flags["roll_range_valid"]
    assert "ROLL_OUT_OF_RANGE" in e1.review_reasons
    assert e1.needs_review
    # Value must NEVER be overwritten
    assert e1.parsed_value == "0801CA259999"

    # Case 2: Config WITHOUT roll_range (optional)
    cfg_without_range = {
        "fields": {
            "enrollment_no": {
                "expected_prefix": "0801CA25",
            }
        }
    }
    res2 = reader.read_fields(dummy_crop_e, None, "format_original", cfg_without_range)
    e2 = res2.fields["enrollment_no"]
    assert e2.validation_flags["roll_range_valid"]
    assert "ROLL_OUT_OF_RANGE" not in e2.review_reasons

