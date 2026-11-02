import os
import time
import hashlib
import logging
from contextlib import asynccontextmanager
from typing import Optional
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, UploadFile, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.manifest_helper import get_manifest_hash, verify_model_checksums
from app.schemas import (
    HealthResponse,
    PredictResponse,
    ErrorResponse,
    ExtractionResult,
    ProcessingMeta,
)
from app.services.ocr_service import ocr_service

# Configure application logging
logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("api")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager:
    Warms up v2 ONNX models at startup, and optionally initializes legacy models when ENABLE_LEGACY=true.
    """
    logger.info(f"Starting {settings.APP_TITLE} v{settings.APP_VERSION}...")
    try:
        from ocr_v2.cell_reader import SharedCellReader, get_ort_session
        sess = get_ort_session()
        reader = SharedCellReader()
        dummy_crop = np.zeros((48, 120, 3), dtype=np.uint8)
        x = reader.preprocess_crops([dummy_crop])
        sess.run(None, {sess.get_inputs()[0].name: x})
        logger.info("v2 ONNX models loaded and warmed up successfully.")
    except Exception as e:
        logger.warning(f"v2 warmup warning: {e}")

    if os.getenv("ENABLE_LEGACY", "").lower() in ("1", "true"):
        try:
            ocr_service.initialize()
            logger.info("Legacy ML inference engine loaded and ready.")
        except Exception as e:
            logger.warning(f"Could not initialize legacy OCR models: {e}")

    # Initialize authentication database
    try:
        from app.auth import init_auth_db
        init_auth_db()
    except Exception as e:
        logger.warning(f"Auth DB init warning: {e}")

    # Recover any interrupted jobs from previous restart
    try:
        from app.jobs import job_store
        job_store.recover_interrupted_jobs()
    except Exception as e:
        logger.warning(f"Job recovery warning: {e}")

    yield

    logger.info(f"Shutting down {settings.APP_TITLE}...")
    try:
        from app.jobs import job_store
        job_store.initiate_shutdown()
    except Exception as e:
        logger.warning(f"Job store shutdown warning: {e}")


app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Enable CORS
cors_allowed = [o.strip() for o in settings.CORS_ORIGINS if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed if cors_allowed and cors_allowed != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.metrics import metrics
import uuid

@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    origin = request.headers.get("origin")
    allowed_origins = [o.strip() for o in settings.CORS_ORIGINS if o.strip()]

    # If origin is not allowed, reject preflight or strip allow-origin
    if request.method == "OPTIONS" and origin:
        if "*" not in allowed_origins and origin not in allowed_origins:
            return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": "CORS origin forbidden."})

    req_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"
    request.state.request_id = req_id
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    response.headers["X-Request-ID"] = req_id
    # Secure response headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'"

    # Enforce CORS origin matching at runtime
    if origin:
        if "*" not in allowed_origins and origin not in allowed_origins:
            if "access-control-allow-origin" in response.headers:
                del response.headers["access-control-allow-origin"]
            if "access-control-allow-credentials" in response.headers:
                del response.headers["access-control-allow-credentials"]

    endpoint = request.url.path
    metrics.record_request(endpoint, response.status_code, elapsed_ms)
    return response


# ==============================================================================
# Error Handlers
# ==============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code = "HTTP_ERROR"
    if exc.status_code == status.HTTP_400_BAD_REQUEST:
        code = "BAD_REQUEST"
    elif exc.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE:
        code = "FILE_TOO_LARGE"
    elif exc.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
        code = "UNPROCESSABLE_IMAGE"

    detail_msg = exc.detail if isinstance(exc.detail, str) else "Request error."
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "detail": detail_msg,
            "error": {"code": code, "message": detail_msg},
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request parameters. Please upload an image file using multipart/form-data under the 'file' parameter.",
            },
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled server error during request processing: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred while processing the image. Please verify image format and retry.",
            },
        },
    )


# ==============================================================================
# Endpoints
# ==============================================================================

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check and model status",
    tags=["System"],
)
async def health_check():
    """
    Lightweight health check endpoint.
    Reports service status, version from VERSION file, manifest hash, and engine name.
    """
    version_file = PROJECT_ROOT / "VERSION"
    app_ver = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "2.0.0"
    m_hash = get_manifest_hash()
    return HealthResponse(
        status="ok",
        version=app_ver,
        engine_name="v2",
        manifest_hash=m_hash,
        ocr_loaded=True,
        detector_loaded=True,
        model_path="models/ppocrv6/rec_ppocr_v6.onnx",
    )


@app.get(
    "/ready",
    summary="Readiness check and model checksum verification",
    tags=["System"],
)
async def ready_check():
    """
    Readiness probe verifying vendored model existence and SHA-256 checksums.
    Fails with HTTP 503 if any model checksum fails.
    """
    valid, err = verify_model_checksums()
    if not valid:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "ready": False, "error": err},
        )
    return {"status": "ready", "ready": True, "checksums_verified": True}


@app.get(
    "/metrics",
    summary="Observability metrics endpoint",
    tags=["System"],
)
async def get_metrics():
    """
    Exposes request counts and latencies, queue length, jobs by status,
    and OCR diagnostic flag counts. Guaranteed zero personal data.
    """
    from app.jobs import job_store
    q_len = job_store.list_active_count()
    return metrics.get_metrics_snapshot(queue_length=q_len)


@app.post(
    "/predict",
    response_model=PredictResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid file format or missing filename"},
        410: {"model": ErrorResponse, "description": "Legacy endpoint deprecated and disabled"},
        413: {"model": ErrorResponse, "description": "Uploaded image exceeds size limit"},
        422: {"model": ErrorResponse, "description": "Unprocessable image data"},
        500: {"model": ErrorResponse, "description": "Internal server processing error"},
    },
    summary="Extract structured fields from exam cover-sheet image",
    tags=["OCR Extraction"],
)
async def predict_exam_page(
    file: UploadFile = File(
        ...,
        description="Exam cover-sheet image file (JPG, PNG, or WEBP format)",
    ),
):
    """
    Primary OCR extraction endpoint:
    Returns HTTP 410 Gone unless ENABLE_LEGACY=true is set.
    """
    enable_legacy = os.getenv("ENABLE_LEGACY", "").lower() in ("1", "true")
    if not enable_legacy:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Legacy endpoint /predict is deprecated. Use /v2/predict instead.",
        )

    t0 = time.perf_counter()
    filename = file.filename or "unknown.png"
    logger.info(f"Received extraction request for file: '{filename}'")

    # 1. Validate file extension
    ext = Path(filename).suffix.lower()
    if ext not in settings.ALLOWED_IMAGE_EXTENSIONS:
        logger.warning(f"Rejected file with invalid extension: '{filename}' ({ext})")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Supported formats: {', '.join(sorted(settings.ALLOWED_IMAGE_EXTENSIONS))}",
        )

    # 2. Read and validate payload size
    try:
        content = await file.read()
    except Exception as e:
        logger.error(f"Failed to read uploaded file payload: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read the uploaded file payload.",
        )

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        logger.warning(f"Rejected oversized payload: {len(content)} bytes (limit {max_bytes} bytes)")
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Uploaded file size ({len(content) / (1024*1024):.2f} MB) exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB} MB.",
        )

    if len(content) < 100:
        logger.warning(f"Rejected empty/truncated payload: {len(content)} bytes")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file payload is empty or truncated.",
        )

    # 3. Decode image in-memory
    np_buf = np.frombuffer(content, dtype=np.uint8)
    img = cv2.imdecode(np_buf, cv2.IMREAD_COLOR)

    if img is None or img.size == 0:
        logger.warning(f"Failed to decode image from byte buffer for '{filename}'")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file could not be decoded as a valid image. Ensure the image is not corrupted.",
        )

    # 4. Execute Core OCR Pipeline
    try:
        raw_result = ocr_service.process_image(img)
    except Exception as e:
        logger.error(f"OCR pipeline processing failure on '{filename}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process image through the OCR pipeline.",
        )

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    sheet_hash = hashlib.sha256(content[:128]).hexdigest()[:8]
    logger.info(f"Successfully processed sheet_{sheet_hash} in {elapsed_ms}ms (needs_review={raw_result.get('needs_review')})")

    return PredictResponse(
        success=True,
        filename=filename,
        result=ExtractionResult(**raw_result),
        processing=ProcessingMeta(
            status="completed",
            processing_time_ms=elapsed_ms,
        ),
    )


from app.routers_v2 import router as router_v2
from app.jobs import router as router_jobs
from app.routers_admin import router as router_admin
app.include_router(router_v2)
app.include_router(router_jobs)
app.include_router(router_admin)

if settings.ENABLE_UI:
    from fastapi.staticfiles import StaticFiles
    frontend_dir = PROJECT_ROOT / "frontend"
    if frontend_dir.exists():
        app.mount("/ui", StaticFiles(directory=str(frontend_dir), html=True), name="ui")

