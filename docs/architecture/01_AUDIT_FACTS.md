# System Audit & Repository Facts

## 1. Inventory

| File Path | One-Line Purpose | Category | Imported By | In Live `/predict`? |
| :--- | :--- | :---: | :--- | :---: |
| `app/main.py` | FastAPI application entrypoint, routes (`/health`, `/predict`), error handlers | SOURCE | None (ASGI root) | Yes |
| `app/config.py` | Configuration settings loaded from environment variables with defaults | CONFIG | `app.main`, `app.services.ocr_service` | Yes |
| `app/schemas.py` | Pydantic response and error data models | SOURCE | `app.main` | Yes |
| `app/services/ocr_service.py` | Service adapter wrapping `OCREngine` as a singleton for FastAPI | SOURCE | `app.main` | Yes |
| `ocr/pipeline.py` | Orchestrates YOLO detection, cropping, OCR, cleaning, fusion, and validation | SOURCE | `app.services.ocr_service`, `tests.*` | Yes |
| `ocr/detection/detector.py` | `YOLOFieldDetector` wrapper around Ultralytics YOLOv8 | SOURCE | `ocr.pipeline`, scripts | Yes |
| `ocr/detection/fallbacks.py` | Deterministic geometric crop fallbacks for missing YOLO detections | SOURCE | `ocr.pipeline`, `ocr.recognition.cropper` | Yes |
| `ocr/recognition/cropper.py` | `FieldCropper` methods for padded crops and companion crops | SOURCE | `ocr.pipeline` | Yes |
| `ocr/recognition/divider.py` | Detects vertical red dividing line between table and words | SOURCE | `ocr.recognition.cropper` | Yes |
| `ocr/recognition/paddle_engine.py` | Manages PaddleOCR engine lifecycle and single-crop OCR inference | SOURCE | `ocr.pipeline`, `ocr.postprocessing.question_marks` | Yes |
| `ocr/postprocessing/cleaning.py` | Strategy B normalizers for enrollment, subject code, and total marks | SOURCE | `ocr.pipeline`, `ocr.postprocessing.fusion`, `evaluation.*` | Yes |
| `ocr/postprocessing/fusion.py` | Dual-source total marks fusion (primary numeric, tightened, words) | SOURCE | `ocr.pipeline`, `evaluation.*` | Yes |
| `ocr/postprocessing/word_parser.py` | Parser for English number words written in marks-in-words box | SOURCE | `ocr.postprocessing.fusion` | Yes |
| `ocr/postprocessing/question_marks.py` | Table row detector, cell cropper, and per-question score extractor | SOURCE | `ocr.pipeline` | Yes |
| `ocr/validation/sanity.py` | Rule-based bounds and format validator setting `needs_review` | SOURCE | `ocr.pipeline` | Yes |
| `data.yaml` | Dataset definition for YOLOv8 training (3 classes) | CONFIG | Ultralytics YOLO CLI/trainer | No |
| `models/registry.json` | Metadata declaration for model artifacts and versions | CONFIG | Documentation / Tooling | No |
| `requirements.txt` | Top-level project Python package dependencies | CONFIG | pip installer | No |
| `evaluation/benchmark.py` | Benchmark A 146-page regression evaluation harness | EVALUATION | `evaluation.benchmarks.run`, `tests.test_regression` | No |
| `evaluation/benchmarks/config.py` | Centralized suite configurations for Benchmark A and B | EVALUATION | `evaluation.benchmarks.run` | No |
| `evaluation/benchmarks/run.py` | Unified CLI runner supporting `--dataset benchmark_a|benchmark_b` | EVALUATION | Standalone CLI | No |
| `evaluation/metrics.py` | Accuracy metrics calculation and string normalization utilities | EVALUATION | `evaluation.benchmark`, `evaluation.benchmarks.run` | No |
| `evaluation/test_backend_5images.py` | Smoke evaluation script against live HTTP server | EVALUATION | Standalone CLI | No |
| `tests/test_api.py` | Functional integration tests for FastAPI HTTP routes | TEST | Standalone CLI (`run_all_tests`) | No |
| `tests/test_cleaners.py` | Unit tests for Strategy B cleaners, word parser, fusion, and validator | TEST | unittest runner | No |
| `tests/test_ocr_pipeline.py` | Tests for cropper bounding box clipping and divider detection | TEST | unittest runner | No |
| `tests/test_question_marks.py` | Tests for table line detection, text parsing, and contracts | TEST | unittest runner | No |
| `tests/test_regression.py` | Regression test asserting zero regressions against 146-page baseline | TEST | unittest runner | No |
| `test_ocr.py` | Legacy root-level OCR integration test script | TEST | Standalone CLI | No |
| `profile_pipeline.py` | Profiling harness measuring latencies across pipeline stages | SCRIPT | Standalone CLI | No |
| `run_new_batch.py` | Standalone batch extraction script for Format V2 images | SCRIPT | Standalone CLI | No |
| `scripts/reextract_format_v2_fallbacks.py` | Targeted recovery script for Format V2 fallback crops | SCRIPT | Standalone CLI | No |
| `scripts/label_benchmark_b.py` | Interactive CLI labeling tool for Benchmark B | SCRIPT | Standalone CLI | No |
| `scripts/train_yolo.py` | Wrapper script invoking YOLOv8 training | SCRIPT | Standalone CLI | No |
| `scripts/convert_xml_to_yolo.py` | Converts Pascal VOC XML bounding box annotations to YOLO format | SCRIPT | Standalone CLI | No |
| `scripts/extract_pdf_pages.py` | Converts raw exam booklet PDF pages into PNG images | SCRIPT | Standalone CLI | No |
| `scripts/prepare_dataset.py` | Splits raw images and annotations into train/val subsets | SCRIPT | Standalone CLI | No |
| `scripts/image_croping.py` | Legacy YOLO inference and cropping script | SCRIPT | Standalone CLI | No |
| `scripts/infer_crop.py` | YOLO inference utility script | SCRIPT | Standalone CLI | No |
| `text_regex_cleaning.py` | Monolithic legacy postprocessing script | SCRIPT | Standalone CLI | No |
| `compare_cleaned_vs_verified.py` | CSV comparison utility against verified labels | SCRIPT | Standalone CLI | No |
| `models/best.pt` | Fine-tuned YOLOv8n weights (6.05 MB) | MODEL | `ocr.detection.detector` | Yes |
| `models/best.onnx` | Exported ONNX model of field detector (11.85 MB) | MODEL | Unused in production | No |
| `models/yolov8n.pt` | Base Ultralytics YOLOv8n checkpoint (6.25 MB) | MODEL | `scripts.train_yolo` | No |
| `data/canonical_labels.csv` | Ground truth labels for 146 Benchmark A cover sheets | DATA | `evaluation.benchmark`, `tests.test_regression` | No |
| `data/canonical_labels_v2.csv` | Ground truth labels for 145 Benchmark B cover sheets | DATA | `evaluation.benchmarks.run` | No |

