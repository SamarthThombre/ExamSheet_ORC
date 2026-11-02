"""
app/auth.py: Authentication and Role-Based Access Control for Exam Paper OCR Extractor API.
- Enforces API key verification via X-API-Key header.
- Stores cryptographic SHA-256 hashes of keys in SQLite (never plaintext).
- Never leaks API keys to log output (sanitized display).
- Enforces job ownership and admin-only key management.
"""

import hashlib
import hmac
import os
import secrets
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from fastapi import Header, HTTPException, Depends, status

from app.config import settings

logger = logging.getLogger("api.auth")

DB_PATH = Path(settings.DB_PATH)
ADMIN_DEFAULT_KEY = os.getenv("ADMIN_API_KEY", "ep_admin_master_secret_key_deploy2")


class KeyInfo(BaseModel):
    key_id: str
    name: str
    role: str  # "admin" or "user"
    rate_limit_rpm: int = 60
    max_concurrent_jobs: int = 3
    created_at: str
    is_active: bool = True


class KeyCreateRequest(BaseModel):
    name: str = Field(..., description="Descriptive identifier for the key owner")
    role: str = Field(default="user", description="'admin' or 'user'")
    rate_limit_rpm: int = Field(default=60, description="Requests per minute quota")
    max_concurrent_jobs: int = Field(default=3, description="Maximum concurrent active jobs")


class KeyCreateResponse(BaseModel):
    key_id: str
    name: str
    role: str
    api_key: str = Field(..., description="Plaintext API key shown ONLY once at creation")
    rate_limit_rpm: int
    max_concurrent_jobs: int
    created_at: str


def hash_key(plain_key: str) -> str:
    """Computes SHA-256 digest of API key."""
    return hashlib.sha256(plain_key.encode("utf-8")).hexdigest()


def mask_key(plain_key: Optional[str]) -> str:
    """Masks an API key for safe logging (e.g. 'ep_adm****')."""
    if not plain_key:
        return "[none]"
    if len(plain_key) <= 8:
        return "****"
    return f"{plain_key[:6]}****{plain_key[-2:]}"


def init_auth_db():
    """Initializes api_keys table in SQLite database and ensures admin key exists."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id TEXT PRIMARY KEY,
                key_hash TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                rate_limit_rpm INTEGER DEFAULT 60,
                max_concurrent_jobs INTEGER DEFAULT 3,
                created_at TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            )
            """
        )
        conn.commit()

        # Check if any admin key exists; if not, create default master admin key
        cursor.execute("SELECT COUNT(*) FROM api_keys WHERE role = 'admin' AND is_active = 1")
        admin_count = cursor.fetchone()[0]

        default_admin_key = os.getenv("ADMIN_API_KEY", "ep_admin_master_secret_key_deploy2")
        admin_hash = hash_key(default_admin_key)

        cursor.execute("SELECT key_id FROM api_keys WHERE key_hash = ?", (admin_hash,))
        if not cursor.fetchone():
            now_iso = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT OR REPLACE INTO api_keys 
                (key_id, key_hash, name, role, rate_limit_rpm, max_concurrent_jobs, created_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                ("admin_default", admin_hash, "System Default Admin", "admin", 600, 20, now_iso),
            )
            conn.commit()
            logger.info("Initialized default administrative API key (hash stored).")


def get_key_from_db(plain_key: str) -> Optional[KeyInfo]:
    """Retrieves key metadata by verifying hash in database."""
    k_hash = hash_key(plain_key)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT key_id, name, role, rate_limit_rpm, max_concurrent_jobs, created_at, is_active
            FROM api_keys
            WHERE key_hash = ? AND is_active = 1
            """,
            (k_hash,),
        )
        row = cursor.fetchone()
        if row:
            return KeyInfo(
                key_id=row[0],
                name=row[1],
                role=row[2],
                rate_limit_rpm=row[3],
                max_concurrent_jobs=row[4],
                created_at=row[5],
                is_active=bool(row[6]),
            )
    return None


async def get_current_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> KeyInfo:
    """FastAPI dependency to authenticate caller via X-API-Key header."""
    if not x_api_key:
        logger.warning("Authentication failed: Missing X-API-Key header.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header. Please provide a valid API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    info = get_key_from_db(x_api_key)
    if not info:
        logger.warning(f"Authentication failed: Invalid API key ({mask_key(x_api_key)}).")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return info


async def require_admin(current_key: KeyInfo = Depends(get_current_key)) -> KeyInfo:
    """Dependency verifying caller has admin privileges."""
    if current_key.role != "admin":
        logger.warning(f"Authorization failed: key {current_key.key_id} attempted admin action without role=admin.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Administrative privileges required.",
        )
    return current_key


def create_new_key(req: KeyCreateRequest) -> KeyCreateResponse:
    """Generates a secure random API key, hashes it, and persists metadata."""
    token = secrets.token_urlsafe(32)
    plain_key = f"ep_{token}"
    k_hash = hash_key(plain_key)
    key_id = f"key_{secrets.token_hex(6)}"
    now_iso = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO api_keys 
            (key_id, key_hash, name, role, rate_limit_rpm, max_concurrent_jobs, created_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (key_id, k_hash, req.name, req.role, req.rate_limit_rpm, req.max_concurrent_jobs, now_iso),
        )
        conn.commit()

    logger.info(f"Created new API key '{key_id}' for name='{req.name}', role='{req.role}' (hash stored).")
    return KeyCreateResponse(
        key_id=key_id,
        name=req.name,
        role=req.role,
        api_key=plain_key,
        rate_limit_rpm=req.rate_limit_rpm,
        max_concurrent_jobs=req.max_concurrent_jobs,
        created_at=now_iso,
    )


def list_keys() -> List[Dict[str, Any]]:
    """Returns list of API key records without hashes or plaintext."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT key_id, name, role, rate_limit_rpm, max_concurrent_jobs, created_at, is_active
            FROM api_keys
            ORDER BY created_at DESC
            """
        )
        rows = cursor.fetchall()
        return [
            {
                "key_id": r[0],
                "name": r[1],
                "role": r[2],
                "rate_limit_rpm": r[3],
                "max_concurrent_jobs": r[4],
                "created_at": r[5],
                "is_active": bool(r[6]),
            }
            for r in rows
        ]


def revoke_key(key_id: str) -> bool:
    """Revokes an API key by setting is_active = 0."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE api_keys SET is_active = 0 WHERE key_id = ?", (key_id,))
        conn.commit()
        return cursor.rowcount > 0
