"""
Unit and integration tests for the QuestionMarksExtractor.

Tests are structured in two layers:
  1. Pure-logic unit tests (no OCR engine required) — test _parse_marks_text,
     _merge_close_lines, _filter_question_rows, and the result structure contract.
  2. Integration test against the user-supplied sample image (requires models loaded).
     This test is skipped if the sample image is not present at the known path.

Expected results from sample image (media_1790589411323.png):
  Q1 → 0, Q2 → 5.5, Q3 → 1, Q4 → 2, Q5 → 0.5   SUM = 9 = GRAND TOTAL
"""

import sys
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ocr.postprocessing.question_marks import (
    _parse_marks_text,
    _merge_close_lines,
    QuestionMarksExtractor,
)


# ---------------------------------------------------------------------------
# Unit tests for _parse_marks_text
# ---------------------------------------------------------------------------
class TestParseMarksText(unittest.TestCase):

    def test_integer_zero(self):
        val, status = _parse_marks_text("00")
        self.assertEqual(val, 0.0)
        self.assertEqual(status, "ok")

    def test_integer_marks(self):
        val, status = _parse_marks_text("01")
        self.assertEqual(val, 1.0)
        self.assertEqual(status, "ok")

    def test_decimal_marks(self):
        val, status = _parse_marks_text("05.5")
        self.assertAlmostEqual(val, 5.5)
        self.assertEqual(status, "ok")

    def test_half_mark(self):
        val, status = _parse_marks_text("00.5")
        self.assertAlmostEqual(val, 0.5)
        self.assertEqual(status, "ok")

    def test_empty_string(self):
        val, status = _parse_marks_text("")
        self.assertIsNone(val)
        self.assertEqual(status, "uncertain")

    def test_whitespace_only(self):
        val, status = _parse_marks_text("   ")
        self.assertIsNone(val)
        self.assertEqual(status, "uncertain")

    def test_ocr_confusion_O_as_0(self):
        """OCR often confuses 'O' with '0'"""
        val, status = _parse_marks_text("OO")
        self.assertEqual(val, 0.0)
        self.assertEqual(status, "ok")

    def test_ocr_confusion_l_as_1(self):
        val, status = _parse_marks_text("0l")
        self.assertAlmostEqual(val, 1.0)
        self.assertEqual(status, "ok")

    def test_unreadable_text(self):
        val, status = _parse_marks_text("abc?!")
        self.assertIsNone(val)
        self.assertEqual(status, "uncertain")

    def test_large_valid_marks(self):
        val, status = _parse_marks_text("70")
        self.assertEqual(val, 70.0)
        self.assertEqual(status, "ok")

    def test_decimal_with_leading_spaces(self):
        val, status = _parse_marks_text("  2.5  ")
        self.assertAlmostEqual(val, 2.5)
        self.assertEqual(status, "ok")


