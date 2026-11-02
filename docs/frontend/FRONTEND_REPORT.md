# Frontend Audit and Target Design Report

## Step 1: Frontend Architecture Audit

### 1. Technology Stack
- **Platform**: Android Native (minSdk: 24, targetSdk: 37, compileSdk: 37)
- **Language & Runtime**: Kotlin 2.3.20 on JetBrains JBR 25 (Gradle 9.5.0, Android Gradle Plugin 8.9.0)
- **UI Framework**: Jetpack Compose (Material 3 BOM 2024.09.00) with Compose Navigation (`androidx.navigation.compose:2.8.0`)
- **Image Loading**: Coil Compose (`io.coil-kt:coil-compose:2.7.0`)
- **Networking**: Retrofit 2.11.0 + OkHttp 4.12.0 with Gson converter and HttpLoggingInterceptor
- **Local Persistence**: Room 2.6.1 (`AppDatabase`, `BatchDao`, `SheetDao`, `ScanRecordDao`) with KSP compiler
- **Settings Store**: AndroidX DataStore Preferences (`androidx.datastore:datastore-preferences:1.1.1`)
- **Background Execution**: AndroidX WorkManager (`androidx.work:work-runtime-ktx:2.9.1`)
- **Scanning**: Google Play Services ML Kit Document Scanner (`play-services-mlkit-document-scanner:16.0.0-beta1`) and Android Activity Result Photo Picker (`ActivityResultContracts.GetMultipleContents` / `PickVisualMedia`)
- **Image Processing**: Android Graphics (`BitmapFactory`, `Matrix`, `ExifInterface`)

### 2. Entry Point, Screens, Navigation & State Handling
- **Entry Point**: `MainActivity.kt:38-59` (`ComponentActivity` setting `SheetDataExtractorTheme` and launching `AppNavigation`).
- **Existing Screens in Codebase**:
  1. `BatchListScreen.kt`: Multi-batch card list with creation dialog, server health indicator, and navigation to batch detail.
  2. `BatchDetailScreen.kt`: Grid/list of sheets in a batch, queue pause/resume controls, export buttons (CSV/PDF), image import dialog.
  3. `BatchReviewScreen.kt`: Single-sheet inspection with zoomable image, editable fields, rotation buttons, and next/prev sheet navigation.
  4. `HomeScreen.kt`: Legacy quick-scan single-sheet screen.
  5. `CameraCaptureScreen.kt`: Legacy CameraX view.
  6. `ImagePreviewScreen.kt`: Legacy crop and preview before single upload.
  7. `ResultScreen.kt`: Legacy single-sheet result screen.
  8. `HistoryScreen.kt`: Legacy single-scan history records list.
- **Navigation**: Handled via Jetpack Compose `NavHost` in `MainActivity.kt:100-205` with routes `Routes.BATCHES`, `Routes.BATCH_DETAIL`, `Routes.BATCH_REVIEW`, and `Routes.QUICK_SCAN`.
- **State Handling**:
  - `BatchViewModel.kt`: Owns `uiState: StateFlow<BatchUiState>` managing active batch, sheet list, queue worker status, and validation map.
  - `OcrViewModel.kt`: Owns `uiState: StateFlow<OcrUiState>` managing legacy single scan screen states and history records.

### 3. Networking Layer & Backend Endpoints Called Today
- **Networking Layer**: `RetrofitClient.kt` singleton creating OkHttpClient with 30s connect timeout, 120s read timeout, and Gson serialization.
- **Current Endpoints Called**:
  - `GET /health` (`OcrApiService.kt:21-22`, `OcrRepository.kt:61`, `SheetProcessingWorker.kt:123`): Model health check.
  - `POST /predict` (`OcrApiService.kt:25-28`, `OcrRepository.kt:106`, `SheetProcessingWorker.kt:167`): **Legacy v1 single-sheet prediction**.
  - **Neither `POST /v2/predict` nor `POST /v2/batch` was called anywhere in the app.**
- **Base URL Setting**:
  - Set in `RetrofitClient.kt:20` (`const val DEFAULT_EMULATOR_BASE_URL = "http://10.0.2.2:8000/"`)
  - Stored reactively in DataStore via `ServerPreferences.kt:19` (`const val DEFAULT_URL = "http://10.0.2.2:8000/"`)
  - Configurable via `ServerConfigDialog.kt`.

### 4. Backend API Contract (OCR v2)
Audited directly from backend source files `app/routers_v2.py`, `app/schemas.py`, and `tests_v2/test_api_v2.py`:

#### A. Single Sheet: `POST /v2/predict`
- **Definition**: `app/routers_v2.py:219-235`
- **Request Parameters**:
  - `file: UploadFile = File(...)` (`app/routers_v2.py:221`): Multipart cover-sheet image (JPEG, PNG, WEBP).
  - `extract_total_marks: bool = Form(True)` (`app/routers_v2.py:222`): Whether to extract total marks.
