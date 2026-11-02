"""
Unit tests for OCR postprocessing cleaners, word parser, score fusion, and sanity validator.
These fast-running unit tests execute in milliseconds without requiring ML model loading.
"""

import unittest
from ocr.postprocessing.cleaning import fix_enrollment_no, fix_total_marks, clean_single_subject_code
from ocr.postprocessing.word_parser import parse_marks_in_words
from ocr.postprocessing.fusion import combine_grand_total_and_words
from ocr.validation.sanity import SanityValidator


class TestEnrollmentCleaner(unittest.TestCase):
    def test_standard_forward_enrollment(self):
        self.assertEqual(fix_enrollment_no("0801CA251001"), "0801CA251001")
        self.assertEqual(fix_enrollment_no("Enrolment No. 0801CA251015"), "0801CA251015")

    def test_symbol_and_digit_lookalikes(self):
        # '(' for 'C', 'S' for '5', 'l' for '1'
        self.assertEqual(fix_enrollment_no("0801(A2S1001"), "0801CA251001")
        self.assertEqual(fix_enrollment_no("0801CA25l00l"), "0801CA251001")

    def test_upside_down_inverted_read(self):
        # Inverted OCR read ending with reversed 080 anchor
        inverted_ocr = "1001S2AC1080"
        res = fix_enrollment_no(inverted_ocr)
        self.assertIsNotNone(res)
        self.assertTrue(res.startswith("0801CA25"))

    def test_empty_and_garbage_inputs(self):
        self.assertIsNone(fix_enrollment_no(None))
        self.assertIsNone(fix_enrollment_no(""))
        self.assertIsNone(fix_enrollment_no("   "))


class TestTotalMarksCleaner(unittest.TestCase):
    def test_pure_digits(self):
        self.assertEqual(fix_total_marks("54"), 54)
        self.assertEqual(fix_total_marks("12"), 12)

    def test_equation_with_rounding(self):
        # 53=54 -> 54
        self.assertEqual(fix_total_marks("53=54 GRAND TOTAL"), 54)
        self.assertEqual(fix_total_marks("23.5=24"), 24)

    def test_empty_and_corrupt_inputs(self):
        self.assertIsNone(fix_total_marks(None))
        self.assertIsNone(fix_total_marks(""))
        self.assertIsNone(fix_total_marks("GRAND TOTAL"))


class TestMarksInWordsParser(unittest.TestCase):
    def test_standard_two_digit_words(self):
        res = parse_marks_in_words("fifty four")
        self.assertEqual(res["value"], 54)
        self.assertGreaterEqual(res["conf"], 0.8)

    def test_hyphenated_and_noise_surrounded(self):
        res = parse_marks_in_words("ds fifty four One")
        self.assertEqual(res["value"], 54)

    def test_teens_and_single_digits(self):
        self.assertEqual(parse_marks_in_words("twelve")["value"], 12)
        self.assertEqual(parse_marks_in_words("six")["value"], 6)
        self.assertEqual(parse_marks_in_words("forty")["value"], 40)

    def test_unrecognized_text(self):
        res = parse_marks_in_words("random non numeric gibberish")
        self.assertIsNone(res["value"])
        self.assertEqual(res["conf"], 0.0)


class TestDualSourceFusion(unittest.TestCase):
    def test_agree_exact(self):
        res = combine_grand_total_and_words("54", "54", "fifty four")
        self.assertEqual(res["final"], 54)
        self.assertIn(res["status"], ["AGREE_EXACT", "AGREE_ORIG_AND_TIGHT_GT"])
        self.assertFalse(res["needs_review"])

    def test_recovery_by_tight_crop(self):
        # Orig GT corrupted by box border, tightened GT clean
        res = combine_grand_total_and_words("3=GRAND", "46", "forty six")
        self.assertEqual(res["final"], 46)
        self.assertFalse(res["needs_review"])

    def test_recovery_by_words(self):
        # Numeric box completely unreadable
        res = combine_grand_total_and_words("", "", "thirty eight")
        self.assertEqual(res["final"], 38)

    def test_dangling_equation_conflict_flags_review(self):
        # Orig has dangling '=GRAND' with conflict against words -> page 000089 scenario
        res = combine_grand_total_and_words("23.5=24 =GRAND", "24", "thirty eight")
        self.assertTrue(res["needs_review"])


class TestSanityValidator(unittest.TestCase):
    def test_valid_payload(self):
        needs_review, reasons = SanityValidator.validate_fields(
            enrollment_no="0801CA251001",
            subject_code="CT10718",
            total_marks_corrected=54,
            fusion_needs_review=False,
        )
        self.assertFalse(needs_review)
        self.assertEqual(len(reasons), 0)

    def test_missing_rollno_flags_review(self):
        needs_review, reasons = SanityValidator.validate_fields(
            enrollment_no=None,
            subject_code="CT10718",
            total_marks_corrected=54,
            fusion_needs_review=False,
        )
        self.assertTrue(needs_review)
        self.assertTrue(any("enrolment" in r.lower() for r in reasons))

    def test_out_of_range_marks_flags_review(self):
        needs_review, reasons = SanityValidator.validate_fields(
            enrollment_no="0801CA251001",
            subject_code="CT10718",
            total_marks_corrected=95,  # Max allowable is 70
            fusion_needs_review=False,
        )
        self.assertTrue(needs_review)
        self.assertTrue(any("total_marks" in r.lower() for r in reasons))


if __name__ == "__main__":
    unittest.main()
