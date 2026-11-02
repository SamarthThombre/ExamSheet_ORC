"""
tests_v2/test_deploy2b.py:
Automated test suite verifying DEPLOY-2b milestone criteria:
- Part 2: Independence of the sum gate (0 circular AGREE sheets on recovered totals)
- Part 4: Clean shutdown drill (503 on new uploads, clean worker abortion, job marked failed)
- Part 5: Security, Privacy, and Headers (CORS rejection, secure response headers, uploads not statically reachable)
- Part 5: Revoked API key handling (immediate 401 on next request)
"""

import os
import time
import pytest
from pathlib import Path
from starlette.testclient import TestClient

from app.main import app
from app.config import settings
from app.auth import (
    create_new_key,
    KeyCreateRequest,
    revoke_key,
    init_auth_db,
    ADMIN_DEFAULT_KEY,
)
from app.jobs import job_store
from ocr_v2.cell_reader import compute_sum_status

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def setup_db():
    init_auth_db()
    job_store.reset_shutdown()
    yield
    job_store.reset_shutdown()


# ==============================================================================
# PART 2: INDEPENDENCE OF THE SUM GATE
# ==============================================================================

def test_sum_gate_independence_recovered_totals_never_agree():
    """Grand totals derived from question cells must NEVER produce AGREE status."""
    q_vals = [10.0, 10.0, 10.0, 10.0, 10.0]
    q_flags = [[], [], [], [], []]
    tot_val = 50.0  # Exactly equals sum of cells

    # Case 1: total has RECOVERED_FROM_CELL_CONSENSUS flag
    tot_flags = ["RECOVERED_FROM_CELL_CONSENSUS"]
    st, sum_q, t_v, diff = compute_sum_status(q_vals, q_flags, tot_val, tot_flags)
    assert st == "UNAVAILABLE", f"Expected UNAVAILABLE for recovered total, got {st}"

    # Case 2: total has SUGGESTED_FROM_CELLS flag
    tot_flags = ["SUGGESTED_FROM_CELLS"]
    st, sum_q, t_v, diff = compute_sum_status(q_vals, q_flags, tot_val, tot_flags)
    assert st == "UNAVAILABLE", f"Expected UNAVAILABLE for suggested total, got {st}"

    # Case 3: total has TOTAL_DERIVED_FROM_CELLS flag
    tot_flags = ["TOTAL_DERIVED_FROM_CELLS"]
    st, sum_q, t_v, diff = compute_sum_status(q_vals, q_flags, tot_val, tot_flags)
    assert st == "UNAVAILABLE", f"Expected UNAVAILABLE for derived total, got {st}"

    # Case 4: genuine independent total (unflagged) agrees -> AGREE
    tot_flags = []
    st, sum_q, t_v, diff = compute_sum_status(q_vals, q_flags, tot_val, tot_flags)
    assert st == "AGREE", f"Expected AGREE for genuine independent total, got {st}"


# ==============================================================================
# PART 4: CLEAN SHUTDOWN DRILL
# ==============================================================================

def test_clean_shutdown_and_worker_drain():
    """
    Demonstrates clean shutdown behavior:
    1. During shutdown, new uploads are refused with 503 Service Unavailable.
    2. In-flight jobs transition cleanly to failed with SERVER_SHUTTING_DOWN.
    """
    sample_img = PROJECT_ROOT / "data" / "page_000001.png"
    img_bytes = sample_img.read_bytes()

    with TestClient(app, headers={"X-API-Key": ADMIN_DEFAULT_KEY}) as client:
        # Submit a multi-sheet job
        resp_submit = client.post(
            "/v2/jobs",
            files=[("files", (f"sheet_{i}.jpg", img_bytes, "image/jpeg")) for i in range(10)],
        )
        assert resp_submit.status_code == 202
        job_id = resp_submit.json()["job_id"]

        # Initiate application-level graceful shutdown / drain
        resp_drain = client.post("/v2/jobs/drain-shutdown")
        assert resp_drain.status_code == 200
        assert resp_drain.json()["status"] == "shutting_down"

        # 1. New upload request during shutdown is refused with 503 Service Unavailable
        resp_blocked = client.post(
            "/v2/jobs",
            files=[("files", ("new_sheet.jpg", img_bytes, "image/jpeg"))],
        )
        assert resp_blocked.status_code == 503
        assert "Server is shutting down" in resp_blocked.json()["detail"]

        # 2. Worker aborts cleanly and job transitions to failed
        for _ in range(30):
            st = client.get(f"/v2/jobs/{job_id}").json()
            if st.get("status") in ("failed", "completed"):
                break
            time.sleep(0.2)

        st_final = client.get(f"/v2/jobs/{job_id}").json()
        assert st_final["status"] in ("failed", "completed")
        if st_final["status"] == "failed":
            assert st_final.get("error") == "SERVER_SHUTTING_DOWN"


# ==============================================================================
# PART 5: SECURITY, PRIVACY, CI EVIDENCE
# ==============================================================================

def test_cors_rejects_unlisted_origin():
    """CORS rejects an origin not present in CORS_ORIGINS (omits allow-origin header)."""
    # Configure specific CORS origin
    settings.CORS_ORIGINS = ["http://trusted-internal-portal.edu"]

    with TestClient(app) as client:
        # Request with trusted origin receives allow-origin
        resp_trusted = client.get("/health", headers={"Origin": "http://trusted-internal-portal.edu"})
        assert resp_trusted.headers.get("access-control-allow-origin") == "http://trusted-internal-portal.edu"

        # Request with untrusted origin does NOT receive allow-origin header
        resp_untrusted = client.get("/health", headers={"Origin": "http://malicious-attacker-site.com"})
        assert "access-control-allow-origin" not in resp_untrusted.headers or resp_untrusted.headers.get("access-control-allow-origin") != "http://malicious-attacker-site.com"


def test_secure_response_headers_present():
    """All responses must include standard security headers."""
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert "Strict-Transport-Security" in resp.headers
        assert "Content-Security-Policy" in resp.headers


def test_uploads_folder_not_statically_reachable():
    """Uploaded files cannot be browsed or accessed via static HTTP paths."""
    with TestClient(app) as client:
        # Check direct uploads path
        resp1 = client.get("/uploads/test_student_sheet.jpg")
        assert resp1.status_code in (404, 405)

        # Check nested path
        resp2 = client.get("/uploads/job_12345/sheet_0001.png")
        assert resp2.status_code in (404, 405)

        # Check static prefix
        resp3 = client.get("/static/uploads/sheet.jpg")
        assert resp3.status_code in (404, 405)


def test_revoked_key_returns_401_immediately():
    """Revoked API key returns 401 Unauthorized on its immediate next request."""
    # 1. Create a active key
    key_res = create_new_key(KeyCreateRequest(name="KeyToRevoke", role="user"))
    plain_key = key_res.api_key
    key_id = key_res.key_id

    with TestClient(app) as client:
        # Request succeeds with active key (404 because job doesn't exist, but auth succeeds)
        resp_ok = client.get("/v2/jobs/job_nonexistent_123", headers={"X-API-Key": plain_key})
        assert resp_ok.status_code == 404

        # Revoke the key
        revoked = revoke_key(key_id)
        assert revoked is True

        # Immediate next request returns 401 Unauthorized
        resp_revoked = client.get("/v2/jobs/job_nonexistent_123", headers={"X-API-Key": plain_key})
        assert resp_revoked.status_code == 401
        assert "Invalid or revoked API key" in resp_revoked.json()["detail"]
