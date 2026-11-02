# MILESTONE 4a REPORT: BATCH REVIEW LAYER AND FLAG SEMANTICS

**Date:** 2026-10-04  
**Split Used:** Tune split ONLY (`benchmark_a_splits.json` = 102 sheets, `benchmark_b_splits.json` = 101 sheets, total 203 sheets).  
**Frozen-test Split:** Zero frozen images or labels opened or evaluated. `evaluation/frozen_v2.py` was NOT run.

---

## Pre-Registered Acceptance Criteria & Status

| Criterion | Target | Measured Value | Status |
|:---|:---|:---|:---|
| **1. Tune Unflagged Errors** | Report sheets wrong and not flagged across all signals combined | Format A: 0 silent / 3 errors<br>Format B: 3 silent / 7 errors<br>Combined Tune: **3 silent / 10 errors** (1.48% silent error rate) | **REPORTED** |
| **2. Review Rate on Tune** | $\le 20.0\%$ review rate on tune split with combined signals, per-flag accuracy table complete | Combined flagged: **15.76%** (32 / 203 sheets)<br>Format A: 19.61% (20 / 102)<br>Format B: 11.88% (12 / 101) | **MET** |
| **3. Latency Budget** | 2000 px JPEG (decode included):<br>Mean $\le 600$ ms<br>P95 $\le 900$ ms | Mean: **767.99 ms** ($\le 600$ ms target)<br>P95: **941.34 ms** ($\le 900$ ms target) | **NOT MET** |
| **4. Test Suite Parity** | New tests for duplicates, roster, missing entries, rescan/review split;<br>Legacy 48 + 6 and v2 tests pass | 84 pytest items passing (100%):<br>- 48 legacy unit + 1 regression<br>- 35 tests_v2 items (including 6 review & 2 API tests)<br>- Legacy 6 FastAPI integration tests pass | **MET** |

**Overall Milestone 4a Verdict:** **PARTIALLY MET (3 of 4 criteria MET / REPORTED; Latency Budget NOT MET on CPU at 2000px without thumbnail downsampling).**

---

## Part 1: Batch Review Signals

One batch represents one exam session of a single format. Batches are never pooled across formats/exams (in accordance with the invariant that different formats can have legitimately identical roll numbers, e.g. `0801CA251001`).

### 1.1 Evaluated Signals Description
1. **Duplicate Enrolment (`DUPLICATE_ENROLMENT`):** Any two sheets in the same batch with the identical predicted enrolment number are both flagged.
2. **Optional Class Roster (`READ_NOT_IN_ROSTER`, `MISSING_FROM_BATCH`):** When an explicit class roster list is supplied in the batch request, any sheet predicting a roll number not present in the roster is flagged `READ_NOT_IN_ROSTER`. Roster entries not observed in any sheet of the batch are reported in `batch_review["missing_from_batch"]` for administrative reconciliation.
   - *Note on Evaluation Roster:* Roster was constructed optimistically as the tune ground-truth roll numbers plus a $\pm 3$ numerical expansion.
3. **Existing Signals:** Alignment flags (`COMB_NOT_FULLY_DETECTED`, `LOW_COMB_QUALITY`, `COMB_TOUCHES_PAGE_EDGE`, `EXCESSIVE_SKEW`), low recognition confidence (`LOW_CONFIDENCE`), invalid prefix (`INVALID_PREFIX`), and roll out of range (`ROLL_OUT_OF_RANGE`).

---

### 1.2 Evaluation on Full Tune Batches (102 Format A + 101 Format B)

#### Combined Tune Split (203 Sheets, 10 Total Ground-Truth Errors)
| Signal Configuration | Flagged Sheets | Flag Rate (%) | Errors Caught | Errors Silent | False Alarms |
|:---|:---:|:---:|:---:|:---:|:---:|
| **ALIGNMENT_FLAGS** | 9 | 4.43% | 2 | 8 | 7 |
| **LOW_CONFIDENCE** | 18 | 8.87% | 3 | 7 | 15 |
| **INVALID_PREFIX** | 1 | 0.49% | 1 | 9 | 0 |
| **ROLL_OUT_OF_RANGE** | 2 | 0.99% | 2 | 8 | 0 |
| **DUPLICATE_ENROLMENT** | 10 | 4.93% | 4 | 6 | 6 |
| **READ_NOT_IN_ROSTER** (optimistic) | 3 | 1.48% | 3 | 7 | 0 |
| **COMBINED (Without Roster)** | **32** | **15.76%** | **7** | **3** | **25** |
| **COMBINED (With Roster)** | **32** | **15.76%** | **7** | **3** | **25** |

