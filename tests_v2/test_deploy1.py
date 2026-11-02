"""
tests_v2/test_deploy1.py
Comprehensive regression tests for DEPLOY-1 criteria:
1. Import hygiene: app/ and ocr_v2/ decouple completely from ocr/, experiments/, tests/
2. Declared subject code: subject_code_declared parameter handling and source tag
3. Partial sheet detection: cut-off image raises PARTIAL_SHEET and propagates flag
4. Jobs API: asynchronous job submission, monotonic progress, results retrieval, and deletion
"""

import os
import re
import ast
import json
import time
import pytest
from pathlib import Path
from starlette.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
from app.main import app
from app.jobs import job_store


def test_import_hygiene():
    """Verifies that no file under app/ or ocr_v2/ imports from ocr/, experiments/, or tests/."""
    IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+(ocr|experiments|tests)(?:\.|\s|$)", re.MULTILINE)
    PATH_RE = re.compile(r"[\"'](?:experiments|tests|ocr)[\\/]", re.MULTILINE)

    violations = []
    for target_dir in [PROJECT_ROOT / "app", PROJECT_ROOT / "ocr_v2"]:
        for py_file in target_dir.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if line.strip().startswith("#"):
                    continue
                if IMPORT_RE.search(line):
                    violations.append((str(py_file.relative_to(PROJECT_ROOT)), line_no, line.strip(), "FORBIDDEN_IMPORT"))
                elif PATH_RE.search(line):
                    violations.append((str(py_file.relative_to(PROJECT_ROOT)), line_no, line.strip(), "FORBIDDEN_PATH_REF"))

    assert len(violations) == 0, f"Found import hygiene violations: {violations}"


def test_declared_subject_code():
    """Verifies that subject_code_declared overrides subject_code.value and records source='declared'."""
    with TestClient(app) as client:
        test_img = PROJECT_ROOT / "data" / "page_000001.png"
        assert test_img.exists()

        with open(test_img, "rb") as f:
            resp = client.post(
                "/v2/predict",
                files={"file": ("page_000001.png", f, "image/jpeg")},
                data={"subject_code_declared": "CT88888"},
            )

        assert resp.status_code == 200
        data = resp.json()
        sc = data["subject_code"]
        assert sc["value"] == "CT88888"
        assert sc["source"] == "declared"
        assert "subject_code_read" in sc
        # Ensure SUBJECT_CODE_DISAGREES is off by default
        assert not any("DISAGREES" in r for r in data.get("review_reasons", []))


def test_partial_sheet_detection():
    """Verifies that cut-off sheets receive PARTIAL_SHEET flag and rescan_recommended=True."""
    import cv2
    test_img_path = PROJECT_ROOT / "data" / "page_000001.png"
    img = cv2.imread(str(test_img_path))
    assert img is not None

    # Cut off 30% from the bottom (removing table & GT anchor)
    h, w = img.shape[:2]
    cut_img = img[:int(h * 0.70), :]
    _, buf = cv2.imencode(".jpg", cut_img)

    with TestClient(app) as client:
        resp = client.post(
            "/v2/predict",
            files={"file": ("cut_test.jpg", buf.tobytes(), "image/jpeg")},
            data={"extract_total_marks": "true", "extract_question_marks": "true"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rescan_recommended"] is True
        assert "PARTIAL_SHEET" in data.get("review_reasons", [])
        # Propagated to total_marks
        if "total_marks" in data and isinstance(data["total_marks"], dict):
            assert "PARTIAL_SHEET" in data["total_marks"].get("flags", [])


def test_jobs_api_lifecycle():
    """Verifies full lifecycle of asynchronous jobs: submit, poll monotonic progress, results, delete."""
    with TestClient(app) as client:
        test_img = PROJECT_ROOT / "data" / "page_000001.png"
        content = test_img.read_bytes()

        # Submit 2-sheet job
        resp = client.post(
            "/v2/jobs",
            files=[
                ("files", ("sheet1.jpg", content, "image/jpeg")),
                ("files", ("sheet2.jpg", content, "image/jpeg")),
            ],
            data={"subject_code_declared": "JOB_SUBJ"},
        )
        assert resp.status_code == 202
        job_info = resp.json()
        job_id = job_info["job_id"]
        assert job_info["status"] == "queued"
        assert job_info["total_sheets"] == 2

        # Poll until complete and verify monotonic progress
        last_progress = 0.0
        for _ in range(30):
            st_resp = client.get(f"/v2/jobs/{job_id}")
            assert st_resp.status_code == 200
            st_data = st_resp.json()
            curr_progress = st_data["progress"]
            assert curr_progress >= last_progress, f"Non-monotonic progress: {last_progress} -> {curr_progress}"
            last_progress = curr_progress

            if st_data["status"] == "completed":
                break
            time.sleep(0.5)

        assert st_data["status"] == "completed"
        assert st_data["progress"] == 1.0

        # Retrieve results
        res_resp = client.get(f"/v2/jobs/{job_id}/results")
        assert res_resp.status_code == 200
        results_data = res_resp.json()
        assert len(results_data["results"]) == 2
        for r in results_data["results"]:
            assert r["subject_code"]["value"] == "JOB_SUBJ"
            assert r["subject_code"]["source"] == "declared"

        # Delete job
        del_resp = client.delete(f"/v2/jobs/{job_id}")
        assert del_resp.status_code == 200
        assert del_resp.json().get("deleted") is True

        # Verify 404 after deletion
        assert client.get(f"/v2/jobs/{job_id}").status_code == 404
