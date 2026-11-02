"""
app/validators.py: Comprehensive request validation and safety checks:
- Content-type validation (415 Unsupported Media Type)
- Magic-byte verification (422 Unprocessable Content / Magic Byte Mismatch)
- File size validation (413 Content Too Large)
- Dimension and pixel count validation (422 Oversize Dimensions)
- Corrupt image verification (422 Image Corrupt)
- Maximum batch file count validation (413 / 400)
- Per-key rate limiting (429 Too Many Requests)
- Per-key concurrent jobs limit (429 Too Many Requests)
"""

import time
import threading
from typing import Tuple, Dict, List
import cv2
import numpy as np
from fastapi import HTTPException, status

from app.config import settings

# Allowed Magic Bytes Signatures
MAGIC_JPEG = b"\xff\xd8\xff"
MAGIC_PNG = b"\x89PNG\r\n\x1a\n"
MAGIC_RIFF = b"RIFF"
MAGIC_WEBP = b"WEBP"

# Dimensional Limits
MAX_IMAGE_WIDTH = 8000
MAX_IMAGE_HEIGHT = 8000
MAX_PIXEL_COUNT = 40_000_000  # 40 Megapixels


def validate_content_type(content_type: str, filename: str):
    """Verifies that the MIME type is an acceptable image type."""
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/jpg", "application/octet-stream"}
    if content_type and content_type.lower() not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported media type '{content_type}'. Expected image/jpeg, image/png, or image/webp.",
        )


def validate_magic_bytes(data: bytes, filename: str):
    """Verifies image magic bytes to ensure file content matches image formats."""
    if len(data) < 12:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Uploaded file '{filename}' is too small to be a valid image header.",
        )

    is_jpeg = data.startswith(MAGIC_JPEG)
    is_png = data.startswith(MAGIC_PNG)
    is_webp = data.startswith(MAGIC_RIFF) and (data[8:12] == MAGIC_WEBP)

    if not (is_jpeg or is_png or is_webp):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Magic bytes mismatch for '{filename}': file header does not match valid JPEG, PNG, or WEBP.",
        )


def validate_file_size(size_bytes: int, filename: str):
    """Verifies uploaded file size is within configured bounds."""
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if size_bytes > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File '{filename}' ({size_bytes / (1024*1024):.2f} MB) exceeds maximum upload limit of {settings.MAX_UPLOAD_MB} MB.",
        )


def validate_image_dimensions_and_decode(data: bytes, filename: str) -> np.ndarray:
    """Decodes image and verifies dimensions and pixel count are within safe limits."""
    np_buf = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(np_buf, cv2.IMREAD_COLOR)

    if img is None or img.size == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Corrupt image payload: '{filename}' could not be decoded as a valid image.",
        )

    h, w = img.shape[:2]
    if w > MAX_IMAGE_WIDTH or h > MAX_IMAGE_HEIGHT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Image dimensions ({w}x{h}) exceed maximum allowed dimension of {MAX_IMAGE_WIDTH}x{MAX_IMAGE_HEIGHT} px.",
        )

    if (w * h) > MAX_PIXEL_COUNT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Image pixel count ({w * h:,} pixels) exceeds maximum limit of {MAX_PIXEL_COUNT:,} pixels.",
        )

    return img


def validate_batch_file_count(count: int):
    """Verifies total files submitted in a batch job does not exceed ceiling."""
    if count > settings.MAX_FILES_PER_JOB:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Submitted batch of {count} files exceeds limit of {settings.MAX_FILES_PER_JOB} files per job.",
        )
    if count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Batch job must contain at least one file.",
        )


# ==============================================================================
# Rate Limiting & Concurrency Tracker
# ==============================================================================

class RateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._request_history: Dict[str, List[float]] = {}

    def check_rate_limit(self, key_id: str, limit_rpm: int):
        """Enforces sliding 60-second window rate limit for given key_id."""
        now = time.time()
        cutoff = now - 60.0
        with self._lock:
            timestamps = self._request_history.get(key_id, [])
            valid_timestamps = [t for t in timestamps if t > cutoff]
            if len(valid_timestamps) >= limit_rpm:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded ({limit_rpm} requests per minute). Please retry shortly.",
                    headers={"Retry-After": "5"},
                )
            valid_timestamps.append(now)
            self._request_history[key_id] = valid_timestamps


rate_limiter = RateLimiter()
