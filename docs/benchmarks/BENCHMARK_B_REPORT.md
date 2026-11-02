# Benchmark B Report: Format V2 Adaptation & Dual-Suite Evaluation

- **Evaluation Date:** 2026-10-02
- **Dataset Evaluated:** `data/data_v2_images` (145 images)
- **Ground Truth Source:** Verified human labels in `data/data_v2_images/data_v2_labels.csv` (and mirrored to `data/canonical_labels_v2.csv`)

---

## 1. Before vs. After Benchmark Comparison

### Benchmark A (Original 146-Page Cover Sheet Format)
Frozen regression baseline comparison:

| Metric | Target Baseline | Before Modification | After Modification | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Page-Level Accuracy (All 3 Fields)** | **95.21%** (139/146) | 95.21% (139/146) | **95.21%** (139/146) | **Zero Regressions** |
| `enrollment_no` Accuracy | 96.58% (141/146) | 96.58% (141/146) | **96.58%** (141/146) | Maintained |
| `subject_code` Accuracy | 100.00% (146/146) | 100.00% (146/146) | **100.00%** (146/146) | Maintained |
| `total_marks` Accuracy | 98.63% (144/146) | 98.63% (144/146) | **98.63%** (144/146) | Maintained |
| Unit & Integration Tests | 48 Passing | 48 Passing | **48 Passing (100%)** | All Passed |

---

### Benchmark B (New 145-Page Format V2 Answer Book)

| Evaluation Stage | Enrollment Accuracy | Subject Code Accuracy | Operational Default Rate | Notes |
| :--- | :---: | :---: | :---: | :--- |
| **Historical Run (Pre-GT)** | *Not Measured* | *Not Measured* | 2.1% (3/145) | Reported 97.9% "parsed", but parsed into wrong subject |
| **Initial GT Evaluation (Baseline)** | 64.83% (94/145) | **0.00%** (0/145) | 2.1% (3/145) | Legacy `107` -> `CT10718` override broke `CT10715` |
| **After Normalizer & Fallback Fixes** | **73.79%** (107/145) | **91.72%** (133/145) | 2.07% (3/145) | Expanded crop box + booklet header stripping |
| **Batch Mode Extraction** | 73.79% (107/145) | **100.00%** (145/145) | 0.00% (0/145) | Institutional batch consensus across sitting |

---

## 2. Operational Extraction Metrics

* **Total Images Processed:** `145`
* **Average Processing Time:** `23.56s` per image (CPU YOLO detection + 2 crop OCR passes)
* **Processing Failures:** `0 / 145` (100% completed)
* **Enrolment Field Detection:**
  * YOLO Detector Box Used: `42.76%` (62 / 145)
  * Fallback Geometric Box Used: `57.24%` (83 / 145)
* **Subject Code Field Detection:**
  * YOLO Detector Box Used: `20.69%` (30 / 145)
  * Fallback Geometric Box Used: `79.31%` (115 / 145)

---

## 3. Engineering Improvements Made

### A. Format-Aware Layout Fallbacks (`ocr/detection/fallbacks.py`)
- Created format-aware fallback geometry:
  - `format_original`: preserved exactly ($x_1=0.520\cdot W, y_1=0.260\cdot H, x_2=0.985\cdot W, y_2=0.360\cdot H$).
  - `format_v2`: expanded to ($x_1=0.550\cdot W, y_1=0.250\cdot H, x_2=0.990\cdot W, y_2=0.410\cdot H$) for enrollment, and ($x_1=0.040\cdot W, y_1=0.200\cdot H, x_2=0.480\cdot W, y_2=0.350\cdot H$) for subject code.
- Prevented bottom-line clipping on handwritten student numbers located below the `SR No.` booklet header.

### B. Cleaning & Normalization (`ocr/postprocessing/cleaning.py`)
- **Subject Code Parser:**
  - Removed aggressive legacy `if "107" in val: return "CT10718"` override.
  - Added booklet header stripping (`(TOTAL 32 PAGES EXCLUSIVE OF COVER PAGE)`, `subject nomenclature`, etc.) to prevent false matching on words like `EXCLUSIVE` or `COVER`.
  - Added lookalike mapping (`+` $\to$ `7`, `/` $\to$ `1`, `|` $\to$ `1`, `L` $\to$ `1`, `O` $\to$ `0`, `S` $\to$ `5`) before non-alphanumeric filtering.
- **Enrollment Number Normalizer:**
  - Added unicode dash mapping (`\u4e00`, `\u2014`, `\u2013`, `\u2212`, `\uff0d`).
  - Added pre-printed serial number stripping (`SR No. \d+`, `\d{5} SR No.`) and word stripping (`(in words)...`, `zero eight...`).
  - Added multi-line reverse order matching (where student suffix appears before `0801CA25`, e.g. `1019 0801CA25`).

---

## 4. Total Marks

* **Status:** Completely frozen and untouched during this stage.
* The verified ground-truth labels provided in `data_v2_labels.csv` include question marks (`q1` through `q5`) and grand totals, which will serve as the benchmark for question-marks extraction in subsequent stages.

---

## 5. YOLO Retraining Assessment

### Question: Is YOLO retraining justified at this stage?
**Answer: No, not yet.**

### Supporting Evidence:
1. **Subject Code Detection:** Despite YOLO only detecting 20.7% of boxes, geometric fallbacks combined with proper cleaning achieve **91.72% single-crop accuracy** and **100% in batch mode** without retraining weights.
2. **Enrollment Number:** The primary cause of fallback failure on Format B was vertical box boundary clipping ($y_2 = 0.360 \cdot H$ cut off lower handwriting lines), which is resolved geometrically by expanding $y_2$ to $0.410 \cdot H$.
3. **Recommendation:** Retraining YOLO on 145 images should only be considered after Format V2 fallback geometry is fully deployed in production if high-speed single-pass inference is required.
