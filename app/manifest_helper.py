import hashlib
import json
from pathlib import Path
from typing import Tuple, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "models" / "manifest.json"


def get_manifest_hash() -> str:
    """Returns the production manifest SHA-256 hash."""
    if not MANIFEST_PATH.exists():
        return "UNKNOWN_MANIFEST"
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("manifest_hash", "UNKNOWN_MANIFEST")
    except Exception:
        return "ERROR_READING_MANIFEST"


def verify_model_checksums() -> Tuple[bool, Optional[str]]:
    """Verifies SHA-256 checksums of vendored models."""
    if not MANIFEST_PATH.exists():
        return False, "Manifest file models/manifest.json not found"

    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return False, f"Failed to parse manifest: {e}"

    models = data.get("models", {})
    if not models:
        return False, "No models defined in manifest"

    for rel_path, meta in models.items():
        file_path = PROJECT_ROOT / rel_path
        if not file_path.exists():
            return False, f"Model file not found: {rel_path}"

        expected_hash = meta.get("sha256")
        hasher = hashlib.sha256()
        try:
            with open(file_path, "rb") as fp:
                for chunk in iter(lambda: fp.read(65536), b""):
                    hasher.update(chunk)
            actual_hash = hasher.hexdigest()
            if actual_hash != expected_hash:
                return False, f"Checksum mismatch for {rel_path}: expected {expected_hash}, got {actual_hash}"
        except Exception as e:
            return False, f"Error hashing {rel_path}: {e}"

    return True, None
