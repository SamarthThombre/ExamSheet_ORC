# Sheet Data Extractor — Teacher Web Portal

A clean, responsive, single-page web application designed for teachers and exam invigilators to verify and finalize OCR-extracted enrolment numbers and total marks from exam cover sheets.

The web client communicates directly with the FastAPI OCR v2 backend (`http://localhost:8000`), requiring **no Node.js build steps, no npm packages, and zero external runtime dependencies**.

---

## 1. Quick Start

### Step 1: Start the Backend (with OCR v2 enabled)
In a PowerShell window:
```powershell
cd c:\Users\sumit\Desktop\Samarth\python\exam_paper_extractor
$env:USE_OCR_V2="1"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Step 2: Start the Web Frontend
In another PowerShell window:
```powershell
cd c:\Users\sumit\Desktop\Samarth\python\exam_paper_extractor
.\.venv\Scripts\python.exe frontend/serve.py
```
This automatically launches your browser at `http://localhost:3000`.

### Label the extracted v3 PDF pages
The DBMS bundle in `data/data_v3/` can be extracted and labeled separately
from the legacy dataset:
```powershell
.\.venv\Scripts\python.exe scripts\extract_pdf_pages.py --pdf "data\data_v3\DBMS(50-copies)-roll-1-to-54.pdf" --out data\data_v3\images --dpi 300 --start 1
.\.venv\Scripts\python.exe frontend\serve.py --labeler --dataset v3
```
The v3 labeler reads those extracted pages and saves enrollment, subject,
Q1–Q5, and grand-total labels to `data/canonical_labels_v3.csv`. It accepts
addition notation such as `2.5+0.5` for marks with grace points. This workflow
prefills subject `CT10716`; enter only the final four enrollment digits after
the fixed `0801CA25` prefix. It does not edit the v2 image or label files.

For the Data Structure v4 PDF, use the same extraction and labeler with the
v4 paths:
```powershell
.\.venv\Scripts\python.exe scripts\extract_pdf_pages.py --pdf "data\data_v4\data structure copies pdf.pdf" --out data\data_v4\images --dpi 300 --start 1
.\.venv\Scripts\python.exe frontend\serve.py --labeler --dataset v4
```
The v4 labeler defaults the subject code to `CT10222`, shows the fixed
`0801CA25` enrollment prefix, and saves labels in
`data\canonical_labels_v4.csv`.

### Relabel marks in the legacy dataset
To open the old-dataset labeling page directly, run:
```powershell
.\.venv\Scripts\python.exe frontend/serve.py --labeler
```
The page uses the 146 images in `data/raw/images/`, prefills enrollment,
subject, and the existing total marks from `data/canonical_labels.csv`, and
lets you verify `q1`–`q5` and `grand_total` using the v2 marks schema. Saving a
sheet writes those fields (and keeps `total_marks` synchronized with
`grand_total`) to the legacy CSV. A blank question mark means it is not yet
verified; a blank `grand_total` cannot be saved. The server listens only on
`127.0.0.1` because this page can update the local CSV.

*(Alternatively, you can open `frontend/index.html` directly in any modern browser).*

---

## 2. Key Teacher Features

1. **Live Backend Health Indicator**
   - Automatically polls `GET /health` with round-trip latency counter.
   - Click the status pill or gear icon to change the API server address at runtime.

2. **Upfront Batch Setup**
   - **Exam Name & Subject Code**: Teacher declares subject code upfront once per batch.
   - **Optional Class Roster**: Drag-and-drop or select a class list CSV. The portal identifies students missing from the scanned stack and alerts if a scanned sheet doesn't match the class roster.
   - **Cover Sheet Dropzone**: Drag and drop any number of PNG, JPG, or WEBP sheet scans.

3. **Live Processing Queue**
   - Visual progress bar with per-sheet progress cards (`Queued`, `Reading...`, `Done`, `Failed`).
   - One-click retry for any network interruptions.

4. **Quality & Review Dashboard**
   - **Subject Consensus Warning**: Flags a warning banner if scanned subject codes contradict the teacher's declared code.
   - **Duplicate Roll Highlighting**: Wavy underline and red alert banner if duplicate roll numbers appear within the same exam batch.
   - **Missing Roster Students**: Collapsible drawer showing which students from the imported roster have not been scanned.
   - **Metric Cards & Quick Filters**: Filter the sheet list by `All`, `Clean (OK)`, `Needs Review`, or `Rescan Recommended`.
   - **Instant Search**: Find any sheet instantly by typing the tail digits of a roll number.

5. **Sheet Inspector & Inline Editor**
   - High-resolution image preview.
   - Plain-English reason badges for review flags (`Part of the roll number box is cut off`, `Handwriting is hard to read`, etc.).
   - Inline text inputs in the table or the Inspector modal for fast keyboard-based corrections.

6. **Direct Exports**
   - **Export CSV**: Downloads `<subject_code>_<timestamp>.csv` formatted for administrative grading spreadsheets:
     `batch_id, subject_code_declared, filename, enrolment_final, enrolment_ocr, total_marks_final, total_marks_ocr, status, flags`
   - **Print / Save PDF**: Formatted clean marks register via `window.print()` using dedicated `@media print` styling (omits UI navigation and buttons).

---

## 3. File Structure

```text
frontend/
├── index.html        # Semantic HTML5 single-page application structure
├── styles.css        # Clean, modern stylesheet + dedicated print formatting
├── app.js            # Modular client application logic & OCR API integrations
├── labeler.html      # Legacy marks relabeling interface
├── labeler.js        # Legacy marks labeler behavior and API integration
├── labeler.css       # Labeler page styles
├── serve.py          # Local web server and legacy-label persistence API
└── README.md         # Instructions and documentation
```