---

## 2. Import Graph

### Live `/predict` Route Call Graph
```
app.main (predict_exam_page, line 157)
  ├── app.config.settings (line 14)
  ├── app.schemas (PredictResponse, ExtractionResult, ProcessingMeta, line 15)
  └── app.services.ocr_service.ocr_service (line 22)
        └── ocr.pipeline.OCREngine (line 13)
              ├── ocr.detection.detector.YOLOFieldDetector (line 14)
              │     └── ultralytics.YOLO (line 34, lazy loaded)
              ├── ocr.detection.fallbacks.get_enrolment_no_crop (line 15)
              ├── ocr.recognition.cropper.FieldCropper (line 16)
              │     ├── ocr.recognition.divider.detect_red_divider_x (line 11)
              │     └── ocr.detection.fallbacks.get_grand_total_fallback_box (line 12)
              ├── ocr.recognition.paddle_engine.PaddleOCREngine (line 17)
              │     └── paddleocr.PaddleOCR (line 50, isolated find_spec wrapper)
              ├── ocr.postprocessing.cleaning (line 18)
              │     ├── fix_enrollment_no
              │     ├── fix_total_marks
              │     └── clean_single_subject_code
              ├── ocr.postprocessing.fusion.combine_grand_total_and_words (line 23)
              │     ├── ocr.postprocessing.cleaning.fix_total_marks (line 10)
              │     ├── ocr.postprocessing.cleaning.parse_tightened_gt (line 10)
              │     └── ocr.postprocessing.word_parser.parse_marks_in_words (line 11)
              ├── ocr.postprocessing.question_marks.QuestionMarksExtractor (line 24)
              └── ocr.validation.sanity.SanityValidator.validate_fields (line 25)
```

