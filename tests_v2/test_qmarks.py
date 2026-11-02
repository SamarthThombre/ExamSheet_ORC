"""
tests_v2.test_qmarks: Unit and integration tests for question marks extraction,
dual-anchor table detection, cell reading, parser grammar, sum verification,
and FastAPI /v2 endpoint integration.
"""

import os
from pathlib import Path
import cv2
import numpy as np
import pytest
from starlette.testclient import TestClient

from app.main import app
from app.routers_v2 import router as router_v2
from ocr_v2.cell_reader import SharedCellReader, parse_question_cell, compute_sum_status
from ocr_v2.table import DualAnchorTableDetector

if not any(getattr(route, "path", "").startswith("/v2") for route in app.routes):
    app.include_router(router_v2)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def sample_jpeg_bytes():
    sample_path = PROJECT_ROOT / "data" / "raw" / "images" / "page_000004.png"
    if not sample_path.exists():
        pytest.skip(f"Sample image {sample_path} not found")
    img = cv2.imread(str(sample_path))
    success, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert success
    return enc.tobytes()


def test_parse_question_cell_grammar():
    """Verifies Spike 8 retained grammar, lookalike substitution, and zero-padded decimals."""
    # Zero-padded integers & decimals
    v, conf, flags = parse_question_cell("00", 0.95, max_marks=14.0)
    assert v == 0.0
    v, conf, flags = parse_question_cell("01", 0.95, max_marks=14.0)
    assert v == 1.0
    v, conf, flags = parse_question_cell("05.5", 0.95, max_marks=14.0)
    assert v == 5.5
    v, conf, flags = parse_question_cell("00.5", 0.95, max_marks=14.0)
    assert v == 0.5
    
    # Dash as decimal
    v, conf, flags = parse_question_cell("2-5", 0.95, max_marks=14.0)
    assert v == 2.5
    
    # Nil / empty
    v, conf, flags = parse_question_cell("Nil", 0.95, max_marks=14.0)
    assert v is None
    v, conf, flags = parse_question_cell("-", 0.95, max_marks=14.0)
    assert v is None

    # Max marks limit flagging
    v, conf, flags = parse_question_cell("15", 0.95, max_marks=14.0)
    assert v == 15.0
    assert "OUT_OF_RANGE" in flags


def test_compute_sum_status_logic():
    """Verifies Spike 10 4-state sum verification."""
    # Exact agree
    st, sum_q, tot, diff = compute_sum_status([10.0, 10.0, 10.0, 10.0, 10.0], [[]]*5, 50.0, [])
    assert st == "AGREE"
    assert sum_q == 50.0
    assert diff == 0.0

    # Possible grace (+1 or +2)
    st, sum_q, tot, diff = compute_sum_status([10.0, 10.0, 10.0, 10.0, 10.0], [[]]*5, 51.0, [])
    assert st == "POSSIBLE_GRACE"
    assert diff == 1.0

    st, sum_q, tot, diff = compute_sum_status([10.0, 10.0, 10.0, 10.0, 10.0], [[]]*5, 52.0, [])
    assert st == "POSSIBLE_GRACE"
    assert diff == 2.0

    # Mismatch
    st, sum_q, tot, diff = compute_sum_status([10.0, 10.0, 10.0, 10.0, 10.0], [[]]*5, 55.0, [])
    assert st == "MISMATCH"

    # Unavailable due to unparsed cell
    st, sum_q, tot, diff = compute_sum_status([10.0, None, 10.0, 10.0, 10.0], [[]]*5, 50.0, [])
    assert st == "UNAVAILABLE"

    # Unavailable due to flag
    st, sum_q, tot, diff = compute_sum_status([10.0, 10.0, 10.0, 10.0, 10.0], [[], ["LOW_CONFIDENCE"], [], [], []], 50.0, [])
    assert st == "UNAVAILABLE"


def test_predict_with_question_marks(client, sample_jpeg_bytes):
    """Tests /v2/predict with extract_question_marks=True."""
    resp = client.post(
        "/v2/predict",
        files={"file": ("test.jpg", sample_jpeg_bytes, "image/jpeg")},
        data={"extract_total_marks": "true", "extract_question_marks": "true"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "q_marks" in data
    assert len(data["q_marks"]) == 5
    for qm in data["q_marks"]:
        assert "q" in qm
        assert "value" in qm
        assert "raw_text" in qm
        assert "confidence" in qm
        assert "flags" in qm
    assert "marks_sum" in data
    assert data["marks_sum"]["status"] in ("AGREE", "MISMATCH", "POSSIBLE_GRACE", "UNAVAILABLE")
    assert "question_marks" in data["latency_ms"]


def test_predict_backward_compatibility(client, sample_jpeg_bytes):
    """Tests /v2/predict default extract_question_marks=False returns exactly legacy keys."""
    resp = client.post(
        "/v2/predict",
        files={"file": ("test.jpg", sample_jpeg_bytes, "image/jpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "q_marks" not in data
    assert "marks_sum" not in data
    assert "question_marks" not in data["latency_ms"]
