/**
 * Sheet Data Extractor — Teacher Verification Portal
 * Frontend Application Logic (OCR v2)
 */

(function () {
  'use strict';

  // ============================================================================
  // Application State
  // ============================================================================
  const state = {
    apiBaseUrl: (typeof localStorage !== 'undefined' ? localStorage.getItem('ocr_v2_api_url') : null) || 'http://localhost:8000',
    apiKey: (typeof localStorage !== 'undefined' ? localStorage.getItem('ocr_v2_api_key') : null) || 'ep_admin_master_secret_key_deploy2',
    examName: 'Mid-Term Exam 2026',
    subjectCodeDeclared: '',
    rosterList: [], // array of roll strings
    stagedFiles: [], // array of File objects
    processedSheets: [], // array of sheet results
    activeFilter: 'ALL', // 'ALL' | 'OK' | 'CHECK' | 'RESCAN'
    searchQuery: '',
    currentInspectIndex: -1,
    isProcessing: false,
    cancelRequested: false,
    batchConsensusMismatch: false,
    missingRosterRolls: [],
  };

  // ============================================================================
  // Reason Mapper (Matches Android ReasonMapper.kt + prefix support)
  // ============================================================================
  const ReasonMapper = {
    toPlainLanguage(code) {
      if (!code) return '';
      const c = String(code).trim();
      const upper = c.toUpperCase();

      if (upper.startsWith('DUPLICATE_ENROLMENT')) {
        return 'Another sheet has the same roll number';
      }
      if (upper.startsWith('ROLL_OUT_OF_RANGE')) {
        return 'Roll number looks outside usual range';
      }
      if (upper.startsWith('INVALID_PREFIX') || upper.startsWith('PREFIX_')) {
        return 'Roll number prefix looks wrong';
      }
      if (upper.startsWith('LOW_CONFIDENCE') || upper.startsWith('LOW_CONF')) {
        return 'Handwriting is hard to read, please check';
      }
      if (upper.startsWith('READ_NOT_IN_ROSTER')) {
        return 'Not in the class list';
      }
      if (upper.startsWith('RHS_MISSING')) {
        return 'Total marks looks incomplete';
      }
      if (upper.startsWith('OUT_OF_RANGE')) {
        return 'Marks outside 0 to 70';
      }
      if (upper.startsWith('TOTAL_MARKS_REVIEW')) {
        return 'Total marks formula needs verification';
      }
      if (upper.startsWith('NO_KNOWN_CODE_MATCH')) {
        return 'Subject code not recognized';
      }
      if (
        upper === 'SHEET_NOT_RECOGNISED' ||
        upper.startsWith('PAGE_CUT_OFF') ||
        upper.startsWith('PAGE_') ||
        upper === 'UNKNOWN_LAYOUT' ||
        upper === 'NO_VALUES'
      ) {
        return 'Sheet not recognised. Scan the whole sheet in colour with the scanner.';
      }
      if (
        upper.startsWith('RESCAN_RECOMMENDED') ||
        upper.startsWith('COMB_TOUCHES_PAGE_EDGE') ||
        upper.startsWith('COMB_NOT_FULLY_DETECTED')
      ) {
        return 'Sheet not recognised. Scan the whole sheet in colour with the scanner.';
      }
      if (upper.startsWith('PAGE_CUT_OFF_OR_UNRECOGNISED')) {
        return 'Sheet not recognised. Scan the whole sheet in colour with the scanner.';
      }
      if (upper.startsWith('EXCESSIVE_SKEW')) {
        return 'Page is tilted. Rescan recommended';
      }
      return c;
    },
    isRescanFlag(code) {
      if (!code) return false;
      const upper = String(code).trim().toUpperCase();
      return (
        upper === 'SHEET_NOT_RECOGNISED' ||
        upper.startsWith('PAGE_') ||
        upper === 'UNKNOWN_LAYOUT' ||
        upper === 'NO_VALUES' ||
        upper.startsWith('RESCAN_RECOMMENDED') ||
        upper.startsWith('COMB_TOUCHES_PAGE_EDGE') ||
        upper.startsWith('COMB_NOT_FULLY_DETECTED') ||
        upper.startsWith('PAGE_CUT_OFF_OR_UNRECOGNISED') ||
        upper.startsWith('EXCESSIVE_SKEW') ||
        upper === 'API_ERROR'
      );
    },
    getTagCategory(code) {
      if (!code) return 'info';
      const upper = String(code).trim().toUpperCase();
      if (this.isRescanFlag(code)) {
        return 'rescan';
      }
      // Subject code flags are informational only and never affect sheet status
      if (upper.startsWith('NO_KNOWN_CODE_MATCH') || upper.includes('SUBJECT_CODE') || upper.startsWith('SUBJECT_')) {
        return 'info';
      }
      // Recognized review flags
      if (
        upper.startsWith('DUPLICATE_ENROLMENT') ||
        upper.startsWith('ROLL_OUT_OF_RANGE') ||
        upper.startsWith('INVALID_PREFIX') ||
        upper.startsWith('PREFIX_') ||
        upper.startsWith('LOW_CONFIDENCE') ||
        upper.startsWith('LOW_CONF') ||
        upper.startsWith('READ_NOT_IN_ROSTER') ||
        upper.startsWith('RHS_MISSING') ||
        upper.startsWith('OUT_OF_RANGE') ||
        upper.startsWith('TOTAL_MARKS_REVIEW') ||
        upper.startsWith('ALIGNMENT_') ||
        upper === 'NEEDS_REVIEW'
      ) {
        return 'check';
      }
      // All other unknown codes: display in small grey text
      return 'info';
    }
  };

  function buildResultsCSV(sheets, declaredSubjectCode) {
    const headers = [
      'filename',
      'subject_code',
      'enrolment_no',
      'marks',
      'q1',
      'q2',
      'q3',
      'q4',
      'q5'
    ];

    const escapeCsv = (val) => {
      if (val === null || val === undefined) return '';
      const str = String(val);
      if (str.includes(',') || str.includes('"') || str.includes('\n')) {
        return `"${str.replace(/"/g, '""')}"`;
      }
      return str;
    };

    const rows = (sheets || []).map(s => {
      const filename = s.filename || '';
      const subjectCode = declaredSubjectCode || (s.subject_code ? (s.subject_code.matched_code || s.subject_code.value || '') : '');
      const enrolmentNo = s.final_enrolment || '';
      const marks = s.final_total_marks !== undefined && s.final_total_marks !== null ? s.final_total_marks : '';
      const q1 = (s.q1 !== undefined && s.q1 !== null) ? s.q1 : '';
      const q2 = (s.q2 !== undefined && s.q2 !== null) ? s.q2 : '';
      const q3 = (s.q3 !== undefined && s.q3 !== null) ? s.q3 : '';
      const q4 = (s.q4 !== undefined && s.q4 !== null) ? s.q4 : '';
      const q5 = (s.q5 !== undefined && s.q5 !== null) ? s.q5 : '';

      return [
        escapeCsv(filename),
        escapeCsv(subjectCode),
        escapeCsv(enrolmentNo),
        escapeCsv(marks),
        escapeCsv(q1),
        escapeCsv(q2),
        escapeCsv(q3),
        escapeCsv(q4),
        escapeCsv(q5)
      ].join(',');
    });

    return [headers.join(','), ...rows].join('\r\n');
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { buildResultsCSV };
  }

  if (typeof document === 'undefined') {
    return;
  }

  // ============================================================================
  // DOM Elements
  // ============================================================================
  const el = {
    // Navigation / Header
    serverStatusBtn: document.getElementById('serverStatusBtn'),
    serverStatusText: document.getElementById('serverStatusText'),
    serverPingMs: document.getElementById('serverPingMs'),
    btnNewBatchNav: document.getElementById('btnNewBatchNav'),
    btnSettings: document.getElementById('btnSettings'),

    // Views
    viewNewBatch: document.getElementById('viewNewBatch'),
    viewProcessing: document.getElementById('viewProcessing'),
    viewReview: document.getElementById('viewReview'),

    // View 1: New Batch
    inputExamName: document.getElementById('inputExamName'),
    inputSubjectCode: document.getElementById('inputSubjectCode'),
    rosterDropArea: document.getElementById('rosterDropArea'),
    inputRosterFile: document.getElementById('inputRosterFile'),
    rosterStatusLabel: document.getElementById('rosterStatusLabel'),
    rosterSummary: document.getElementById('rosterSummary'),
    rosterCountChip: document.getElementById('rosterCountChip'),
    btnClearRoster: document.getElementById('btnClearRoster'),
    sheetsDropZone: document.getElementById('sheetsDropZone'),
    inputSheetFiles: document.getElementById('inputSheetFiles'),
    btnBrowseSheets: document.getElementById('btnBrowseSheets'),
    stagedFilesContainer: document.getElementById('stagedFilesContainer'),
    stagedCountLabel: document.getElementById('stagedCountLabel'),
    btnClearStaged: document.getElementById('btnClearStaged'),
    stagedThumbs: document.getElementById('stagedThumbs'),
    btnStartProcessing: document.getElementById('btnStartProcessing'),
    btnSheetCount: document.getElementById('btnSheetCount'),

    // View 2: Processing
    procProgressTitle: document.getElementById('procProgressTitle'),
    procProgressFraction: document.getElementById('procProgressFraction'),
    procProgressPct: document.getElementById('procProgressPct'),
    procProgressBar: document.getElementById('procProgressBar'),
    queueGrid: document.getElementById('queueGrid'),
    btnCancelProcessing: document.getElementById('btnCancelProcessing'),
    btnProceedToReview: document.getElementById('btnProceedToReview'),

    // View 3: Review
    revSubjectBadge: document.getElementById('revSubjectBadge'),
    revExamBadge: document.getElementById('revExamBadge'),
    alertContainer: document.getElementById('alertContainer'),
    countTotal: document.getElementById('countTotal'),
    countOk: document.getElementById('countOk'),
    countCheck: document.getElementById('countCheck'),
    countRescan: document.getElementById('countRescan'),
    chipAllCount: document.getElementById('chipAllCount'),
    chipCheckCount: document.getElementById('chipCheckCount'),
    chipRescanCount: document.getElementById('chipRescanCount'),
    chipOkCount: document.getElementById('chipOkCount'),
    inputSearchRoll: document.getElementById('inputSearchRoll'),
    reviewTableBody: document.getElementById('reviewTableBody'),
    missingRosterBox: document.getElementById('missingRosterBox'),
    missingRosterToggle: document.getElementById('missingRosterToggle'),
    missingRosterCount: document.getElementById('missingRosterCount'),
    missingRosterBody: document.getElementById('missingRosterBody'),
    missingTagsGrid: document.getElementById('missingTagsGrid'),
    btnExportCsv: document.getElementById('btnExportCsv'),
    btnExportBatchPdf: document.getElementById('btnExportBatchPdf'),
    btnPrintReport: document.getElementById('btnPrintReport'),
    printExamTitle: document.getElementById('printExamTitle'),
    printSubjectCode: document.getElementById('printSubjectCode'),
    printDate: document.getElementById('printDate'),
    printTotalCount: document.getElementById('printTotalCount'),

    // Export Confirmation Modal
    exportConfirmModal: document.getElementById('exportConfirmModal'),
    btnCloseExportConfirm: document.getElementById('btnCloseExportConfirm'),
    exportConfirmMessage: document.getElementById('exportConfirmMessage'),
    btnReviewFirst: document.getElementById('btnReviewFirst'),
    btnExportAnyway: document.getElementById('btnExportAnyway'),

    // Modals
    inspectorModal: document.getElementById('inspectorModal'),
    inspectorTitle: document.getElementById('inspectorTitle'),
    inspectorFilename: document.getElementById('inspectorFilename'),
    btnCloseInspector: document.getElementById('btnCloseInspector'),
    inspectorImg: document.getElementById('inspectorImg'),
    inspectorReasonsList: document.getElementById('inspectorReasonsList'),
    editEnrolment: document.getElementById('editEnrolment'),
    rawEnrolmentText: document.getElementById('rawEnrolmentText'),
    confEnrolment: document.getElementById('confEnrolment'),
    editTotalMarks: document.getElementById('editTotalMarks'),
    rawMarksText: document.getElementById('rawMarksText'),
    editQ1: document.getElementById('editQ1'),
    editQ2: document.getElementById('editQ2'),
    editQ3: document.getElementById('editQ3'),
    editQ4: document.getElementById('editQ4'),
    editQ5: document.getElementById('editQ5'),
    rawQ1Text: document.getElementById('rawQ1Text'),
    rawQ2Text: document.getElementById('rawQ2Text'),
    rawQ3Text: document.getElementById('rawQ3Text'),
    rawQ4Text: document.getElementById('rawQ4Text'),
    rawQ5Text: document.getElementById('rawQ5Text'),
    inspectorQSum: document.getElementById('inspectorQSum'),
    inspectorSumStatus: document.getElementById('inspectorSumStatus'),
    inspectorFormatBadge: document.getElementById('inspectorFormatBadge'),
    btnSaveInspector: document.getElementById('btnSaveInspector'),
    btnPrevSheet: document.getElementById('btnPrevSheet'),
    btnNextSheet: document.getElementById('btnNextSheet'),
    sheetNavIndex: document.getElementById('sheetNavIndex'),

    // Settings Modal
    settingsModal: document.getElementById('settingsModal'),
    inputApiBaseUrl: document.getElementById('inputApiBaseUrl'),
    inputApiKey: document.getElementById('inputApiKey'),
    serverTestResult: document.getElementById('serverTestResult'),
    btnCloseSettings: document.getElementById('btnCloseSettings'),
    btnTestApi: document.getElementById('btnTestApi'),
    btnSaveSettings: document.getElementById('btnSaveSettings'),

    toastContainer: document.getElementById('toastContainer')
  };

  // ============================================================================
  // Toast Notifications
  // ============================================================================
  function showToast(message, duration = 3000) {
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    el.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transition = 'opacity 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  // ============================================================================
  // View Router
  // ============================================================================
  function switchView(viewName) {
    el.viewNewBatch.classList.remove('active');
    el.viewProcessing.classList.remove('active');
    el.viewReview.classList.remove('active');

    if (viewName === 'NEW_BATCH') {
      el.viewNewBatch.classList.add('active');
      el.btnNewBatchNav.style.display = 'none';
    } else if (viewName === 'PROCESSING') {
      el.viewProcessing.classList.add('active');
      el.btnNewBatchNav.style.display = 'none';
    } else if (viewName === 'REVIEW') {
      el.viewReview.classList.add('active');
      el.btnNewBatchNav.style.display = 'inline-flex';
      renderReviewDashboard();
    }
  }

  // ============================================================================
  // Backend Health Ping & Settings
  // ============================================================================
  async function pingServer(customUrl = null) {
    const targetUrl = (customUrl || state.apiBaseUrl).replace(/\/+$/, '');
    const startTime = performance.now();

    try {
      const resp = await fetch(`${targetUrl}/health`, {
        method: 'GET',
        headers: {
          'X-API-Key': state.apiKey || 'ep_admin_master_secret_key_deploy2'
        },
        cache: 'no-cache'
      });
      const durationMs = Math.round(performance.now() - startTime);

      if (resp.ok) {
        const data = await resp.json();
        return {
          ok: true,
          durationMs,
          data
        };
      } else {
        return {
          ok: false,
          durationMs,
          statusText: `HTTP ${resp.status}: ${resp.statusText}`
        };
      }
    } catch (err) {
      return {
        ok: false,
        durationMs: Math.round(performance.now() - startTime),
        error: err.message
      };
    }
  }

  async function updateServerStatusIndicator() {
    const res = await pingServer();
    if (res.ok) {
      el.serverStatusBtn.className = 'status-pill status-online';
      el.serverStatusText.textContent = 'API Connected';
      el.serverPingMs.textContent = `${res.durationMs} ms`;
    } else {
      el.serverStatusBtn.className = 'status-pill status-offline';
      el.serverStatusText.textContent = 'API Offline';
      el.serverPingMs.textContent = '--';
    }
  }

  // Poll health periodically
  updateServerStatusIndicator();
  setInterval(updateServerStatusIndicator, 15000);

  // ============================================================================
  // File Upload & Staging Handlers
  // ============================================================================
  function updateStartButtonState() {
    const count = state.stagedFiles.length;
    const hasSubject = (el.inputSubjectCode.value || '').trim().length > 0;
    el.btnSheetCount.textContent = count;
    el.btnStartProcessing.disabled = count === 0 || !hasSubject;
  }

  el.inputSubjectCode.addEventListener('input', updateStartButtonState);

  // Roster CSV Handler
  el.rosterDropArea.addEventListener('click', () => el.inputRosterFile.click());
  el.inputRosterFile.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (evt) => {
      const text = evt.target.result;
      const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
      const parsedRolls = [];

      for (const line of lines) {
        // Support CSV row with commas: take the first item
        const firstCol = line.split(',')[0].trim().replace(/['"]/g, '');
        if (firstCol && !firstCol.toLowerCase().includes('roll') && !firstCol.toLowerCase().includes('enrol')) {
          parsedRolls.push(firstCol.toUpperCase());
        }
      }

      // Safe limit up to 500 rolls to avoid browser memory lag
      state.rosterList = [...new Set(parsedRolls)].slice(0, 500);
      el.rosterStatusLabel.textContent = `Selected: ${file.name}`;
      el.rosterCountChip.textContent = `${state.rosterList.length} students loaded`;
      el.rosterSummary.style.display = 'flex';
      showToast(`Loaded roster with ${state.rosterList.length} roll numbers.`);
    };
    reader.readAsText(file);
  });

  el.btnClearRoster.addEventListener('click', (e) => {
    e.stopPropagation();
    state.rosterList = [];
    el.inputRosterFile.value = '';
    el.rosterStatusLabel.textContent = 'Click to select roster CSV (one roll number per row)';
    el.rosterSummary.style.display = 'none';
    showToast('Class roster cleared.');
  });

  // Sheet Files Drag & Drop
  el.btnBrowseSheets.addEventListener('click', (e) => {
    e.stopPropagation();
    el.inputSheetFiles.click();
  });
  el.sheetsDropZone.addEventListener('click', () => el.inputSheetFiles.click());

  ['dragenter', 'dragover'].forEach(eventName => {
    el.sheetsDropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      el.sheetsDropZone.classList.add('dragover');
    }, false);
  });

  ['dragleave', 'drop'].forEach(eventName => {
    el.sheetsDropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      el.sheetsDropZone.classList.remove('dragover');
    }, false);
  });

  el.sheetsDropZone.addEventListener('drop', (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    stageFiles(Array.from(files));
  });

  el.inputSheetFiles.addEventListener('change', (e) => {
    stageFiles(Array.from(e.target.files));
  });

  function stageFiles(files) {
    const validExts = ['.jpg', '.jpeg', '.png', '.webp'];
    const imageFiles = files.filter(f => {
      const ext = f.name.substring(f.name.lastIndexOf('.')).toLowerCase();
      return validExts.includes(ext);
    });

    if (imageFiles.length === 0) {
      showToast('Please select valid image files (.png, .jpg, .webp)');
      return;
    }

    state.stagedFiles = [...state.stagedFiles, ...imageFiles];
    renderStagedFiles();
    updateStartButtonState();
  }

  function renderStagedFiles() {
    if (state.stagedFiles.length === 0) {
      el.stagedFilesContainer.style.display = 'none';
      return;
    }

    el.stagedFilesContainer.style.display = 'block';
    el.stagedCountLabel.textContent = `${state.stagedFiles.length} sheets selected`;
    el.stagedThumbs.innerHTML = '';

    // Render up to 24 thumbnails for performance
    const renderLimit = Math.min(state.stagedFiles.length, 24);
    for (let i = 0; i < renderLimit; i++) {
      const f = state.stagedFiles[i];
      const item = document.createElement('div');
      item.className = 'thumb-item';
      const img = document.createElement('img');
      img.src = URL.createObjectURL(f);
      img.title = f.name;
      item.appendChild(img);
      el.stagedThumbs.appendChild(item);
    }
  }

  /**
   * Preprocess file for safe, efficient upload: Automatically resizes client-side
   * to canonical pipeline resolution (maxEdge 1600px) and compresses to ~300KB JPEG.
   * Respects EXIF orientation metadata via createImageBitmap from-image.
   */
  async function prepareImageForUpload(file) {
    return new Promise((resolve) => {
      const maxEdge = 1600;

      const renderToJpeg = (source, naturalW, naturalH) => {
        let w = naturalW;
        let h = naturalH;

        if (w > maxEdge || h > maxEdge) {
          if (w > h) {
            h = Math.round((h * maxEdge) / w);
            w = maxEdge;
          } else {
            w = Math.round((w * maxEdge) / h);
            h = maxEdge;
          }
        }

        const canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d');
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(source, 0, 0, w, h);

        canvas.toBlob((blob) => {
          if (!blob) {
            resolve(file);
            return;
          }
          const resizedFile = new File([blob], file.name.replace(/\.[^.]+$/, '.jpg'), { type: 'image/jpeg' });
          resolve(resizedFile);
        }, 'image/jpeg', 0.85);
      };

      if (typeof createImageBitmap === 'function') {
        createImageBitmap(file, { imageOrientation: 'from-image' })
          .then((bmp) => {
            renderToJpeg(bmp, bmp.width, bmp.height);
          })
          .catch(() => {
            const img = new Image();
            const objUrl = URL.createObjectURL(file);
            img.onload = () => {
              URL.revokeObjectURL(objUrl);
              renderToJpeg(img, img.naturalWidth || img.width, img.naturalHeight || img.height);
            };
            img.onerror = () => {
              URL.revokeObjectURL(objUrl);
              resolve(file);
            };
            img.src = objUrl;
          });
      } else {
        const img = new Image();
        const objUrl = URL.createObjectURL(file);
        img.onload = () => {
          URL.revokeObjectURL(objUrl);
          renderToJpeg(img, img.naturalWidth || img.width, img.naturalHeight || img.height);
        };
        img.onerror = () => {
          URL.revokeObjectURL(objUrl);
          resolve(file);
        };
        img.src = objUrl;
      }
    });
  }

  el.btnClearStaged.addEventListener('click', () => {
    state.stagedFiles = [];
    el.inputSheetFiles.value = '';
    renderStagedFiles();
    updateStartButtonState();
  });

  // ============================================================================
  // Batch Execution Pipeline (View 2)
  // ============================================================================
  el.btnStartProcessing.addEventListener('click', () => {
    state.examName = el.inputExamName.value.trim() || 'Exam Batch';
    state.subjectCodeDeclared = el.inputSubjectCode.value.trim().toUpperCase();

    if (!state.subjectCodeDeclared) {
      alert('Please provide a Subject Code.');
      return;
    }
    if (state.stagedFiles.length === 0) {
      alert('Please add at least one exam cover sheet.');
      return;
    }

    startBatchProcessing();
  });

  async function startBatchProcessing() {
    state.isProcessing = true;
    state.cancelRequested = false;

    // Initialize processed sheets array
    state.processedSheets = state.stagedFiles.map((f, idx) => ({
      id: idx + 1,
      file: f,
      filename: f.name,
      thumbUrl: URL.createObjectURL(f),
      status: 'QUEUED', // 'QUEUED' | 'READING' | 'DONE' | 'FAILED'
      error: null,
      enrolment: null,
      subject_code: null,
      total_marks: null,
      format_id: null,
      needs_review: false,
      rescan_recommended: false,
      review_reasons: [],
      is_confirmed: false,
      final_enrolment: '',
      final_total_marks: '',
      notes: ''
    }));

    switchView('PROCESSING');
    renderProcessingQueue();

    let completedCount = 0;
    const total = state.processedSheets.length;

    for (let i = 0; i < total; i++) {
      if (state.cancelRequested) break;

      const item = state.processedSheets[i];
      item.status = 'READING';
      updateQueueItemView(item);

      el.procProgressTitle.textContent = `Reading ${item.filename}...`;
      el.procProgressFraction.textContent = `${completedCount} / ${total} completed`;
      el.procProgressPct.textContent = `${Math.round((completedCount / total) * 100)}%`;
      el.procProgressBar.style.width = `${Math.round((completedCount / total) * 100)}%`;

      try {
        // Preprocess file for safe, efficient upload
        const uploadFile = await prepareImageForUpload(item.file);
        const formData = new FormData();
        formData.append('file', uploadFile);
        formData.append('extract_total_marks', 'true');
        formData.append('extract_question_marks', 'true');

        const resp = await fetch(`${state.apiBaseUrl}/v2/predict`, {
          method: 'POST',
          headers: {
            'X-API-Key': state.apiKey || 'ep_admin_master_secret_key_deploy2'
          },
          body: formData
        });

        if (!resp.ok) {
          throw new Error(`Server returned HTTP ${resp.status}`);
        }

        const data = await resp.json();
        item.status = 'DONE';
        item.format_id = data.format_id || data.detected_format || 'UNKNOWN';
        item.enrolment = data.enrolment || {};
        item.subject_code = data.subject_code || {};
        item.total_marks = data.total_marks || {};
        item.rescan_recommended = Boolean(data.rescan_recommended);
        if (data.image_preview) {
          item.thumbUrl = data.image_preview;
        }

        item.final_enrolment = (item.enrolment.value || '').toUpperCase();
        item.final_total_marks = (item.total_marks.value !== undefined && item.total_marks.value !== null) ? item.total_marks.value : '';

        // Question marks q1..q5 mapping if returned
        const qList = Array.isArray(data.q_marks) ? data.q_marks : (Array.isArray(data.question_marks) ? data.question_marks : []);
        item.q_marks = qList;
        for (let i = 1; i <= 5; i++) {
          item[`q${i}`] = '';
        }
        qList.forEach((qm, idx) => {
          const num = qm.q !== undefined ? qm.q : (qm.q_number !== undefined ? qm.q_number : (qm.question !== undefined ? qm.question : (idx + 1)));
          if (num >= 1 && num <= 5) {
            item[`q${num}`] = (qm.value !== undefined && qm.value !== null) ? qm.value : '';
          }
        });
        item.marks_sum = data.marks_sum || null;

        // Check if layout UNKNOWN, no values, or page flag
        const hasEnrolVal = Boolean(item.enrolment && item.enrolment.value);
        const hasTotalVal = Boolean(item.total_marks && item.total_marks.value !== null && item.total_marks.value !== undefined);
        const hasValues = hasEnrolVal || hasTotalVal;
        const pageFlag = Boolean(data.page_status === 'CUT_OFF' || data.page_status === 'NOT_FOUND' ||
          (Array.isArray(data.review_reasons) && data.review_reasons.some(r => r.startsWith('PAGE_') || r === 'PAGE_CUT_OFF_OR_UNRECOGNISED')));

        const isUnrecognised = (item.format_id === 'UNKNOWN') || (!hasValues) || pageFlag || item.rescan_recommended;
        item.review_reasons = Array.isArray(data.review_reasons) ? [...data.review_reasons] : [];

        if (isUnrecognised) {
          item.rescan_recommended = true;
          item.needs_review = true;
          if (!item.review_reasons.includes('SHEET_NOT_RECOGNISED')) {
            item.review_reasons.unshift('SHEET_NOT_RECOGNISED');
          }
        } else {
          const eReview = Boolean(item.enrolment.needs_review);
          const aReview = Boolean(data.alignment && data.alignment.needs_review);
          const tmFlags = Array.isArray(item.total_marks.flags) ? item.total_marks.flags : [];
          const tmReview = tmFlags.includes('needs_review') ||
            (Array.isArray(data.review_reasons) && data.review_reasons.some(r => String(r).startsWith('TOTAL_MARKS_REVIEW')));
          item.needs_review = eReview || aReview || tmReview;
        }

      } catch (err) {
        item.status = 'FAILED';
        item.error = err.message || 'Network / Inference error';
        item.needs_review = true;
        item.rescan_recommended = true;
        item.review_reasons = ['API_ERROR'];
      }

      completedCount++;
      updateQueueItemView(item);

      el.procProgressFraction.textContent = `${completedCount} / ${total} completed`;
      el.procProgressPct.textContent = `${Math.round((completedCount / total) * 100)}%`;
      el.procProgressBar.style.width = `${Math.round((completedCount / total) * 100)}%`;
    }

    state.isProcessing = false;
    el.procProgressTitle.textContent = state.cancelRequested ? 'Processing stopped.' : 'Batch processing complete!';
    el.btnCancelProcessing.style.display = 'none';
    el.btnProceedToReview.style.display = 'inline-flex';

    // Run batch-level evaluations (duplicates, roster, subject consensus)
    evaluateBatchLevelQuality();

    // Automatically transition to Review view if all completed
    if (!state.cancelRequested) {
      setTimeout(() => switchView('REVIEW'), 800);
    }
  }

  function renderProcessingQueue() {
    el.queueGrid.innerHTML = '';
    el.btnCancelProcessing.style.display = 'inline-flex';
    el.btnProceedToReview.style.display = 'none';

    state.processedSheets.forEach(item => {
      const card = document.createElement('div');
      card.className = 'queue-card';
      card.id = `queue-card-${item.id}`;

      card.innerHTML = `
        <img class="queue-thumb" src="${item.thumbUrl}" alt="thumb" />
        <div class="queue-info">
          <div class="queue-name" title="${item.filename}">${item.filename}</div>
          <div class="queue-status-row" id="queue-status-${item.id}">
            <span class="badge badge-neutral">Queued</span>
          </div>
        </div>
      `;
      el.queueGrid.appendChild(card);
    });
  }

  function updateQueueItemView(item) {
    const statusContainer = document.getElementById(`queue-status-${item.id}`);
    if (!statusContainer) return;

    if (item.status === 'QUEUED') {
      statusContainer.innerHTML = '<span class="badge badge-neutral">Queued</span>';
    } else if (item.status === 'READING') {
      statusContainer.innerHTML = '<span class="badge badge-primary">Reading...</span>';
    } else if (item.status === 'DONE') {
      if (item.rescan_recommended) {
        statusContainer.innerHTML = '<span class="badge badge-danger">Rescan</span>';
      } else if (item.needs_review) {
        statusContainer.innerHTML = '<span class="badge badge-warning">Check</span>';
      } else {
        statusContainer.innerHTML = '<span class="badge badge-success">Done (OK)</span>';
      }
    } else if (item.status === 'FAILED') {
      statusContainer.innerHTML = `<span class="badge badge-danger">Failed</span> <button class="btn-text-danger btn-retry" data-id="${item.id}">Retry</button>`;
    }
  }

  el.btnCancelProcessing.addEventListener('click', () => {
    state.cancelRequested = true;
    showToast('Stopping processing queue...');
  });

  el.btnProceedToReview.addEventListener('click', () => {
    switchView('REVIEW');
  });

  // ============================================================================
  // Batch Review Quality & Diagnostics Logic
  // ============================================================================
  function evaluateBatchLevelQuality() {
    // 1. Identify duplicates
    const rollMap = new Map();
    state.processedSheets.forEach(sheet => {
      const roll = (sheet.final_enrolment || '').trim();
      if (roll && roll !== 'UNKNOWN' && roll !== 'NONE') {
        if (!rollMap.has(roll)) rollMap.set(roll, []);
        rollMap.get(roll).push(sheet);
      }
    });

    // 2. Class Roster Reconciliation (Optional)
    state.missingRosterRolls = [];
    let foundRolls = new Set();
    if (state.rosterList.length > 0) {
      foundRolls = new Set(
        state.processedSheets.map(s => (s.final_enrolment || '').trim()).filter(Boolean)
      );
      state.missingRosterRolls = state.rosterList.filter(r => !foundRolls.has(r));
    }

    // 3. Update each sheet's duplicate / roster flags and needs_review
    state.processedSheets.forEach(sheet => {
      const roll = (sheet.final_enrolment || '').trim();
      const isDup = Boolean(roll && rollMap.has(roll) && rollMap.get(roll).length > 1);
      const isNotInRoster = Boolean(state.rosterList.length > 0 && roll && !state.rosterList.includes(roll));

      // Manage DUPLICATE_ENROLMENT in review_reasons
      if (isDup && !sheet.review_reasons.includes('DUPLICATE_ENROLMENT')) {
        sheet.review_reasons.push('DUPLICATE_ENROLMENT');
      } else if (!isDup && sheet.review_reasons.includes('DUPLICATE_ENROLMENT')) {
        sheet.review_reasons = sheet.review_reasons.filter(r => r !== 'DUPLICATE_ENROLMENT');
      }

      // Manage READ_NOT_IN_ROSTER in review_reasons
      if (isNotInRoster && !sheet.review_reasons.includes('READ_NOT_IN_ROSTER')) {
        sheet.review_reasons.push('READ_NOT_IN_ROSTER');
      } else if (!isNotInRoster && sheet.review_reasons.includes('READ_NOT_IN_ROSTER')) {
        sheet.review_reasons = sheet.review_reasons.filter(r => r !== 'READ_NOT_IN_ROSTER');
      }

      // If sheet is confirmed by teacher, it is verified (needs_review = false)
      if (sheet.is_confirmed) {
        sheet.needs_review = false;
      } else {
        // Otherwise re-check field level reviews or batch flags
        const eReview = Boolean(sheet.enrolment && sheet.enrolment.needs_review);
        const aReview = Boolean(sheet.alignment && sheet.alignment.needs_review);
        const tmFlags = sheet.total_marks && Array.isArray(sheet.total_marks.flags) ? sheet.total_marks.flags : [];
        const tmReview = tmFlags.includes('needs_review') ||
          (Array.isArray(sheet.review_reasons) && sheet.review_reasons.some(r => String(r).startsWith('TOTAL_MARKS_REVIEW')));

        sheet.needs_review = eReview || aReview || tmReview || isDup || isNotInRoster;
      }
    });

    // 3. Subject Code Consensus Check
    const declared = state.subjectCodeDeclared;
    let mismatchCount = 0;
    let totalWithSubject = 0;

    state.processedSheets.forEach(s => {
      const readSubj = s.subject_code ? (s.subject_code.matched_code || s.subject_code.value || '') : '';
      if (readSubj) {
        totalWithSubject++;
        if (readSubj !== declared) {
          mismatchCount++;
        }
      }
    });

    state.batchConsensusMismatch = totalWithSubject > 0 && (mismatchCount / totalWithSubject > 0.35);
  }

  // ============================================================================
  // Review Dashboard View (View 3)
  // ============================================================================
  function renderReviewDashboard() {
    el.revSubjectBadge.textContent = `SUBJ: ${state.subjectCodeDeclared || 'NOT SPECIFIED'}`;
    el.revExamBadge.textContent = `EXAM: ${state.examName || 'UNNAMED'}`;

    // Update Print Metadata
    el.printExamTitle.textContent = state.examName;
    el.printSubjectCode.textContent = state.subjectCodeDeclared;
    el.printDate.textContent = new Date().toLocaleDateString();
    el.printTotalCount.textContent = state.processedSheets.length;

    // Render Diagnostic Warning Banners
    renderAlertBanners();

    // Update Metric Counters
    let total = state.processedSheets.length;
    let rescan = 0;
    let check = 0;
    let ok = 0;

    state.processedSheets.forEach(s => {
      if (s.rescan_recommended) rescan++;
      else if (s.needs_review && !s.is_confirmed) check++;
      else ok++;
    });

    el.countTotal.textContent = total;
    el.countOk.textContent = ok;
    el.countCheck.textContent = check;
    el.countRescan.textContent = rescan;

    el.chipAllCount.textContent = total;
    el.chipOkCount.textContent = ok;
    el.chipCheckCount.textContent = check;
    el.chipRescanCount.textContent = rescan;

    // Render Missing Roster Box
    if (state.missingRosterRolls.length > 0) {
      el.missingRosterBox.style.display = 'block';
      el.missingRosterCount.textContent = state.missingRosterRolls.length;
      el.missingTagsGrid.innerHTML = state.missingRosterRolls
        .map(r => `<span class="roster-missing-tag">${r}</span>`)
        .join('');
    } else {
      el.missingRosterBox.style.display = 'none';
    }

    renderReviewTable();
  }

  function renderAlertBanners() {
    el.alertContainer.innerHTML = '';

    // Consensus Mismatch Alert
    if (state.batchConsensusMismatch) {
      const banner = document.createElement('div');
      banner.className = 'alert-banner alert-warning';
      banner.innerHTML = `
        <svg class="alert-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
        <div>
          <strong>Subject Code Warning:</strong> Scanned sheets show a different subject code than declared (<code>${state.subjectCodeDeclared}</code>). Please double-check the exam bundle.
        </div>
      `;
      el.alertContainer.appendChild(banner);
    }

    // Duplicates Alert
    const duplicateSheets = state.processedSheets.filter(s => s.review_reasons.includes('DUPLICATE_ENROLMENT'));
    if (duplicateSheets.length > 0) {
      const banner = document.createElement('div');
      banner.className = 'alert-banner alert-danger';
      banner.innerHTML = `
        <svg class="alert-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
        <div>
          <strong>Duplicate Roll Numbers Detected:</strong> ${duplicateSheets.length} sheets share the same roll number in this batch. Inspect and verify highlighted rows below.
        </div>
      `;
      el.alertContainer.appendChild(banner);
    }
  }

  function renderReviewTable() {
    el.reviewTableBody.innerHTML = '';

    const query = state.searchQuery.toLowerCase().trim();
    const filtered = state.processedSheets.filter(sheet => {
      // 1. Search Query Filter
      if (query && !sheet.final_enrolment.toLowerCase().includes(query)) {
        return false;
      }
      // 2. Status Chip Filter
      if (state.activeFilter === 'OK') {
        return !sheet.rescan_recommended && (!sheet.needs_review || sheet.is_confirmed);
      }
      if (state.activeFilter === 'CHECK') {
        return sheet.needs_review && !sheet.rescan_recommended && !sheet.is_confirmed;
      }
      if (state.activeFilter === 'RESCAN') {
        return sheet.rescan_recommended;
      }
      return true; // 'ALL'
    });

    if (filtered.length === 0) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td colspan="12" style="text-align: center; color: var(--neutral-500); padding: 2rem;">No sheets match the selected filter.</td>`;
      el.reviewTableBody.appendChild(tr);
      return;
    }

    filtered.forEach(sheet => {
      const tr = document.createElement('tr');
      const isDuplicate = sheet.review_reasons.includes('DUPLICATE_ENROLMENT');

      if (sheet.rescan_recommended) tr.className = 'row-rescan';
      else if (sheet.needs_review && !sheet.is_confirmed) tr.className = 'row-check';

      // Status pill
      let statusHtml = '';
      if (sheet.rescan_recommended) {
        statusHtml = '<span class="badge badge-danger">Rescan</span>';
      } else if (sheet.needs_review && !sheet.is_confirmed) {
        statusHtml = '<span class="badge badge-warning">Check</span>';
      } else {
        statusHtml = '<span class="badge badge-success">OK / Verified</span>';
      }

      // Plain language reason tags (with grey info styling for unknown/subject codes)
      const reasonTags = (sheet.review_reasons || [])
        .map(code => {
          const plain = ReasonMapper.toPlainLanguage(code);
          const cat = ReasonMapper.getTagCategory(code);
          const cls = cat === 'rescan' ? 'reason-rescan' : (cat === 'check' ? 'reason-check' : 'reason-info');
          return `<span class="reason-tag ${cls}">${plain}</span>`;
        })
        .join('');

      tr.innerHTML = `
        <td class="font-mono text-muted">${sheet.id}</td>
        <td class="no-print">
          <img src="${sheet.thumbUrl}" class="table-thumb" title="Click to inspect" data-id="${sheet.id}" />
        </td>
        <td class="roll-cell ${isDuplicate ? 'roll-duplicate' : ''}">
          <input type="text" value="${sheet.final_enrolment}" class="form-input mono uppercase inline-roll-input" data-id="${sheet.id}" style="width: 140px; padding: 4px 6px;" />
        </td>
        <td class="qmarks-cell">
          <input type="number" step="0.5" min="0" max="70" value="${sheet.q1 !== undefined && sheet.q1 !== null ? sheet.q1 : ''}" class="form-input mono inline-q-input" data-id="${sheet.id}" data-q="1" placeholder="-" />
        </td>
        <td class="qmarks-cell">
          <input type="number" step="0.5" min="0" max="70" value="${sheet.q2 !== undefined && sheet.q2 !== null ? sheet.q2 : ''}" class="form-input mono inline-q-input" data-id="${sheet.id}" data-q="2" placeholder="-" />
        </td>
        <td class="qmarks-cell">
          <input type="number" step="0.5" min="0" max="70" value="${sheet.q3 !== undefined && sheet.q3 !== null ? sheet.q3 : ''}" class="form-input mono inline-q-input" data-id="${sheet.id}" data-q="3" placeholder="-" />
        </td>
        <td class="qmarks-cell">
          <input type="number" step="0.5" min="0" max="70" value="${sheet.q4 !== undefined && sheet.q4 !== null ? sheet.q4 : ''}" class="form-input mono inline-q-input" data-id="${sheet.id}" data-q="4" placeholder="-" />
        </td>
        <td class="qmarks-cell">
          <input type="number" step="0.5" min="0" max="70" value="${sheet.q5 !== undefined && sheet.q5 !== null ? sheet.q5 : ''}" class="form-input mono inline-q-input" data-id="${sheet.id}" data-q="5" placeholder="-" />
        </td>
        <td class="marks-cell">
          <input type="number" value="${sheet.final_total_marks}" min="0" max="100" step="0.5" class="form-input mono inline-marks-input" data-id="${sheet.id}" style="width: 80px; padding: 4px 6px;" />
        </td>
        <td class="no-print">${statusHtml}</td>
        <td>${reasonTags || '<span class="text-muted" style="font-size: 0.8rem;">Clean reading</span>'}</td>
        <td class="no-print" style="white-space: nowrap;">
          ${sheet.rescan_recommended ? `<button class="btn btn-warning btn-sm btn-rescan" data-id="${sheet.id}" style="margin-right: 4px;" title="Sheet not recognised. Scan the whole sheet in colour with the scanner.">Rescan</button>` : ''}
          <button class="btn btn-secondary btn-sm btn-inspect" data-id="${sheet.id}">
            Inspect
          </button>
        </td>
      `;

      el.reviewTableBody.appendChild(tr);
    });

    // Attach Rescan click listeners
    document.querySelectorAll('.btn-rescan').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const id = parseInt(btn.dataset.id, 10);
        const s = state.processedSheets.find(item => item.id === id);
        if (s) {
          triggerRescanForSheet(s);
        }
      });
    });

    // Attach inline change listeners
    document.querySelectorAll('.inline-roll-input').forEach(input => {
      input.addEventListener('change', (e) => {
        const id = parseInt(e.target.dataset.id, 10);
        const s = state.processedSheets.find(item => item.id === id);
        if (s) {
          s.final_enrolment = e.target.value.trim().toUpperCase();
          s.is_confirmed = true;
          evaluateBatchLevelQuality();
          renderReviewDashboard();
        }
      });
    });

    document.querySelectorAll('.inline-marks-input').forEach(input => {
      input.addEventListener('change', (e) => {
        const id = parseInt(e.target.dataset.id, 10);
        const s = state.processedSheets.find(item => item.id === id);
        if (s) {
          s.final_total_marks = e.target.value.trim();
          s.is_confirmed = true;
          renderReviewDashboard();
        }
      });
    });

    document.querySelectorAll('.inline-q-input').forEach(input => {
      input.addEventListener('change', (e) => {
        const id = parseInt(e.target.dataset.id, 10);
        const qNum = e.target.dataset.q;
        const s = state.processedSheets.find(item => item.id === id);
        if (s && qNum) {
          s[`q${qNum}`] = e.target.value.trim();
          s.is_confirmed = true;
          renderReviewDashboard();
        }
      });
    });

    // Attach Inspect click listeners
    document.querySelectorAll('.btn-inspect, .table-thumb').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const id = parseInt(btn.dataset.id, 10);
        const idx = state.processedSheets.findIndex(item => item.id === id);
        if (idx !== -1) {
          openInspector(idx);
        }
      });
    });
  }

  function triggerRescanForSheet(sheet) {
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = 'image/png,image/jpeg,image/webp';
    fileInput.onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      sheet.file = file;
      sheet.filename = file.name;
      sheet.thumbUrl = URL.createObjectURL(file);
      sheet.status = 'READING';
      showToast(`Rescanning Sheet #${sheet.id} (${file.name})...`);
      renderReviewDashboard();

      try {
        const uploadFile = await prepareImageForUpload(file);
        const formData = new FormData();
        formData.append('file', uploadFile);
        formData.append('extract_total_marks', 'true');
        formData.append('extract_question_marks', 'true');

        const resp = await fetch(`${state.apiBaseUrl}/v2/predict`, {
          method: 'POST',
          headers: {
            'X-API-Key': state.apiKey || 'ep_admin_master_secret_key_deploy2'
          },
          body: formData
        });

        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        sheet.status = 'DONE';
        sheet.format_id = data.format_id || data.detected_format || 'UNKNOWN';
        sheet.enrolment = data.enrolment || {};
        sheet.subject_code = data.subject_code || {};
        sheet.total_marks = data.total_marks || {};
        sheet.rescan_recommended = Boolean(data.rescan_recommended);
        if (data.image_preview) {
          sheet.thumbUrl = data.image_preview;
        }

        const hasEnrolVal = Boolean(sheet.enrolment && sheet.enrolment.value);
        const hasTotalVal = Boolean(sheet.total_marks && sheet.total_marks.value !== null && sheet.total_marks.value !== undefined);
        const hasValues = hasEnrolVal || hasTotalVal;
        const pageFlag = Boolean(data.page_status === 'CUT_OFF' || data.page_status === 'NOT_FOUND' ||
          (Array.isArray(data.review_reasons) && data.review_reasons.some(r => r.startsWith('PAGE_') || r === 'PAGE_CUT_OFF_OR_UNRECOGNISED')));

        const isUnrecognised = (sheet.format_id === 'UNKNOWN') || (!hasValues) || pageFlag || sheet.rescan_recommended;
        sheet.review_reasons = Array.isArray(data.review_reasons) ? [...data.review_reasons] : [];

        if (isUnrecognised) {
          sheet.rescan_recommended = true;
          sheet.needs_review = true;
          if (!sheet.review_reasons.includes('SHEET_NOT_RECOGNISED')) {
            sheet.review_reasons.unshift('SHEET_NOT_RECOGNISED');
          }
        } else {
          sheet.needs_review = Boolean(sheet.enrolment.needs_review || (data.alignment && data.alignment.needs_review));
        }

        sheet.final_enrolment = (sheet.enrolment.value || '').toUpperCase();
        sheet.final_total_marks = (sheet.total_marks.value !== undefined && sheet.total_marks.value !== null) ? sheet.total_marks.value : '';
        const qList = Array.isArray(data.q_marks) ? data.q_marks : (Array.isArray(data.question_marks) ? data.question_marks : []);
        sheet.q_marks = qList;
        for (let i = 1; i <= 5; i++) {
          sheet[`q${i}`] = '';
        }
        qList.forEach((qm, idx) => {
          const num = qm.q !== undefined ? qm.q : (qm.q_number !== undefined ? qm.q_number : (qm.question !== undefined ? qm.question : (idx + 1)));
          if (num >= 1 && num <= 5) {
            sheet[`q${num}`] = (qm.value !== undefined && qm.value !== null) ? qm.value : '';
          }
        });
        sheet.marks_sum = data.marks_sum || null;
        showToast(`Rescan complete for Sheet #${sheet.id}`);
      } catch (err) {
        sheet.status = 'FAILED';
        sheet.error = err.message;
        sheet.rescan_recommended = true;
        sheet.needs_review = true;
        sheet.review_reasons = ['SHEET_NOT_RECOGNISED', 'API_ERROR'];
        showToast(`Rescan failed: ${err.message}`);
      }
      evaluateBatchLevelQuality();
      renderReviewDashboard();
    };
    fileInput.click();
  }

  // Filter Chips and Metric Cards Click Handlers
  document.querySelectorAll('.metric-card, .chip-btn').forEach(button => {
    button.addEventListener('click', () => {
      const filter = button.dataset.filter;
      state.activeFilter = filter;

      document.querySelectorAll('.metric-card').forEach(b => b.classList.toggle('active', b.dataset.filter === filter));
      document.querySelectorAll('.chip-btn').forEach(b => b.classList.toggle('active', b.dataset.filter === filter));

      renderReviewTable();
    });
  });

  el.inputSearchRoll.addEventListener('input', (e) => {
    state.searchQuery = e.target.value;
    renderReviewTable();
  });

  // Missing roster toggle
  el.missingRosterToggle.addEventListener('click', () => {
    const isVisible = el.missingRosterBody.style.display !== 'none';
    el.missingRosterBody.style.display = isVisible ? 'none' : 'block';
  });

  // ============================================================================
  // Sheet Inspector Modal (View 4)
  // ============================================================================
  function openInspector(index) {
    if (index < 0 || index >= state.processedSheets.length) return;
    state.currentInspectIndex = index;
    const sheet = state.processedSheets[index];

    el.inspectorTitle.textContent = `Sheet #${sheet.id} Details`;
    el.inspectorFilename.textContent = sheet.filename;
    el.inspectorImg.src = sheet.thumbUrl;

    el.editEnrolment.value = sheet.final_enrolment;
    el.editTotalMarks.value = sheet.final_total_marks;

    el.rawEnrolmentText.textContent = sheet.enrolment ? (sheet.enrolment.raw_text || '--') : '--';
    el.confEnrolment.textContent = sheet.enrolment && sheet.enrolment.confidence !== undefined 
      ? `${Math.round(sheet.enrolment.confidence * 100)}%` 
      : '--%';
    el.rawMarksText.textContent = sheet.total_marks ? (sheet.total_marks.raw_text || '--') : '--';
    el.inspectorFormatBadge.textContent = sheet.format_id ? `Format ${sheet.format_id}` : 'Format Auto';

    // Question marks Q1..Q5
    const qList = Array.isArray(sheet.q_marks) ? sheet.q_marks : [];
    const getRawQ = (num) => {
      const match = qList.find(qm => (qm.q === num || qm.q_number === num || qm.question === num));
      return match ? (match.raw_text || (match.value !== undefined ? String(match.value) : '--')) : '--';
    };

    if (el.editQ1) el.editQ1.value = (sheet.q1 !== undefined && sheet.q1 !== null) ? sheet.q1 : '';
    if (el.editQ2) el.editQ2.value = (sheet.q2 !== undefined && sheet.q2 !== null) ? sheet.q2 : '';
    if (el.editQ3) el.editQ3.value = (sheet.q3 !== undefined && sheet.q3 !== null) ? sheet.q3 : '';
    if (el.editQ4) el.editQ4.value = (sheet.q4 !== undefined && sheet.q4 !== null) ? sheet.q4 : '';
    if (el.editQ5) el.editQ5.value = (sheet.q5 !== undefined && sheet.q5 !== null) ? sheet.q5 : '';

    if (el.rawQ1Text) el.rawQ1Text.textContent = getRawQ(1);
    if (el.rawQ2Text) el.rawQ2Text.textContent = getRawQ(2);
    if (el.rawQ3Text) el.rawQ3Text.textContent = getRawQ(3);
    if (el.rawQ4Text) el.rawQ4Text.textContent = getRawQ(4);
    if (el.rawQ5Text) el.rawQ5Text.textContent = getRawQ(5);

    // Dynamic Q-sum computation in Inspector
    const updateInspectorSum = () => {
      const qVals = [
        parseFloat(el.editQ1?.value) || 0,
        parseFloat(el.editQ2?.value) || 0,
        parseFloat(el.editQ3?.value) || 0,
        parseFloat(el.editQ4?.value) || 0,
        parseFloat(el.editQ5?.value) || 0,
      ];
      const sum = qVals.reduce((a, b) => a + b, 0);
      const tot = parseFloat(el.editTotalMarks?.value);
      if (el.inspectorQSum) el.inspectorQSum.textContent = isNaN(sum) ? '--' : sum.toFixed(1).replace(/\.0$/, '');
      if (el.inspectorSumStatus) {
        if (isNaN(tot) || isNaN(sum)) {
          el.inspectorSumStatus.textContent = 'UNAVAILABLE';
          el.inspectorSumStatus.style.color = 'var(--neutral-500)';
        } else if (Math.abs(sum - tot) < 0.01) {
          el.inspectorSumStatus.textContent = 'AGREE (Match)';
          el.inspectorSumStatus.style.color = 'var(--success)';
        } else {
          el.inspectorSumStatus.textContent = `MISMATCH (Diff: ${Math.abs(sum - tot).toFixed(1)})`;
          el.inspectorSumStatus.style.color = 'var(--danger)';
        }
      }
    };
    updateInspectorSum();

    [el.editQ1, el.editQ2, el.editQ3, el.editQ4, el.editQ5, el.editTotalMarks].forEach(inp => {
      if (inp) inp.oninput = updateInspectorSum;
    });

    // Reasons list
    el.inspectorReasonsList.innerHTML = '';
    if (sheet.review_reasons && sheet.review_reasons.length > 0) {
      sheet.review_reasons.forEach(code => {
        const div = document.createElement('div');
        const cat = ReasonMapper.getTagCategory(code);
        const cls = cat === 'rescan' ? 'reason-rescan' : (cat === 'check' ? 'reason-check' : 'reason-info');
        div.className = `reason-tag ${cls}`;
        div.style.padding = '6px 10px';
        div.textContent = ReasonMapper.toPlainLanguage(code);
        el.inspectorReasonsList.appendChild(div);
      });
    } else {
      el.inspectorReasonsList.innerHTML = '<span class="text-muted" style="font-size: 0.85rem;">All fields clean and verified.</span>';
    }

    el.sheetNavIndex.textContent = `${index + 1} of ${state.processedSheets.length}`;
    el.btnPrevSheet.disabled = index === 0;
    el.btnNextSheet.disabled = index === state.processedSheets.length - 1;

    el.inspectorModal.style.display = 'flex';
  }

  el.btnSaveInspector.addEventListener('click', () => {
    const sheet = state.processedSheets[state.currentInspectIndex];
    if (sheet) {
      sheet.final_enrolment = el.editEnrolment.value.trim().toUpperCase();
      sheet.final_total_marks = el.editTotalMarks.value.trim();
      if (el.editQ1) sheet.q1 = el.editQ1.value.trim();
      if (el.editQ2) sheet.q2 = el.editQ2.value.trim();
      if (el.editQ3) sheet.q3 = el.editQ3.value.trim();
      if (el.editQ4) sheet.q4 = el.editQ4.value.trim();
      if (el.editQ5) sheet.q5 = el.editQ5.value.trim();
      sheet.is_confirmed = true;
      sheet.needs_review = false;
      sheet.rescan_recommended = false;

      evaluateBatchLevelQuality();
      renderReviewDashboard();
      showToast(`Sheet #${sheet.id} confirmed and saved.`);
    }

    // Move to next sheet if available, else close
    if (state.currentInspectIndex < state.processedSheets.length - 1) {
      openInspector(state.currentInspectIndex + 1);
    } else {
      el.inspectorModal.style.display = 'none';
    }
  });

  el.btnPrevSheet.addEventListener('click', () => {
    if (state.currentInspectIndex > 0) {
      openInspector(state.currentInspectIndex - 1);
    }
  });

  el.btnNextSheet.addEventListener('click', () => {
    if (state.currentInspectIndex < state.processedSheets.length - 1) {
      openInspector(state.currentInspectIndex + 1);
    }
  });

  el.btnCloseInspector.addEventListener('click', () => {
    el.inspectorModal.style.display = 'none';
  });

  // ============================================================================
  // Export Actions: CSV & Batch PDF
  // ============================================================================

  // Pending export action type ('CSV' | 'PDF')
  let pendingExportAction = null;

  function countUnreviewedSheets() {
    return state.processedSheets.filter(s => (s.needs_review && !s.is_confirmed) || s.rescan_recommended).length;
  }

  function checkReviewBeforeExport(actionType, callback) {
    const unreviewed = countUnreviewedSheets();
    if (unreviewed > 0) {
      pendingExportAction = callback;
      el.exportConfirmMessage.textContent = `${unreviewed} sheets still need checking. Export anyway?`;
      el.exportConfirmModal.style.display = 'flex';
    } else {
      callback();
    }
  }

  el.btnReviewFirst.addEventListener('click', () => {
    el.exportConfirmModal.style.display = 'none';
    pendingExportAction = null;
    // Switch filter to 'CHECK' or 'RESCAN' to assist teacher
    const checkBtn = document.querySelector('.chip-btn[data-filter="CHECK"]');
    if (checkBtn) checkBtn.click();
  });

  el.btnExportAnyway.addEventListener('click', () => {
    el.exportConfirmModal.style.display = 'none';
    if (pendingExportAction) {
      const act = pendingExportAction;
      pendingExportAction = null;
      act();
    }
  });

  el.btnCloseExportConfirm.addEventListener('click', () => {
    el.exportConfirmModal.style.display = 'none';
    pendingExportAction = null;
  });

  function buildResultsCSV(sheets, declaredSubjectCode) {
    // Exact headers required: filename, subject_code, enrolment_no, marks, q1, q2, q3, q4, q5
    const headers = [
      'filename',
      'subject_code',
      'enrolment_no',
      'marks',
      'q1',
      'q2',
      'q3',
      'q4',
      'q5'
    ];

    const escapeCsv = (val) => {
      if (val === null || val === undefined) return '';
      const str = String(val);
      if (str.includes(',') || str.includes('"') || str.includes('\n')) {
        return `"${str.replace(/"/g, '""')}"`;
      }
      return str;
    };

    const rows = (sheets || []).map(s => {
      const filename = s.filename || '';
      const subjectCode = declaredSubjectCode || (s.subject_code ? (s.subject_code.matched_code || s.subject_code.value || '') : '');
      const enrolmentNo = s.final_enrolment || '';
      const marks = s.final_total_marks !== undefined && s.final_total_marks !== null ? s.final_total_marks : '';
      const q1 = (s.q1 !== undefined && s.q1 !== null) ? s.q1 : '';
      const q2 = (s.q2 !== undefined && s.q2 !== null) ? s.q2 : '';
      const q3 = (s.q3 !== undefined && s.q3 !== null) ? s.q3 : '';
      const q4 = (s.q4 !== undefined && s.q4 !== null) ? s.q4 : '';
      const q5 = (s.q5 !== undefined && s.q5 !== null) ? s.q5 : '';

      return [
        escapeCsv(filename),
        escapeCsv(subjectCode),
        escapeCsv(enrolmentNo),
        escapeCsv(marks),
        escapeCsv(q1),
        escapeCsv(q2),
        escapeCsv(q3),
        escapeCsv(q4),
        escapeCsv(q5)
      ].join(',');
    });

    return [headers.join(','), ...rows].join('\r\n');
  }

  function performExportCsv() {
    if (state.processedSheets.length === 0) {
      showToast('No records to export.');
      return;
    }

    const subject = (state.subjectCodeDeclared || 'SUBJECT').replace(/[^a-zA-Z0-9_-]/g, '_');
    const csvContent = '\uFEFF' + buildResultsCSV(state.processedSheets, state.subjectCodeDeclared);
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');

    const dateStr = new Date().toISOString().slice(0, 10);
    link.href = url;
    link.download = `${subject}_${dateStr}.csv`;
    link.click();
    URL.revokeObjectURL(url);

    showToast(`Exported ${state.processedSheets.length} records to CSV.`);
  }

  el.btnExportCsv.addEventListener('click', () => {
    checkReviewBeforeExport('CSV', performExportCsv);
  });

  /**
   * Generates a multi-page PDF containing all batch images in order.
   * Standard A4 pages (595.28 x 841.89 points), aspect ratio preserved, centered.
   * Pure JavaScript PDF-1.4 binary encoder with DCTDecode streams (JPEG).
   */
  async function performExportBatchPdf() {
    if (state.processedSheets.length === 0) {
      showToast('No sheets to export.');
      return;
    }

    showToast('Building batch PDF, please wait...');

    // Convert an image file or object URL to JPEG binary buffer + dimensions
    async function convertImageToJpeg(file) {
      return new Promise((resolve, reject) => {
        const img = new Image();
        const objUrl = URL.createObjectURL(file);
        img.onload = () => {
          URL.revokeObjectURL(objUrl);
          const maxDim = 2000;
          let w = img.naturalWidth || img.width;
          let h = img.naturalHeight || img.height;

          if (w > maxDim || h > maxDim) {
            if (w > h) {
              h = Math.round((h * maxDim) / w);
              w = maxDim;
            } else {
              w = Math.round((w * maxDim) / h);
              h = maxDim;
            }
          }

          const canvas = document.createElement('canvas');
          canvas.width = w;
          canvas.height = h;
          const ctx = canvas.getContext('2d');
          ctx.drawImage(img, 0, 0, w, h);

          canvas.toBlob((blob) => {
            if (!blob) {
              reject(new Error('Canvas to blob failed'));
              return;
            }
            const reader = new FileReader();
            reader.onloadend = () => {
              const u8 = new Uint8Array(reader.result);
              resolve({ bytes: u8, width: w, height: h });
            };
            reader.readAsArrayBuffer(blob);
          }, 'image/jpeg', 0.85);
        };
        img.onerror = () => {
          URL.revokeObjectURL(objUrl);
          reject(new Error('Failed to load image for PDF export'));
        };
        img.src = objUrl;
      });
    }

    try {
      const pageImages = [];
      for (let i = 0; i < state.processedSheets.length; i++) {
        const sheet = state.processedSheets[i];
        const jpegData = await convertImageToJpeg(sheet.file);
        pageImages.push(jpegData);
      }

      // Build PDF-1.4 structures
      // A4 dimensions in points (72 points/inch)
      const a4Width = 595.28;
      const a4Height = 841.89;
      const margin = 20;
      const maxW = a4Width - (margin * 2);
      const maxH = a4Height - (margin * 2);

      const numPages = pageImages.length;
      // Object indexing:
      // 1: Catalog
      // 2: Pages
      // For each page i (0-indexed):
      // Page obj: 3 + i*3
      // Content stream obj: 4 + i*3
      // XObject Image obj: 5 + i*3

      const objects = []; // array of { id, data: Uint8Array }

      function strToBytes(str) {
        const arr = new Uint8Array(str.length);
        for (let i = 0; i < str.length; i++) {
          arr[i] = str.charCodeAt(i) & 0xff;
        }
        return arr;
      }

      function concatArrays(arrs) {
        let total = 0;
        for (const a of arrs) total += a.length;
        const res = new Uint8Array(total);
        let offset = 0;
        for (const a of arrs) {
          res.set(a, offset);
          offset += a.length;
        }
        return res;
      }

      // 1 0 obj Catalog
      const catalogStr = `1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n`;
      objects.push({ id: 1, data: strToBytes(catalogStr) });

      // 2 0 obj Pages
      const pageKids = [];
      for (let i = 0; i < numPages; i++) {
        pageKids.push(`${3 + i * 3} 0 R`);
      }
      const pagesStr = `2 0 obj\n<< /Type /Pages /Kids [ ${pageKids.join(' ')} ] /Count ${numPages} >>\nendobj\n`;
      objects.push({ id: 2, data: strToBytes(pagesStr) });

      for (let i = 0; i < numPages; i++) {
        const img = pageImages[i];
        const pageId = 3 + i * 3;
        const contentId = 4 + i * 3;
        const imageId = 5 + i * 3;

        // Calculate aspect ratio fit on A4
        const aspect = img.width / img.height;
        let fitW = maxW;
        let fitH = fitW / aspect;
        if (fitH > maxH) {
          fitH = maxH;
          fitW = fitH * aspect;
        }

        const posX = margin + (maxW - fitW) / 2;
        const posY = margin + (maxH - fitH) / 2;

        // Content stream: q <w> 0 0 <h> <x> <y> cm /Im<i> Do Q
        const contentStrBody = `q\n${fitW.toFixed(2)} 0 0 ${fitH.toFixed(2)} ${posX.toFixed(2)} ${posY.toFixed(2)} cm\n/Im${i + 1} Do\nQ\n`;
        const contentBytes = strToBytes(contentStrBody);
        const contentObjStr = `${contentId} 0 obj\n<< /Length ${contentBytes.length} >>\nstream\n${contentStrBody}endstream\nendobj\n`;
        objects.push({ id: contentId, data: strToBytes(contentObjStr) });

        // Image XObject
        const imgHeader = `${imageId} 0 obj\n<< /Type /XObject /Subtype /Image /Width ${img.width} /Height ${img.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${img.bytes.length} >>\nstream\n`;
        const imgFooter = `\nendstream\nendobj\n`;
        const imgFullData = concatArrays([strToBytes(imgHeader), img.bytes, strToBytes(imgFooter)]);
        objects.push({ id: imageId, data: imgFullData });

        // Page object
        const pageObjStr = `${pageId} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${a4Width} ${a4Height}] /Contents ${contentId} 0 R /Resources << /XObject << /Im${i + 1} ${imageId} 0 R >> >> >>\nendobj\n`;
        objects.push({ id: pageId, data: strToBytes(pageObjStr) });
      }

      // Sort objects by ID for clean PDF xref
      objects.sort((a, b) => a.id - b.id);

      const headerBytes = strToBytes('%PDF-1.4\n%\xE2\xE3\xCF\xD3\n');
      const xrefOffsets = [];
      let currentOffset = headerBytes.length;

      const bodyChunks = [headerBytes];
      for (const obj of objects) {
        xrefOffsets[obj.id] = currentOffset;
        bodyChunks.push(obj.data);
        currentOffset += obj.data.length;
      }

      // Build xref table
      const totalObjs = objects.length + 1;
      let xrefStr = `xref\n0 ${totalObjs}\n0000000000 65535 f \n`;
      for (let i = 1; i < totalObjs; i++) {
        const off = String(xrefOffsets[i] || 0).padStart(10, '0');
        xrefStr += `${off} 00000 n \n`;
      }

      const startXref = currentOffset;
      const trailerStr = `trailer\n<< /Size ${totalObjs} /Root 1 0 R >>\nstartxref\n${startXref}\n%%EOF\n`;
      bodyChunks.push(strToBytes(xrefStr + trailerStr));

      const finalPdfBlob = new Blob(bodyChunks, { type: 'application/pdf' });
      const pdfUrl = URL.createObjectURL(finalPdfBlob);
      const link = document.createElement('a');

      const subject = (state.subjectCodeDeclared || 'SUBJECT').replace(/[^a-zA-Z0-9_-]/g, '_');
      const dateStr = new Date().toISOString().slice(0, 10);
      link.href = pdfUrl;
      link.download = `${subject}_${dateStr}.pdf`;
      link.click();
      URL.revokeObjectURL(pdfUrl);

      showToast(`Exported batch PDF with ${numPages} pages.`);
    } catch (err) {
      console.error(err);
      alert(`Error generating PDF: ${err.message}`);
    }
  }

  el.btnExportBatchPdf.addEventListener('click', () => {
    checkReviewBeforeExport('PDF', performExportBatchPdf);
  });

  el.btnPrintReport.addEventListener('click', () => {
    window.print();
  });

  // ============================================================================
  // Settings Modal Handlers
  // ============================================================================
  el.btnSettings.addEventListener('click', () => {
    el.inputApiBaseUrl.value = state.apiBaseUrl;
    if (el.inputApiKey) {
      el.inputApiKey.value = state.apiKey;
    }
    el.serverTestResult.innerHTML = '';
    el.settingsModal.style.display = 'flex';
  });

  el.serverStatusBtn.addEventListener('click', () => {
    el.btnSettings.click();
  });

  el.btnCloseSettings.addEventListener('click', () => {
    el.settingsModal.style.display = 'none';
  });

  el.btnTestApi.addEventListener('click', async () => {
    const testUrl = el.inputApiBaseUrl.value.trim();
    el.serverTestResult.innerHTML = '<span class="text-muted">Pinging backend...</span>';

    const res = await pingServer(testUrl);
    if (res.ok) {
      el.serverTestResult.innerHTML = `
        <div style="color: var(--success); font-weight: 600;">
          &#10003; Connection Successful (${res.durationMs} ms)!
        </div>
        <div class="font-mono text-muted" style="font-size: 0.8rem; margin-top: 4px;">
          Detector: ${res.data.detector_loaded ? 'Loaded' : 'Not Loaded'} | OCR: ${res.data.ocr_loaded ? 'Ready' : 'Pending'}
        </div>
      `;
    } else {
      el.serverTestResult.innerHTML = `
        <div style="color: var(--danger); font-weight: 600;">
          &#10007; Connection Failed (${res.durationMs} ms)
        </div>
        <div class="text-muted" style="font-size: 0.8rem; margin-top: 4px;">
          ${res.error || res.statusText || 'Unable to reach backend at specified URL.'}
        </div>
      `;
    }
  });

  el.btnSaveSettings.addEventListener('click', () => {
    const newUrl = el.inputApiBaseUrl.value.trim();
    const newKey = el.inputApiKey ? el.inputApiKey.value.trim() : '';
    if (newUrl) {
      state.apiBaseUrl = newUrl;
      localStorage.setItem('ocr_v2_api_url', newUrl);
    }
    if (newKey) {
      state.apiKey = newKey;
      localStorage.setItem('ocr_v2_api_key', newKey);
    }
    updateServerStatusIndicator();
    el.settingsModal.style.display = 'none';
    showToast('Settings saved.');
  });

  // "New Batch" Nav button handler
  el.btnNewBatchNav.addEventListener('click', () => {
    if (confirm('Start a new batch? Current unsaved review items will be cleared.')) {
      state.stagedFiles = [];
      state.processedSheets = [];
      state.subjectCodeDeclared = '';
      el.inputSubjectCode.value = '';
      renderStagedFiles();
      updateStartButtonState();
      switchView('NEW_BATCH');
    }
  });

  // Close modals when clicking backdrop
  window.addEventListener('click', (e) => {
    if (e.target === el.inspectorModal) el.inspectorModal.style.display = 'none';
    if (e.target === el.settingsModal) el.settingsModal.style.display = 'none';
  });

  if (typeof window !== 'undefined') {
    window.buildResultsCSV = buildResultsCSV;
  }
})();