- **Production Leaks**: Production code (`app/`, `ocr/`) contains **zero** imports into `scripts/`, `experiments/`, `notebooks/`, or `evaluation/`.
- **Hardcoded Paths in Production**: Production code contains **zero** absolute Windows file paths. Model path resolution is centralized in `app/config.py` line 21 via `BASE_DIR / "models" / "best.pt"`.

---

## 3. Live Request Trace

Step-by-step trace from `POST /predict` (`app/main.py:157`) to HTTP response:

| Step | Function | File:Line | Action / Model Invoked | Execution Mode | Measured Time (Avg) |
| :---: | :--- | :--- | :--- | :---: | :---: |
| 1 | `predict_exam_page` | `app/main.py:177` | Validates file extension against `{'.jpg', '.jpeg', '.png', '.webp'}` | Always | <0.1 ms |
| 2 | `predict_exam_page` | `app/main.py:187` | Reads payload, verifies bytes between 100 B and 25 MB (`MAX_UPLOAD_SIZE_MB`) | Always | ~0.5 ms |
| 3 | `cv2.imdecode` | `app/main.py:212` | Decodes byte buffer into BGR NumPy array | Always | 0.198 s (`PROFILE_REPORT.md:92`) |
| 4 | `OCREngine.process_image` | `ocr/pipeline.py:94` | Defensively normalizes image to 3-channel BGR; checks $H, W \ge 200$ | Always | <0.1 ms |
| 5 | `YOLOFieldDetector.detect_fields` | `ocr/pipeline.py:106` | Runs YOLOv8n inference (`models/best.pt`) at `imgsz=1280`, `conf=0.30` | Always | 0.950 s (`PROFILE_REPORT.md:92`) |
| 6 | `get_enrolment_no_crop` | `ocr/pipeline.py:119` | Checks YOLO `enrolment_no` box; falls back to format_original box if missing | Always | <0.1 ms |
| 7 | `PaddleOCREngine.ocr_crop` | `ocr/pipeline.py:125` | **OCR Call 1**: reads `enrolment_no` crop | Always | 8.590 s (`PROFILE_REPORT.md:35`) |
| 8 | `FieldCropper.crop_padded_box` | `ocr/pipeline.py:132` | Crops `subject_code` if detected by YOLO | Conditional | <0.1 ms |
| 9 | `PaddleOCREngine.ocr_crop` | `ocr/pipeline.py:138` | **OCR Call 2**: reads `subject_code` crop | Conditional (YOLO hit) | 5.222 s (`PROFILE_REPORT.md:37`) |
| 10 | `FieldCropper.crop_padded_box` | `ocr/pipeline.py:146` | Crops primary `grand_total` if detected by YOLO | Conditional | <0.1 ms |
| 11 | `PaddleOCREngine.ocr_crop` | `ocr/pipeline.py:152` | **OCR Call 3**: reads primary `grand_total` crop | Conditional (YOLO hit) | 4.226 s (`PROFILE_REPORT.md:38`) |
| 12 | `get_grand_total_and_companion_crops` | `ocr/pipeline.py:163` | Runs divider detection (`detect_red_divider_x`), produces tightened GT and words crops | Always | 0.004 s (`PROFILE_REPORT.md:92`) |
| 13 | `PaddleOCREngine.ocr_crop` | `ocr/pipeline.py:172` | **OCR Call 4**: reads `grand_total_tightened` crop | Always | 3.705 s (`PROFILE_REPORT.md:41`) |
| 14 | `PaddleOCREngine.ocr_crop` | `ocr/pipeline.py:173` | **OCR Call 5**: reads `marks_in_words` crop | Always | 5.906 s (`PROFILE_REPORT.md:36`) |
| 15 | `fix_enrollment_no` | `ocr/pipeline.py:183` | Normalizes roll number via CA25 anchor and digit lookalike repairs | Always | <0.5 ms |
| 16 | `clean_single_subject_code` | `ocr/pipeline.py:187` | Normalizes institutional subject code | Always | <0.2 ms |
| 17 | `combine_grand_total_and_words` | `ocr/pipeline.py:192` | Fuses numeric GT, tightened GT, and words OCR | Always | 0.001 s (`PROFILE_REPORT.md:92`) |
| 18 | `SanityValidator.validate_fields` | `ocr/pipeline.py:203` | Evaluates bounding rules, sets `needs_review` flag | Always | <0.1 ms |
| 19 | `QuestionMarksExtractor.extract_question_marks` | `ocr/pipeline.py:212` | Detects table grid; performs **10.8 OCR calls** on Q1-Q5 cells; verifies row sum | Always | 22.204 s (`PROFILE_REPORT.md:34`) |
| 20 | `PredictResponse` | `app/main.py:237` | Constructs Pydantic response model and returns JSON | Always | <0.5 ms |

