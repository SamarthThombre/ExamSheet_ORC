# V4 EVALUATION PROTOCOL (SEALED TEST SET SPECIFICATION)

## 1. Objectives & Scope
This protocol defines the formal requirements for the collection, blind labeling, cryptographic sealing, and single-execution evaluation of the **v4 sealed test dataset**. 

Following the unsealing and transition of v3 to development/diagnostic data in Spike 14 and Milestone 8, **v4 will serve as the true, untuned, sealed benchmark** to evaluate production readiness.

---

## 2. Dataset Collection Requirements
The target dataset must satisfy the following minimum criteria:
- **Sheet Count**: At least 40 sheets (recommended target: 50–60 sheets).
- **Domain Independence**: Must originate from a completely different examination session, course, or date than Tune (v1/v2) and v3.
- **Layout Diversity**: Must include both layouts:
  - **Format A (format_original)**: Red ink cover sheets with 12-cell comb, vertical 5-question table, and Grand Total block.
  - **Format B (format_v2)**: Orange ink cover sheets with 12-cell comb, horizontal 5-question table, and Grand Total block.
- **Acquisition Hardware Diversity**:
  - High-speed ADF (Automatic Document Feeder) multi-function office scanners.
  - Flatbed desktop scanners.
  - Smartphone camera captures under varied real-world lighting conditions (ambient incandescent, fluorescent, direct sunlight, oblique shadows, slight perspective tilt).
- **Physical Paper & Tone Diversity**:
  - Varied paper stocks: standard white 75–80 gsm, off-white recycled paper, warm newsprint/parchment tones.
  - Minor physical distortions: slight page skew ($\pm 3^\circ$), slight non-flat folds, varying staple shadows.

---

## 3. Blind Labelling Procedure
To guarantee unbiased ground truth, labeling must adhere strictly to the following protocol:
1. **Independent Annotators**: The annotators who create the ground truth must NOT be developers of the OCR engine, rules, or post-processing pipelines.
2. **Tooling**: Annotations must be conducted using the standard project labeling tool (`app/main.py` UI or designated ground truth intake interface).
3. **Mandatory Schema Columns**:
   - `image_filename`: Base name of the image (e.g. `page_000001.png`).
   - `layout`: Ground truth layout (`format_original`, `format_v2`, or `other`).
   - `enrollment_no`: Full 12-character student enrollment identifier (e.g. `0801CA251001`).
   - `subject_code`: Subject code string (e.g. `CT10718`).
   - `grand_total`: Grand total marks integer or expression (e.g. `38`, `37.5=38`, `35+2=37`).
   - `q1`, `q2`, `q3`, `q4`, `q5`: Marks per question cell (e.g. `10`, `9.5`, `02.5+0.5`).
   - `marks_status`: Semicolon-delimited unreadable/scribble marker flags for cells where marks cannot be legitimately discerned (e.g. `q1:unreadable;q3:unreadable`).
4. **Verification**: A secondary independent reviewer cross-checks 100% of labels against physical scans before cryptographic sealing.

---

## 4. Sealing Rules & Integrity Controls
Once collected and labeled, the v4 dataset must remain strictly sealed under the following cryptographic and operational controls:
1. **Developer Blindness**:
   - No developer or contributor modifying `ocr_v2/`, `configs/`, `app/`, or test suites may view, decode, inspect, or run exploratory analysis on v4 images or labels.
   - Any accidental viewing or ad-hoc scripting constitutes contamination and invalidates the dataset.
2. **Cryptographic Image Manifest**:
   - Upon intake, generate a canonical SHA-256 hash for every raw image in `data/data_v4/images/`.
   - Store hashes in `experiments/v4/v4_images_manifest.json`.
3. **Ground Truth Hash Locking**:
   - Compute and record the SHA-256 hash of `data/canonical_labels_v4.csv`.
   - Record both hashes into `experiments/v4/v4_seal_manifest.json`.
4. **Filesystem Immutability**:
   - Set all image files and ground truth CSVs to read-only permissions on disk.

---

## 5. Single-Run Execution Protocol
Evaluation on v4 must take place exactly once under the automated single-run harness:
1. **Code Freeze Verification**:
   - The execution harness (`run_sealed_once.py`) validates that all files in `experiments/m7b/manifest.json` match their frozen SHA-256 signatures.
2. **Image Manifest Verification**:
   - `run_sealed_once.py` verifies every input image against `v4_images_manifest.json`.
3. **Single-Run Lock**:
   - Before executing, `run_sealed_once.py` checks for the presence of `v4.lock`.
   - If `v4.lock` exists, execution is immediately aborted with a fatal error.
   - Upon successful completion of the single run, `v4.lock` is written containing the run timestamp, processed image count, and SHA-256 checksum of the generated predictions CSV.
4. **Scoring**:
   - Run `score_sealed.py --dataset v4 --predictions-csv experiments/v4/v4_predictions.csv --gt-csv data/canonical_labels_v4.csv --criteria experiments/m8/v4_criteria.json`.
   - Evaluates layout accuracy against the `layout` column, per-layout metrics, enrolment accuracy with/without batch signals, grand total exactness, q-cell accuracy on unflagged cells, sum-gate statuses, and latency mean/P95.
   - Every criterion is evaluated and printed CHARACTER FOR CHARACTER.
5. **Archival**:
   - Predictions, score summary, and effective settings are committed immediately to the permanent repository archive and labeled as `"v4 sealed test results"`.