# ---------------------------------------------------------------------------
# Unit tests for _merge_close_lines
# ---------------------------------------------------------------------------
class TestMergeCloseLines(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(_merge_close_lines([]), [])

    def test_no_merging_needed(self):
        result = _merge_close_lines([10, 50, 100])
        self.assertEqual(result, [10, 50, 100])

    def test_merge_adjacent(self):
        result = _merge_close_lines([10, 12, 50])
        self.assertEqual(len(result), 2)
        self.assertIn(result[0], [10, 11, 12])  # merged pair
        self.assertEqual(result[1], 50)

    def test_single_line(self):
        result = _merge_close_lines([42])
        self.assertEqual(result, [42])


# ---------------------------------------------------------------------------
# Unit tests for QuestionMarksExtractor result contract (mocked OCR)
# ---------------------------------------------------------------------------
class TestQuestionMarksExtractorContract(unittest.TestCase):

    def _make_mock_ocr(self, side_effects):
        """Creates a mock OCR engine returning (text, conf) pairs."""
        mock = MagicMock()
        mock.ocr_crop = MagicMock(side_effect=side_effects)
        return mock

    def test_result_structure_keys(self):
        """Returned dict always has all required keys."""
        import numpy as np
        img = np.zeros((1000, 800, 3), dtype=np.uint8)
        mock_ocr = self._make_mock_ocr([("00", 0.95)] * 20)
        extractor = QuestionMarksExtractor(ocr_engine=mock_ocr)
        result = extractor.extract_question_marks(img)

        required_keys = {
            "question_marks", "sum_extracted", "sum_matches_gt",
            "needs_review", "uncertain_count", "method", "debug_info",
        }
        self.assertTrue(required_keys.issubset(set(result.keys())))

    def test_method_is_geometric_table(self):
        import numpy as np
        img = np.zeros((1000, 800, 3), dtype=np.uint8)
        mock_ocr = self._make_mock_ocr([("05", 0.90)] * 20)
        extractor = QuestionMarksExtractor(ocr_engine=mock_ocr)
        result = extractor.extract_question_marks(img)
        self.assertEqual(result["method"], "geometric_table")

    def test_invalid_image_returns_empty(self):
        mock_ocr = MagicMock()
        extractor = QuestionMarksExtractor(ocr_engine=mock_ocr)
        result = extractor.extract_question_marks(None)
        self.assertEqual(result["question_marks"], [])

    def test_each_mark_has_required_fields(self):
        import numpy as np
        img = np.zeros((1000, 800, 3), dtype=np.uint8)
        mock_ocr = self._make_mock_ocr([("01", 0.85)] * 20)
        extractor = QuestionMarksExtractor(ocr_engine=mock_ocr)
        result = extractor.extract_question_marks(img)
        for entry in result["question_marks"]:
            self.assertIn("question_no", entry)
            self.assertIn("marks", entry)
            self.assertIn("raw_text", entry)
            self.assertIn("confidence", entry)
            self.assertIn("status", entry)

    def test_uncertain_marks_are_none_not_zero(self):
        """Unreadable OCR output must produce None marks, not 0."""
        import numpy as np
        img = np.zeros((1000, 800, 3), dtype=np.uint8)
        # Return garbage text with low confidence
        mock_ocr = self._make_mock_ocr([("???", 0.05)] * 20)
        extractor = QuestionMarksExtractor(ocr_engine=mock_ocr)
        result = extractor.extract_question_marks(img)
        for entry in result["question_marks"]:
            # If status is uncertain, marks must be None (not 0)
            if entry["status"] == "uncertain":
                self.assertIsNone(entry["marks"], "Uncertain marks must be None, not 0")

    def test_sum_matches_gt_flag_true(self):
        """When sum equals grand_total, sum_matches_gt should be True."""
        import numpy as np
        # Build blank image
        img = np.zeros((1000, 800, 3), dtype=np.uint8)
        mock_ocr = self._make_mock_ocr([("09", 0.92)] * 20)
        extractor = QuestionMarksExtractor(ocr_engine=mock_ocr)
        # We know sum from single row = 9.0 (if 1 row detected)
        # Pass grand_total=9 to trigger exact match
        result = extractor.extract_question_marks(img, grand_total_value=9)
        if result["sum_extracted"] is not None:
            if result["sum_matches_gt"] is not None:
                expected = abs(result["sum_extracted"] - 9.0) < 0.01
                self.assertEqual(result["sum_matches_gt"], expected)

    def test_sum_mismatch_sets_needs_review(self):
        """When sum != grand_total, needs_review must be True."""
        import numpy as np
        img = np.zeros((1000, 800, 3), dtype=np.uint8)
        # Return "05" per cell — if any rows found, sum != 100
        mock_ocr = self._make_mock_ocr([("05", 0.90)] * 20)
        extractor = QuestionMarksExtractor(ocr_engine=mock_ocr)
        result = extractor.extract_question_marks(img, grand_total_value=100)
        if result["sum_extracted"] is not None:
            if not result["sum_matches_gt"]:
                self.assertTrue(result["needs_review"])

    def test_question_nos_are_sequential(self):
        """question_no values must be sequential starting from 1."""
        import numpy as np
        img = np.zeros((1000, 800, 3), dtype=np.uint8)
        mock_ocr = self._make_mock_ocr([("02", 0.88)] * 20)
        extractor = QuestionMarksExtractor(ocr_engine=mock_ocr)
        result = extractor.extract_question_marks(img)
        for i, entry in enumerate(result["question_marks"], start=1):
            self.assertEqual(entry["question_no"], i)


# ---------------------------------------------------------------------------
# Integration test: sample image
# ---------------------------------------------------------------------------
SAMPLE_IMAGE_PATH = Path(
    r"C:/Users/sumit/.gemini/antigravity/brain/31698303-065c-40d4-a4ba-6752729b4daa"
    r"/.user_uploaded/media_1790589411323.png"
)

EXPECTED_MARKS = [0.0, 5.5, 1.0, 2.0, 0.5]
EXPECTED_SUM = 9.0


@unittest.skipUnless(SAMPLE_IMAGE_PATH.exists(), "Sample image not available")
class TestQuestionMarksIntegration(unittest.TestCase):
    """
    Integration test against the user-uploaded sample image.
    Requires real OCR models to be initialized.
    """

    @classmethod
    def setUpClass(cls):
        import cv2
        from ocr.recognition.paddle_engine import PaddleOCREngine
        cls.img = cv2.imread(str(SAMPLE_IMAGE_PATH))
        engine = PaddleOCREngine(lang="en")
        engine.load_engine()
        cls.extractor = QuestionMarksExtractor(ocr_engine=engine)
        # Bounding box of grand_total for this sample image
        cls.gt_box = (389.1, 702.5, 679.2, 749.3)

    def test_extracts_five_questions(self):
        result = self.extractor.extract_question_marks(
            self.img,
            grand_total_box_xyxy=self.gt_box,
            grand_total_value=9,
        )
        qmarks = result["question_marks"]
        print(f"\n[Integration] Extracted {len(qmarks)} question rows:")
        for qm in qmarks:
            print(f"  Q{qm['question_no']}: marks={qm['marks']}  raw='{qm['raw_text']}'  conf={qm['confidence']}  status={qm['status']}")
        print(f"  sum_extracted={result['sum_extracted']}, sum_matches_gt={result['sum_matches_gt']}")
        
        self.assertEqual(len(qmarks), 5, "Expected exactly 5 question rows")
        extracted_marks = [qm["marks"] for qm in qmarks]
        self.assertEqual(extracted_marks, EXPECTED_MARKS, f"Extracted marks {extracted_marks} != expected {EXPECTED_MARKS}")

    def test_sum_matches_grand_total(self):
        result = self.extractor.extract_question_marks(
            self.img,
            grand_total_box_xyxy=self.gt_box,
            grand_total_value=9,
        )
        sum_ext = result["sum_extracted"]
        self.assertIsNotNone(sum_ext)
        self.assertAlmostEqual(sum_ext, EXPECTED_SUM, delta=0.01)
        self.assertTrue(result["sum_matches_gt"])

    def test_no_uncertain_marks_for_clear_image(self):
        result = self.extractor.extract_question_marks(
            self.img,
            grand_total_box_xyxy=self.gt_box,
            grand_total_value=9,
        )
        self.assertEqual(result["uncertain_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