Total average request time: **51.10 seconds** (`PROFILE_REPORT.md:15`).

---

## 4. Field-by-Field Actual Behaviour

| Field | Localisation Method | OCR Crop Name & Target | Cleaning / Normalisation Pipeline | Hardcoded Defaults / Constants | Failure Mode in JSON |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `enrollment_no` / `rollno` | YOLO `enrolment_no` (`conf>=0.30`). Bounds check: $0.20H \le y_1 \le 0.42H$, $0.40W \le x_1 \le 0.75W$. Fallback: `[0.52W, 0.26H, 0.985W, 0.36H]` (`fallbacks.py:84`). | `enrolment_no` ($251 \times 1141$ px) | `_strip_enrollment_label` $\to$ inverted 180° check $\to$ forward CA25 anchor $\to$ digit lookalikes $\to$ reverse anchor $\to$ legacy suffix (`cleaning.py:177`). | Prefix `"0801CA25"` (`cleaning.py:212, 235, 240`). | `null`, sets `needs_review: true`. |
| `subject_code` | YOLO `subject_code` (`conf>=0.30`). If YOLO misses, crop is `None` (`pipeline.py:141`). Fallback in `fallbacks.py:30` exists but is **not called** in `pipeline.py`. | `subject_code` ($188 \times 902$ px) | `clean_single_subject_code`: strips headers/metadata $\to$ lookalike mapping (`+`$\to$`7`, `/`$\to$`1`) $\to$ direct code checks $\to$ institutional regex (`cleaning.py:246`). | Default `"CT10718"` (`cleaning.py:246`). | Defaults silently to `"CT10718"`. |
| `total_marks` | YOLO `grand_total` (`conf>=0.30`, `pipeline.py:146`). | `grand_total` ($134 \times 896$ px) | `fix_total_marks`: strips labels $\to$ lookalike mapping $\to$ equation evaluation $\to$ rounding checks $\to$ single digit range check (`cleaning.py:99`). | `max_marks = 70` (`cleaning.py:99`). | `null`. |
| `total_marks_corrected` | Dual crops: tightened GT via `detect_red_divider_x` (`cropper.py:34`) + companion words crop (`x1_gt - 0.28W`, `cropper.py:65`). | `grand_total_tightened` ($181 \times 829$ px) & `marks_in_words` ($248 \times 792$ px) | `combine_grand_total_and_words`: tri-source agreement logic (primary, tight, words) $\to$ fallback recovery $\to$ conflict flagging (`fusion.py:33`). | Word parser threshold `0.70` (`word_parser.py:80`). Max marks `70`. | `null` if all fail; sets `needs_review: true`. |
| `question_marks` | Geometric table grid: horizontal lines detected via morphological opening from $0.48H$ to grand total $y_1$ (`question_marks.py:30, 93`). | Separate crop per table cell (avg 10.8 calls/page, $71 \times 496$ px) | `_parse_marks_text`: regex digit parsing $\to$ lookalike mapping $\to$ sum verification against `total_marks_corrected` (`question_marks.py:180`). | Table start $0.48H$; columns: Q `[0.05W, 0.20W]`, Marks `[0.20W, 0.50W]`. | Empty list `[]`, `sum_extracted: null`, sets `needs_review: true` on mismatch. |

---

## 5. Format Handling

