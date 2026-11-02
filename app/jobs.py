"""
app.jobs: Asynchronous Jobs API implementation for high-throughput batch processing.
- Multi-sheet background processing with thread-safe worker pool.
- SQLite-backed state persistence (WAL mode) with atomic updates.
- Role-based access control and job ownership enforcement.
- Per-key concurrent job caps and rate limiting.
- Zero-PII logging: no roll numbers, marks, subject codes, or original filenames in logs.
- Automatic server restart recovery (marks interrupted jobs as failed).
- Batch review analysis on completion (duplicates, ROLL_OUTLIER, subject code consensus).
"""

import os
import json
import uuid
import shutil
import sqlite3
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, File, UploadFile, Form, HTTPException, Depends, Request, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.auth import KeyInfo, get_current_key, require_admin
from app.validators import (
    validate_content_type,
    validate_magic_bytes,
    validate_file_size,
    validate_image_dimensions_and_decode,
    validate_batch_file_count,
    rate_limiter,
)
from app.operations import check_free_disk
from app.metrics import metrics
from app.routers_v2 import get_pipeline, process_sheet_bytes, ALLOWED_EXTENSIONS
from ocr_v2.batch import BatchSubjectCodeConsensus
from ocr_v2.review import BatchReviewManager

logger = logging.getLogger("api.jobs")
router = APIRouter(prefix="/v2/jobs", tags=["Jobs API"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = Path(settings.UPLOAD_DIR)
JOBS_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(settings.DB_PATH)


class JobStore:
    def __init__(self, db_path: Path, storage_dir: Path):
        self.db_path = db_path
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._is_shutting_down = False
        self._init_db()

    def initiate_shutdown(self):
        """Initiates application-level graceful shutdown: refuses new uploads and terminates workers cleanly."""
        self._is_shutting_down = True
        logger.info("Application drain/shutdown initiated: new jobs will be refused (503).")

    def reset_shutdown(self):
        """Resets shutdown state (used for testing)."""
        self._is_shutting_down = False

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    key_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_sheets INTEGER NOT NULL,
                    processed_sheets INTEGER DEFAULT 0,
                    progress REAL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    error TEXT,
                    upload_dir TEXT NOT NULL,
                    meta_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def get_job_dir(self, job_id: str) -> Path:
        return self.storage_dir / job_id

    def list_active_count(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'processing')")
            return cursor.fetchone()[0]

    def count_active_jobs_for_key(self, key_id: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM jobs WHERE key_id = ? AND status IN ('queued', 'processing')", (key_id,))
            return cursor.fetchone()[0]

    def recover_interrupted_jobs(self):
        """Marks any job interrupted by a server restart as failed."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs 
                SET status = 'failed', 
                    error = 'SERVER_RESTARTED_DURING_EXECUTION',
                    completed_at = ?
                WHERE status IN ('queued', 'processing')
                """,
                (now_iso,),
            )
            recovered = cursor.rowcount
            conn.commit()
            if recovered > 0:
                logger.info(f"Startup recovery: marked {recovered} interrupted jobs as failed.")

    def create_job(
        self,
        key_id: str,
        files_data: List[tuple],
        subject_code_declared: Optional[str] = None,
        extract_total_marks: bool = True,
        extract_question_marks: bool = True,
        roster: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        # Check graceful shutdown drain
        if self._is_shutting_down:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service Unavailable: Server is shutting down.",
                headers={"Retry-After": "30"},
            )

        # Enforce global queue limit
        active_count = self.list_active_count()
        if active_count >= settings.MAX_QUEUED_JOBS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Job queue is full ({active_count}/{settings.MAX_QUEUED_JOBS} active jobs). Please retry later.",
                headers={"Retry-After": "10"},
            )

        job_id = f"job_{uuid.uuid4().hex[:16]}"
        job_folder = self.get_job_dir(job_id)
        job_folder.mkdir(parents=True, exist_ok=True)

        saved_files = []
        for idx, (orig_filename, content) in enumerate(files_data):
            ext = Path(orig_filename).suffix.lower()
            safe_name = f"sheet_{idx:04d}{ext}"
            file_path = job_folder / safe_name
            file_path.write_bytes(content)
            saved_files.append((safe_name, str(file_path)))

        now_iso = datetime.now(timezone.utc).isoformat()
        meta = {
            "job_id": job_id,
            "key_id": key_id,
            "status": "queued",
            "total_sheets": len(saved_files),
            "processed_sheets": 0,
            "progress": 0.0,
            "created_at": now_iso,
            "completed_at": None,
            "error": None,
            "subject_code_declared": subject_code_declared,
            "extract_total_marks": extract_total_marks,
            "extract_question_marks": extract_question_marks,
            "roster": roster or [],
            "files": saved_files,
        }

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO jobs 
                (job_id, key_id, status, total_sheets, processed_sheets, progress, created_at, upload_dir, meta_json)
                VALUES (?, ?, ?, ?, 0, 0.0, ?, ?, ?)
                """,
                (job_id, key_id, "queued", len(saved_files), now_iso, str(job_folder), json.dumps(meta)),
            )
            conn.commit()

        # Launch background processing
        threading.Thread(
            target=self._run_job_worker,
            args=(job_id,),
            daemon=True,
        ).start()

        logger.info(f"Enqueued job '{job_id}' ({len(saved_files)} sheets) for key_id='{key_id}'.")
        return {
            "job_id": job_id,
            "status": "queued",
            "total_sheets": len(saved_files),
            "status_url": f"/v2/jobs/{job_id}",
            "created_at": now_iso,
        }

    def _run_job_worker(self, job_id: str):
        job_folder = self.get_job_dir(job_id)
        results_file = job_folder / "results.json"

        # Read job metadata
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT meta_json FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if not row:
                return
            meta = json.loads(row[0])

            conn.execute("UPDATE jobs SET status = 'processing' WHERE job_id = ?", (job_id,))
            conn.commit()

        try:
            pipeline = get_pipeline()
            results = []
            total = meta["total_sheets"]
            last_progress = 0.0

            for idx, (safe_filename, file_path_str) in enumerate(meta["files"]):
                # Check if server shutdown was initiated
                if self._is_shutting_down:
                    logger.info(f"Shutdown requested; marking job '{job_id}' as failed/aborted.")
                    now_iso = datetime.now(timezone.utc).isoformat()
                    with self._get_connection() as conn:
                        conn.execute(
                            """
                            UPDATE jobs 
                            SET status = 'failed', error = 'SERVER_SHUTTING_DOWN', completed_at = ?
                            WHERE job_id = ?
                            """,
                            (now_iso, job_id),
                        )
                        conn.commit()
                    return

                # Check if job was deleted mid-run
                if not job_folder.exists():
                    logger.info(f"Job '{job_id}' directory removed; aborting worker execution.")
                    return

                content = Path(file_path_str).read_bytes()
                sheet_res = process_sheet_bytes(
                    content,
                    safe_filename,
                    pipeline,
                    extract_total_marks=meta.get("extract_total_marks", True),
                    extract_question_marks=meta.get("extract_question_marks", True),
                    subject_code_declared=meta.get("subject_code_declared"),
                )
                results.append(sheet_res)

                # Monotonic progress calculation
                curr_progress = min(1.0, max(last_progress, round((idx + 1) / float(total), 4)))
                last_progress = curr_progress

                # Record metrics for diagnostic flags
                flags = sheet_res.get("all_flags") or []
                metrics.record_flags_batch(flags)

                with self._get_connection() as conn:
                    conn.execute(
                        """
                        UPDATE jobs 
                        SET processed_sheets = ?, progress = ? 
                        WHERE job_id = ?
                        """,
                        (idx + 1, curr_progress, job_id),
                    )
                    conn.commit()

            # Mark complete
            completed_iso = datetime.now(timezone.utc).isoformat()
            meta["status"] = "completed"
            meta["progress"] = 1.0
            meta["completed_at"] = completed_iso

            with open(results_file, "w", encoding="utf-8") as fp:
                json.dump(results, fp, indent=2)

            with self._get_connection() as conn:
                conn.execute(
                    """
                    UPDATE jobs 
                    SET status = 'completed', progress = 1.0, completed_at = ?, meta_json = ?
                    WHERE job_id = ?
                    """,
                    (completed_iso, json.dumps(meta), job_id),
                )
                conn.commit()

            logger.info(f"Completed processing job '{job_id}' ({total} sheets processed).")

        except Exception as e:
            logger.error(f"Error processing job '{job_id}': {e}", exc_info=True)
            failed_iso = datetime.now(timezone.utc).isoformat()
            with self._get_connection() as conn:
                conn.execute(
                    """
                    UPDATE jobs 
                    SET status = 'failed', error = ?, completed_at = ?
                    WHERE job_id = ?
                    """,
                    (str(e), failed_iso, job_id),
                )
                conn.commit()

    def get_job_status(self, job_id: str, caller_key: KeyInfo) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT job_id, key_id, status, total_sheets, processed_sheets, progress, created_at, completed_at, error, meta_json
                FROM jobs WHERE job_id = ?
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")

            owner_key = row[1]
            if caller_key.role != "admin" and caller_key.key_id != owner_key:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: job owned by another key.")

            # Load any partial results available so far
            job_folder = self.get_job_dir(job_id)
            results_file = job_folder / "results.json"
            partial_results = []
            if results_file.exists():
                try:
                    partial_results = json.loads(results_file.read_text(encoding="utf-8"))
                except Exception:
                    pass

            return {
                "job_id": row[0],
                "status": row[2],
                "total_sheets": row[3],
                "processed_sheets": row[4],
                "progress": row[5],
                "created_at": row[6],
                "completed_at": row[7],
                "error": row[8],
                "sheets_available": len(partial_results),
            }

    def get_job_results(self, job_id: str, caller_key: KeyInfo) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT job_id, key_id, status, meta_json FROM jobs WHERE job_id = ?",
                (job_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")

            owner_key = row[1]
            if caller_key.role != "admin" and caller_key.key_id != owner_key:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: job owned by another key.")

            job_status = row[2]
            meta = json.loads(row[3]) if row[3] else {}

        if job_status != "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Job '{job_id}' is not yet completed (current status: {job_status}).",
            )

        job_dir = self.get_job_dir(job_id)
        results_file = job_dir / "results.json"
        if not results_file.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Results file not found.")

        results = json.loads(results_file.read_text(encoding="utf-8"))

        # Batch-level review
        review_mgr = BatchReviewManager()
        roster_list = meta.get("roster", [])
        batch_review = review_mgr.evaluate_batch(results, roster=roster_list)

        # Subject code consensus
        consensus_eval = BatchSubjectCodeConsensus()
        consensus_records = []
        for idx, r in enumerate(results):
            s_code = None
            if isinstance(r.get("subject_code"), dict):
                s_code = r["subject_code"].get("matched_code") or r["subject_code"].get("value")
            consensus_records.append({
                "sheet_name": r.get("filename", f"sheet_{idx}"),
                "matched_code": s_code,
                "fields": {
                    "subject_code": {
                        "parsed_value": s_code,
                        "raw_text": r.get("subject_code", {}).get("raw_text", "") if isinstance(r.get("subject_code"), dict) else "",
                        "confidence": r.get("subject_code", {}).get("confidence", 0.0) if isinstance(r.get("subject_code"), dict) else 0.0,
                    }
                }
            })
        consensus_res = consensus_eval.compute_consensus(
            consensus_records,
            subject_code_declared=meta.get("subject_code_declared"),
        )

        return {
            "job_id": job_id,
            "status": "completed",
            "total_sheets": len(results),
            "results": results,
            "review": {
                "flagged_sheets": batch_review.flagged_sheets,
                "rescan_count": batch_review.rescan_count,
                "duplicate_enrolments": batch_review.duplicate_enrolments,
                "missing_from_batch": batch_review.missing_from_batch,
                "subject_code_consensus": {
                    "consensus_code": consensus_res.consensus_code,
                    "agreement_ratio": consensus_res.agreement_ratio,
                    "status": consensus_res.status,
                    "vote_counts": consensus_res.vote_counts,
                },
            },
        }

    def delete_job(self, job_id: str, caller_key: KeyInfo) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key_id, upload_dir FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")

            owner_key = row[0]
            upload_dir = row[1]
            if caller_key.role != "admin" and caller_key.key_id != owner_key:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: job owned by another key.")

            conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            conn.commit()

        # Delete physical artifacts
        if upload_dir and Path(upload_dir).exists():
            shutil.rmtree(upload_dir, ignore_errors=True)

        logger.info(f"Deleted job '{job_id}' and wiped storage directory.")
        return {"job_id": job_id, "deleted": True}


job_store = JobStore(DB_PATH, JOBS_DIR)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def submit_job(
    files: List[UploadFile] = File(...),
    subject_code_declared: Optional[str] = Form(None),
    extract_total_marks: bool = Form(True),
    extract_question_marks: bool = Form(True),
    roster: Optional[str] = Form(None),  # Comma-separated or JSON list
    current_key: KeyInfo = Depends(get_current_key),
):
    """Enqueues an asynchronous multi-sheet processing job (authenticated)."""
    # 1. Rate limit check
    rate_limiter.check_rate_limit(current_key.key_id, current_key.rate_limit_rpm)

    # 2. Check per-key active job quota
    active_key_jobs = job_store.count_active_jobs_for_key(current_key.key_id)
    if active_key_jobs >= current_key.max_concurrent_jobs:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Concurrent job limit exceeded for this API key ({active_key_jobs}/{current_key.max_concurrent_jobs} active).",
            headers={"Retry-After": "10"},
        )

    # 3. Check free disk space
    has_space, free_mb = check_free_disk(min_free_mb=500)
    if not has_space:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Server storage full: only {free_mb} MB available.",
        )

    # 4. Validate file count
    validate_batch_file_count(len(files))

    # 5. Read and validate each file payload
    files_data = []
    for f in files:
        validate_content_type(f.content_type, f.filename or "unknown.jpg")
        content = await f.read()
        validate_file_size(len(content), f.filename or "unknown.jpg")
        validate_magic_bytes(content, f.filename or "unknown.jpg")
        validate_image_dimensions_and_decode(content, f.filename or "unknown.jpg")
        files_data.append((f.filename or "sheet.jpg", content))

    # Parse optional roster
    parsed_roster = []
    if roster:
        try:
            if roster.strip().startswith("["):
                parsed_roster = json.loads(roster)
            else:
                parsed_roster = [r.strip() for r in roster.split(",") if r.strip()]
        except Exception:
            parsed_roster = [r.strip() for r in roster.split(",") if r.strip()]

    return job_store.create_job(
        key_id=current_key.key_id,
        files_data=files_data,
        subject_code_declared=subject_code_declared,
        extract_total_marks=extract_total_marks,
        extract_question_marks=extract_question_marks,
        roster=parsed_roster,
    )


@router.get("/{job_id}")
async def get_job(job_id: str, current_key: KeyInfo = Depends(get_current_key)):
    """Retrieves current job status, total sheets, processed count, and progress."""
    return job_store.get_job_status(job_id, current_key)


@router.get("/{job_id}/results")
async def get_results(job_id: str, current_key: KeyInfo = Depends(get_current_key)):
    """Retrieves full extraction results and batch review for a completed job."""
    return job_store.get_job_results(job_id, current_key)


@router.delete("/{job_id}")
async def cancel_or_delete_job(job_id: str, current_key: KeyInfo = Depends(get_current_key)):
    """Cancels and purges a job and its outputs."""
    return job_store.delete_job(job_id, current_key)


@router.post("/drain-shutdown", summary="Initiate graceful server shutdown and worker drain", tags=["Operations"])
async def trigger_drain_shutdown(current_key: KeyInfo = Depends(require_admin)):
    """Initiates application-level drain: in-flight jobs abort cleanly, new uploads return 503."""
    job_store.initiate_shutdown()
    return {"status": "shutting_down", "message": "Server drain initiated. New uploads will be refused (503)."}
