# DATASET MANAGEMENT & WORKFLOW GUIDE

This document describes the dataset lifecycle, canonical ground-truth formats, labeling workflows, and dataset versioning for the Exam Paper OCR Extractor.

---

## 1. Directory Organization

```text
data/
├── canonical_labels.csv          # Canonical ground-truth reference for 146 cover sheets
├── experimental_ocr_cache.csv    # Companion crop OCR cache for fast batch evaluation
├── README.md                     # Dataset overview & quick reference
├── raw/
│   ├── images/                   # High-resolution cover-sheet scans (page_000001.png to page_000146.png)
│   └── labels/                   # Original VOC XML and YOLO TXT annotations
└── dataset/                      # YOLO training/validation split (80/20)
    ├── train/
    │   ├── images/
    │   └── labels/
    └── val/
        ├── images/
        └── labels/
```

---

## 2. Canonical Ground-Truth Schema

The canonical ground truth is maintained in `data/canonical_labels.csv` with the following contract:

| Column Name | Type | Description | Example |
| :--- | :---: | :--- | :--- |
| `image_filename` | `str` | Unique filename of the cover sheet image | `page_000001.png` |
| `enrollment_no` | `str` | Normalized student roll number | `0801CA251001` |
| `subject_code` | `str` | Normalized institutional subject code | `CT10718` |
| `total_marks` | `int` | Verified total marks obtained | `54` |

*Note: For backward compatibility with legacy scripts, `data/verified_labels - Copy.csv` is preserved as an alias.*

---

## 3. Dataset Lifecycle & Operational Pipeline

```text
Raw PDF Document
       ↓  (scripts/extract_pdf_pages.py)
Extracted PNG Images (300 DPI)
       ↓  (scripts/label_cover_sheet.py / LabelImg)
Labeled Ground Truth & Annotations
       ↓  (scripts/prepare_dataset.py)
Train / Validation Split (80 / 20)
       ↓  (scripts/train_yolo.py)
YOLOv8 Field Detector Training
       ↓  (evaluation/benchmark.py)
Evaluation & Regression Verification
```

### A. Extracting Pages from PDF
To convert multi-page exam PDF documents into cleanly named 300 DPI images:
```powershell
python scripts/extract_pdf_pages.py --pdf path/to/exam_bundle.pdf --output-dir data/raw/images --dpi 300
```

### B. Interactive Ground-Truth Labeling Tool
To review images and enter verified ground truth without manual spreadsheet editing:
```powershell
python scripts/label_cover_sheet.py --images-dir data/raw/images --csv data/canonical_labels.csv
```
Features:
* Displays current image filename and existing label.
* Skips already-labeled images by default.
* Validates `enrollment_no` (format `0801CA25XXXX`) and `total_marks` (integer in range 0–70).
* Automatically persists updates on save.

### C. YOLO Bounding Box Annotation
Bounding boxes for tabular fields are annotated using `LabelImg` or compatible tools with standard classes:
* `0`: `enrolment_no`
* `1`: `grand_total`
* `2`: `subject_code`

### D. Splitting Dataset for Training
To partition annotated images into training and validation sets:
```powershell
python scripts/prepare_dataset.py --source-images data/raw/images --source-labels data/raw/labels --output-dir data/dataset --train-ratio 0.80
```

---

## 4. Dataset Versioning Strategy

As new exam sessions are processed, dataset versions should be managed via simple manifests:
* **Version Format**: `data/manifests/v1.0.0.json`, `data/manifests/v1.1.0.json`
* **Manifest Content**:
  ```json
  {
    "version": "1.0.0",
    "date": "2026-09-27",
    "total_images": 146,
    "train_count": 116,
    "val_count": 30,
    "source_archive": "exam_cover_sheets_2026_fall",
    "labels_file": "data/canonical_labels.csv"
  }
  ```
* **Immutability Principle**: Once a dataset version is benchmarked, its image files and ground-truth rows must never be overwritten in-place.
