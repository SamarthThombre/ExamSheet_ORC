"""
tests_v2.test_api_v2: Unit and integration tests for OCR v2 FastAPI endpoints.
Tests /v2/predict and /v2/batch, validates error handling and legacy non-interference.
"""

import os
from pathlib import Path
import cv2
import pytest

# Enable OCR v2 router
os.environ["USE_OCR_V2"] = "1"

from starlette.testclient import TestClient
from app.main import app
from app.routers_v2 import router as router_v2

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


def test_predict_valid_jpeg(client, sample_jpeg_bytes):
    """Tests single-sheet /v2/predict returns 200 and conforms to expected schema."""
    resp = client.post(
        "/v2/predict",
        files={"file": ("page_000004.jpg", sample_jpeg_bytes, "image/jpeg")},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    # Schema checks
    assert data["format_id"] in ("format_original", "format_v2")
    assert "enrolment" in data
    assert "value" in data["enrolment"]
    assert "confidence" in data["enrolment"]
    assert "char_confidences" in data["enrolment"]
    assert "needs_review" in data["enrolment"]
    assert "review_reasons" in data["enrolment"]

    assert "subject_code" in data
    assert "value" in data["subject_code"]
    assert "confidence" in data["subject_code"]

    assert "total_marks" in data
    assert "value" in data["total_marks"]
    assert "confidence" in data["total_marks"]
    assert "flags" in data["total_marks"]

    assert "alignment" in data
    for field in ("dx", "dy", "rot_deg", "quality_score", "needs_review", "review_reasons"):
        assert field in data["alignment"]

    assert "overall_needs_review" in data
    assert "latency_ms" in data
    for key in ("decode", "format_detect", "normalise", "crop", "read", "total"):
        assert key in data["latency_ms"]
        assert isinstance(data["latency_ms"][key], (int, float))

    # Field reading checks on page_000004
    assert data["enrolment"]["value"] == "0801CA251008"
    assert data["subject_code"]["value"] == "CT10718"


def test_predict_corrupt_file(client):
    """Tests corrupt file upload returns 400 Bad Request."""
    corrupt_bytes = b"This is not a real image at all, just corrupt text payload."
    resp = client.post(
        "/v2/predict",
        files={"file": ("corrupt.jpg", corrupt_bytes, "image/jpeg")},
    )
    assert resp.status_code == 400


def test_predict_unsupported_extension(client):
    """Tests unsupported file extension returns 400 Bad Request."""
    resp = client.post(
        "/v2/predict",
        files={"file": ("document.pdf", b"%PDF-1.4...", "application/pdf")},
    )
    assert resp.status_code == 400


def test_batch_consensus_declared_match(client, sample_jpeg_bytes):
    """Tests multi-sheet /v2/batch returns 200 with batch consensus matching declared code."""
    files = [
        ("files", ("sheet_1.jpg", sample_jpeg_bytes, "image/jpeg")),
        ("files", ("sheet_2.jpg", sample_jpeg_bytes, "image/jpeg")),
        ("files", ("sheet_3.jpg", sample_jpeg_bytes, "image/jpeg")),
        ("files", ("sheet_4.jpg", sample_jpeg_bytes, "image/jpeg")),
        ("files", ("sheet_5.jpg", sample_jpeg_bytes, "image/jpeg")),
    ]
    resp = client.post(
        "/v2/batch",
        files=files,
        data={"subject_code_declared": "CT10718"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert data["total_sheets"] == 5
    assert len(data["sheets"]) == 5
    assert "batch_consensus" in data

    consensus = data["batch_consensus"]
    assert consensus["status"] == "OK"
    assert consensus["consensus_code"] == "CT10718"
    assert consensus["agreement_ratio"] == 1.0
    assert consensus["valid_votes"] == 5


def test_batch_consensus_declared_mismatch(client, sample_jpeg_bytes):
    """Tests multi-sheet /v2/batch correctly flags declared code mismatch."""
    files = [
        ("files", ("sheet_1.jpg", sample_jpeg_bytes, "image/jpeg")),
        ("files", ("sheet_2.jpg", sample_jpeg_bytes, "image/jpeg")),
        ("files", ("sheet_3.jpg", sample_jpeg_bytes, "image/jpeg")),
        ("files", ("sheet_4.jpg", sample_jpeg_bytes, "image/jpeg")),
        ("files", ("sheet_5.jpg", sample_jpeg_bytes, "image/jpeg")),
    ]
    resp = client.post(
        "/v2/batch",
        files=files,
        data={"subject_code_declared": "CT10715"},  # Sheet is CT10718
    )
    assert resp.status_code == 200
    data = resp.json()

    consensus = data["batch_consensus"]
    assert consensus["status"] == "DECLARED_MISMATCH"
    assert consensus["consensus_code"] == "CT10715"
    assert consensus["evidence"]["top_code"] == "CT10718"
    assert consensus["subject_code_declared"] == "CT10715"


def test_batch_review_signals_and_roster(client, sample_jpeg_bytes):
    """Tests /v2/batch applies duplicate detection and optional roster check."""
    import json
    files = [
        ("files", ("sheet_1.jpg", sample_jpeg_bytes, "image/jpeg")),
        ("files", ("sheet_2.jpg", sample_jpeg_bytes, "image/jpeg")),
    ]
    # Roster has sheet_1 roll (0801CA251008) and another roll number
    roster_list = ["0801CA251008", "0801CA251099"]
    resp = client.post(
        "/v2/batch",
        files=files,
        data={"roster": json.dumps(roster_list)},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert "batch_review" in data
    br = data["batch_review"]
    assert br["roster_provided"] is True
    # Two identical sheets uploaded -> duplicate flagged!
    assert "0801CA251008" in br["duplicate_enrolments"]
    assert len(br["duplicate_enrolments"]["0801CA251008"]) == 2
    # 0801CA251099 was not in the batch -> missing from batch
    assert "0801CA251099" in br["missing_from_batch"]

    # Verify per-sheet flags
    sheet1 = data["sheets"][0]
    assert "rescan_recommended" in sheet1
    assert "needs_review" in sheet1
    assert sheet1["needs_review"] is True
    assert "DUPLICATE_ENROLMENT" in sheet1["review_reasons"]


def test_predict_schema_semantics(client, sample_jpeg_bytes):
    """Verifies that /v2/predict includes rescan_recommended and needs_review fields."""
    resp = client.post(
        "/v2/predict",
        files={"file": ("page_000004.jpg", sample_jpeg_bytes, "image/jpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "rescan_recommended" in data
    assert isinstance(data["rescan_recommended"], bool)
    assert "needs_review" in data
    assert isinstance(data["needs_review"], bool)
    assert "review_reasons" in data
    assert isinstance(data["review_reasons"], list)

    assert "rescan_recommended" in data["enrolment"]
    assert "rescan_recommended" in data["alignment"]


def test_legacy_predict_unaffected(client):
    """Ensures legacy /predict returns 410 unless ENABLE_LEGACY=true."""
    test_img_path = PROJECT_ROOT / "data" / "raw" / "images" / "page_000001.png"
    with open(test_img_path, "rb") as f:
        resp = client.post(
            "/predict",
            files={"file": (test_img_path.name, f, "image/png")},
        )
    if os.environ.get("ENABLE_LEGACY", "").lower() == "true":
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["rollno"] == "0801CA251001"
        assert data["result"]["subject_code"] == "CT10718"
        assert data["result"]["total_marks_corrected"] == 54
    else:
        assert resp.status_code == 410


def test_localiser_default_off(client, sample_jpeg_bytes):
    """Asserts that page localiser is OFF by default and response fields are null/NOT_RUN."""
    from app.config import settings
    assert settings.ENABLE_PAGE_LOCALISER is False

    resp = client.post(
        "/v2/predict",
        files={"file": ("page_000004.jpg", sample_jpeg_bytes, "image/jpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["page_status"] == "NOT_RUN"
    assert data["page_confidence"] is None
    assert data["page_quad"] is None
