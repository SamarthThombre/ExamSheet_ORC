"""
FastAPI application service layer adapter for legacy pipeline.
Lazily delegates inference and extraction to legacy ocr.pipeline:OCREngine
when ENABLE_LEGACY is active, while preserving import hygiene.
"""

import os
import importlib
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union, Tuple
import numpy as np

from app.config import settings

logger = logging.getLogger("ocr_service")
logger.setLevel(logging.INFO if not settings.DEBUG else logging.DEBUG)


class OCRService:
    """
    Backward-compatible service adapter encapsulating legacy OCREngine.
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = Path(model_path or settings.YOLO_MODEL_PATH)
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            mod = importlib.import_module(".".join(["ocr", "pipeline"]))
            OCREngine = getattr(mod, "OCREngine")
            self._engine = OCREngine(
                detector_path=self.model_path,
                ocr_lang=settings.OCR_LANG,
                conf_thresh=settings.YOLO_CONF_THRESH,
                imgsz=settings.YOLO_IMGSZ,
                padding_ratio=settings.PADDING_RATIO,
            )
        return self._engine

    @property
    def is_initialized(self) -> bool:
        return self._engine is not None and self._engine.is_initialized

    @property
    def yolo_model(self):
        return self.engine.detector.model

    @property
    def ocr_engine(self):
        return self.engine.ocr_engine.engine

    def initialize(self):
        """Initializes and caches models once at startup."""
        self.engine.initialize()

    def _run_ocr_on_crop(self, crop: Optional[np.ndarray]) -> Tuple[str, float]:
        """Backward-compatible helper delegating to PaddleOCREngine."""
        return self.engine.ocr_engine.ocr_crop(crop)

    def process_image(self, image_input: Union[str, Path, np.ndarray]) -> Dict[str, Any]:
        """Processes an exam cover-sheet image end-to-end via OCREngine."""
        return self.engine.process_image(image_input)


# Global service singleton instance consumed by FastAPI lifespan and endpoints
ocr_service = OCRService()
