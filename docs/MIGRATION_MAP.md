# RESTRUCTURING MIGRATION MAP

This document maps all original files to their target modular locations, explaining the rationale, import adjustments, and behavior preservation for each file.

---

## 1. Core OCR Engine Modularization

| Original Path | Target Path | Rationale & Responsibility | Import Changes | Behavior Changed? |
| :--- | :--- | :--- | :--- | :---: |
| `scripts/image_croping.py` (fallbacks) | `ocr/detection/fallbacks.py` | Isolate layout geometry fallbacks for `enrolment_no` and `grand_total`. | None | **NO** |
| `scripts/image_croping.py` (divider) | `ocr/recognition/divider.py` | Isolate red divider boundary detection algorithm. | None | **NO** |
| `scripts/image_croping.py` (cropping) | `ocr/recognition/cropper.py` | Isolate field cropping, padding, and companion crop generation. | Imports `divider.py`, `fallbacks.py` | **NO** |
| `app/services/ocr_service.py` (paddle engine) | `ocr/recognition/paddle_engine.py` | Encapsulate PaddleOCR initialization, CPU flags, and torch isolation hook. | None | **NO** |
| `text_regex_cleaning.py` (cleaners) | `ocr/postprocessing/cleaning.py` | Strategy B regex cleaning for `enrolment_no`, `subject_code`, `total_marks`. | None | **NO** |
| `text_regex_cleaning.py` (word parser) | `ocr/postprocessing/word_parser.py` | English words-to-number parser (`parse_marks_in_words`). | None | **NO** |
| `text_regex_cleaning.py` (fusion) | `ocr/postprocessing/fusion.py` | Dual-source total marks fusion engine (`combine_grand_total_and_words`). | Imports `cleaning.py`, `word_parser.py` | **NO** |
| `app/services/ocr_service.py` (sanity) | `ocr/validation/sanity.py` | Format & range sanity validator, assigning `needs_review` flags without mutating data. | None | **NO** |
| `app/services/ocr_service.py` (orchestrator) | `ocr/pipeline.py` | Top-level `OCREngine` orchestrator coordinating detection, crops, OCR, fusion, and sanity. | Imports `ocr.*` submodules | **NO** |
| `app/services/ocr_service.py` | `app/services/ocr_service.py` | Retained as backward-compatible singleton adapter delegating to `ocr.pipeline.OCREngine`. | Imports `ocr.pipeline.OCREngine` | **NO** |

---

## 2. Evaluation & Benchmarking Modularization

| Original Path | Target Path | Rationale & Responsibility | Import Changes | Behavior Changed? |
| :--- | :--- | :--- | :--- | :---: |
| `compare_cleaned_vs_verified.py` | `evaluation/benchmark.py` | Reusable 146-page benchmark runner evaluating accuracy across all fields. | Imports `evaluation.metrics` | **NO** |
| `compare_cleaned_vs_verified.py` (scoring) | `evaluation/metrics.py` | Standalone metric computation (page-level, field-level, confusion matrix). | None | **NO** |
| `cleaned_ocr_results.csv` | `evaluation/reports/cleaned_ocr_results.csv` | Move generated output CSV out of root. | Updated file paths | **NO** |
| `comparison_report.csv` | `evaluation/reports/comparison_report.csv` | Move generated comparison report CSV out of root. | Updated file paths | **NO** |
| `test/before_cleaned_ocr_results.csv` | `evaluation/reports/baseline_cleaned_ocr_results.csv` | Archive baseline benchmark snapshot. | None | **NO** |
| `test/before_comparison_report.csv` | `evaluation/reports/baseline_comparison_report.csv` | Archive baseline benchmark comparison snapshot. | None | **NO** |

---

## 3. Data & Models Organization

| Original Path | Target Path | Rationale & Responsibility | Import Changes | Behavior Changed? |
| :--- | :--- | :--- | :--- | :---: |
| `data/verified_labels - Copy.csv` | `data/canonical_labels.csv` | Standardize ground-truth filename (with backward-compatible symlink/copy). | None | **NO** |
| `data.yaml` | `configs/data.yaml` | Centralize YOLO dataset split configuration. | Path updated in training script | **NO** |
| `classes.txt` | `configs/classes.txt` | Centralize class labels. | None | **NO** |
| `models/best.pt` | `models/detector/v1_best.pt` | Standardize model versioning under `models/detector/` (with fallback to `models/best.pt`). | Centralized via `app/config.py` | **NO** |

---

## 4. Tests Organization

| Original Path | Target Path | Rationale & Responsibility | Import Changes | Behavior Changed? |
| :--- | :--- | :--- | :--- | :---: |
| `test/test_api.py` | `tests/test_api.py` | Formal automated test suite for FastAPI backend endpoints & regression. | Imports `app.main` | **NO** |
| `test/verify_integration.py` | `tests/test_regression.py` | Formal regression test validating 100% parity against baseline. | Updated benchmark paths | **NO** |

---

## 5. Experimental Scripts & Artifacts Archival

| Original Path | Target Path | Rationale & Responsibility | Import Changes | Behavior Changed? |
| :--- | :--- | :--- | :--- | :---: |
| `test/marks_fusion_experiment.py` | `experiments/trials/marks_fusion_experiment.py` | Archive original sandbox fusion prototype. | None | **NO** |
| `test/experimental_parsers.py` | `experiments/trials/experimental_parsers.py` | Archive exploratory regex variations. | None | **NO** |
| `test/run_experiments.py` | `experiments/trials/run_experiments.py` | Archive sweep runner. | None | **NO** |
| `test/analyze_failures.py` | `experiments/trials/analyze_failures.py` | Archive scratch failure analyzer. | None | **NO** |
| `test/investigate_boxes_and_dividers.py` | `experiments/trials/investigate_boxes_and_dividers.py` | Archive red divider exploratory script. | None | **NO** |
| `test/make_visual_report.py` | `experiments/trials/make_visual_report.py` | Archive HTML visual report generator. | None | **NO** |
| `test/generate_experimental_ocr.py` | `experiments/trials/generate_experimental_ocr.py` | Archive cache generator script. | None | **NO** |
| `test/audit_flagged.py` | `experiments/trials/audit_flagged.py` | Archive audit tool. | None | **NO** |
| `test/audit_unflagged.py` | `experiments/trials/audit_unflagged.py` | Archive audit tool. | None | **NO** |
| `test/evaluate_fusion_benchmark.py` | `experiments/trials/evaluate_fusion_benchmark.py` | Archive fusion evaluation script. | None | **NO** |
| `test/sample_crops/` | `experiments/sample_crops/` | Archive sample crops used during debugging. | None | **NO** |
| `notebooks/*.ipynb` | `experiments/notebooks/*.ipynb` | Archive historical Colab exploration notebooks. | None | **NO** |
| `prepare_dataset.py` (root copy) | *Removed (Redundant)* | Duplicate of `scripts/prepare_dataset.py`. | None | **NO** |
| `123.jpeg` (root copy) | `assets/demo_page.jpeg` | Move stray root image to assets. | None | **NO** |