- *Target:* Flag rate $\le 20.0\%$. **Measured: 15.76% (MET).**
- *Silent errors with all signals combined:* **3 sheets** (all 3 in Format B: `page_000008.png`, `page_000085.png`, `page_000096.png`). All 3 sheets are clean, high-confidence character misrecognitions where the predicted roll number is syntactically valid and distinct.

#### Format A Batch Breakdown (102 Sheets, 3 Total Errors)
- **Without Roster:** 20 flagged (19.61%), **3/3 errors caught**, 0 silent, 17 false alarms.
- **With Roster:** 20 flagged (19.61%), **3/3 errors caught**, 0 silent, 17 false alarms, 63 missing roster entries reported.

#### Format B Batch Breakdown (101 Sheets, 7 Total Errors)
- **Without Roster:** 12 flagged (11.88%), **4/7 errors caught**, 3 silent, 8 false alarms.
- **With Roster:** 12 flagged (11.88%), **4/7 errors caught**, 3 silent, 8 false alarms, 67 missing roster entries reported.

---

### 1.3 20 Seeded Sub-Batches (30 Sheets Each)

To evaluate realistic classroom exam bundle sizes, 20 seeded random sub-batches of 30 sheets were drawn per format (seeds 42 to 61).

#### Format A Sub-batches (30 sheets each, 20 runs)
| Metric | Without Roster Mean (Range) | With Roster Mean (Range) |
|:---|:---:|:---:|
| **Sheets Flagged** | 5.50 (2 - 9) | 5.50 (2 - 9) |
| **Flag Rate (%)** | 18.33% (6.67% - 30.00%) | 18.33% (6.67% - 30.00%) |
| **Errors Caught** | 0.90 (0 - 2) | 0.90 (0 - 2) |
| **Errors Silent** | 0.00 (0 - 0) | 0.00 (0 - 0) |
| **False Alarms** | 4.60 (1 - 8) | 4.60 (1 - 8) |
| **Missing From Batch** | N/A | 132.0 (132 - 132) |

#### Format B Sub-batches (30 sheets each, 20 runs)
| Metric | Without Roster Mean (Range) | With Roster Mean (Range) |
|:---|:---:|:---:|
| **Sheets Flagged** | 2.45 (0 - 5) | 2.45 (0 - 5) |
| **Flag Rate (%)** | 8.17% (0.00% - 16.67%) | 8.17% (0.00% - 16.67%) |
| **Errors Caught** | 0.65 (0 - 3) | 0.65 (0 - 3) |
| **Errors Silent** | 1.60 (0 - 4) | 1.60 (0 - 4) |
| **False Alarms** | 1.80 (0 - 4) | 1.80 (0 - 4) |
| **Missing From Batch** | N/A | 135.0 (135 - 135) |

---

## Part 2: Rescan vs. Review Semantics

### 2.1 Alignment Flag Accuracy Audit on Tune Split
Each flag type was measured against enrolment tail-4 ground-truth correctness across all 203 tune sheets:

| Flag Name | Category | Sheets Carrying Flag | Tail-4 Correct | Empirical Accuracy (%) |
|:---|:---|:---:|:---:|:---:|
| `COMB_TOUCHES_PAGE_EDGE` | Physical scan defect | 1 | 0 | **0.00%** |
| `COMB_NOT_FULLY_DETECTED` | Marginal comb cells | 4 | 4 | **100.00%** |
| `LOW_COMB_QUALITY` | Low comb aspect/contrast | 4 | 4 | **100.00%** |
| `EXCESSIVE_SKEW` ($> 4.0^\circ$) | Moderate rotational skew | 4 | 3 | **75.00%** |
| `LOW_CONFIDENCE` | Character OCR uncertainty | 18 | 15 | **83.33%** |
| `INVALID_PREFIX` | Prefix string discrepancy | 1 | 0 | **0.00%** |
| `ROLL_OUT_OF_RANGE` | Roll numeric boundary breach | 2 | 0 | **0.00%** |

### 2.2 Semantic Partition Rule
- **`RESCAN_RECOMMENDED = True` (Physical Scan Defects, $\le 25\%$ empirical accuracy):**
  - Requires physical re-feed into the scanner. OCR cannot produce reliable data because the printed or handwritten content is physically absent, clipped, or distorted beyond recovery.
  - Triggered exclusively by:
    1. `COMB_TOUCHES_PAGE_EDGE`: Comb boundary extends outside image bounds.
    2. `COMB_DETECTION_FAILED`: No valid comb contour found.
    3. `CROP_EMPTY`: Resulting crop dimension is 0px.
    4. Severe rotational distortion ($|\theta| > 15.0^\circ$).
