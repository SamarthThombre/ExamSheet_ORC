# Benchmark B Specification: Format V2 Answer Books

## 1. Overview

Benchmark B evaluates model generalization on a newly introduced collection of **145 exam cover images** (`data/data_v2_images/page_000001.png` to `page_000145.png`).

---

## 2. Format V2 Characteristics vs Format A

| Characteristic | Format A (Benchmark A) | Format B (Benchmark B) |
| :--- | :--- | :--- |
| **Document Type** | First page cover sheet | 32-page answer book cover page |
| **Top Header** | Examination cover sheet | `MAIN ANSWER BOOK (TOTAL 32 PAGES EXCLUSIVE OF COVER PAGE)` |
| **Serial Number** | Sheet No. (stamped bottom) | `SR No. XXXXX` (printed top left near enrollment) |
| **Subject Code** | Printed code `CT10718` | Printed code `CT10715` (Computer Networks) |
| **Enrollment Layout**| Box on right side | Box on right side, adjacent to `SR No.` |
| **Question Marks** | 5-question table present | Inner question summary table |

---

## 3. Historical Baseline (Operational Extraction Metrics)

In the initial exploratory run ([run_new_batch.py](file:///c:/Users/sumit/Desktop/Samarth/python/exam_paper_extractor/run_new_batch.py)), operational metrics without ground truth were recorded:

* **Total Images Processed:** `145`
* **Throughput:** `23.56s` per image (CPU detection + 2 crop OCR passes)
* **Enrolment Detection:**
  * YOLO Box Used: `42.8%` (62 / 145)
  * Fallback Box Used: `57.2%` (83 / 145)
* **Subject Code Detection:**
  * YOLO Box Used: `20.7%` (30 / 145)
  * Fallback Box Used: `79.3%` (115 / 145)
* **Subject Code Parsed:** `97.9%` (142 / 145)
* **Subject Code Defaulted:** `2.1%` (3 / 145)

> [!NOTE]
> These historical metrics are operational extraction rates, **not ground-truth accuracy**.

---

## 4. Ground-Truth Workflow

Ground truth for Benchmark B is stored in:
`data/canonical_labels_v2.csv`

Schema:
```csv
image_filename,enrollment_no,subject_code,total_marks,status
page_000001.png,0801CA251001,CT10715,,verified
```

### Labeling Utility
To record verified ground truth, annotators run:
```bash
python scripts/label_benchmark_b.py
```
* Shows the image filename, dimensions, and prediction hints.
* Automatically resumes from the first unlabeled image.
* Safely appends and flushes after each entry.

---

## 5. Diagnostic Error Categorization

When evaluated with ground truth, errors are classified into:

1. `CROP_ERROR`: The detector or fallback box clipped or missed the field entirely.
2. `OCR_ERROR`: The text in the crop was clean, but OCR misrecognized characters.
3. `NORMALIZATION_ERROR`: The OCR read correctly, but postprocessing stripped or substituted characters incorrectly.
4. `PARSER_ERROR`: Regex or parsing logic failed to extract the structured field value.
5. `DEFAULTED`: Field was unparseable or absent, falling back to institutional defaults.
6. `VALIDATION_ERROR`: Value failed sanity invariants (e.g., character length or formatting pattern).
