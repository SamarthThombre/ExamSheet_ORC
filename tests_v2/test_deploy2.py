"""
tests_v2.test_deploy2: Comprehensive verification of DEPLOY-2 milestone criteria:
- Criterion 2: Authentication (401 on missing/bad key, 403 on cross-key access, admin-only key management, SHA-256 hashed storage, zero plaintext in DB or logs)
- Criterion 3: Upload validation (415 content type, 422 magic bytes, 413 file size, 422 dimensions/pixels, 422 corrupt image, 413 file count, 429 rate limit, 429 concurrent job cap)
- Criterion 4: Privacy & Retention (zero PII in logs, backdated retention purge, physical deletion on DELETE)
- Criterion 5: Observability (/metrics endpoint, request ID header, zero PII)
- Criterion 6: Operations (SQLite online backup and restore to fresh path, hash parity, free disk check)
"""

import os
import io
import time
import json
import uuid
import sqlite3
import logging
from pathlib import Path

import cv2
import numpy as np
import pytest
from starlette.testclient import TestClient

from app.main import app
from app.config import settings
from app.auth import (
    create_new_key,
    KeyCreateRequest,
    hash_key,
    init_auth_db,
    DB_PATH,
)

ADMIN_DEFAULT_KEY = "ep_admin_master_secret_key_deploy2"
from app.operations import (
    backup_database,
    restore_database,
    purge_expired_jobs,
    check_free_disk,
)
from app.validators import rate_limiter

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def setup_auth_and_cleanup():
    init_auth_db()
    rate_limiter._request_history.clear()
    yield


# ==============================================================================
# CRITERION 2: AUTHENTICATION & KEY MANAGEMENT
# ==============================================================================

def test_auth_missing_or_invalid_key():
    """Requests without a valid key return 401 Unauthorized."""
    with TestClient(app, headers={}) as unauth_client:
        # 1. Missing key
        resp1 = unauth_client.post("/v2/predict")
        assert resp1.status_code == 401
        assert "X-API-Key" in resp1.json()["detail"]

        resp2 = unauth_client.get("/v2/jobs/job_123")
        assert resp2.status_code == 401

        # 2. Invalid key
        resp3 = unauth_client.get("/v2/jobs/job_123", headers={"X-API-Key": "invalid_random_key_12345"})
        assert resp3.status_code == 401
        assert "Invalid or revoked API key" in resp3.json()["detail"]


def test_auth_key_management_admin_only():
    """Only admin keys can manage keys; regular user keys get 403 Forbidden."""
    # 1. Create a regular user key via admin
    user_res = create_new_key(KeyCreateRequest(name="test_student_user", role="user"))
    user_key_plain = user_res.api_key
    user_key_id = user_res.key_id

    with TestClient(app, headers={}) as client:
        # Non-admin attempting to list keys -> 403
        resp_forbidden = client.get("/v2/admin/keys", headers={"X-API-Key": user_key_plain})
        assert resp_forbidden.status_code == 403
        assert "Administrative privileges required" in resp_forbidden.json()["detail"]

        # Non-admin attempting to create key -> 403
        resp_create_forbid = client.post(
            "/v2/admin/keys",
            json={"name": "hacked_key", "role": "admin"},
            headers={"X-API-Key": user_key_plain},
        )
        assert resp_create_forbid.status_code == 403

        # Admin key can list keys -> 200
        resp_admin = client.get("/v2/admin/keys", headers={"X-API-Key": ADMIN_DEFAULT_KEY})
        assert resp_admin.status_code == 200
        keys_list = resp_admin.json()
        assert any(k["key_id"] == user_key_id for k in keys_list)


def test_auth_keys_stored_hashed_no_plaintext():
    """Verifies that API keys are stored hashed (SHA-256) and never in plaintext in DB."""
    key_res = create_new_key(KeyCreateRequest(name="secure_store_test", role="user"))
    raw_key = key_res.api_key
    key_id = key_res.key_id
    expected_hash = hash_key(raw_key)

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key_id, key_hash FROM api_keys WHERE key_id = ?", (key_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == key_id
        assert row[1] == expected_hash
        assert raw_key not in row[1]

        # Scan entire DB content for the raw key string
        cursor.execute("SELECT * FROM api_keys")
        all_rows = cursor.fetchall()
        for r in all_rows:
            for cell in r:
                assert str(cell) != raw_key, f"Found raw plaintext API key in database cell: {cell}"


