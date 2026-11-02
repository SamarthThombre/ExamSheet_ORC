# Exam Paper Cover Sheet OCR Extractor (v2.0)

A high-accuracy, production-ready machine learning extraction system and FastAPI REST service designed to detect, recognize, deskew, and normalize tabular fields from handwritten university examination answer cover sheets.

---

## 1. System Overview

The system processes university examination cover-sheet scans and extracts structured data with deterministic validation:
- **`enrollment_no`**: Student roll number, normalized to the institutional pattern (`0801CA25XXXX`).
- **`subject_code`**: Subject code (`CT10718`), verified via single-line cropping and template anchors.
- **`grand_total`**: Numerical grand total marks, verified against question-cell marks.
- **`q_marks` ($q_1 \dots q_5$)**: Per-question marks table, with stacked fraction parsing ($9\frac{1}{2}$, $0.5$) and crossed-out scribble rejection.
- **`marks_sum`**: Deterministic sum gate evaluating sum consistency (`AGREE`, `POSSIBLE_GRACE`, `MISMATCH`, `UNAVAILABLE`).
- **`page_status`**: Optional page quadrilateral boundary localization and perspective deskew for smartphone photographs.

### Supported Layout Formats
1. **Format A (`format_original`)**: Red-box institutional cover sheet with 12-box enrollment comb, vertical marks table ($q_1 \dots q_5$), and crest emblem.
2. **Format B (`format_v2`)**: Orange-box institutional cover sheet with 12-box enrollment comb, horizontal marks table ($q_1 \dots q_5$), and dual left/right subject code anchors.
3. **`UNKNOWN` Layout**: Non-cover pages, blank scans, or inverted sheets; strictly returns zero parsed values to prevent data leakage.

---

## 2. Architecture & Pipeline

```text
Client (Web App / Mobile / CLI / Automation Scripts)
      |
      | POST /v2/predict or POST /v2/batch
      v
FastAPI REST API (app/routers_v2.py)
      |
      +--> 1. Page Localiser (ocr_v2/page_localiser.py) [Configurable: Default OFF]
      |       - Multi-scale contour detection & convex quad validation
      |       - Perspective rectification & rotation deskew
      |
      +--> 2. Format Detector (ocr_v2/formats.py)
      |       - Multi-cue classifier: comb hue saturation, printed geometry anchors
      |       - Crest / table header / Grand Total template matching in canonical space
      |
      +--> 3. Page Normaliser (ocr_v2/normaliser.py)
      |       - Comb box anchor detection & canonical width scaling (1600w)
      |       - Affine transform compensation (dx, dy, rot_deg)
      |
      +--> 4. Field Cropper (ocr_v2/cropper.py)
      |       - Deterministic coordinate crops from format YAML configuration
      |       - Grand total and single-line subject code extraction
      |
      +--> 5. Field & Cell Reader (ocr_v2/reader.py, ocr_v2/cell_reader.py)
      |       - PP-OCRv6 ONNX recognition model with CTC decoding
      |       - Visual stacked fraction detection (morphological component separation)
      |       - Crossed-out scribble detector & CTC top-2 margin confidence check
      |
      +--> 6. Sum-Check Gate & Review Flagging (app/routers_v2.py, ocr_v2/batch.py)
              - Evaluates sum(q1..q5) == grand_total (exact or +1 grace tolerance)
              - Batch duplicate roll number signal validation
      v
Structured JSON API Output
```

---

## 3. Directory Structure

```text
exam_paper_extractor/
├── app/                        # Production FastAPI REST backend
│   ├── config.py               # Settings (ENABLE_PAGE_LOCALISER, etc.)
│   ├── main.py                 # Application factory & routes
│   └── routers_v2.py           # v2 API endpoints (/v2/predict, /v2/batch)
├── ocr_v2/                     # Core OCR v2 engine package
│   ├── formats.py              # Multi-feature FormatDetector (Format A, B, UNKNOWN)
│   ├── page_localiser.py       # Page boundary localization & quad deskew
│   ├── normaliser.py           # PageNormaliser affine alignment
│   ├── cropper.py              # FieldCropper & coordinate transforms
│   ├── reader.py               # FieldReader & PP-OCRv6 inference
│   ├── cell_reader.py          # Question cell parsing & fraction detection
│   ├── batch.py                # Batch sanity & duplicate roll checks
│   ├── templates/              # Grayscale layout anchor templates
│   └── assets/                 # Header & crest anchor templates
├── configs/
│   └── formats/                # Format definitions (format_original.yaml, format_v2.yaml)
├── tests/                      # Baseline test suite
├── tests_v2/                   # Comprehensive OCR v2 unit and integration tests
├── run_sealed_once.py          # Generalised single-run execution harness for sealed benchmarks
├── score_sealed.py             # Generalised benchmark scoring script (framing subset support)
├── LIMITATIONS.md              # Operational boundaries & measured empirical weak points
├── DEMO_SCRIPT.md              # Interactive demonstration & verification script
├── requirements.txt            # Python dependencies
└── README.md                   # System documentation
```