- **Automatic Detection**: **None**. The codebase has no format classifier or automatic booklet discriminator.
- **Production Routing**: `ocr/pipeline.py` line 119 calls `get_enrolment_no_crop(img, enrolment_box_xyxy=enrol_box, padding_ratio=self.padding_ratio)`. Because `format_name` is omitted, it defaults to `"format_original"` (`ocr/detection/fallbacks.py:37`).
- **Benchmark / Utility Routing**: Format V2 geometry is selected **manually** by passing `format_name="format_v2"` in offline utility scripts:
  - `run_new_batch.py:368`
  - `scripts/reextract_format_v2_fallbacks.py:65`
- **Result**: In production `/predict`, Format V2 exam booklets are evaluated against Format 1 geometric boundaries ($y_2=0.360\cdot H$), resulting in vertical clipping of enrollment numbers unless YOLO hits.

---

## 6. Duplication

| Component A | Component B | Equivalent? | Used in Live `/predict` | Used in Benchmarks / Offline |
| :--- | :--- | :---: | :--- | :--- |
| `ocr/postprocessing/cleaning.py:clean_single_subject_code` | `ocr/postprocessing/cleaning.py:fix_subject_code` | No (regex single crop vs batch-mode majority vote) | `clean_single_subject_code` (`pipeline.py:187`) | `fix_subject_code` used in batch evaluation (`benchmark.py:108`) |
| `ocr/postprocessing/cleaning.py:fix_enrollment_no` | `ocr/postprocessing/cleaning.py:legacy_fix_enrollment_no` | No (anchor-based parser vs legacy 4-char suffix mapper) | `fix_enrollment_no` (`pipeline.py:183`) | `legacy_fix_enrollment_no` invoked as fallback (`cleaning.py:242`) |
| `ocr/postprocessing/cleaning.py:fix_total_marks` | `ocr/postprocessing/cleaning.py:legacy_fix_total_marks` | No (equation/rounding parser vs naive regex digit finder) | `fix_total_marks` (`pipeline.py:189`) | `legacy_fix_total_marks` invoked as fallback (`cleaning.py:188`) |
| `ocr/pipeline.py:OCREngine` | `profile_pipeline.py:ProfilingOCREngine` | Subclass (adds timing wrappers around each method) | `OCREngine` (`ocr_service.py:27`) | `ProfilingOCREngine` (`profile_pipeline.py:62`) |
| `ocr/pipeline.py:OCREngine` | `run_new_batch.py` | Partially (re-implements crop and OCR loop imperatively) | `OCREngine` | `run_new_batch.py:358` |
| `ocr/postprocessing/cleaning.py` | `text_regex_cleaning.py` | Yes (legacy monolithic script predating refactoring) | `ocr/postprocessing/cleaning.py` | Dead code / unimported |
| `ocr/recognition/cropper.py:FieldCropper` | `scripts/image_croping.py` | Yes (duplicate box padding and cv2 cropping logic) | `FieldCropper` | Standalone script |

---

## 7. Mixed Responsibilities

- **`ocr.pipeline:OCREngine.process_image` (`ocr/pipeline.py:64`)**:
  Mixes: 1) image decoding & channel validation, 2) YOLO detection execution, 3) fallback bounding coordinate calculation, 4) multi-crop PaddleOCR orchestration, 5) postprocessing/cleaning invocation, 6) dual-source score fusion, 7) sanity validation, 8) table line segmentation & question marks extraction, and 9) output dictionary formatting.
- **`ocr.recognition.cropper:FieldCropper.get_grand_total_and_companion_crops` (`ocr/recognition/cropper.py:34`)**:
  Mixes: 1) spatial array slicing, 2) image color processing (calling `detect_red_divider_x`), 3) geometric bounding box projection for words, and 4) fallback coordinates retrieval.
- **`ocr.postprocessing.question_marks:QuestionMarksExtractor.extract_question_marks` (`ocr/postprocessing/question_marks.py:53`)**:
  Mixes: 1) image thresholding & morphological filtering for table lines, 2) cell coordinate math, 3) sequential OCR engine calls, 4) text regex parsing, 5) arithmetic cross-validation against grand total, and 6) status decision logic.
- **`ocr.postprocessing.cleaning:fix_total_marks` (`ocr/postprocessing/cleaning.py:99`)**:
  Mixes: 1) OCR string noise cleaning, 2) character lookalike substitution, 3) arithmetic expression parsing and calculation (`add_sum = a + b`), and 4) LHS vs RHS rounding equality verification.
