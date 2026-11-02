"""
Unit tests for ocr_v2.formats.
"""

import pytest
import numpy as np
import cv2
from ocr_v2.formats import FormatDetector, FormatIdentificationResult


def test_format_detector_rejects_blank():
    detector = FormatDetector()
    blank = np.full((1200, 850, 3), 255, dtype=np.uint8)
    res = detector.identify(blank)
    assert res.format_id == "UNKNOWN"
    assert res.needs_review
    assert "BLANK_OR_UNIFORM_IMAGE" in res.reasons


def test_format_detector_rejects_invalid_aspect():
    detector = FormatDetector()
    # Aspect ratio = 1400 / 900 = 1.55 (landscape)
    landscape = np.full((900, 1400, 3), 200, dtype=np.uint8)
    landscape[100:200, 100:500] = 50
    res = detector.identify(landscape)
    assert res.format_id == "UNKNOWN"
    assert res.needs_review
    assert any("INVALID_ASPECT_RATIO" in r for r in res.reasons)


def test_format_detector_format_original_synthetic():
    detector = FormatDetector()
    # Format A aspect ~ 0.707 (height 1414, width 1000), bright white background (> 200)
    img = np.full((1414, 1000, 3), 235, dtype=np.uint8)

    # Red comb lines in Format A window: [0.25*1414:0.38*1414, 0.50*1000:0.99*1000]
    cx, cy, bw, bh = 750, 440, 420, 50
    x1, y1 = int(cx - bw/2), int(cy - bh/2)
    x2, y2 = int(cx + bw/2), int(cy + bh/2)
    cv2.rectangle(img, (x1, y1), (x2, y2), (20, 20, 220), 3)
    cell_w = bw / 12.0
    for i in range(1, 12):
        cv2.line(img, (int(x1 + i * cell_w), y1), (int(x1 + i * cell_w), y2), (20, 20, 220), 2)

    res = detector.identify(img)
    assert res.format_id == "format_original"
    assert not res.needs_review
    assert res.confidence >= 0.65


def test_format_detector_format_v2_synthetic():
    detector = FormatDetector()
    # Format B aspect ~ 0.750 (height 1333, width 1000), gray/tinted background (< 175)
    img = np.full((1333, 1000, 3), 150, dtype=np.uint8)

    # Orange comb lines in Format B window: [0.24*1333:0.42*1333, 0.53*1000:0.99*1000]
    cx, cy, bw, bh = 770, 440, 420, 50
    x1, y1 = int(cx - bw/2), int(cy - bh/2)
    x2, y2 = int(cx + bw/2), int(cy + bh/2)
    # Orange color in BGR: B=50, G=120, R=210
    cv2.rectangle(img, (x1, y1), (x2, y2), (50, 120, 210), 3)
    cell_w = bw / 12.0
    for i in range(1, 12):
        cv2.line(img, (int(x1 + i * cell_w), y1), (int(x1 + i * cell_w), y2), (50, 120, 210), 2)

    res = detector.identify(img)
    assert res.format_id == "format_v2"
    assert not res.needs_review
    assert res.confidence >= 0.65
