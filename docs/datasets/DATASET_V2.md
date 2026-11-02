# Dataset Specification: Format V2 (`data_v2_images`)

## 1. Dataset Overview

* **Directory:** `data/data_v2_images`
* **File Count:** 145 images (`page_000001.png` through `page_000145.png`) + `manifest.csv`
* **Source Documents:** Scanned answer booklet cover pages from Master of Computer Applications (MCA) Computer Networks examinations (`cn_2026_*.pdf`).
* **Resolution Range:** High-resolution scans (typically 2200x3300 to 2550x3300 pixels).

---

## 2. Field Layout & Geometric Topology

Unlike the single-sheet cover format in Dataset A, Dataset V2 features a 32-page booklet format:

1. **Booklet Identification:**
   * Upper-left region contains booklet serial number: `SR No. XXXXX`.
2. **Subject Code (`CT10715`):**
   * Located in the left quadrant below the main title.
   * Geometric ratio: approximately $x \in [0.04 \cdot W, 0.48 \cdot W]$, $y \in [0.24 \cdot H, 0.35 \cdot H]$.
3. **Enrollment Number (`0801CA25XXXX`):**
   * Located in the right quadrant adjacent to the SR number.
   * Geometric ratio: approximately $x \in [0.52 \cdot W, 0.985 \cdot W]$, $y \in [0.26 \cdot H, 0.36 \cdot H]$.

---

## 3. Labeling and Validation

Canonical labels are recorded in `data/canonical_labels_v2.csv`.
Only verified ground truth from human annotation is recognized for Benchmark B metrics.