- **`app.main:predict_exam_page` (`app/main.py:157`)**:
  Mixes: 1) HTTP multipart parsing & validation, 2) file extension and byte buffer validation, 3) cv2 image decoding, 4) service layer execution, 5) performance timing calculation, and 6) JSON response serialization.

---

## 8. Hardcoded Values

| Hardcoded Value | File:Line | Category | Purpose |
| :--- | :--- | :--- | :--- |
| `"0801CA25"` | `ocr/postprocessing/cleaning.py:49, 212, 235, 240` | Prefix | Hardcoded institutional roll number prefix prepended to all student roll numbers |
| `"CT10718"` | `ocr/postprocessing/cleaning.py:246, 268, 282, 302` | Default | Default subject code returned when detection or parsing fails |
| `"CT10715"` | `ocr/postprocessing/cleaning.py:266, 280` | Constant | Specific target subject code for Format V2 |
| `max_marks = 70` | `ocr/postprocessing/cleaning.py:99` | Limit | Upper bound for valid exam marks |
| `0 <= numeric_marks <= 70` | `ocr/validation/sanity.py:61` | Limit | Sanity validation range for total marks |
| `r"^0801CA25\d{4}$"` | `ocr/validation/sanity.py:42` | Regex | Mandatory regex format for valid enrollment number |
| `[0.527*W, 0.755*H, 0.945*W, 0.795*H]` | `ocr/detection/fallbacks.py:15` | Coordinates | Fallback bounding box for `grand_total` |
| `[0.050*W, 0.240*H, 0.450*W, 0.350*H]` | `ocr/detection/fallbacks.py:30` | Coordinates | Fallback bounding box for `subject_code` (original format) |
| `[0.040*W, 0.200*H, 0.480*W, 0.350*H]` | `ocr/detection/fallbacks.py:29` | Coordinates | Fallback bounding box for `subject_code` (Format V2) |
| `[0.520*W, 0.260*H, 0.985*W, 0.360*H]` | `ocr/detection/fallbacks.py:84` | Coordinates | Fallback bounding box for `enrolment_no` (original format) |
| `[0.550*W, 0.250*H, 0.990*W, 0.410*H]` | `ocr/detection/fallbacks.py:79` | Coordinates | Fallback bounding box for `enrolment_no` (Format V2) |
| `TABLE_Y_START_FRAC = 0.48` | `ocr/postprocessing/question_marks.py:30` | Ratio | Vertical start position of question table on page |
| `OCR_CONF_THRESH = 0.30` | `ocr/postprocessing/question_marks.py:42` | Threshold | Confidence cutoff for question table cells |
| `conf_thresh = 0.35` | `ocr/pipeline.py:39` | Threshold | Default YOLO confidence cutoff in `OCREngine` |
| `YOLO_CONF_THRESH = 0.30` | `app/config.py:27` | Threshold | Default YOLO confidence cutoff in FastAPI config |
| `imgsz = 1280` | `app/config.py:28`, `ocr/pipeline.py:40` | Dimension | Resolution for YOLO inference scaling |
| `padding_ratio = 0.05` | `app/config.py:29`, `ocr/pipeline.py:41` | Ratio | Margin added to YOLO bounding boxes |
| `MAX_UPLOAD_SIZE_MB = 25` | `app/config.py:36` | Limit | Maximum allowed HTTP upload payload size |

---

## 9. Evaluation and Tests

### Test Suites (48 Tests Total in `tests/`)

