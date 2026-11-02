import os
import sys
import json
from pathlib import Path
import pytest
import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ["USE_OCR_V2"] = "1"

from ocr_v2.reader import parse_total_marks, BatchedONNXReader
from ocr_v2.fields import FieldCropper, extract_total_crop_tmpl
from ocr_v2.normalise import PageNormaliser
import yaml
from starlette.testclient import TestClient
from app.main import app
from app.routers_v2 import get_pipeline, router as router_v2

if not any(getattr(route, "path", "").startswith("/v2") for route in app.routes):
    app.include_router(router_v2)

# -----------------------------------------------------------------------------
# 1. ARITHMETIC ROUNDING & PARSER TEST CASES
# -----------------------------------------------------------------------------
def test_parse_total_marks_equations():
    # Equation with RHS: use RHS
    val, flags = parse_total_marks("53.5=54", 0.95)
    assert val == 54
    assert "needs_review" not in flags

    val, flags = parse_total_marks("52.5 = 53", 0.95)
    assert val == 53
    assert "needs_review" not in flags

    val, flags = parse_total_marks("43.5=44", 0.95)
    assert val == 44
    assert "needs_review" not in flags

def test_parse_total_marks_half_mark_missing_rhs():
    # Contains .5 with no '=' or no RHS -> flag RHS_MISSING and needs_review
    val, flags = parse_total_marks("52.5", 0.95)
    assert val is None
    assert "RHS_MISSING" in flags
    assert "needs_review" in flags

    val, flags = parse_total_marks("53.5=", 0.95)
    assert val is None
    assert "RHS_MISSING" in flags
    assert "needs_review" in flags

def test_parse_total_marks_out_of_range():
    val, flags = parse_total_marks("85", 0.95)
    assert val is None
    assert "OUT_OF_RANGE" in flags
    assert "needs_review" in flags

    val, flags = parse_total_marks("-5", 0.95)
    assert val is None
    assert "OUT_OF_RANGE" in flags
    assert "needs_review" in flags

def test_parse_total_marks_low_confidence():
    val, flags = parse_total_marks("45", 0.60)
    assert val == 45
    assert any("LOW_CONF" in f for f in flags)
    assert "needs_review" in flags

def test_parse_total_marks_empty_and_non_numeric():
    val, flags = parse_total_marks("", 0.0)
    assert val is None
    assert "EMPTY_READ" in flags

    val, flags = parse_total_marks("AB", 0.95)
    assert val is None
    assert "NON_NUMERIC" in flags


# -----------------------------------------------------------------------------
# 2. FORMAT A EXTRACTION ON 3 SAMPLE TUNE SHEETS
# -----------------------------------------------------------------------------
def test_format_a_total_marks_extraction():
    pipeline = get_pipeline()
    with open(PROJECT_ROOT / "data" / "splits" / "benchmark_a_splits.json") as f:
        tune_a = json.load(f)["tune_images"][:3]

    for fn in tune_a:
        img_p = PROJECT_ROOT / "data" / "raw" / "images" / fn
        img = cv2.imread(str(img_p))
        assert img is not None

        cfg = pipeline.configs["format_original"]
        align_res = pipeline.normaliser.align_page(img, "format_original", cfg)
        crops = pipeline.cropper.crop_fields(align_res.image, "format_original", cfg, align_res.comb_box, align_res.quality_score)
        assert "grand_total" in crops
        gt_crop = crops["grand_total"].crop
        assert gt_crop.size > 0
        assert crops["grand_total"].status == "OK"

        res = pipeline.reader.read_total_marks(gt_crop)
        assert "value" in res
        assert "raw_text" in res
        assert "confidence" in res
        assert "flags" in res
        assert isinstance(res["confidence"], float)


# -----------------------------------------------------------------------------
# 3. FORMAT B EXTRACTION ON 3 SAMPLE TUNE SHEETS
# -----------------------------------------------------------------------------
def test_format_b_total_marks_extraction():
    pipeline = get_pipeline()
    with open(PROJECT_ROOT / "data" / "splits" / "benchmark_b_splits.json") as f:
        tune_b = json.load(f)["tune_images"][:3]

    for fn in tune_b:
        img_p = PROJECT_ROOT / "data" / "data_v2_images" / fn
        img = cv2.imread(str(img_p))
        assert img is not None

        cfg = pipeline.configs["format_v2"]
        align_res = pipeline.normaliser.align_page(img, "format_v2", cfg)
        crops = pipeline.cropper.crop_fields(align_res.image, "format_v2", cfg, align_res.comb_box, align_res.quality_score)
        assert "grand_total" in crops
        gt_crop = crops["grand_total"].crop
        assert gt_crop.size > 0
        assert crops["grand_total"].status == "OK"

        res = pipeline.reader.read_total_marks(gt_crop)
        assert "value" in res
        assert "raw_text" in res
        assert "confidence" in res
        assert "flags" in res


# -----------------------------------------------------------------------------
# 4. API INTEGRATION & BACKWARD COMPATIBILITY
# -----------------------------------------------------------------------------
def test_api_v2_predict_includes_total_marks():
    client = TestClient(app)
    with open(PROJECT_ROOT / "data" / "splits" / "benchmark_a_splits.json") as f:
        fn = json.load(f)["tune_images"][0]
    img_p = PROJECT_ROOT / "data" / "raw" / "images" / fn

    with open(img_p, "rb") as f:
        content = f.read()

    resp = client.post("/v2/predict", files={"file": (fn, content, "image/png")})
    assert resp.status_code == 200
    data = resp.json()

    # Total marks structure
    assert "total_marks" in data
    tm = data["total_marks"]
    assert "value" in tm
    assert "raw_text" in tm
    assert "confidence" in tm
    assert "flags" in tm

    # Backward compatibility: existing response fields unchanged
    assert "enrolment" in data
    assert "subject_code" in data
    assert "alignment" in data
    assert "latency_ms" in data
    assert "rescan_recommended" in data
    assert "needs_review" in data
    assert "review_reasons" in data