- **Response Structure** (`app/routers_v2.py:166-216`):
  - `filename: str` (`line 167`)
  - `format_id: str` (`line 168`): `"format_original"` or `"format_v2"`
  - `rescan_recommended: bool` (`line 169`): Flag indicating unrecoverable comb/crop geometry error
  - `needs_review: bool` (`line 170`): True if any field or alignment requires teacher review
  - `review_reasons: List[str]` (`line 171`): List of active reason codes
  - `overall_needs_review: bool` (`line 172`)
  - `enrolment: dict` (`lines 173-181`):
    - `value: Optional[str]`: Cleaned 12-char roll number (or null)
    - `raw_text: str`: Raw OCR characters
    - `confidence: float`: Mean confidence [0.0, 1.0]
    - `char_confidences: List[float]`: Per-character confidences
    - `needs_review: bool`: Field-specific review flag
    - `rescan_recommended: bool`: Field-specific rescan flag
    - `review_reasons: List[str]`: Enrolment specific reason codes
  - `subject_code: dict` (`lines 182-190`):
    - `value: Optional[str]`: Extracted/matched subject code
    - `raw_text: str`: Raw OCR characters
    - `confidence: float`: Reading confidence
    - `matched_code: Optional[str]`: Syllabus-matched code
    - `needs_review: bool`: Review flag
    - `rescan_recommended: bool`: Rescan flag
    - `review_reasons: List[str]`: Subject-code specific reason codes
  - `total_marks: dict` (`lines 191-198`):
    - `value: Optional[Union[int, float, str]]`: Extracted grand total (e.g. 54 or 54.0)
    - `raw_text: Optional[str]`: Raw OCR characters
    - `confidence: Optional[float]`: OCR confidence
    - `flags: List[str]`: List of marks flags (e.g. `RHS_MISSING`, `OUT_OF_RANGE`, `needs_review`)
    - (Or `{"status": "SKIPPED"}` if `extract_total_marks=False`)
  - `alignment: dict` (`lines 199-207`):
    - `dx: float`, `dy: float`, `rot_deg: float`, `quality_score: float`
    - `needs_review: bool`, `rescan_recommended: bool`, `review_reasons: List[str]`
  - `latency_ms: dict` (`lines 208-215`):
    - `decode`, `format_detect`, `normalise`, `crop`, `read`, `total`

#### B. Multi-Sheet Batch: `POST /v2/batch`
- **Definition**: `app/routers_v2.py:237-316`
- **Request Parameters**:
  - `files: List[UploadFile] = File(...)` (`app/routers_v2.py:239`): List of multipart cover-sheet images
  - `subject_code_declared: Optional[str] = Form(None)` (`app/routers_v2.py:240`): Subject code declared by teacher
  - `roster: Optional[str] = Form(None)` (`app/routers_v2.py:241`): JSON array or comma-separated roll numbers
  - `extract_total_marks: bool = Form(True)` (`app/routers_v2.py:242`)
- **Response Structure** (`app/routers_v2.py:304-316`):
  - `total_sheets: int` (`line 305`)
  - `sheets: List[dict]` (`line 306`): Per-sheet results conforming to `/v2/predict` response with batch review signals attached
  - `batch_consensus: dict` (`line 307`):
    - `status: str` (`"OK"`, `"DECLARED_MISMATCH"`, `"NO_CONSENSUS"`, `"NO_VALID_READS"`)
    - `consensus_code: Optional[str]`
    - `agreement_ratio: float`
    - `is_unanimous: bool`
    - `needs_review: bool`
    - `valid_votes: int`
    - `vote_distribution: Dict[str, int]`
    - `subject_code_declared: Optional[str]`
    - `evidence: Optional[dict]`
  - `batch_review: dict` (`lines 308-315`):
    - `total_sheets: int`
    - `flagged_sheets: int`
    - `rescan_count: int`
    - `duplicate_enrolments: Dict[str, List[str]]` (mapping duplicate roll numbers to list of sheet names)
    - `roster_provided: bool`
    - `missing_from_batch: List[str]` (roster students with no sheet found in batch)

