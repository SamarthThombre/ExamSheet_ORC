"""
Unit tests for ocr_v2.normalise.
"""

import pytest
import numpy as np
import cv2
from pathlib import Path
from ocr_v2.normalise import PageNormaliser, AlignmentResult, TransformMatrix


def test_normaliser_resize_to_canonical_width():
    normaliser = PageNormaliser(target_width=1600)
    img = np.zeros((3000, 2000, 3), dtype=np.uint8)
    resized, scale = normaliser.resize_to_canonical_width(img)
    assert resized.shape[1] == 1600
    assert resized.shape[0] == 2400
    assert abs(scale - 0.8) < 1e-4


def test_normaliser_orientation_0_180():
    normaliser = PageNormaliser(target_width=1600)
    # Right-side-up image with heavy ink in top 20%
    img_up = np.full((1000, 700, 3), 255, dtype=np.uint8)
    img_up[:150, 100:600] = 50  # dark header
    corrected, flipped = normaliser.check_orientation_0_180(img_up)
    assert not flipped
    assert np.array_equal(corrected, img_up)

    # Inverted image with heavy ink in bottom 20%
    img_inv = np.full((1000, 700, 3), 255, dtype=np.uint8)
    img_inv[850:, 100:600] = 50
    corrected_inv, flipped_inv = normaliser.check_orientation_0_180(img_inv)
    assert flipped_inv
    # Corrected should now have ink at the top
    assert np.mean(corrected_inv[:150, :]) < 200


def test_normaliser_comb_box_detection_synthetic():
    normaliser = PageNormaliser(target_width=1600)
    img = np.full((2200, 1600, 3), 250, dtype=np.uint8)

    # Draw synthetic red comb box in Format A search window: [0.22*2200 : 0.39*2200, 0.48*1600 : 0.99*1600]
    # y in [600, 700], x in [900, 1500] (aspect ratio = 600 / 100 = 6.0)
    cx, cy, bw, bh = 1200, 650, 600, 80
    x1, y1 = int(cx - bw/2), int(cy - bh/2)
    x2, y2 = int(cx + bw/2), int(cy + bh/2)

    # Red border
    cv2.rectangle(img, (x1, y1), (x2, y2), (20, 20, 220), 4)
    # Vertical cell dividers
    cell_w = bw / 12.0
    for i in range(1, 12):
        lx = int(x1 + i * cell_w)
        cv2.line(img, (lx, y1), (lx, y2), (20, 20, 220), 2)

    rect, quality, status = normaliser.detect_comb_box(img, is_format_b=False)
    assert rect is not None
    assert status == "OK"
    assert quality > 0.50
    detected_cx, detected_cy = rect[0]
    assert abs(detected_cx - cx) < 15
    assert abs(detected_cy - cy) < 15


def test_normaliser_align_page_synthetic():
    normaliser = PageNormaliser(target_width=1600)
    img = np.full((2200, 1600, 3), 250, dtype=np.uint8)

    # Comb box slightly shifted
    cx, cy, bw, bh = 1220, 670, 600, 80
    x1, y1 = int(cx - bw/2), int(cy - bh/2)
    x2, y2 = int(cx + bw/2), int(cy + bh/2)
    cv2.rectangle(img, (x1, y1), (x2, y2), (20, 20, 220), 4)
    cell_w = bw / 12.0
    for i in range(1, 12):
        cv2.line(img, (int(x1 + i * cell_w), y1), (int(x1 + i * cell_w), y2), (20, 20, 220), 2)

    res = normaliser.align_page(img, format_id="format_original")
    assert isinstance(res, AlignmentResult)
    assert res.quality_score > 0.50
    assert not res.needs_review
    assert abs(res.transform.dx) > 0 or abs(res.transform.dy) > 0


def test_normaliser_comb_not_found():
    normaliser = PageNormaliser(target_width=1600)
    # Blank white page
    img = np.full((2200, 1600, 3), 255, dtype=np.uint8)
    res = normaliser.align_page(img, format_id="format_original")
    assert res.needs_review is True
    assert res.comb_box is None
    assert any("COMB_DETECTION_FAILED" in r for r in res.review_reasons)
    assert any("RESCAN_RECOMMENDED" in r for r in res.review_reasons)


def test_normaliser_comb_not_fully_detected():
    normaliser = PageNormaliser(target_width=1600)
    img = np.full((2200, 1600, 3), 255, dtype=np.uint8)
    # Draw a truncated / partial comb (only 8 cells, width = 450px, aspect = 6.0 < 6.5)
    cx, cy, bw, bh = 1200, 650, 450, 75
    x1, y1 = int(cx - bw/2), int(cy - bh/2)
    x2, y2 = int(cx + bw/2), int(cy + bh/2)
    cv2.rectangle(img, (x1, y1), (x2, y2), (20, 20, 220), 4)
    for i in range(1, 8):
        lx = int(x1 + i * (bw / 8.0))
        cv2.line(img, (lx, y1), (lx, y2), (20, 20, 220), 2)

    res = normaliser.align_page(img, format_id="format_original")
    assert res.needs_review is True
    assert any("COMB_NOT_FULLY_DETECTED" in r or "LOW_COMB_QUALITY" in r for r in res.review_reasons)
    assert any("RESCAN_RECOMMENDED" in r for r in res.review_reasons)


def test_normaliser_comb_touches_page_edge():
    normaliser = PageNormaliser(target_width=1600)
    img = np.full((2200, 1600, 3), 255, dtype=np.uint8)
    # Draw comb touching right page border (x2 = 1598)
    bw, bh = 600, 80
    x2 = 1598
    x1 = x2 - bw
    cy = 650
    y1, y2 = int(cy - bh/2), int(cy + bh/2)
    cv2.rectangle(img, (x1, y1), (x2, y2), (20, 20, 220), 4)
    cell_w = bw / 12.0
    for i in range(1, 12):
        cv2.line(img, (int(x1 + i * cell_w), y1), (int(x1 + i * cell_w), y2), (20, 20, 220), 2)

    res = normaliser.align_page(img, format_id="format_original")
    assert res.needs_review is True
    assert any("COMB_TOUCHES_PAGE_EDGE" in r for r in res.review_reasons)


def test_normaliser_excessive_skew():
    normaliser = PageNormaliser(target_width=1600)
    img = np.full((2200, 1600, 3), 255, dtype=np.uint8)
    # Draw comb rotated by 6 degrees
    cx, cy, bw, bh = 1200, 650, 600, 80
    cnt_rect = ((cx, cy), (bw, bh), 6.0)
    box = cv2.boxPoints(cnt_rect).astype(int)
    cv2.drawContours(img, [box], 0, (20, 20, 220), 4)

    res = normaliser.align_page(img, format_id="format_original")
    assert res.needs_review is True
    assert any("EXCESSIVE_SKEW" in r for r in res.review_reasons)
