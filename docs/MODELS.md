# MODELS SPECIFICATION & REGISTRY GUIDE

This document describes the active production models, weights, runtime configurations, and evaluation metrics for the Exam Paper OCR Extractor.

---

## 1. Model Registry (`models/registry.json`)

The project maintains a centralized, machine-readable model registry in [`models/registry.json`](file:///c:/Users/sumit/Desktop/Samarth/python/exam_paper_extractor/models/registry.json):

```json
{
  "schema_version": "1.0.0",
  "models": {
    "field_detector": {
      "model_id": "yolov8n-exam-fields-v1",
      "task": "object_detection",
      "framework": "ultralytics",
      "architecture": "yolov8n",
      "weights_file": "best.pt",
      "onnx_file": "best.onnx",
      "input_resolution": 1280,
      "default_confidence_threshold": 0.30,
      "classes": {
        "0": "enrolment_no",
        "1": "grand_total",
        "2": "subject_code"
      }
    },
    "text_recognizer": {
      "model_id": "pp-ocrv4-mobile-en",
      "task": "optical_character_recognition",
      "framework": "paddlepaddle / paddleocr",
      "version": "PP-OCRv4",
      "language": "en",
      "use_angle_cls": false,
      "runtime": "CPU"
    }
  }
}
```

---

## 2. Active Production Models

### A. YOLOv8n Field Detector (`models/best.pt`)
* **Task**: Localizes tabular bounding boxes on high-resolution cover-sheet scans.
* **Architecture**: Ultralytics YOLOv8 nano (`yolov8n`).
* **Input Resolution**: `1280 x 1280` pixels.
* **Trained Classes**:
  - `0: enrolment_no`: Bounding box of the student enrollment/roll number box.
  - `1: grand_total`: Bounding box of the grand total score cell (contains printed label and score).
  - `2: subject_code`: Bounding box of the institutional subject code cell.
* **Confidence Threshold**: `0.30` (production default in `app/config.py`).
* **Crop Padding**: `0.05` (5% padding clamped to image bounds).
* **Deterministic Fallback**: If YOLO misses `enrolment_no` (e.g. `page_000039`, `page_000103`), `ocr.detection.fallbacks.get_enrolment_no_crop` applies layout crop `(0.520*W, 0.260*H, 0.985*W, 0.360*H)`.

### B. PaddleOCR Recognizer (`PP-OCRv4`)
* **Task**: Text recognition from cropped field images.
* **Architecture**: Mobile PP-OCRv4 recognition model.
* **Language**: English (`lang="en"`).
* **Classifier**: Angle classification disabled (`use_angle_cls=False`) for low-latency line processing.
* **Execution Device**: CPU inference with `FLAGS_enable_pir_api=0` and `FLAGS_use_onednn=0`.
* **Windows Python 3.13 Runtime Guard**: Handled in `ocr.recognition.paddle_engine.PaddleOCREngine` via dynamic `torch` import interception to prevent Windows `WinError 127` in `torch.lib.shm.dll`.

---

## 3. Benchmark Accuracy & Validation

Evaluated against the frozen 146-page ground-truth reference:

| Field | Accuracy | Matches | Notes |
| :--- | :---: | :---: | :--- |
| `subject_code` | **100.00%** | 146 / 146 | Normalized institutional code `CT10718`. |
| `total_marks` | **98.63%** | 144 / 146 | Dual-source fusion (`grand_total` + `marks_in_words`). Only 2 remaining ambiguities, both flagged for human review. |
| `enrollment_no` | **96.58%** | 141 / 146 | Strategy B normalization. Only 5 handwriting ambiguities remaining. |
| **Whole-Page (All 3 Fields)** | **95.21%** | 139 / 146 | Exact match on all three fields simultaneously. |

---

## 4. Retraining & Model Export

To train a new version of the YOLO field detector:
```powershell
# 1. Prepare dataset split
python scripts/prepare_dataset.py

# 2. Train YOLOv8n
python scripts/train_yolo.py --data configs/data.yaml --epochs 50 --imgsz 1280

# 3. Export to ONNX for production optimization
python -c "from ultralytics import YOLO; model = YOLO('models/best.pt'); model.export(format='onnx')"
```