### 5. What is Broken, Confusing, Duplicated or Dead in the Current UI
1. **Dead backend endpoints**: Entire app called legacy v1 `/predict` and completely ignored `/v2/predict` and `/v2/batch`.
2. **Duplicated navigation paths**: App had two competing flows: a multi-batch workflow and a "Quick Scan" single-image flow.
3. **Redundant screens and models**: `HomeScreen`, `CameraCaptureScreen`, `ImagePreviewScreen`, `ResultScreen`, and `HistoryScreen` duplicated batch functionality with an obsolete `ScanRecord` database table.
4. **No class roster import**: Teachers had no mechanism to import a class list CSV to cross-check student attendance.
5. **No declared subject code consensus banner**: The app never collected the teacher's declared subject code upfront or alerted them if sheets disagreed.
6. **Cryptic error codes**: Flags like `DUPLICATE_ENROLMENT` or `COMB_TOUCHES_PAGE_EDGE` were not translated into teacher-friendly plain language.
7. **No roll duplicate grouping**: Sheets with duplicate roll numbers were scattered across the list with no visual pairing.
8. **Total marks treated as high-confidence**: Total marks lacked the cautionary check indicator reflecting that marks extraction is less reliable than enrolment.
9. **Unsafe bulk confirm**: Flagged sheets could be erroneously bulk-confirmed without human verification.
10. **Confusing queue controls**: Background worker had complex pause/resume controls that made batch progress opaque during demos.
11. **Scattered settings**: Server URL configuration was buried in dialogs rather than accessible via a clean, dedicated Settings screen.
12. **No crop bounding highlights on sheet detail**: Teachers could not visually verify the exact comb or total marks crop location against the full page image.
13. **Inconsistent export formats**: CSV headers did not match the required teacher export schema (`batch_id`, `subject_code_declared`, `filename`, `enrolment_final`, `enrolment_ocr`, `total_marks_final`, `total_marks_ocr`, `status`, `flags`).
14. **Lack of offline / connection error clarity**: Raw network timeout or connection refused exceptions displayed cryptic stack traces.

---

## Step 2: Target Design

The redesigned application adheres to a clean, focused, 4-screen flow tailored for a teacher's real evaluation session, plus a tiny Settings screen.

### 1. Screen 1: NEW BATCH
- **Required Inputs**:
  - Exam Name (e.g., "Mid-Term Fall 2026")
  - Subject Code (e.g., "CT10718") - declared once per batch.
- **Optional Input**:
  - "Import class list" button to import a CSV file containing one enrolment number per line. Shows imported student count badge once loaded.
- **Action Buttons**:
  - Two prominent buttons: **"Scan pages"** (launches Google ML Kit Document Scanner if supported, with graceful camera fallback) and **"Import images"** (multi-image picker for emulator or device gallery).

### 2. Screen 2: PROCESSING
- **Thumbnail Grid**: Visual grid displaying imported sheets with clear status indicators:
  - `Queued` (waiting)
  - `Reading` (spinner with "Reading...")
  - `Done` (green checkmark)
  - `Failed` (red alert with manual "Retry" button)
- **Controls**: Sequential uploading with 30s per-sheet timeout. Once all sheets finish, automatically transitions to or enables "Review Batch".

### 3. Screen 3: REVIEW LIST
- **Header Counts**: Summary cards displaying `Total`, `OK`, `Check`, and `Rescan`.
- **Filter Chips**: `All`, `Check`, `Rescan`, `Done`.
- **Priority Sorting**: Sheets needing attention (`needs_review` or `rescan_recommended`) appear first.
- **Informational Banners**:
  - Missing from batch: If a class list was imported, lists roll numbers missing from the batch.
  - Subject code mismatch: If batch consensus disagrees with the declared code, shows one quiet top banner (`"Detected CT10715 on most sheets; declared CT10718"`).
- **Sheet Rows**:
  - Sheet thumbnail.
  - Read enrolment and total marks with inline editability.
  - Small "check" indicator on total marks reminding teachers that marks extraction requires visual verification.
  - Plain-language status chip (e.g., `"Another sheet has the same roll number"`, `"Part of the roll number box is cut off. Rescan this page"`).
  - Visual warning grouping for duplicate roll numbers.
- **Actions**:
  - **"Confirm all OK"**: Instantly confirms only unflagged sheets (flagged sheets cannot be bulk-confirmed).
  - Tap row to navigate to Sheet Detail.
  - Top-Right Action: **Export** (CSV and PDF via Android Share Sheet).

### 4. Screen 4: SHEET DETAIL
- **Zoomable Page View**: Interactive zoom & pan showing the full cover-sheet image.
- **Highlighted Crop ROIs**: Overlays showing the estimated enrolment comb bounding box and total marks bounding box.
- **Fields & Status**:
  - Editable enrolment number with OCR confidence indicator.
  - Editable total marks with OCR confidence indicator.
  - Plain-language review reason banner.
- **Bottom Actions**:
  - **"Confirm"**: Marks sheet as confirmed and advances.
  - **"Rescan this page"**: Replaces the image with a newly scanned/imported image.
  - **"Next sheet that needs check"**: Jumps directly to the next sheet requiring human attention.

### 5. Settings Screen & Exports
- **Settings Screen**:
  - Server URL text field (default `http://10.0.2.2:8000/`).
  - "Test connection" button pinging `/health` with immediate latency and model readiness feedback.
- **Export CSV**:
  - Columns: `batch_id,subject_code_declared,filename,enrolment_final,enrolment_ocr,total_marks_final,total_marks_ocr,status,flags`
  - Filename: `<subject>_<date>.csv`
- **Export PDF**:
  - One A4 page per sheet in scan order, JPEG-compressed.
  - Filename: `<subject>_<date>.pdf`
  - Both opened directly via the Android system share sheet.
