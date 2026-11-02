# Multi-Suite Benchmark Architecture

## 1. Overview

The Exam Paper OCR Extractor supports two distinct formal benchmark suites to validate extraction reliability, accuracy, and generalization across diverse exam cover sheet formats without regression:

```text
                                Benchmark Runner
                        (evaluation/benchmarks/run.py)
                                      │
                   ┌──────────────────┴──────────────────┐
                   ↓                                     ↓
              Benchmark A                           Benchmark B
        data/canonical_labels.csv             data/canonical_labels_v2.csv
           (146 images, Format A)                (145 images, Format B)
                   │                                     │
                   └──────────────────┬──────────────────┘
                                      ↓
                             Shared OCR Pipeline
                          (Format-Aware Geometry)
```

---

## 2. Benchmark Suite Definitions

| Suite | Dataset Directory | Image Count | Cover Format | Canonical Ground Truth | Target Fields |
| :--- | :--- | :---: | :--- | :--- | :--- |
| **Benchmark A** | `data/raw/images/` | 146 | Original university exam cover sheet | `data/canonical_labels.csv` | `enrollment_no`, `subject_code`, `total_marks` |
| **Benchmark B** | `data/data_v2_images/` | 145 | Format V2 (32-Page Main Answer Book) | `data/canonical_labels_v2.csv` | `enrollment_no`, `subject_code` |

---

## 3. Benchmark Execution Commands

The unified benchmark CLI runner allows independent selection and evaluation of each benchmark:

### Run Benchmark A (Original Dataset Regression Suite)
```bash
python -m evaluation.benchmarks.run --dataset benchmark_a
```
* **Output Artifacts:** `evaluation/reports/benchmark_a/` (`summary.md`, `latest_benchmark_report.csv`, `mismatches.csv`)
* **Behavior:** Compares extracted predictions against frozen 146-page baseline. Asserts **0 new regressions**.

### Run Benchmark B (New Format V2 Suite)
```bash
python -m evaluation.benchmarks.run --dataset benchmark_b
```
* **Output Artifacts:** `evaluation/reports/benchmark_b/` (`summary.md`, `errors.csv`)
* **Behavior:** Reads extractions, reports operational metrics (YOLO detection rate, fallback usage, defaulting rate). When ground-truth labels are present in `data/canonical_labels_v2.csv`, calculates exact field accuracies.

---

## 4. Ground-Truth Invariants & Integrity Rule

* Ground-truth labels must be verified by a human annotator.
* Confidence scores, regex-cleaned text, and defaulted values must **never** be treated as ground truth.
* No pseudo-accuracy is calculated for Benchmark B until verified labels are recorded via `scripts/label_benchmark_b.py`.