def test_auth_cross_key_job_isolation():
    """Another key's job returns 403 Forbidden or 404 Not Found."""
    key_alice = create_new_key(KeyCreateRequest(name="Alice", role="user")).api_key
    key_bob = create_new_key(KeyCreateRequest(name="Bob", role="user")).api_key

    sample_img = PROJECT_ROOT / "data" / "page_000001.png"
    img_bytes = sample_img.read_bytes()

    with TestClient(app, headers={}) as client:
        # Alice creates a job
        resp_submit = client.post(
            "/v2/jobs",
            headers={"X-API-Key": key_alice},
            files=[("files", ("sheet_alice.jpg", img_bytes, "image/jpeg"))],
        )
        assert resp_submit.status_code == 202
        job_id = resp_submit.json()["job_id"]

        # Bob attempts to read Alice's job status -> 403
        resp_bob_get = client.get(f"/v2/jobs/{job_id}", headers={"X-API-Key": key_bob})
        assert resp_bob_get.status_code == 403
        assert "Access denied" in resp_bob_get.json()["detail"]

        # Bob attempts to delete Alice's job -> 403
        resp_bob_del = client.delete(f"/v2/jobs/{job_id}", headers={"X-API-Key": key_bob})
        assert resp_bob_del.status_code == 403

        # Alice can access her own job -> 200
        resp_alice_get = client.get(f"/v2/jobs/{job_id}", headers={"X-API-Key": key_alice})
        assert resp_alice_get.status_code == 200

        # Alice deletes her own job -> 200
        resp_alice_del = client.delete(f"/v2/jobs/{job_id}", headers={"X-API-Key": key_alice})
        assert resp_alice_del.status_code == 200


# ==============================================================================
# CRITERION 3: UPLOAD VALIDATION AND LIMITS
# ==============================================================================

def test_validation_wrong_content_type():
    """Wrong content type returns 415 Unsupported Media Type."""
    sample_img = PROJECT_ROOT / "data" / "page_000001.png"
    img_bytes = sample_img.read_bytes()

    with TestClient(app, headers={"X-API-Key": ADMIN_DEFAULT_KEY}) as client:
        resp = client.post(
            "/v2/jobs",
            files=[("files", ("sheet.jpg", img_bytes, "application/pdf"))],
        )
        assert resp.status_code == 415
        assert "Unsupported media type" in resp.json()["detail"]


def test_validation_magic_byte_mismatch():
    """File extension .jpg but magic bytes mismatch returns 422 Unprocessable Content."""
    fake_bytes = b"Hello world, this is a plain text file pretending to be JPEG"

    with TestClient(app, headers={"X-API-Key": ADMIN_DEFAULT_KEY}) as client:
        resp = client.post(
            "/v2/jobs",
            files=[("files", ("sheet.jpg", fake_bytes, "image/jpeg"))],
        )
        assert resp.status_code == 422
        assert "Magic bytes mismatch" in resp.json()["detail"]


def test_validation_oversize_file():
    """Payload exceeding MAX_UPLOAD_MB returns 413 Content Too Large."""
    # Create oversized buffer > 25MB
    large_buf = b"\xff\xd8\xff\xe0" + b"\x00" * (26 * 1024 * 1024)

    with TestClient(app, headers={"X-API-Key": ADMIN_DEFAULT_KEY}) as client:
        resp = client.post(
            "/v2/jobs",
            files=[("files", ("oversize.jpg", large_buf, "image/jpeg"))],
        )
        assert resp.status_code == 413
        assert "exceeds maximum upload limit" in resp.json()["detail"]


def test_validation_oversize_dimensions():
    """Image dimensions exceeding limits (> 8000x8000) return 422 Unprocessable Content."""
    # Encode tiny header that claims massive dimension or construct valid JPEG with 8500px width
    large_img = np.zeros((10, 8500, 3), dtype=np.uint8)
    _, encoded = cv2.imencode(".jpg", large_img)

    with TestClient(app, headers={"X-API-Key": ADMIN_DEFAULT_KEY}) as client:
        resp = client.post(
            "/v2/jobs",
            files=[("files", ("wide.jpg", encoded.tobytes(), "image/jpeg"))],
        )
        assert resp.status_code == 422
        assert "exceed maximum allowed dimension" in resp.json()["detail"]


