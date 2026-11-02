# Client Migration and Integration Guide (v2.0 Deployment)

This document details all API updates, contract changes, error handling, and behavioral modifications required for client applications (Android client and Web UI client) integrating with the Exam Paper OCR Extractor v2 backend.

---

## 1. Executive Summary of Changes

1. **Default Engine & Endpoints**:
   - The production extraction engine is **v2** (`/v2/predict`, `/v2/batch`, `/v2/jobs`).
   - The legacy endpoint (`/predict`) now returns **`HTTP 410 Gone`** by default. Set environment variable `ENABLE_LEGACY=true` only for legacy regression testing.
2. **Asynchronous Batch Processing (`/v2/jobs`)**:
   - High-throughput asynchronous batch submission via `POST /v2/jobs`.
   - Job polling via `GET /v2/jobs/{id}` with monotonic progress (`0.0` to `1.0`).
   - Retrieval of completed batch outputs via `GET /v2/jobs/{id}/results`.
   - Job cancellation/cleanup via `DELETE /v2/jobs/{id}`.
   - Throttling: Queue returns `HTTP 429` when busy.
3. **Declared Subject Code (`subject_code_declared`)**:
   - Clients can optionally supply a form parameter `subject_code_declared` (string) to `/v2/predict`, `/v2/batch`, or `/v2/jobs`.
   - When supplied:
     - `subject_code.value` is guaranteed to match `subject_code_declared`.
     - `subject_code.source` is set to `"declared"`.
     - The per-sheet OCR reading is preserved in `subject_code.subject_code_read`.
     - `SUBJECT_CODE_DISAGREES` warning remains suppressed by default.
4. **Partial Sheet Detection (`PARTIAL_SHEET`)**:
   - If an uploaded sheet has its enrolment comb, marks table, or grand-total anchor cut off or missing, the API returns:
     - `rescan_recommended: true`
     - Reason tag `"PARTIAL_SHEET"` in `review_reasons`.
     - The `"PARTIAL_SHEET"` flag propagated to all returned field blocks (`enrolment`, `subject_code`, `total_marks`, `q_marks`).
   - Client response: Show "Sheet not recognised. Scan the whole sheet in colour with the scanner." with a Rescan button.

---

## 2. Web UI Client Changes (`frontend/`)

### 2.1 Endpoint Target
- All single-sheet requests point to `POST /v2/predict`.
- Batch uploads point to `POST /v2/batch` or `POST /v2/jobs`.

### 2.2 Upload Preparation
- Image Long Side: ~2000 px recommended.
- Compression: JPEG quality 90.
- Respect EXIF orientation headers.

### 2.3 Form Fields
- `file`: Multipart image upload.
- `subject_code_declared`: String (optional, e.g. `"CS101"`).
- `extract_total_marks`: `true` (default).
- `extract_question_marks`: `true` (default).

### 2.4 CSV Export Specification
Export format strictly requires 9 columns with UTF-8 BOM:
```csv
filename,subject_code,enrolment_no,marks,q1,q2,q3,q4,q5
```
- `subject_code`: Uses declared code if provided; otherwise OCR-read code.
- `marks`: Grand total integer or decimal.
- `q1`-`q5`: Extracted question marks (empty string if unanswered/blank).

---

## 3. Android Client Integration

### 3.1 Scanner Mode & Configuration
- **Scanner Library**: Google ML Kit Document Scanner.
- **Scanner Mode**: Base document scanner mode (`SCANNER_MODE_BASE` / crop and rotate only).
- **Prohibited**: Do NOT apply ML cleaning filters, grayscale, or black-and-white conversion.
- **Format**: Output JPEG at quality 90.
- **Gallery Import**: Enabled inside the document scanner UI so every imported image passes through the crop/rotate confirmation stage. Separate bypass gallery pickers are disabled.

### 3.2 Error & Rescan Messages
When the API returns:
- `layout_confidence == 0.0` or `format_id == "UNKNOWN"`
- `rescan_recommended == true`
- Review reasons containing `"PARTIAL_SHEET"` or `"CUT_OFF"`

**Display Message**:
> "Sheet not recognised. Scan the whole sheet in colour with the scanner."

**User Action**: Provide an immediate "Rescan" button reopening the camera scanner.

---

## 4. Response Schema Reference (`/v2/predict`)

```json
{
  "filename": "page_000001.png",
  "format_id": "format_original",
  "detected_format": "format_original",
  "layout_confidence": 0.998,
  "rescan_recommended": false,
  "needs_review": false,
  "review_reasons": [],
  "enrolment": {
    "value": "0801CA251001",
    "raw_text": "0801CA251001",
    "confidence": 0.992,
    "char_confidences": [0.99, 0.99, 0.99, 0.99],
    "needs_review": false,
    "rescan_recommended": false,
    "review_reasons": []
  },
  "subject_code": {
    "value": "CT10718",
    "raw_text": "CT10718",
    "confidence": 0.965,
    "source": "declared",
    "subject_code_read": "CT10718",
    "needs_review": false,
    "rescan_recommended": false,
    "review_reasons": []
  },
  "total_marks": {
    "value": 54,
    "raw_text": "54",
    "confidence": 0.985,
    "flags": []
  },
  "q_marks": [
    {"q": 1, "value": 10.0, "raw_text": "10", "confidence": 0.98, "flags": []},
    {"q": 2, "value": 12.0, "raw_text": "12", "confidence": 0.97, "flags": []},
    {"q": 3, "value": 8.0, "raw_text": "08", "confidence": 0.99, "flags": []},
    {"q": 4, "value": 10.0, "raw_text": "10", "confidence": 0.95, "flags": []},
    {"q": 5, "value": 14.0, "raw_text": "14", "confidence": 0.96, "flags": []}
  ],
  "latency_ms": {
    "total": 68.4
  }
}
```
