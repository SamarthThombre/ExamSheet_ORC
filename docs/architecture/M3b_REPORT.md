# Milestone 3b Close-Out Report: Pre-Frozen Verification & Alignment Residual Audit

**Author:** OCR v2 Engineering Team  
**Date:** October 4, 2026  
**Status:** Complete  
**Scope:** Verification on the tune split only (203 unperturbed sheets, 60-sheet perturbation subset across 3 new seeds and 0..10° rotation sweeps). **Zero access to frozen test images or ground truth.**

---

## 1. Pre-Registered Criteria & Official Verdicts

| Pre-Registered Criterion | Target | Measured Value | Verdict |
|:---|:---|:---|:---:|
| **Clean-sheet comb residual P95 reported; post-correction ground-truth alignment error at mild P95 $\le 5$ px** | Residual P95 reported;<br>GT Error P95 $\le 5.0$ px | Clean P95: **216.48 px** (A: 105.50 px, B: 246.23 px);<br>Rot Mild P95: **0.644 px**;<br>Comb Mild P95: **0.919 px** | **MET** |
| **Rotation estimator: $\|est - true\| \le 1.0^\circ$ for $\ge 95\%$ of rotation-only runs** | $\ge 95.0\%$ of runs $\le 1.0^\circ$;<br>$\le 5$ runs exceeding $1.0^\circ$ | **61.06%** (403 / 660 runs $\le 1.0^\circ$);<br>257 runs exceeded $1.0^\circ$ | **NOT MET** |
| **Combined moderate over 3 new seeds: mean $\ge 88\%$ and no seed below $80\%$** | Mean $\ge 88.0\%$;<br>$\min \ge 80.0\%$ | Mean: **88.89%**;<br>Range: **[85.00%, 95.00%]** (101: 86.67%, 202: 95.00%, 303: 85.00%) | **MET** |
| **Legacy tests (48 + 6) pass and legacy /predict outputs unchanged** | 48/48 unit + 6/6 API pass;<br>Zero diff on legacy `/predict` | **48/48 unit passed**, **6/6 API passed**;<br>**Zero diff** on page 01, 04, 05, 12 | **MET** |
| **Manifest complete and tag created** | All models, files, pip freeze;<br>frozen tag | Extended manifest with 18 code/config files, 5 ONNX model files, 113 packages | **MET** |

---

## 2. Part 1: Clean-Sheet Alignment Residuals & Crop Margins

### 2.1 Nominal Config Offset vs Ground-Truth Residual Reconciliation
In Milestone 3, a mild-severity residual of $36.65$ px was reported, seemingly contradicting Milestone 2b's claim of $0.0$ px error.
- **Root Cause Reconciliation**:
  1. In Milestone 3, alignment error was calculated by comparing the detected comb corners against the fixed nominal ROI rectangle from `configs/formats/*.yaml` (`[0.520, 0.260, 0.985, 0.360]`). On unperturbed clean scans, the physical printed comb does not match the YAML coordinates exactly due to template printing and scanning offsets ($30$ to $50$ px shift).
  2. In Milestone 2b, the benchmark measured ground-truth perturbation reversal error: applying a known affine transform to the clean image, detecting the comb, reversing the transform, and measuring $\|\text{det\_pts} - \text{true\_transformed\_pts}\|$.
- **Re-measurement against Ground Truth Transformed Corners**:
  - **Rotation-Only Mild ($\pm 3^\circ$)**: Mean = **0.400 px**, P95 = **0.644 px** ($\le 5.0$ px $\rightarrow$ **MET**).
  - **Combined Mild**: Mean = **0.607 px**, P95 = **0.919 px** ($\le 5.0$ px $\rightarrow$ **MET**).

### 2.2 Unperturbed Clean Scans ($N = 203$ tune sheets)
- **Distance to Nominal YAML Coordinates**:
  - **Overall (203 sheets)**: Mean = $74.03$ px, P95 = **$216.48$ px** (Min = $0.0$ px, Max = $265.95$ px).
  - **Format A (102 sheets)**: Mean = $94.55$ px, P95 = **$105.50$ px**.
  - **Format B (101 sheets)**: Mean = $53.31$ px, P95 = **$246.23$ px**.
- **Crop Window Safety Margin**:
  - Minimum Margin: **0.0 px** (0.0 comb cell widths).
  - Mean Margin: **15.74 px** (0.33 comb cell widths).
  - P95 Margin: **26.85 px** (0.56 comb cell widths).

---

## 3. Part 2: Rotation Estimator Evaluation (0° to 10°)

A comprehensive sweep of true rotation angles $0^\circ, 1^\circ, 2^\circ, \dots, 10^\circ$ was evaluated across the 60 tune sheets ($660$ total evaluations).

### 3.1 Overall Angle Estimation Performance
- **Mean Absolute Error (MAE)**: **$1.175^\circ$**
- **Maximum Error**: **$10.00^\circ$**
- **Runs with $\|est - true\| \le 1.0^\circ$**: **403 / 660 (61.06%)** [Target $\ge 95.0\%$ $\rightarrow$ **NOT MET**]
- **Runs exceeding $1.0^\circ$ error**: **257 runs**
- **Sheets with true rotation $> 4.0^\circ$ NOT flagged for RESCAN**: **26 / 360 (7.22%)** (92.78% correctly flagged `RESCAN_RECOMMENDED`).

### 3.2 Accuracy & Rescan Rate by True Angle

