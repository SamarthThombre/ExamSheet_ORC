"""
app/routers_admin.py: Administrative routes for API key management, retention purge,
and database backups.
Strictly restricted to callers with role='admin'.
"""

from pathlib import Path
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import (
    KeyInfo,
    KeyCreateRequest,
    KeyCreateResponse,
    require_admin,
    create_new_key,
    list_keys,
    revoke_key,
)
from app.operations import purge_expired_jobs, backup_database
from app.config import settings

router = APIRouter(prefix="/v2/admin", tags=["Administration"])


@router.post("/keys", response_model=KeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def generate_key(req: KeyCreateRequest, admin: KeyInfo = Depends(require_admin)):
    """Creates a new API key with designated role and rate limits (admin only)."""
    return create_new_key(req)


@router.get("/keys", response_model=List[Dict[str, Any]])
async def get_all_keys(admin: KeyInfo = Depends(require_admin)):
    """Lists all active and inactive API keys without exposing hashes (admin only)."""
    return list_keys()


@router.delete("/keys/{key_id}")
async def delete_key(key_id: str, admin: KeyInfo = Depends(require_admin)):
    """Revokes an API key (admin only)."""
    ok = revoke_key(key_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Key '{key_id}' not found.")
    return {"key_id": key_id, "revoked": True}


@router.post("/purge")
async def trigger_purge(retention_days: int = settings.RETENTION_DAYS, admin: KeyInfo = Depends(require_admin)):
    """Triggers retention purge of jobs and uploads older than retention_days (admin only)."""
    purged = purge_expired_jobs(retention_days)
    return {"purged_jobs_count": purged, "retention_days": retention_days}


@router.post("/backup")
async def trigger_backup(admin: KeyInfo = Depends(require_admin)):
    """Executes online backup of SQLite database (admin only)."""
    backup_path = Path(settings.DB_PATH).parent / f"backup_jobs_{int(Path(settings.DB_PATH).stat().st_mtime)}.db"
    dest = backup_database(backup_path)
    return {"backup_file": str(dest), "status": "completed"}
