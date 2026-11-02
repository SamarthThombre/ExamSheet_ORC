# Sheet Data Extractor — Android Client Application (v2 Teacher Edition)

A clean, native Android application built with **Jetpack Compose**, **Kotlin Coroutines**, **Room Database**, and **Retrofit** designed specifically for teachers and exam invigilators to scan or import batches of exam cover sheets, run automated OCR recognition via the FastAPI OCR v2 backend, review & correct flags, and export finalized records to CSV and printable PDF.

---

## 1. System Overview & Architecture

```text
[ Android Device / Emulator ]
       │
       ├─ Declare Exam Name & Subject Code (+ Optional CSV Roster)
       ├─ Import Images (Gallery / Storage) or Scan Pages (CameraX)
       ├─ Local Room Database (Batches & Sheets persisted offline)
       │
       ▼ (Multipart HTTP POST /v2/predict or /v2/batch)
[ FastAPI OCR v2 Backend (app/main.py with USE_OCR_V2=1) ]
       │
       ├─ Format Identification (Format A vs Format B)
       ├─ Alignment & Comb Detection (Anchor & Crop Extraction)
       ├─ Enrolment & Total Marks Recognition (PaddleOCR ONNX)
       ├─ Flag Semantics: needs_review vs rescan_recommended
       │
       ▼ (Structured JSON Response: OcrV2PredictResponse)
[ Android Review & Export Flow ]
       │
       ├─ Review List: Summary counters (Total, OK, Check, Rescan)
       ├─ Quality Checks: Duplicate roll highlight, Roster missing alerts, Subject consensus
       ├─ Sheet Inspector: Zoomable image, ROI crop overlays, inline edit & verify
       └─ Export: Standardized CSV (<subject>_<timestamp>.csv) & Printable PDF
```

---

## 2. Four-Screen Teacher Workflow

The app adheres strictly to a focused, 4-screen design that eliminates clutter and maximizes teacher efficiency:

1. **New Batch Screen (`NewBatchScreen.kt`)**
   - **Exam Name & Subject Code**: Declared once upfront (Subject Code is required for validation).
   - **Optional Class Roster**: Import CSV containing student roll numbers. Automatically reconciles processed sheets against the roster.
   - **Action Buttons**: "Scan Pages" (CameraX) and "Import Images" (system multi-image picker).

2. **Processing Screen (`ProcessingScreen.kt`)**
   - **Live Queue**: Real-time progress bar with per-sheet processing cards.
   - **Per-Sheet Status**: Displays thumbnail, current status (`Queued`, `Reading...`, `Done`, `Failed`).
   - **Error Handling**: One-tap "Retry" button on failed sheets; "Proceed to Review" when finished.

3. **Review List Screen (`ReviewListScreen.kt`)**
   - **Metrics Banner**: Four quick-count metric cards: `Total`, `OK`, `Check`, `Rescan`.
   - **Filter Chips**: Filter by `All`, `Needs Review`, `Rescan`, or `Done`.
   - **Quality Banners**:
     - *Subject Code Consensus Warning*: Alerts teacher if scanned sheets disagree with declared code.
     - *Duplicate Enrolment Alert*: Flags duplicates within the same batch.
     - *Missing from Roster Section*: Lists students from the imported roster with no sheet scanned.
   - **Export Buttons**: Direct export to CSV and formatted printable PDF.

4. **Sheet Detail Inspector (`SheetDetailScreen.kt`)**
   - **Zoomable Image View**: High-resolution image canvas with bounding box overlays for detected enrolment combs and marks crops.
   - **Plain-Language Reason Badges**: Converts technical backend flags into actionable teacher alerts (e.g. `BLURRY_OR_OFF_CENTER`, `TAIL_UNCERTAIN`, `FORMAT_MISMATCH`).
   - **Inline Editor**: Allows immediate correction of Enrolment Number and Total Marks, recalculating review state instantly upon save.

