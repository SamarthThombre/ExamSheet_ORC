# Operations Runbook: Exam Paper OCR Extractor

## 1. System Overview & Architecture
The Exam Paper OCR Extractor is a self-contained, air-gapped system providing automated student enrolment, subject code, and marks extraction from scanned examination cover sheets.

### Core Architecture Components:
- **FastAPI Application**: Web tier handling HTTP ingestion, authentication, rate limiting, and observability.
- **OCR v2 Pipeline (`ocr_v2`)**: Normalisation, table detection, comb detection, ONNX inference (`rec_ppocr_v6.onnx`), question cell reading, and batch review.
- **Asynchronous Jobs API (`/v2/jobs`)**: Background multi-sheet processing with monotonic progress reporting, concurrency control, and SQLite WAL persistence.
- **Key Store (`api_keys` table in SQLite)**: SHA-256 hashed API key management and role-based access control (`admin` vs `user`).
- **Zero-PII Logging**: Server logs redact roll numbers, marks, subject codes, and original filenames.

---

## 2. Configuration & Environment Variables

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `API_PORT` | `8000` | HTTP service port |
| `API_HOST` | `0.0.0.0` | Binding host |
| `DB_PATH` | `jobs.db` | Path to persistent SQLite database |
| `UPLOAD_DIR` | `data/jobs` | Storage location for job uploads and outputs |
| `RETENTION_DAYS` | `7` | Days before completed jobs/uploads are eligible for purge |
| `MAX_UPLOAD_MB` | `25` | Max upload size per sheet |
| `MAX_FILES_PER_JOB` | `200` | Max sheets submitted per batch job |
| `ADMIN_API_KEY` | `ep_admin_master_secret_key_deploy2` | Bootstrap master administrative API key |
| `ENABLE_PAGE_LOCALISER`| `false` | Page boundary localiser (must stay false) |
| `ORT_NUM_THREADS` | `4` | OnnxRuntime intra-op thread count |

---

## 3. Operational Procedures

### 3.1 Service Startup
```bash
# Production startup with Uvicorn
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

### 3.2 Readiness & Health Checks
- **Liveness Probe**: `GET /health` -> Returns `200 OK` with system uptime.
- **Readiness Probe**: `GET /ready` -> Returns `200 OK` after verifying SHA-256 checksums of vendored ONNX models.
- **Observability Metrics**: `GET /metrics` -> Returns request latencies (mean, p95), status counts, queue lengths, and diagnostic flag counts without PII.

### 3.3 API Key Management
Key creation requires administrative credentials (`X-API-Key: <admin_key>`):
```bash
# Create a new user key
curl -X POST http://localhost:8000/v2/admin/keys \
  -H "X-API-Key: ep_admin_master_secret_key_deploy2" \
  -H "Content-Type: application/json" \
  -d '{"name": "evaluator_lab_1", "role": "user", "rate_limit_rpm": 60, "max_concurrent_jobs": 3}'

# List active keys
curl -X GET http://localhost:8000/v2/admin/keys \
  -H "X-API-Key: ep_admin_master_secret_key_deploy2"

# Revoke a key
curl -X DELETE http://localhost:8000/v2/admin/keys/key_123456 \
  -H "X-API-Key: ep_admin_master_secret_key_deploy2"
```

### 3.4 Database Backup & Disaster Recovery
The system uses SQLite online backup API to ensure consistent snapshots even under active write loads:
```bash
# Trigger an online backup via admin endpoint
curl -X POST http://localhost:8000/v2/admin/backup \
  -H "X-API-Key: ep_admin_master_secret_key_deploy2"

# Programmatic restore (using app.operations.restore_database)
python -c "from app.operations import restore_database; restore_database('backup.db', 'jobs.db')"
```

### 3.5 Retention Lifecycle Purge
To clean up jobs and disk artifacts older than `RETENTION_DAYS`:
```bash
curl -X POST http://localhost:8000/v2/admin/purge \
  -H "X-API-Key: ep_admin_master_secret_key_deploy2"
```

### 3.6 Graceful Shutdown
Uvicorn intercepts `SIGTERM` / `SIGINT` signals:
1. Inflight requests finish within graceful timeout window.
2. Background executor completes current sheet inference.
3. If interrupted mid-processing, restart automatically triggers `job_store.recover_interrupted_jobs()`, marking incomplete jobs as `failed` to prevent orphaned locks.

---

## 4. Incident Response & Troubleshooting

| Symptom | Probable Cause | Action |
| :--- | :--- | :--- |
| `HTTP 401 Unauthorized` | Missing or invalid `X-API-Key` | Verify header is present and key is active. |
| `HTTP 403 Forbidden` | Non-admin caller accessing `/v2/admin/*` or accessing another key's job | Ensure caller owns job or has admin privileges. |
| `HTTP 413 Content Too Large` | File exceeds 25 MB or batch exceeds 200 sheets | Split batch or compress images below limit. |
| `HTTP 415 Unsupported Media Type` | Upload is not JPEG/PNG/WEBP | Ensure payload MIME is image/jpeg or image/png. |
| `HTTP 422 Unprocessable Entity` | Magic byte mismatch or corrupt image bytes | Inspect scan file integrity. |
| `HTTP 429 Too Many Requests` | Exceeded RPM or max concurrent active jobs | Respect `Retry-After` header and wait for jobs to complete. |
| `HTTP 503 Storage Full` | Less than 500 MB free disk on host | Run `/v2/admin/purge` or expand disk volume. |
