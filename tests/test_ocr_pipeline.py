"""
Unit and integration tests for OCR pipeline detection fallbacks and image cropper.
"""

import unittest
import numpy as np

from ocr.detection.fallbacks import get_enrolment_no_crop
from ocr.recognition.cropper import FieldCropper
from ocr.recognition.divider import detect_red_divider_x


class TestDetectionFallbacks(unittest.TestCase):
    def test_enrolment_fallback_dimensions(self):
        # Given a 1000x2000 image with no YOLO detection provided -> fallback engaged
        img = np.zeros((1000, 2000, 3), dtype=np.uint8)
        crop, used_fallback = get_enrolment_no_crop(img, enrolment_box_xyxy=None)

        self.assertTrue(used_fallback)
        # Expected: x1 = 0.520*2000 = 1040, x2 = 0.985*2000 = 1970 (width = 930)
        # Expected: y1 = 0.260*1000 = 260, y2 = 0.360*1000 = 360 (height = 100)
        self.assertEqual(crop.shape[0], 100)
        self.assertEqual(crop.shape[1], 930)
        self.assertEqual(crop.shape[2], 3)


class TestCropperAndDivider(unittest.TestCase):
    def test_cropper_clamping(self):
        img = np.zeros((500, 500, 3), dtype=np.uint8)

        # Box extending beyond boundaries
        box = (-50, -50, 600, 600)
        crop = FieldCropper.crop_padded_box(img, box, padding_ratio=0.0)
        self.assertEqual(crop.shape[:2], (500, 500))

    def test_red_divider_detection_synthetic(self):
        # Create image with a vertical red line in the search window (20% to 42% of 400px = 80px to 168px)
        synthetic = np.full((100, 400, 3), 255, dtype=np.uint8)
        # BGR red: (0, 0, 255)
        synthetic[:, 120:124] = [0, 0, 255]
        cut_x, ratio = detect_red_divider_x(synthetic)
        self.assertTrue(120 <= cut_x <= 135)
        self.assertAlmostEqual(ratio, 120 / 400.0, delta=0.03)


if __name__ == "__main__":
    unittest.main()
