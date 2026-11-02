# Exam Paper OCR Extractor API Specification (v2.0)

Base URL: `http://<host>:<port>`

---

## 1. System & Health Endpoints

### 1.1 `GET /health`
Lightweight health and status probe. Returns service version and production manifest hash.

**Response `200 OK`**:
```json
{
  "status": "ok",
  "version": "2.0.0",
  "manifest_hash": "501db792e22164b18b0c24010de88d9de988fe2bbf72a85bf7ad03c2410ff0bf",
  "ocr_loaded": true,
  "detector_loaded": true,
  "model_path": "models/PP-OCRv6_medium_rec_onnx/inference.onnx"
}
```

### 1.2 `GET /ready`
Readiness probe verifying vendored model existence and SHA-256 checksum integrity.

**Response `200 OK`**:
```json
{
  "status": "ready",
  "ready": true,
  "checksums_verified": true
}
```

**Response `503 Service Unavailable`** (on checksum mismatch or missing weight files):
```json
{
  "status": "unavailable",
  "ready": false,
  "error": "Checksum mismatch for models/PP-OCRv6_medium_rec_onnx/inference.onnx"
}
```

---

## 2. Synchronous OCR Endpoints

### 2.1 `POST /v2/predict`
Synchronous single-sheet extraction endpoint.

**Request**: `multipart/form-data`
- `file`: File binary (JPG, PNG).
- `subject_code_declared`: String (optional).
- `extract_total_marks`: Boolean (`true` by default).
- `extract_question_marks`: Boolean (`false` by default).
- `phase`: String (`"full"`).

**Response `200 OK`**:
Returns structured JSON with fields:
`format_id`, `detected_format`, `layout_confidence`, `rescan_recommended`, `needs_review`, `review_reasons`, `enrolment`, `subject_code`, `total_marks`, `q_marks` (if requested), `latency_ms`.

### 2.2 `POST /v2/batch`
Synchronous batch extraction endpoint with bundle consensus.

**Request**: `multipart/form-data`
- `files`: List of File binaries.
- `subject_code_declared`: String (optional).
- `roster`: JSON list or comma-separated roll numbers (optional).

**Response `200 OK`**:
Returns `{ "total_sheets": N, "sheets": [...], "batch_consensus": {...}, "batch_review": {...} }`.

### 2.3 `POST /predict` (Legacy)
Legacy extraction endpoint.
- Returns **`410 Gone`** by default:
  `{"success": false, "error": {"code": "HTTP_ERROR", "message": "Legacy endpoint /predict is deprecated. Use /v2/predict instead."}}`
- If environment variable `ENABLE_LEGACY=true` is set, legacy YOLOv8 + PaddleOCR pipeline is executed.

---

## 3. Asynchronous Jobs API (`/v2/jobs`)

Designed for high-throughput multi-sheet exam batches.

### 3.1 `POST /v2/jobs`
Submits a background batch job.

**Request**: `multipart/form-data`
- `files`: Multiple image files (`.jpg`, `.png`).
- `subject_code_declared`: String (optional).
- `extract_total_marks`: Boolean (default `true`).
- `extract_question_marks`: Boolean (default `false`).

**Response `202 Accepted`**:
```json
{
  "job_id": "7d9b23f8-45c1-4b19-9132-021b18e69814",
  "status": "queued",
  "total_sheets": 60,
  "created_at": "2026-10-20T08:00:00Z"
}
```

**Throttling Response `429 Too Many Requests`**:
Returned when the server queue capacity (`MAX_JOBS_QUEUE=5`) is reached.

### 3.2 `GET /v2/jobs/{job_id}`
Polls progress and status of a submitted job.

**Response `200 OK`**:
```json
{
  "job_id": "7d9b23f8-45c1-4b19-9132-021b18e69814",
  "status": "processing",
  "total_sheets": 60,
  "processed_sheets": 35,
  "progress": 0.5833,
  "created_at": "2026-10-20T08:00:00Z",
  "completed_at": null,
  "error": null
}
```
*Note*: `progress` is guaranteed to be monotonically non-decreasing (`0.0` to `1.0`).

### 3.3 `GET /v2/jobs/{job_id}/results`
Retrieves full per-sheet outputs once the job is completed.

**Response `200 OK`**:
```json
{
  "job_id": "7d9b23f8-45c1-4b19-9132-021b18e69814",
  "status": "completed",
  "total_sheets": 60,
  "results": [
    { /* Identical schema to /v2/predict for sheet 1 */ },
    { /* Identical schema to /v2/predict for sheet 2 */ }
  ]
}
```

**Response `409 Conflict`**: Returned if results are requested while job is still `queued` or `processing`.

### 3.4 `DELETE /v2/jobs/{job_id}`
Cancels processing (if active) and purges job records and artifacts from storage.

**Response `200 OK`**:
```json
{
  "job_id": "7d9b23f8-45c1-4b19-9132-021b18e69814",
  "deleted": true
}
```
