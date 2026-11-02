# Web Frontend Architecture & Implementation Report

## 1. Overview & Objectives

In response to the requirement for a simple, demo-ready client interface for teachers, we implemented a standalone Web Frontend under `frontend/`. 

The web application satisfies all key functional requirements:
- **Zero Heavy Toolchain**: Built with vanilla HTML5, CSS3, and ES6 JavaScript. No Node.js build pipelines, webpack configurations, or npm package bloat.
- **Direct Backend Integration**: Connects to the frozen FastAPI OCR v2 backend (`/health`, `/v2/predict`, `/v2/batch`).
- **Complete Teacher Flow**: 
  1. *New Batch Setup* (Exam info, declared subject code, optional class roster CSV, multi-image dropzone).
  2. *Live Processing Queue* (Real-time progress bar, individual sheet status chips, retry on failure).
  3. *Review & Quality Dashboard* (Metric counter cards, duplicate roll detection, subject code consensus mismatch banner, missing roster reconciliation, search and filtering).
  4. *Sheet Inspector & Editor* (Document image view, plain-English reason translations, inline editing of enrolment and marks).
  5. *Administrative Exports* (Standardized CSV download and print-ready PDF view).

---

## 2. API Contract Mapping

| Frontend Feature | Backend API Endpoint | Request Details | Handled Response Fields |
|---|---|---|---|
| Live Health & Latency Indicator | `GET /health` | None | `status`, `ocr_loaded`, `detector_loaded`, round-trip ping time |
| Sheet OCR Inference | `POST /v2/predict` | `multipart/form-data`: `file`, `extract_total_marks=true` | `enrolment` (value, raw_text, confidence), `total_marks` (value, raw_text), `subject_code`, `format_id`, `needs_review`, `rescan_recommended`, `review_reasons` |
| Batch Quality Checks | Client-Side Reconciliation | Evaluates batch after sheets complete | Cross-sheet duplicate enrolment, subject consensus vs declared code, roster missing / extra students |

---

## 3. Screen Workflows

```text
[ Screen 1: New Batch ]
       │
       ├─ Enter Exam Name & Required Subject Code
       ├─ Drag & Drop Cover Sheet Scans (.png, .jpg, .webp)
       ├─ (Optional) Import Student Roster CSV
       │
       ▼ [ "Start Processing Batch" ]
[ Screen 2: Processing Queue ]
       │
       ├─ Overall Progress Bar (0% -> 100%)
       ├─ Per-Sheet Live Thumbnail & State (Queued, Reading..., Done, Failed)
       ├─ Retries on Network Interruption
       │
       ▼ [ Automatic Transition or "Proceed to Review" ]
[ Screen 3: Review & Quality Dashboard ]
       │
       ├─ Header Badges: Declared Subject Code & Exam Name
       ├─ Quality Alerts:
       │    ├─ Subject Code Consensus Warning (if >35% of detected codes differ)
       │    └─ Duplicate Enrolment Warning (if two sheets have the same roll)
       ├─ Metric Cards: Total | Clean (OK) | Needs Review | Rescan Recommended
       ├─ Filter Chips & Instant Roll Number Search
       ├─ Optional Drawer: Missing Roster Students (Not scanned)
       │
       ├─ Actions:
       │    ├─ Inline Quick Edit in Table
       │    ├─ "Inspect" Button -> [ Screen 4: Inspector Modal ]
       │    ├─ "Export CSV" -> Standard CSV (<subject>_<timestamp>.csv)
       │    └─ "Print / Save PDF" -> Formatted window.print() view
```

---

## 4. Reason Translation Specification

The web client maps raw backend error flags to plain-English teacher guidance, identical to the Android application's `ReasonMapper`:

| Backend Flag | Plain-English Teacher Label | Flag Type |
|---|---|---|
| `DUPLICATE_ENROLMENT` | Another sheet has the same roll number | Needs Review |
| `ROLL_OUT_OF_RANGE` | Roll number looks outside usual range | Needs Review |
| `INVALID_PREFIX` | Roll number prefix looks wrong | Needs Review |
| `LOW_CONFIDENCE` / `LOW_CONF` | Handwriting is hard to read, please check | Needs Review |
| `READ_NOT_IN_ROSTER` | Not in the class list | Needs Review |
| `RHS_MISSING` | Total marks looks incomplete | Needs Review |
| `OUT_OF_RANGE` | Marks outside 0 to 70 | Needs Review |
| `TOTAL_MARKS_REVIEW` | Total marks formula needs verification | Needs Review |
| `NO_KNOWN_CODE_MATCH` | Subject code not recognized | Needs Review |
| `COMB_TOUCHES_PAGE_EDGE` / `COMB_NOT_FULLY_DETECTED` | Roll box cut off. Rescan recommended | Rescan Recommended |
| `EXCESSIVE_SKEW` | Page is tilted. Rescan recommended | Rescan Recommended |

---

## 5. Verification & Testing

- **Backend Readiness**: Verified active FastAPI server at `http://localhost:8000` with `USE_OCR_V2=1`.
- **Inference Verification**: Tested `POST /v2/predict` against `data/raw/images/page_000001.png` — returned HTTP 200 with format `format_original`, enrolment `0801CA251001`, total marks `54`.
- **Frontend Serving**: Created `frontend/serve.py` allowing instant zero-configuration local hosting on port 3000.