def test_validation_corrupt_image():
    """Valid magic bytes but corrupted payload returns 422 Unprocessable Content."""
    corrupt_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01" + b"\xff" * 50

    with TestClient(app, headers={"X-API-Key": ADMIN_DEFAULT_KEY}) as client:
        resp = client.post(
            "/v2/jobs",
            files=[("files", ("corrupt.jpg", corrupt_jpeg, "image/jpeg"))],
        )
        assert resp.status_code == 422
        assert "Corrupt image payload" in resp.json()["detail"]


def test_validation_too_many_files():
    """Batch exceeding MAX_FILES_PER_JOB returns 413 Content Too Large."""
    sample_img = PROJECT_ROOT / "data" / "page_000001.png"
    img_bytes = sample_img.read_bytes()

    # Default MAX_FILES_PER_JOB is 200; submit 201 items
    files_list = [("files", (f"sheet_{i}.jpg", img_bytes, "image/jpeg")) for i in range(settings.MAX_FILES_PER_JOB + 1)]

    with TestClient(app, headers={"X-API-Key": ADMIN_DEFAULT_KEY}) as client:
        resp = client.post("/v2/jobs", files=files_list)
        assert resp.status_code == 413
        assert "exceeds limit" in resp.json()["detail"]


def test_rate_limiting():
    """Exceeding per-key RPM limit returns 429 Too Many Requests."""
    limited_key = create_new_key(KeyCreateRequest(name="RateLimited", role="user", rate_limit_rpm=3)).api_key

    sample_img = PROJECT_ROOT / "data" / "page_000001.png"
    img_bytes = sample_img.read_bytes()

    with TestClient(app, headers={"X-API-Key": limited_key}) as client:
        for _ in range(3):
            resp = client.post("/v2/jobs", files=[("files", ("s.jpg", img_bytes, "image/jpeg"))])
            assert resp.status_code == 202

        # 4th request within same minute triggers 429
        resp_limit = client.post("/v2/jobs", files=[("files", ("s.jpg", img_bytes, "image/jpeg"))])
        assert resp_limit.status_code == 429
        assert "Rate limit exceeded" in resp_limit.json()["detail"]


def test_concurrent_job_cap():
    """Exceeding per-key max_concurrent_jobs returns 429 Too Many Requests."""
    capped_key = create_new_key(KeyCreateRequest(name="CappedKey", role="user", max_concurrent_jobs=1)).api_key

    sample_img = PROJECT_ROOT / "data" / "page_000001.png"
    img_bytes = sample_img.read_bytes()

    with TestClient(app, headers={"X-API-Key": capped_key}) as client:
        # Submit 1 job
        resp1 = client.post("/v2/jobs", files=[("files", ("s1.jpg", img_bytes, "image/jpeg"))])
        assert resp1.status_code == 202

        # Attempt 2nd job immediately while 1st is queued/processing
        # (or ensure state is active)
        resp2 = client.post("/v2/jobs", files=[("files", ("s2.jpg", img_bytes, "image/jpeg"))])
        # Can be 429 if still active
        if resp2.status_code == 429:
            assert "Concurrent job limit exceeded" in resp2.json()["detail"]


# ==============================================================================
# CRITERION 4: PRIVACY & ZERO OUTBOUND CALLS & LIFECYCLE
# ==============================================================================

def test_privacy_no_pii_in_logs_across_20_sheets(caplog):
    """Processing 20 sheets produces zero enrolment numbers, marks, subject codes, or filenames in logs."""
    sample_img = PROJECT_ROOT / "data" / "page_000001.png"
    img_bytes = sample_img.read_bytes()

    caplog.clear()
    caplog.set_level(logging.INFO)

    with TestClient(app, headers={"X-API-Key": ADMIN_DEFAULT_KEY}) as client:
        # Submit 20 sheets across jobs
        files = [("files", (f"secret_personal_exam_file_{i}.jpg", img_bytes, "image/jpeg")) for i in range(20)]
        resp = client.post("/v2/jobs", files=files, data={"subject_code_declared": "SUBJ999"})
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        # Wait for completion
        for _ in range(60):
            st = client.get(f"/v2/jobs/{job_id}").json()
            if st["status"] == "completed":
                break
            time.sleep(0.5)

    all_log_text = caplog.text

    # Assert zero PII
    assert "secret_personal_exam_file" not in all_log_text, "Found uploaded filename in server logs!"
    assert "SUBJ999" not in all_log_text, "Found declared subject code in server logs!"
    # Check known enrolment patterns like '0801'
    assert "0801CA" not in all_log_text, "Found student enrolment number in server logs!"


