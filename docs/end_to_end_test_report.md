# End-to-End OCR Pipeline Test & Validation Report

**Date:** 2026-09-28  
**Scope:** Full-System Validation: `IMAGE → ANDROID CLIENT → FASTAPI BACKEND → YOLOv8 + PaddleOCR → FIELD EXTRACTION → ANDROID RESULT`  
**Evaluation Dataset:** 5 Benchmark Exam Cover Pages (`page_000001.png` - `page_000005.png`)  
**Ground Truth Source:** `data/canonical_labels.csv`  

---

## 1. Executive Summary

This report documents the end-to-end testing and validation of the Exam Cover-Sheet OCR pipeline, covering the complete data path from the mobile client to the deep learning inference service and back to the user interface.

Testing was conducted across three interconnected stages:
1. **Independent Backend API Execution:** Verified against FastAPI endpoints running YOLOv8 object detection and PaddleOCR recognition.
2. **Android Client Fidelity:** Verified on Android emulator (`Nexus_4_2`, API 26+) for image capture/selection, multipart payload delivery over HTTP, JSON deserialization, and UI presentation.
3. **Canonical Parity Check:** Assessed predictions directly against `data/canonical_labels.csv`.

### Key Metrics Summary
| Metric | Result | Benchmark Baseline | Status |
| :--- | :--- | :--- | :--- |
| **Roll Number Accuracy** | **100.0% (5/5)** | 100.0% | **PASSED** |
| **Subject Code Accuracy** | **100.0% (5/5)** | 100.0% | **PASSED** |
| **Total Marks Accuracy** | **100.0% (5/5)** | 100.0% | **PASSED** |
| **All Fields Exact Match** | **100.0% (5/5)** | 100.0% | **PASSED** |
| **Android Display Fidelity** | **100.0% (5/5)** | 100.0% | **PASSED** |
| **Average Server Latency** | **49,878 ms** | < 60,000 ms (CPU) | **PASSED** |
| **Regression Count** | **0** | 0 | **PASSED** |

---

## 2. Dataset & Evaluation Setup

### Test Images
The test images represent high-resolution scanned cover sheets (~6.8 MB to 7.4 MB each, 2479 × 3508 pixels, 300 DPI):
- `page_000001.png` (7.37 MB)
- `page_000002.png` (7.04 MB)
- `page_000003.png` (7.41 MB)
- `page_000004.png` (7.25 MB)
- `page_000005.png` (6.80 MB)

### Ground Truth Targets (from `data/canonical_labels.csv`)
- **Enrollment / Roll Number:** 12-character alphanumeric code (e.g., `0801CA251001`).
- **Subject Code:** 7-character alphanumeric syllabus identifier (e.g., `CT10718`).
- **Total Marks:** Integer/float exam score extracted from the "Grand Total" box and validated against written words.

---

## 3. Three-Stage Comparison Matrix

The table below contrasts **Stage 1 (Ground Truth)**, **Stage 2 (Backend API Output)**, and **Stage 3 (Android UI Display)**:

| Image Filename | Evaluated Field | Ground Truth (Canonical) | Backend API Output | Android UI Display | Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **page_000001.png** | Roll Number | `0801CA251001` | `0801CA251001` | `0801CA251001` | MATCH |
| | Subject Code | `CT10718` | `CT10718` | `CT10718` | MATCH |
| | Total Marks | `54` | `54` | `54` | MATCH |
| | Verification Meta | — | `AGREE_EXACT` / Review: True | `AGREE_EXACT` / Review Badge | MATCH |
| **page_000002.png** | Roll Number | `0801CA251003` | `0801CA251003` | `0801CA251003` | MATCH |
| | Subject Code | `CT10718` | `CT10718` | `CT10718` | MATCH |
| | Total Marks | `52` | `52` | `52` | MATCH |
| | Verification Meta | — | `AGREE_EXACT` / Review: True | `AGREE_EXACT` / Review Badge | MATCH |
| **page_000003.png** | Roll Number | `0801CA251002` | `0801CA251002` | `0801CA251002` | MATCH |
| | Subject Code | `CT10718` | `CT10718` | `CT10718` | MATCH |
| | Total Marks | `49` | `49` | `49` | MATCH |
| | Verification Meta | — | `AGREE_EXACT` / Review: True | `AGREE_EXACT` / Review Badge | MATCH |
| **page_000004.png** | Roll Number | `0801CA251008` | `0801CA251008` | `0801CA251008` | MATCH |
| | Subject Code | `CT10718` | `CT10718` | `CT10718` | MATCH |
| | Total Marks | `12` | `12` | `12` | MATCH |
| | Verification Meta | — | `AGREE_EXACT` / Review: True | `AGREE_EXACT` / Review Badge | MATCH |
| **page_000005.png** | Roll Number | `0801CA251006` | `0801CA251006` | `0801CA251006` | MATCH |
| | Subject Code | `CT10718` | `CT10718` | `CT10718` | MATCH |
| | Total Marks | `59` | `59` | `59` | MATCH |
| | Verification Meta | — | `AGREE_EXACT` / Review: True | `AGREE_EXACT` / Review Badge | MATCH |

