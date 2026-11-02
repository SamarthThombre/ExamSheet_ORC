# BASELINE 146-PAGE BENCHMARK (FROZEN REFERENCE)

**Recorded Date**: 2026-09-27  
**Benchmark Target**: 146 Exam-Paper Cover Sheets (`page_000001.png` to `page_000146.png`)  
**Ground Truth Reference**: `data/verified_labels - Copy.csv` (146 verified rows)  
**Execution Environment**: Python 3.13.15 (Windows AMD64), CPU inference  

---

## 1. Overall Benchmark Summary

| Metric | Count / Matches | Total Pages | Accuracy (%) |
| :--- | :---: | :---: | :---: |
| **Page-Level (All 3 Fields Exact)** | **139** | **146** | **95.21%** |
| **Subject Code (`subject_code`)** | **146** | **146** | **100.00%** |
| **Total Marks (`total_marks_corrected`)** | **144** | **146** | **98.63%** |
| **Enrollment Number (`enrollment_no`)** | **141** | **146** | **96.58%** |
| **Missing / Unparsable Fields** | **0** | **146** | **0.00%** |
| **Known Regressions** | **0** | **146** | **0.00%** |

---

## 2. Benchmark Execution Commands

The baseline benchmark is executed via:

```powershell
# 1. Run batch cleaning and dual-source score fusion
python text_regex_cleaning.py

# 2. Run ground-truth comparison and evaluation
python compare_cleaned_vs_verified.py
```

* **Execution Runtime**: ~2.74 seconds total (batch parsing, fusion, and comparison).
* **Output Artifacts**:
  - `cleaned_ocr_results.csv` (146 rows)
  - `comparison_report.csv` (146 rows)

---

## 3. Detailed Per-Field Breakdown

### A. Subject Code Extraction
* **Matches**: 146 / 146 (100.00%)
* **Mismatches**: 0
* **Behavior**: Normalizes institutional course code `CT10718` across all variants and noise patterns.

### B. Total Marks Extraction (`total_marks_corrected`)
* **Matches**: 144 / 146 (98.63%)
* **Mismatches**: 2 / 146 (1.37%)
* **Fusion Status Breakdown**:
  - `AGREE_EXACT`: 87 pages (both Orig GT and Tight GT agree on exact marks)
  - `AGREE_ORIG_AND_TIGHT_GT`: 43 pages (both Orig and Tight GT derived identical numeric value)
  - `RECOVERED_BY_TIGHT_GT`: 6 pages (Orig GT had noise; Tight GT recovered mark)
  - `RECOVERED_BY_WORDS`: 3 pages (Orig GT was unreadable; recovered from words crop)
  - `GT_ONLY`: 3 pages (only single source available)
  - `COMPLETED_BY_WORDS`: 2 pages (single digit completed by tens from words)
  - `ROUND_TENS_RESOLVED_BY_WORDS_AND_TIGHT_ZERO`: 1 page
  - `DISAGREE_RESOLVED_BY_WORDS`: 1 page
* **The 2 Total Marks Mismatches**:
  1. `page_000089.png`: Predicted `24` vs Ground Truth `28` (Examiner wrote $23.5 + 4.5 = 28$, OCR read `=8` and rounded $23.5=$ to 24 while words read `'Thanty eight'` = 38). **Flagged with `needs_review = True`**.
  2. `page_000121.png`: Predicted `5` vs Ground Truth `54` (Ink blended with printed baseline and examiner initials 'AP'; OCR read `- 5` instead of 54). **Flagged with `needs_review = True`**.

### C. Enrollment Number Extraction (`enrollment_no_corrected`)
* **Matches**: 141 / 146 (96.58%)
* **Mismatches**: 5 / 146 (3.42%)
* **Missing Detections**: 0 (Both `page_000039.png` and `page_000103.png` recovered to exact ground truth via deterministic geometric layout fallback).
* **The 5 Enrollment Mismatches** (visual digit ambiguities in cursive handwriting):
  1. `page_000059.png`: Predicted `0801CA251069` vs GT `0801CA251064` (Handwritten 4 has closed top resembling 9).
  2. `page_000061.png`: Predicted `0801CA251063` vs GT `0801CA251069` (Handwritten 9 has broken loop resembling 3).
  3. `page_000112.png`: Predicted `0801CA251129` vs GT `0801CA251119` (Handwritten 1 has slant resembling 2).
  4. `page_000122.png`: Predicted `0801CA251122` vs GT `0801CA251128` (Handwritten 8 has open bottom resembling 2).
  5. `page_000143.png`: Predicted `0801CA251157` vs GT `0801CA251151` (Handwritten 1 has hooked serif resembling 7).

---

## 4. `needs_review` Diagnostic Flags

* **Flagged Pages (`needs_review = True`)**: 7 pages
  - Correctly flagged (true errors caught): 2 pages (`page_000089.png`, `page_000121.png`)
  - Cautious flags (correct marks with minor OCR disagreement): 5 pages (`page_000028.png`, `page_000077.png`, `page_000082.png`, `page_000090.png`, `page_000120.png`)
* **Unflagged Pages (`needs_review = False`)**: 139 pages
  - Completely correct: 132 pages
  - Total marks accuracy on unflagged pages: **139 / 139 (100.00%)**
  - Subject code accuracy on unflagged pages: **139 / 139 (100.00%)**

---

## 5. Automated API & Integration Baseline

The automated test suite in `test/test_api.py` establishes:
1. `GET /health`: Returns 200 OK (`ocr_loaded: true`, `detector_loaded: true`).
2. `POST /predict` (valid image): Returns 200 OK with `ExtractionResult` matching ground truth.
3. `POST /predict` (invalid format): Returns 400 Bad Request.
4. `POST /predict` (corrupt payload): Returns 422 Unprocessable Content.
5. `POST /predict` (missing file): Returns 422 Validation Error.
6. **Direct vs API Regression**: **0 mismatches** between direct `OCRService.process_image()` and FastAPI `POST /predict`.

---

## 6. Freeze Commitment

This document forms the frozen baseline for the entire restructuring process. Any future phase that causes any metric to drop below these numbers, or causes any regression on the 139 currently matching pages, is considered a failure and must be reverted.
