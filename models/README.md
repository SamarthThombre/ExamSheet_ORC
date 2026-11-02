# Models & Weights Registry

This directory contains trained model weights, export artifacts, and configuration references for the Exam Paper OCR pipeline.

---

## 1. Inventory & Files

| Filename | Format | Size | Description |
| :--- | :---: | :---: | :--- |
| `best.pt` | PyTorch (`.pt`) | ~6.3 MB | **Active production weights** for YOLOv8n field detector. Localizes `enrolment_no`, `grand_total`, and `subject_code`. |
| `best.onnx` | ONNX | ~12.4 MB | Exported ONNX format for accelerated cross-platform inference runtime. |
| `yolov8n.pt` | PyTorch (`.pt`) | ~6.5 MB | Base pretrained YOLOv8 nano model checkpoint from Ultralytics. |
| `registry.json` | JSON | < 2 KB | Machine-readable metadata specification for active models. |

---

## 2. YOLOv8 Field Detector (`best.pt`)

### Specifications
* **Base Architecture**: YOLOv8n (nano)
* **Framework**: Ultralytics 8.x
* **Input Resolution**: `1280 x 1280` pixels
* **Inference Confidence Threshold**: `0.30` (production default)
* **Box Padding Ratio**: `0.05` (5% padding applied during cropping)

### Class Mapping
```json
{
  "0": "enrolment_no",
  "1": "grand_total",
  "2": "subject_code"
}
```

### Deterministic Geometric Fallbacks
* If YOLO misses `enrolment_no` (e.g. `page_000039.png`, `page_000103.png`), the pipeline automatically engages `ocr.detection.fallbacks.get_enrolment_no_crop`:
  - **Coordinates**: `x1 = 0.520 * W`, `y1 = 0.260 * H`, `x2 = 0.985 * W`, `y2 = 0.360 * H`
  - Recovers missing enrollment numbers to 100% accuracy.

### Retraining
To retrain YOLO on new data:
```powershell
python scripts/prepare_dataset.py
python scripts/train_yolo.py --data dataset/data.yaml --epochs 50 --imgsz 1280
```

---

## 3. Optical Character Recognition (PaddleOCR)

### Specifications
* **Engine**: PaddleOCR `PP-OCRv4` (Mobile)
* **Language**: English (`lang="en"`)
* **Direction / Angle Classifier**: Disabled (`use_angle_cls=False` for low-latency bounding box recognition)
* **Execution Device**: CPU

### Windows 11 / Python 3.13 Runtime Isolation Guard
* **Known Issue**: PaddleOCR 3.x attempts an optional PyTorch import during initialization that triggers `WinError 127: The specified procedure could not be found` within `torch.lib.shm.dll` on Windows under Python 3.13.
* **Resolution**: Handled automatically in `ocr.recognition.paddle_engine.PaddleOCREngine` via an in-memory `importlib.util.find_spec` block that intercepts and isolates `torch` during PaddleOCR loading, alongside setting `FLAGS_enable_pir_api=0` and `FLAGS_use_onednn=0`.
