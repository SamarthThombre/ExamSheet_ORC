# Privacy and Data Protection Policy

## 1. Zero Outbound Network Activity (Air-Gapped Operation)
The Exam Paper OCR Extractor API operates strictly in an isolated, offline environment:
- **No external telemetry**: No analytics, telemetry, or diagnostic events are transmitted.
- **Vendored weights**: All ONNX machine learning models and character dictionaries are bundled locally within the application directory (`models/` and `ocr_v2/assets/`). No models or dependencies are downloaded at runtime.
- **Verification**: Verified by automated static AST scanning (`scripts/scan_outbound_network.py`).

## 2. PII Redaction in Operational Logs
To prevent leakage of Personally Identifiable Information (PII) or student examination records:
- **Enrolment Numbers**: Student roll and enrolment identifiers are completely omitted from application logs.
- **Subject Codes & Marks**: Question marks, totals, and exam codes are strictly barred from log output.
- **Original Filenames**: Raw filenames uploaded by clients are pseudonymized or hashed to ephemeral identifiers (`sheet_<hash>`).
- **Binary Image Buffers**: Image bytes, raw crops, and base64 payloads are never written to disk logs.
- **Structured Correlation**: Logs include an ephemeral `request_id` and timing/status metadata only.

## 3. Data Retention and Lifecycle Purge
Exam scripts and batch job artifacts are managed under strict lifecycle rules:
- **Retention Period**: Files uploaded to `UPLOAD_DIR/<job_id>/` and results in SQLite are retained for a maximum configurable period (`RETENTION_DAYS`, default 7 days).
- **Automated Purge**: Routine purge sweeps identify and permanently delete expired job directories and database entries.
- **Explicit Deletion**: The `DELETE /v2/jobs/{id}` endpoint allows callers to immediately cancel, delete, and wipe all uploaded images, intermediate crops, and extracted results.
