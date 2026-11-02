"""
Unit tests for ocr_v2.fields.
"""

import pytest
import numpy as np
from ocr_v2.fields import FieldCropper, FieldCropResult


def test_field_cropper_nominal_rois():
    cropper = FieldCropper()
    img = np.zeros((2260, 1600, 3), dtype=np.uint8)

    cfg = {
        "fields": {
            "enrollment_no": {"roi": [0.520, 0.260, 0.985, 0.360]},
            "subject_code": {"roi": [0.040, 0.280, 0.460, 0.355]},
            "grand_total": {"status": "deferred_phase2"},
        }
    }

    crops = cropper.crop_fields(img, format_id="format_original", format_config=cfg)

    assert "enrollment_no" in crops
    assert "subject_code" in crops
    assert "grand_total" in crops

    e_crop = crops["enrollment_no"]
    assert e_crop.status == "FALLBACK_NOMINAL_ROI"
    assert e_crop.crop.shape[1] > 0
    assert e_crop.crop.shape[0] > 0

    s_crop = crops["subject_code"]
    assert s_crop.status == "FALLBACK_NOMINAL_ROI"
    assert s_crop.crop.shape[1] > 0
    assert s_crop.crop.shape[0] > 0

    gt_crop = crops["grand_total"]
    assert gt_crop.status == "ROI_TO_BE_MEASURED"
    assert gt_crop.crop.size == 0


def test_field_cropper_padded_margin():
    cropper = FieldCropper()
    img = np.full((2260, 1600, 3), 240, dtype=np.uint8)

    cfg = {
        "fields": {
            "enrollment_no": {"roi": [0.520, 0.260, 0.985, 0.360]},
        }
    }

    # Simulate comb near page right edge: cx=1310, bw=550 -> right edge is at 1310 + 275 = 1585 (margin to edge = 15 px)
    comb_box = ((1310.0, 720.0), (550.0, 80.0), 0.0)

    crops = cropper.crop_fields(
        img,
        format_id="format_original",
        format_config=cfg,
        comb_box=comb_box,
    )

    e_crop = crops["enrollment_no"]
    assert e_crop.status in ["OK", "COMB_TOUCHES_PAGE_EDGE"]
    # Total crop width must be >= bw + 2 * (0.6 * cell_w)
    cell_w = 550.0 / 12.0
    expected_min_w = 550.0 + 2 * (0.60 * cell_w)
    assert e_crop.crop.shape[1] >= int(expected_min_w) - 2


def test_field_cropper_comb_anchoring():
    cropper = FieldCropper(moderate_margin_h=0.040)
    img = np.zeros((2260, 1600, 3), dtype=np.uint8)

    cfg = {
        "fields": {
            "enrollment_no": {"roi": [0.520, 0.260, 0.985, 0.360]},
            "subject_code": {"roi": [0.040, 0.280, 0.460, 0.355]},
        }
    }

    # Simulate detected comb at cy = 720 (nominal is ~700)
    comb_box = ((1200.0, 720.0), (600.0, 80.0), 0.0)

    crops = cropper.crop_fields(
        img,
        format_id="format_original",
        format_config=cfg,
        comb_box=comb_box,
    )

    s_crop = crops["subject_code"]
    # In Format A, subject code is at cy = comb_cy = 720
    # Half-span = 0.040 * 2260 = 90.4
    expected_sy1 = int(720 - 90.4)
    expected_sy2 = int(720 + 90.4)
    assert abs(s_crop.roi_pixels[1] - expected_sy1) <= 1
    assert abs(s_crop.roi_pixels[3] - expected_sy2) <= 1
