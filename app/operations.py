"""
app/operations.py: Operational utilities for database backups, restores, disk space validation,
and retention purging.
"""

import os
import shutil
import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Tuple, Dict, Any

from app.config import settings

logger = logging.getLogger("api.operations")

DB_PATH = Path(settings.DB_PATH)
UPLOAD_DIR = Path(settings.UPLOAD_DIR)


def check_free_disk(min_free_mb: int = 500) -> Tuple[bool, float]:
    """
    Checks available free disk space on the drive hosting application uploads and database.
    Returns (is_sufficient, free_space_mb).
    """
    target_path = UPLOAD_DIR if UPLOAD_DIR.exists() else Path(".")
    usage = shutil.disk_usage(str(target_path.resolve()))
    free_mb = round(usage.free / (1024 * 1024), 2)
    is_sufficient = free_mb >= min_free_mb
    if not is_sufficient:
        logger.error(f"Insufficient disk space: {free_mb} MB available (minimum required: {min_free_mb} MB).")
    return is_sufficient, free_mb


def backup_database(destination_path: Path) -> Path:
    """
    Creates an atomic, consistent online backup of the SQLite database using SQLite's backup API.
    Works safely with active transactions and WAL mode.
    """
    dest = Path(destination_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        # Initialize empty database if none exists yet
        with sqlite3.connect(DB_PATH) as conn:
            pass

    with sqlite3.connect(DB_PATH) as src_conn:
        with sqlite3.connect(dest) as dst_conn:
            src_conn.backup(dst_conn)

    logger.info(f"Successfully backed up database from {DB_PATH} to {dest}")
    return dest


def restore_database(backup_path: Path, target_path: Path) -> Dict[str, Any]:
    """
    Restores database from backup to target_path and verifies structural integrity.
    """
    b_path = Path(backup_path)
    t_path = Path(target_path)
    if not b_path.exists():
        raise FileNotFoundError(f"Backup file '{b_path}' does not exist.")

    t_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(b_path) as src_conn:
        with sqlite3.connect(t_path) as dst_conn:
            src_conn.backup(dst_conn)

    # Check integrity
    with sqlite3.connect(t_path) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        status = cursor.fetchone()[0]
        if status != "ok":
            raise RuntimeError(f"Database integrity check failed: {status}")

        # Get job count if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
        has_jobs = cursor.fetchone() is not None
        job_count = 0
        if has_jobs:
            cursor.execute("SELECT COUNT(*) FROM jobs")
            job_count = cursor.fetchone()[0]

    logger.info(f"Database restored successfully to {target_path} (integrity: {status}, jobs: {job_count})")
    return {"status": "ok", "integrity": status, "job_count": job_count}


def purge_expired_jobs(retention_days: int = 7) -> int:
    """
    Purges jobs older than retention_days from SQLite and wipes their storage directories.
    """
    if not DB_PATH.exists():
        return 0

    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    purged_count = 0

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
        if not cursor.fetchone():
            return 0

        cursor.execute("SELECT job_id, upload_dir FROM jobs WHERE created_at < ?", (cutoff_date,))
        expired = cursor.fetchall()

        for j_id, u_dir in expired:
            if u_dir and Path(u_dir).exists():
                try:
                    shutil.rmtree(u_dir)
                except Exception as e:
                    logger.warning(f"Could not remove upload dir for expired job {j_id}: {e}")
            purged_count += 1

        cursor.execute("DELETE FROM jobs WHERE created_at < ?", (cutoff_date,))
        conn.commit()

    if purged_count > 0:
        logger.info(f"Purged {purged_count} expired jobs older than {retention_days} days.")
    return purged_count
