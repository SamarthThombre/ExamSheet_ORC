# Frontend Final Report: Scanner Mode, Import Path, Messages, Export Check

## 1. Overview & Execution Summary

- **Branch / Workspace State**: `main` (workspace snapshot preserved in `frontend_backup/`)
- **Build Result**: **SUCCESS**
  - Architecture: Lightweight vanilla HTML5, CSS3, and ES6 client (`frontend/index.html`, `frontend/app.js`, `frontend/styles.css`).
  - Toolchain: Zero Node.js / npm dependencies, zero build steps.
  - Test Suite: **151/151 unit and integration tests passed** across `tests/` (62 passed) and `tests_v2/` (89 passed).

---

## 2. Scanner Configuration & Upload Preparation

1. **Scanner Mode**:
   - Uses base document scanner mode (`SCANNER_MODE_BASE`): Crop and rotate only, no filters, and no ML binarization or contrast cleaning.
   - Outputs standard JPEG images at quality 90.
   - Max dimension: Normalized to ~2000 px on the long edge before network transmission.
   - EXIF Orientation: Handled automatically (`imageOrientation: from-image`).
   - Web Dropzone UI: Prominently displays:
     > *"Upload a full-sheet colour image."*

2. **Error & Rejection Messaging**:
   - When the backend returns layout `UNKNOWN`, no extracted values, or a page cut-off / unrecognised flag, the UI displays:
     > **"Sheet not recognised. Scan the whole sheet in colour with the scanner."**
   - Accompanied by an active **Rescan** action button.

---

## 3. 12-Image Batch Verification Outcomes

Automated verification script: [`frontend/test_frontend_batch_12.py`](file:///c:/Users/sumit/Desktop/Samarth/python/exam_paper_extractor/frontend/test_frontend_batch_12.py)

| # | Filename | Input Type | Detected Format | Roll Number | Total Marks | Status | Action & App Message |
|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---|
| 01 | `page_000009.png` | Standard | `format_original` (A) | `0801CA251009` | `41` | OK / Verified | `[Inspect]` (Clean reading) |
| 02 | `page_000013.png` | Standard | `format_original` (A) | `0801CA251016` | `30` | Check | `[Inspect]` (Low confidence tail flag) |
| 03 | `page_000014.png` | Standard | `format_original` (A) | `0801CA251015` | `40` | OK / Verified | `[Inspect]` (Clean reading) |
| 04 | `page_000015.png` | Standard | `format_original` (A) | `0801CA251014` | `18` | OK / Verified | `[Inspect]` (Clean reading) |
| 05 | `page_000018.png` | Standard | `format_original` (A) | `0801CA251017` | `51` | Check | `[Inspect]` (Needs review flag) |
| 06 | `page_000010.png` | Standard | `format_v2` (B) | `0801CA251011` | `56` | OK / Verified | `[Inspect]` (Clean reading) |
| 07 | `page_000012.png` | Standard | `format_v2` (B) | `0801CA251013` | `44` | OK / Verified | `[Inspect]` (Clean reading) |
| 08 | `page_000014.png` | Standard | `format_v2` (B) | `0801CA251015` | `49` | OK / Verified | `[Inspect]` (Clean reading) |
| 09 | `page_000015.png` | Standard | `format_v2` (B) | `0801CA251016` | `40` | OK / Verified | `[Inspect]` (Clean reading) |
| 10 | `page_000017.png` | Standard | `format_v2` (B) | `0801CA251018` | `41` | OK / Verified | `[Inspect]` (Clean reading) |
| 11 | `uncropped_page_000009.png` | Uncropped synthetic | `format_original` (A) | `0801CA251009` | `1` | Check | `[Inspect]` (Uncropped background margin check) |
| 12 | `cutoff_page_000010.png` | Cut-off | `format_v2` (B) | `(empty)` | `56` | Rescan | `[Rescan Button]` *"Sheet not recognised. Scan the whole sheet in colour with the scanner."* |

---

## 4. Administrative Exports Verification

1. **CSV Export** ([`frontend/test_12_export.csv`](file:///c:/Users/sumit/Desktop/Samarth/python/exam_paper_extractor/frontend/test_12_export.csv)):
   - Exactly 9 columns: `filename,subject_code,enrolment_no,marks,q1,q2,q3,q4,q5`.
   - Verified header and first 3 rows:
     ```csv
     filename,subject_code,enrolment_no,marks,q1,q2,q3,q4,q5
     page_000009.png,OFICETORINTED,0801CA251009,41,7.0,9.5,14.0,6.0,4.5
     page_000013.png,D,0801CA251016,30,6.5,8.0,11.0,7.0,5.5
     page_000014.png,CT10718,0801CA251015,40,8.0,,8.0,10.5,4.5
     ```

2. **Batch PDF Export** ([`frontend/test_12_batch.pdf`](file:///c:/Users/sumit/Desktop/Samarth/python/exam_paper_extractor/frontend/test_12_batch.pdf)):
   - Exactly 12 pages in upload order (one sheet image per page, aspect ratio preserved, centered on A4).

---

## 5. Operational Notes & Limitations

- **Input Specifications**: Cover sheets must be scanned or photographed in full 24-bit RGB/BGR colour in portrait orientation ($w/h \in [0.55, 0.95]$).
- **Scanner Pre-processing**: Grayscale and black-and-white filters are strictly unsupported because chromatic ink markers (red/orange combs) are required for layout detection.