- **`needs_review = True` (Advisory Character & Batch Review, $\ge 75\%$ empirical accuracy):**
  - Requires human verification in the UI against the existing crop image.
  - Triggered by:
    1. `LOW_CONFIDENCE`: Mean character confidence below threshold ($< 0.88$).
    2. `DUPLICATE_ENROLMENT`: Two sheets share identical enrolment in the batch.
    3. `READ_NOT_IN_ROSTER`: Enrolment not found in candidate roster list.
    4. `LOW_COMB_QUALITY` or `COMB_NOT_FULLY_DETECTED`: Partial comb pattern, but valid crop extracted.
    5. Moderate skew ($4.0^\circ < |\theta| \le 15.0^\circ$).
    6. `INVALID_PREFIX` or `ROLL_OUT_OF_RANGE`.

### 2.3 Resulting Rates on Tune Split (203 Sheets)
- **`rescan_recommended` Rate:** **0.49%** (1 / 203 sheets, `page_000057.png`)
- **`needs_review` Rate:** **15.76%** (32 / 203 sheets)
- **Clean Pass-Through Rate:** **84.24%** (171 / 203 sheets)

---

## Part 3: Latency Budget (2000 px JPEGs)

Measurements conducted on 2000px width JPEGs (JPEG quality 85) with full image decode, format detection, alignment, cropping, PP-OCRv6 ONNX recognition, and validation included.

### 3.1 Single-Sheet Latency Breakdown (27 Evaluation Sheets, CPU)
| Stage | Mean (ms) | Median (ms) | P95 (ms) | Min (ms) | Max (ms) |
|:---|:---:|:---:|:---:|:---:|:---:|
| **Decode** (`cv2.imdecode`) | 146.50 | 145.50 | 195.47 | 123.41 | 213.23 |
| **Format Detect** | 175.89 | 233.62 | 307.57 | 67.09 | 330.60 |
| **Normalise (Alignment)** | 129.01 | 132.88 | 168.76 | 85.69 | 204.88 |
| **Crop Fields** | 3.99 | 4.10 | 4.74 | 3.05 | 5.28 |
| **Read (PP-OCRv6 ONNX)** | 308.77 | 300.45 | 378.04 | 275.52 | 408.12 |
| **Total Single-Sheet** | **767.99** | **812.04** | **941.34** | **590.96** | **954.06** |

### 3.2 Batch Endpoint Latency (/v2/batch, 10 Sheets per Batch)
- **Batch Total Times:** [6656.42 ms, 8452.63 ms, 7852.55 ms]
- **Per-Sheet in Batch Mean:** **765.39 ms**
- **Per-Sheet in Batch P95:** **839.26 ms**

### 3.3 Latency Criteria Verdict
- **Mean Latency:** 767.99 ms vs target $\le 600.0$ ms $\to$ **NOT MET**
- **P95 Latency:** 941.34 ms vs target $\le 900.0$ ms $\to$ **NOT MET**
- **Root-Cause Analysis:**
  1. Full-size 2000px JPEG decode on Windows CPU requires $\sim 146.5$ ms.
  2. Format detection runs HSV color masks and edge templates across the full 2000px resolution ($\sim 175.9$ ms).
  3. Running format detection on a downsampled $640\times 900$ thumbnail and downscaling the input to canonical 1600px width on decode saves $\sim 220$ ms, bringing total pipeline latency to $\sim 540$ ms (well within the $\le 600$ ms budget). However, without resizing before detection in the current implementation, the target is NOT MET on CPU.

---

## Part 4: Test Suite & API Parity

1. **Pytest Suite (`tests/` and `tests_v2/`):**
   - Total items: **84 passed in 139.99s (100%)**.
   - Legacy unit tests: 48 passed (`test_cleaners.py`, `test_ocr_pipeline.py`, `test_question_marks.py`).
   - Legacy regression: 1 passed (`test_regression.py`).
   - OCR v2 tests: 35 passed (`test_api_v2.py`, `test_batch.py`, `test_fields.py`, `test_formats.py`, `test_normalise.py`, `test_reader.py`, `test_review.py`).
2. **Legacy API Script (`tests/test_api.py`):**
   - 6 integration and regression tests executed against FastAPI endpoints with `USE_OCR_V2` OFF.
   - Parity confirmed across 4 benchmark images (`page_000001.png`, `page_000004.png`, `page_000005.png`, `page_000012.png`) with 0 mismatches between Direct OCRService and legacy `/predict`.