5. **Settings Screen (`SettingsScreen.kt`)**
   - Direct configuration of backend base URL (defaults to `http://10.0.2.2:8000/` for standard Android Emulator).
   - Live **"Test Connection"** ping against `/health` with round-trip latency counter and clear diagnostic messages.

---

## 3. Backend API Contract (OCR v2)

The client communicates with the frozen FastAPI OCR v2 backend:

| Endpoint | Method | Payload / Query Parameters | Response |
|---|---|---|---|
| `/health` | `GET` | None | `{ "status": "healthy", "version": "...", "ocr_v2_available": true }` |
| `/v2/predict` | `POST` | `multipart/form-data`: `file`, `subject_code_declared` (optional), `extract_total_marks=true` | `OcrV2PredictResponse` (enrolment, total_marks, needs_review, rescan_recommended, review_reasons, format, boxes) |
| `/v2/batch` | `POST` | `multipart/form-data`: `files[]`, `subject_code_declared`, `roster` (CSV string) | `OcrV2BatchResponse` (sheets summary, duplicate_enrolments, missing_from_roster, subject_code_consensus) |

---

## 4. Key Fixes & Engineering Decisions Applied

1. **SQLite 2MB `CursorWindow` Overflow Prevention:**
   - *Issue*: Loading large CSV rosters (e.g. thousands of rows) caused Room's SQLite query to exceed Android's 2MB window buffer (`IllegalStateException: Couldn't read row 0, col 0 from CursorWindow`).
   - *Fix*: Roster ingestion in `NewBatchScreen.kt` and `BatchViewModel.kt` caps parsed records cleanly to 500 entries, preventing database query crashes.

2. **Android 8+ `file://` URI Streaming Fix:**
   - *Issue*: Directly using `ContentResolver.openInputStream(uri)` on `file://` schemes generated `FileUriExposedException` or null streams on newer Android versions.
   - *Fix*: Implemented `openStream(uri)` in `ImagePreprocessor.kt` that detects `file://` schemes and streams directly from `FileInputStream`.

3. **Room Database Schema v3 Migration:**
   - Upgraded Room schema with `fallbackToDestructiveMigration()` for smooth development updates.
   - Schema tracks: `batchId`, `examName`, `subjectCode`, `rosterJson`, `imageUri`, `enrolment`, `totalMarks`, `needsReview`, `rescanRecommended`, `reviewReasonsJson`, `status`, and `isConfirmed`.

4. **Plain English Reason Mapping:**
   - Implemented `ReasonMapper.kt` to translate raw backend enum flags (`COMB_NOT_FULLY_DETECTED`, `TAIL4_LOW_CONFIDENCE`, `PREFIX_SUSPICIOUS`, `EXCESSIVE_SKEW`, `DUPLICATE_ENROLMENT`) into concise, friendly guidance for educators.

---

## 5. Build & Test Instructions

### Prerequisites
- Android Studio Ladybug / Iguana or later
- JDK 17
- Android SDK API 34 (Build Tools 34.0.0, Min SDK 24)
- Android Emulator (e.g., Pixel or Nexus 4 API 26+)

### Command-Line Build & Test
Open PowerShell or bash in `C:\Users\sumit\AndroidStudioProjects\SheetDataExtractor`:

```powershell
# Run unit tests
.\gradlew testDebugUnitTest

# Assemble debug APK
.\gradlew assembleDebug

# Install on running emulator or device
.\gradlew installDebug
```

The compiled APK will be at:
`app/build/outputs/apk/debug/app-debug.apk`

---

## 6. Running with Backend Server

1. Start the FastAPI backend in the `exam_paper_extractor` repo with OCR v2 enabled:
   ```powershell
   cd c:\Users\sumit\Desktop\Samarth\python\exam_paper_extractor
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
2. Verify backend health on your workstation browser:
   `http://localhost:8000/health`
3. In the Android App Settings:
   - If running on Android Emulator: use `http://10.0.2.2:8000/`
   - If running on a physical Android device on the same Wi-Fi: use `http://<YOUR_PC_LOCAL_IP>:8000/`
   - Tap **"Test Connection"** to verify green status before starting a batch.