| Test File | Test Class | Methods Count | Scope & Covered Functionality |
| :--- | :--- | :---: | :--- |
| `tests/test_cleaners.py` | `TestDualSourceFusion` | 4 | Agreement states, tightened crop recovery, word recovery, review conflict |
| `tests/test_cleaners.py` | `TestEnrollmentCleaner` | 4 | Clean enrollment, lookalike mapping, 180° inversion, empty inputs |
| `tests/test_cleaners.py` | `TestMarksInWordsParser` | 4 | Word numbers, hyphenation/noise, teens/single digits, garbage text |
| `tests/test_cleaners.py` | `TestSanityValidator` | 3 | Valid payload, missing rollno review, out-of-range marks review |
| `tests/test_cleaners.py` | `TestTotalMarksCleaner` | 3 | Pure digits, equation rounding, empty/corrupted inputs |
| `tests/test_ocr_pipeline.py` | `TestCropperAndDivider` | 2 | Box coordinate boundary clamping, synthetic red divider detection |
| `tests/test_ocr_pipeline.py` | `TestDetectionFallbacks` | 1 | Fallback coordinate aspect ratio and dimension verification |
| `tests/test_question_marks.py` | `TestMergeCloseLines` | 4 | Edge line merging within 15px threshold |
| `tests/test_question_marks.py` | `TestParseMarksText` | 11 | Number parsing, decimal marks, .5 handling, lookalike O/l repair |
| `tests/test_question_marks.py` | `TestQuestionMarksExtractorContract` | 8 | Result dictionary keys, sequential question IDs, review flag on sum mismatch |
| `tests/test_question_marks.py` | `TestQuestionMarksIntegration` | 3 | End-to-end question mark extraction on sample cover sheet |
| `tests/test_regression.py` | `TestBaselineRegression` | 1 | Asserts exact match $\ge 95.21\%$, 0 regressions on 146-page benchmark |

### Benchmark Evaluation Suites

| Suite Name | Target Dataset | Ground Truth File | Pages | Fields Measured | Runtime | TUNED-ON-TEST Status |
| :--- | :--- | :--- | :---: | :--- | :---: | :---: |
| **Benchmark A** | `data/raw/images` | `data/canonical_labels.csv` | 146 | `enrollment_no`, `subject_code`, `total_marks` | ~0.3 s (from cache) | **TUNED-ON-TEST** (Fallback coordinates and Strategy B rounding logic were iteratively tuned directly against these 146 images) |
| **Benchmark B** | `data/data_v2_images` | `data/canonical_labels_v2.csv` | 145 | `enrollment_no`, `subject_code`, `grand_total` | ~23.5 s / img | **TUNED-ON-TEST** (Format V2 fallback coordinates and normalizers were calibrated directly on these 145 images) |

---

## 10. Data and Models

### Datasets

| Dataset Path | Count | Format | Labels Available | Fields Labelled | Notes |
| :--- | :---: | :---: | :---: | :--- | :--- |
| `data/raw/images` | 146 | PNG (3509x2480 avg) | Yes (`data/canonical_labels.csv`) | `enrollment_no`, `subject_code`, `total_marks`, `sheet_no` | Contains 144 `.txt` and 2 `.csv` files stored directly in the images folder. |
| `data/raw/labels` | 146 | TXT (YOLO) + XML (VOC) | Yes | Bounding boxes: `enrolment_no`, `grand_total`, `subject_code` | Used to train YOLOv8n detector. |
| `data/data_v2_images` | 145 | PNG (3000x4000 avg) | Yes (`data/canonical_labels_v2.csv`) | `enrollment_no`, `subject_code`, `grand_total`, `q1`-`q5` | New Format V2 exam booklets. |

### Model Artifacts

| Model File | Size | Architecture | Trained By | Consumed By | Status |
| :--- | :---: | :---: | :--- | :--- | :---: |
| `models/best.pt` | 6.05 MB | YOLOv8n | Ultralytics YOLOv8 on `data/raw/labels` | `ocr.detection.detector.YOLOFieldDetector` | **Active Production** |
| `models/best.onnx` | 11.85 MB | YOLOv8n (ONNX) | Exported from `models/best.pt` | None | Unused in production |
| `models/yolov8n.pt` | 6.25 MB | YOLOv8n | Official Ultralytics base weights | `scripts/train_yolo.py` | Training base only |
| PaddleOCR Det/Rec | Dynamic cache | `PP-OCRv6_medium` | Pretrained PaddlePaddle weights | `ocr.recognition.paddle_engine.PaddleOCREngine` | **Active Production** |

---

## 11. Notebooks and Scripts