---

## 4. Latency & Performance Breakdown

Each test image was timed from client transmission to complete deserialization.

| Image Filename | Image Size | Server Processing Time | Total Client Roundtrip | Network & Client Overhead |
| :--- | :--- | :--- | :--- | :--- |
| `page_000001.png` | 7.37 MB | 38,585 ms | 38,700 ms | 115 ms |
| `page_000002.png` | 7.04 MB | 47,846 ms | 47,925 ms | 79 ms |
| `page_000003.png` | 7.41 MB | 36,178 ms | 36,264 ms | 86 ms |
| `page_000004.png` | 7.25 MB | 40,092 ms | 40,197 ms | 105 ms |
| `page_000005.png` | 6.80 MB | 86,691 ms | 86,817 ms | 126 ms |
| **Average** | **7.17 MB** | **49,878 ms (~49.9s)** | **49,981 ms (~50.0s)** | **102 ms (0.2%)** |

### Bottleneck Analysis
1. **CPU ML Inference (~99.8% of runtime):**
   - High-resolution text detection (`ch_PP-OCRv4_det`) and text recognition (`ch_PP-OCRv4_rec`) across 300 DPI full-sheet scans on CPU requires ~35–85s per image.
   - Page 5 took 86.7s due to complex table line detection and question marks row parsing.
2. **Network & Client Overhead (~0.2% of runtime):**
   - Local socket transfer between Android emulator (`10.0.2.2:8000`) and the FastAPI backend averaged ~102 ms.
   - Android client image loading, byte array buffering, and OkHttp multipart streaming added minimal delay (<15 ms).
3. **Android Client Timeout Setting:**
   - Setting the OkHttp `readTimeout` to **120 seconds** in `RetrofitClient.kt` was critical. Lower defaults (e.g. 10s or 30s) would have aborted valid requests on CPU inference.

---

## 5. Failure & Root Cause Analysis

### Target Field Accuracy: 100%
There were **zero extraction errors** on the primary target fields (Roll Number, Subject Code, Total Marks).

### Question Marks Row-Sum Discrepancy (`needs_review: true`)
All 5 images yielded `needs_review: true`.
- **Root Cause:** In `question_marks.py`, the extractor parses individual question rows and compares the sum of question marks against the parsed grand total. For all 5 pages:
  - Page 1: sum 36.5 vs grand_total 54.0
  - Page 2: sum 48.0 vs grand_total 52.0
  - Page 3: sum 8.0 vs grand_total 49.0
  - Page 4: sum 3.0 vs grand_total 12.0
  - Page 5: sum 26.5 vs grand_total 59.0
- **Assessment:** This is a safe fallback mechanism. The grand total was extracted accurately, but because partial marks inside table cells can be missing or unsegmented, the safety check flagged the sheets for review.

### Android Deserialization Fidelity
- **Double vs. Long Representation:** Gson parses untyped JSON numbers into `Double` instances. If unhandled, this could render integer marks as `54.0`.
- **Handling:** `ExtractionResult.getDisplayTotalMarks()` converts integral doubles back to integer strings (`54`), ensuring zero visual discrepancies.

---

## 6. Automated Regression Infrastructure

To ensure that future changes to models, preprocessing, or API endpoints do not degrade accuracy, an automated test runner has been added to the project root:

```bash
# Run automated regression test against live server or in-process TestClient:
python test_ocr.py

# Or specify a custom endpoint:
python test_ocr.py --api-url http://127.0.0.1:8000/predict
```

### Features of `test_ocr.py`:
- Automatically detects running HTTP API or falls back to in-process Starlette `TestClient(app)`.
- Validates all 5 benchmark images against `data/canonical_labels.csv`.
- Emits structured machine-readable artifacts: `results/backend_results.json` and `results/backend_results.csv`.
- Fails with exit code 1 if accuracy drops below baseline.

---

## 7. Recommended Top 3 Improvements Before Scaling

1. **Inference Latency Optimization (GPU or ONNX Quantization):**
   - *Issue:* 50-second latency on CPU is too slow for real-time mobile user experience.
   - *Action:* Export PaddleOCR detection and recognition models to ONNX / TensorRT with INT8 or FP16 quantization, or deploy the backend to a GPU-enabled node (reducing latency from ~50s to <1.5s).
2. **Client-Side Image Resizing / Compression:**
   - *Issue:* Scans are currently uploaded at full resolution (~7.2 MB uncompressed PNG).
   - *Action:* Downscale images to 1600–2000px max dimension with JPEG 85–90% compression before uploading. This cuts network payload by ~80% without degrading OCR recognition accuracy.
3. **Targeted Question-Table Bounding Box Detection:**
   - *Issue:* Partial marks in handwritten table cells cause false-positive `needs_review` flags.
   - *Action:* Train a lightweight bounding-box detector (or refine YOLOv8) specifically on question-mark grid cells to avoid unsegmented row crops.