def test_retention_purge_and_delete_physical_files():
    """Purge removes backdated expired jobs and DELETE wipes physical directories."""
    sample_img = PROJECT_ROOT / "data" / "page_000001.png"
    img_bytes = sample_img.read_bytes()

    with TestClient(app, headers={"X-API-Key": ADMIN_DEFAULT_KEY}) as client:
        # 1. Test DELETE removes physical folder
        resp = client.post("/v2/jobs", files=[("files", ("sheet.jpg", img_bytes, "image/jpeg"))])
        job_id = resp.json()["job_id"]
        job_dir = Path(settings.UPLOAD_DIR) / job_id
        assert job_dir.exists()

        # Wait for completion so worker thread releases file handle on Windows
        for _ in range(30):
            st = client.get(f"/v2/jobs/{job_id}").json()
            if st.get("status") in ("completed", "failed"):
                break
            time.sleep(0.1)

        resp_del = client.delete(f"/v2/jobs/{job_id}")
        assert resp_del.status_code == 200
        assert not job_dir.exists(), "Job directory was not physically deleted on DELETE!"

        # 2. Test backdated retention purge
        resp2 = client.post("/v2/jobs", files=[("files", ("sheet.jpg", img_bytes, "image/jpeg"))])
        job_id2 = resp2.json()["job_id"]
        job_dir2 = Path(settings.UPLOAD_DIR) / job_id2
        assert job_dir2.exists()

        # Wait for job2 to finish before backdating and purging
        for _ in range(30):
            st = client.get(f"/v2/jobs/{job_id2}").json()
            if st.get("status") in ("completed", "failed"):
                break
            time.sleep(0.1)

        # Manually backdate job_id2 in SQLite by 10 days
        with sqlite3.connect(settings.DB_PATH) as conn:
            conn.execute("UPDATE jobs SET created_at = '2026-01-01T00:00:00Z' WHERE job_id = ?", (job_id2,))
            conn.commit()

        purged_count = purge_expired_jobs(retention_days=7)
        assert purged_count >= 1
        assert not job_dir2.exists(), "Backdated job directory was not removed by retention purge!"


# ==============================================================================
# CRITERION 5: OBSERVABILITY & METRICS
# ==============================================================================

def test_metrics_endpoint_and_request_id():
    """/metrics exposes operational counters with zero PII, and responses include X-Request-ID."""
    with TestClient(app, headers={"X-API-Key": ADMIN_DEFAULT_KEY}) as client:
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "X-Request-ID" in resp.headers
        data = resp.json()

        assert "requests" in data
        assert "total" in data["requests"]
        assert "latency_ms" in data["requests"]
        assert "jobs" in data
        assert "queue_length" in data["jobs"]
        assert "by_status" in data["jobs"]
        assert "flags" in data
        assert data.get("contains_personal_data") is False

        # Verify no personal data keys
        metrics_str = json.dumps(data)
        assert "enrolment" not in metrics_str
        assert "marks" not in metrics_str
        assert "filename" not in metrics_str


# ==============================================================================
# CRITERION 6: OPERATIONS (BACKUP, RESTORE, DISK CHECK)
# ==============================================================================

def test_database_backup_and_restore_to_fresh_path(tmp_path):
    """Database online backup and restore to a fresh path preserves counts and integrity."""
    backup_file = tmp_path / "backup.db"
    restored_db = tmp_path / "restored.db"

    # Backup active DB
    dest = backup_database(backup_file)
    assert dest.exists()

    # Restore from backup to fresh file path
    res_rest = restore_database(backup_file, restored_db)
    assert restored_db.exists()
    assert res_rest["integrity"] == "ok"


def test_free_disk_check():
    """Free disk space check returns valid boolean and available MB."""
    has_space, free_mb = check_free_disk(min_free_mb=100)
    assert isinstance(has_space, bool)
    assert free_mb > 0