| True Angle ($^\circ$) | Sample Count | Enrolment Tail-4 Accuracy (%) | Rescan Flagged Rate (%) |
|:---:|:---:|:---:|:---:|
| **0.0** | 60 | 96.67% | 1.67% |
| **1.0** | 60 | 93.33% | 1.67% |
| **2.0** | 60 | 95.00% | 8.33% |
| **3.0** | 60 | 90.00% | 35.00% |
| **4.0** | 60 | 83.33% | 76.67% |
| **5.0** | 60 | 66.67% | 93.33% |
| **6.0** | 60 | 45.00% | 93.33% |
| **7.0** | 60 | 28.33% | 95.00% |
| **8.0** | 60 | 16.67% | 93.33% |
| **9.0** | 60 | 5.00% | 91.67% |
| **10.0** | 60 | 1.67% | 90.00% |

### 3.3 Accuracy by Estimated Angle Bin & Diagnosis of 0-1° Bin

| Estimated Bin ($^\circ$) | Sample Count | Avg True Angle ($^\circ$) | Enrolment Tail-4 Accuracy (%) |
|:---:|:---:|:---:|:---:|
| **0 - 1** | **75** | **2.73** | **65.33%** |
| **1 - 2** | 58 | 0.98 | 93.10% |
| **2 - 3** | 61 | 1.87 | 96.72% |
| **3 - 4** | 58 | 2.90 | 93.10% |
| **4 - 5** | 61 | 3.82 | 91.80% |
| **5 - 6** | 59 | 4.83 | 76.27% |
| **6 - 7** | 57 | 5.81 | 59.65% |
| **7 - 8** | 59 | 6.81 | 30.51% |
| **8 - 9** | 56 | 7.79 | 5.36% |
| **9 - 10** | 51 | 8.78 | 1.96% |

#### Root Cause Analysis of the 0-1° Bin Anomaly:
1. **Contour Collapse at Extreme Angles**: When true rotation exceeds $6^\circ$, color-thresholding of red comb lines occasionally fragments the comb structure. `cv2.minAreaRect` fails to detect the full 12-cell bounding contour and falls back to a neutral $0^\circ$ rotation without deskewing, pulling sheets with true $6..10^\circ$ angles into the estimated $0-1^\circ$ bin (hence average true angle = $2.73^\circ$).
2. **Clean Baseline Failures**: 10 distinct sheets (`page_000029`, `page_000041`, `page_000046`, `page_000050`, `page_000083`, `page_000102`, `page_000103`, `page_000111`, `page_000114`, `page_000143`) have intrinsic digit ambiguities or prefix artifacts that fail on clean unperturbed scans at $0^\circ$.

---

## 4. Part 3: Noise Level Evaluation across 3 New Seeds

To confirm that M3 robustness results were not an artifact of random seed choice, combined moderate perturbations were evaluated across 3 completely new random seeds (101, 202, 303) on the 60 tune sheets:

| Perturbation Condition | Seed 101 | Seed 202 | Seed 303 | Mean Accuracy | Range | Target Met? |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Combined Moderate** | 86.67% (52/60) | 95.00% (57/60) | 85.00% (51/60) | **88.89%** | **[85.00%, 95.00%]** | **MET** (Mean $\ge 88.0\%$, Min $\ge 80.0\%$) |
| **Combined Mild** | 90.00% (54/60) | 93.33% (56/60) | 93.33% (56/60) | **92.22%** | **[90.00%, 93.33%]** | Exceeds moderate baseline |

---

## 5. Part 4: Legacy Regression & Extended Manifest

### 5.1 Legacy Test Suite Pass Rate
- Ran `tests/test_api.py` with `USE_OCR_V2=0`: **6 / 6 passed (100%)**.
- Ran full legacy test suite `pytest tests/`: **48 / 48 passed (100%)**.
- Evaluated legacy `/predict` response JSON against pre-M3 outputs on `page_000001.png`, `page_000004.png`, `page_000005.png`, `page_000012.png`: **0 byte / semantic differences**.

### 5.2 Extended Cryptographic Manifest (`v2_checksum_manifest.json`)
The manifest at `experiments/m3/v2_checksum_manifest.json` was extended to include:
- **18 Code & Config Files**: Tracked with SHA-256 and byte size.
- **5 Official ONNX Model Files**:
  - `PP-OCRv6_medium_rec_onnx/inference.onnx` (72,130,229 bytes, SHA-256: `6e60b29...`)
  - `PP-OCRv6_medium_rec_onnx/inference.pdiparams` (49,504,784 bytes)
  - Config and model metadata JSON/YML files.
- **113 Environment Packages**: Complete `pip freeze` snapshot captured.
- **Tag Reference**: Captured `v2-frozen-candidate` metadata.

---

## 6. Part 5: Frozen Acceptance Preparation

- Full Wilson score interval table for $N=88$ and $N=44$ compiled in [FROZEN_ACCEPTANCE.md](file:///c:/Users/sumit/Desktop/Samarth/python/exam_paper_extractor/docs/architecture/FROZEN_ACCEPTANCE.md).
- Updated [evaluation/frozen_v2.py](file:///c:/Users/sumit/Desktop/Samarth/python/exam_paper_extractor/evaluation/frozen_v2.py) acceptance section to compute teacher review rates, silent error rates, dual-mode subject code consensus, and per-format breakdowns.
- `evaluation/frozen_v2.py` has **NOT** been executed.
