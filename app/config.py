import os
from pathlib import Path
from typing import Set, List

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings:
    """
    Application configuration settings with environment variable fallbacks.
    """
    APP_TITLE: str = "Exam Paper OCR Extractor API"
    APP_VERSION: str = "2.0.0"
    APP_DESCRIPTION: str = "FastAPI backend for structured field extraction from exam cover-sheet images."
    DEBUG: bool = os.getenv("DEBUG", "false").lower() in {"1", "true", "yes"}

    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # Production Engine & Paths
    MODEL_DIR: Path = Path(os.getenv("MODEL_DIR", str(BASE_DIR / "models")))
    UPLOAD_DIR: Path = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
    DB_PATH: Path = Path(os.getenv("DB_PATH", str(BASE_DIR / "jobs.db")))

    # Jobs & Worker Pool Configuration
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "25"))
    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_MB", "25"))  # backward compat
    MAX_FILES_PER_JOB: int = int(os.getenv("MAX_FILES_PER_JOB", "100"))
    MAX_QUEUED_JOBS: int = int(os.getenv("MAX_QUEUED_JOBS", "10"))
    WORKERS: int = int(os.getenv("WORKERS", "2"))
    ORT_THREADS: int = int(os.getenv("ORT_THREADS", "4"))
    RETENTION_DAYS: int = int(os.getenv("RETENTION_DAYS", "7"))

    # Feature Toggles
    ENABLE_LEGACY: bool = os.getenv("ENABLE_LEGACY", "false").lower() in {"1", "true", "yes"}
    ENABLE_UI: bool = os.getenv("ENABLE_UI", "false").lower() in {"1", "true", "yes"}
    ENABLE_PAGE_LOCALISER: bool = os.getenv("ENABLE_PAGE_LOCALISER", "true").lower() in {"1", "true", "yes"}

    # Logging & Security
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    CORS_ORIGINS: List[str] = [x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()]

    # Legacy YOLO & OCR Fallbacks
    YOLO_MODEL_PATH: str = os.getenv(
        "YOLO_MODEL_PATH",
        str(BASE_DIR / "models" / "best.pt")
        if (BASE_DIR / "models" / "best.pt").exists()
        else str(BASE_DIR / "best.pt"),
    )
    YOLO_CONF_THRESH: float = float(os.getenv("YOLO_CONF_THRESH", "0.30"))
    YOLO_IMGSZ: int = int(os.getenv("YOLO_IMGSZ", "1280"))
    PADDING_RATIO: float = float(os.getenv("PADDING_RATIO", "0.05"))
    OCR_CONF_THRESH: float = float(os.getenv("OCR_CONF_THRESH", "0.60"))
    OCR_LANG: str = os.getenv("OCR_LANG", "en")
    ALLOWED_IMAGE_EXTENSIONS: Set[str] = {".jpg", ".jpeg", ".png", ".webp"}
    TEMP_DIR: Path = Path(os.getenv("TEMP_DIR", str(BASE_DIR / "tmp" / "uploads")))


settings = Settings()