---

## 4. Setup & Installation

### Requirements
- Python 3.10 to 3.13 (64-bit)
- Windows, Linux, or macOS

### Installation Steps
```powershell
# 1. Clone repository and navigate to root
cd c:\Users\sumit\Desktop\Samarth\python\exam_paper_extractor

# 2. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt
```

---

## 5. Running the Application

### Start the FastAPI Server
```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Interactive Swagger documentation is available at `http://localhost:8000/docs`.

---

## 6. API Reference

### `POST /v2/predict`
Processes a single cover sheet image.

**Request Form Fields:**
- `file`: Image file (PNG, JPEG).
- `extract_total_marks`: (bool, default: `true`) Extract grand total marks.
- `extract_question_marks`: (bool, default: `false`) Extract question marks table ($q_1 \dots q_5$).
- `enable_m7_rules`: (bool, default: `true`) Enable hardened M7 post-processing rules.
- `enable_page_localiser`: (bool, default: `null`) Override global config for page localization.

**Response Structure (JSON):**
```json
{
  "filename": "page_000001.png",
  "detected_format": "format_original",
  "layout_confidence": 0.985,
  "page_status": "NOT_RUN",
  "page_confidence": null,
  "page_quad": null,
  "rescan_recommended": false,
  "needs_review": false,
  "review_reasons": [],
  "enrolment": {
    "value": "0801CA251001",
    "raw_text": "0801CA251001",
    "confidence": 0.992,
    "needs_review": false
  },
  "subject_code": {
    "value": "CT10718",
    "confidence": 0.987,
    "matched_code": "CT10718"
  },
  "total_marks": {
    "value": 54.0,
    "raw_text": "54",
    "confidence": 0.995,
    "flags": []
  },
  "q_marks": [
    {"q_number": 1, "value": 12.0, "raw_text": "12", "flags": []},
    {"q_number": 2, "value": 11.5, "raw_text": "11.5", "flags": []},
    {"q_number": 3, "value": 11.5, "raw_text": "11.5", "flags": []},
    {"q_number": 4, "value": 13.0, "raw_text": "13", "flags": []},
    {"q_number": 5, "value": 5.5, "raw_text": "5.5", "flags": []}
  ],
  "marks_sum": {
    "status": "AGREE",
    "sum_of_questions": 54.0,
    "grand_total": 54.0,
    "difference": 0.0
  }
}
```

### `POST /v2/batch`
Processes multiple cover sheets with batch-level duplicate roll verification.

**Request Form Fields:**
- `files`: List of files (`multipart/form-data`).
- `subject_code_declared`: (optional string) Expected course code for consistency checking.
- `extract_total_marks`: (bool, default: `true`).
- `extract_question_marks`: (bool, default: `false`).

---

## 7. Testing & Verification

Run both test suites to assert complete test coverage:
```powershell
# Legacy test suite
pytest tests/

# Production OCR v2 test suite
pytest tests_v2/
```

---

## 8. Sealed Benchmark Execution & Evaluation (v4 Readiness)

### Sealed Single-Run Execution Harness
```powershell
python run_sealed_once.py `
  --dataset v4 `
  --images-dir data/data_v4/images `
  --output-csv experiments/v4/v4_predictions.csv `
  --manifest experiments/final2/manifest.json `
  --code-is-frozen
```
*Note*: The sealed runner requires `--code-is-frozen`, verifies cryptographic code integrity against the manifest, writes predictions with effective settings, and sets a permanent `<dataset>.lock` file refusing any second execution.

### Benchmark Scoring Harness
```powershell
python score_sealed.py `
  --dataset v4 `
  --predictions-csv experiments/v4/v4_predictions.csv `
  --gt-csv data/canonical_labels_v4.csv `
  --output-json experiments/v4/v4_score_summary.json `
  --criteria docs/criteria_final2.txt
```
*Note*: Automatically decomposes metrics by framing column (`ok` vs `uncropped`) when present in the ground truth, evaluates layout safety against ground truth layout labels, and evaluates character-for-character criteria.

