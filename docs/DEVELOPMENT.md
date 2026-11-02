# DEVELOPER & CONTRIBUTOR WORKFLOW GUIDE

This document provides technical instructions for extending, benchmarking, and maintaining the Exam Paper OCR Extractor codebase.

---

## 1. Environment Setup

### Prerequisites
* Python 3.10 to 3.13 (64-bit)
* Windows, Linux, or macOS

```powershell
# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install production and development dependencies
pip install -r requirements.txt
```

---

## 2. Code Architecture & Responsibilities

The codebase follows strict separation of concerns:

```text
ocr/
├── detection/         # Answers: WHERE is the field? (YOLOFieldDetector, fallbacks)
├── recognition/       # Answers: WHAT does it say? (FieldCropper, divider, PaddleOCREngine)
├── postprocessing/    # Answers: HOW to normalize text? (cleaning, word_parser, fusion)
├── validation/        # Answers: IS the output plausible? (SanityValidator)
└── pipeline.py        # Top-level orchestrator: coordinates stages into ExtractionResult
```

### Critical Invariant: The FastAPI Contract is Frozen
Do not modify routes in `app/main.py` or Pydantic models in `app/schemas.py`. Any new pipeline features must be adapted through `app/services/ocr_service.py` to maintain exact backward compatibility.

---

## 3. Extending the System

### A. How to Add a New OCR Engine
1. Implement a class in `ocr/recognition/` implementing the recognition interface:
   ```python
   class CustomOCREngine:
       def run_ocr(self, img_bgr: np.ndarray) -> str:
           # Perform OCR recognition and return extracted string
           ...
   ```
2. Integrate into `ocr.pipeline.OCREngine` as an interchangeable recognizer or fallback.
3. Add corresponding unit tests in `tests/test_ocr_pipeline.py`.

### B. How to Add a New Detector Version
1. Place trained weights under `models/` (e.g. `models/v2_best.pt`).
2. Update `models/registry.json` with the new model metadata, hyperparameters, and dataset version.
3. Update `app/config.py` default or set `YOLO_MODEL_PATH` in `.env`.
4. Run regression verification:
   ```powershell
   python -m unittest tests/test_regression.py
   ```

### C. How to Add a New Dataset Version
1. Extract images using `scripts/extract_pdf_pages.py`.
2. Label cover sheets using `scripts/label_cover_sheet.py`.
3. Create a versioned manifest under `data/manifests/`.
4. Run the benchmark runner on the new dataset:
   ```powershell
   python -m evaluation.benchmark --ground-truth data/new_dataset_labels.csv
   ```

---

## 4. Running Benchmarks & Tests

### Running the Standardized Benchmark
Evaluates accuracy across all fields and asserts 0 regressions:
```powershell
python -m evaluation.benchmark
```
* Generates reports under `evaluation/reports/`:
  - `summary.md`: Markdown summary table
  - `latest_benchmark_report.csv`: Per-page prediction and ground-truth comparison
  - `mismatches.csv`: Ambiguity breakdown

### Running Automated Tests
```powershell
# 1. Run fast unit and regression tests (< 0.5 seconds, no model loading)
python -m unittest tests/test_cleaners.py tests/test_ocr_pipeline.py tests/test_regression.py

# 2. Run end-to-end FastAPI integration and parity tests
python tests/test_api.py
```

### Adding New Tests
* Unit tests for regex and string normalization belong in `tests/test_cleaners.py`.
* Tests for image geometry, box clamping, and coordinate fallbacks belong in `tests/test_ocr_pipeline.py`.
* Ground-truth regression assertions belong in `tests/test_regression.py`.