| Script / Notebook Path | Purpose | Production Imports It? | Duplicates Production Logic? | Runnable Today? |
| :--- | :--- | :---: | :---: | :---: |
| `scripts/convert_xml_to_yolo.py` | Converts Pascal VOC XML to YOLO format | No | No | Yes |
| `scripts/extract_pdf_pages.py` | Extracts pages from PDF booklets to PNG | No | No | Yes (requires pdf2image) |
| `scripts/image_croping.py` | Standalone image cropping tool | No | Yes (`FieldCropper`) | Yes |
| `scripts/infer_crop.py` | Performs YOLO inference and saves crops | No | Yes (`YOLOFieldDetector`) | Yes |
| `scripts/label_benchmark_b.py` | Terminal interface for entering ground truth | No | No | Yes |
| `scripts/label_cover_sheet.py` | Terminal tool for cover sheet labeling | No | No | Yes |
| `scripts/prepare_dataset.py` | Splits data into train and validation sets | No | No | Yes |
| `scripts/reextract_format_v2_fallbacks.py` | Re-crops and re-evaluates Format V2 fallback images | No | Partially (imports cleaners) | Yes |
| `scripts/run_ocr.py` | CLI test runner for PaddleOCR | No | Yes (`PaddleOCREngine`) | Yes |
| `scripts/train_yolo.py` | Launches YOLOv8 model training | No | No | Yes (requires ultralytics) |
| `profile_pipeline.py` | Profiling harness measuring latency | No | Wraps `OCREngine` | Yes |
| `run_new_batch.py` | Imperative batch processor for Format V2 | No | Yes (`OCREngine` loop) | Yes |
| `compare_cleaned_vs_verified.py` | Diff tool for CSV predictions vs ground truth | No | No | Yes |
| `text_regex_cleaning.py` | Monolithic legacy cleaning script | No | Yes (`ocr.postprocessing`) | Yes (unreferenced) |
| `test_ocr.py` | Root-level HTTP test script | No | No | Yes |
| `experiments/notebooks/Field Detection.ipynb` | Exploratory notebook for YOLO detection | No | Yes | UNKNOWN (Colab env) |
| `experiments/notebooks/colab_crop_only.ipynb` | Exploratory cropping notebook | No | Yes | UNKNOWN (Colab env) |
| `experiments/notebooks/colab_ocr_only.ipynb` | Exploratory OCR notebook | No | Yes | UNKNOWN (Colab env) |
| `experiments/notebooks/exam_ocr_cleaned (1).ipynb` | Legacy regex cleaning experiments | No | Yes | UNKNOWN (Colab env) |

---

## 12. Unknowns and Contradictions

1. **Model Version Contradiction (`models/registry.json:23-26` vs Runtime)**:
   `models/registry.json` specifies `"model_id": "pp-ocrv4-mobile-en"`, version `"PP-OCRv4"`. In actual execution, PaddleOCR 3.7.0 initializes `PP-OCRv6_medium_det` and `PP-OCRv6_medium_rec` cached in `C:\Users\sumit\.paddlex\official_models`.
2. **YOLO Confidence Threshold Contradiction (`app/config.py:27` vs `ocr/pipeline.py:39`)**:
   `app/config.py` specifies `YOLO_CONF_THRESH = 0.30`, but `ocr/pipeline.py` defines the default parameter as `conf_thresh: float = 0.35`. When instantiated via FastAPI (`ocr_service.py:30`), 0.30 is passed; when instantiated directly via `OCREngine()`, 0.35 is used.
3. **Format Selection Omission in Production (`ocr/pipeline.py:119`)**:
   `ocr/detection/fallbacks.py` supports `format_name="format_v2"`, but `ocr/pipeline.py` never passes `format_name`, defaulting unconditionally to `"format_original"`. There is no automatic format detector in the live pipeline.
4. **Subject Code Fallback Omission in Production (`ocr/pipeline.py:141`)**:
   `ocr/detection/fallbacks.py:18` defines `get_subject_code_fallback_box`, but `ocr/pipeline.py` does not call it when YOLO fails to detect `subject_code`, setting crop to `None` and passing an empty string to `clean_single_subject_code`.
5. **YOLO Training Split Provenance**:
   Exact training/validation split indices, random seeds, and training duration used to produce `models/best.pt` are UNKNOWN (no training run logs or hyperparameter artifacts exist in the repository).
6. **ONNX Model Parity**:
   Whether `models/best.onnx` produces bit-for-bit identical bounding box predictions to `models/best.pt` is UNKNOWN (it is never tested or loaded by any test or production module).
7. **`data/raw/images` Directory Pollution**:
   `data/raw/images` contains 146 PNG images, 144 YOLO `.txt` annotation files, and 2 `.csv` files stored within the image directory itself.
