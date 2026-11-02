"""
YOLOv8 Field Detector wrapper for exam paper cover sheets.
Handles model loading, inference, confidence filtering, and defensive bounding box clipping.
"""

import logging
from pathlib import Path
from typing import Dict, Any, Union, Optional
import numpy as np

logger = logging.getLogger("ocr.detection.detector")

EXPECTED_CLASSES = {"enrolment_no", "subject_code", "grand_total"}


class YOLOFieldDetector:
    """
    Encapsulates YOLOv8 field detection with boundary validation.
    """

    def __init__(self, model_path: Union[str, Path]):
        self.model_path = Path(model_path)
        self.model = None
        self.is_loaded = False

    def load_model(self):
        """Loads YOLO detector weights into memory."""
        if self.is_loaded:
            return

        if not self.model_path.exists():
            raise FileNotFoundError(f"YOLO detector weights not found at: {self.model_path.resolve()}")

        from ultralytics import YOLO
        logger.info(f"Loading YOLOv8 detector from: {self.model_path}")
        self.model = YOLO(str(self.model_path))
        self.is_loaded = True
        logger.info("YOLOv8 detector loaded successfully.")

    def detect_fields(
        self,
        img: np.ndarray,
        conf_thresh: float = 0.35,
        imgsz: int = 1280,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Runs field detection on the input image.
        Returns a dictionary mapping class_name -> {'conf': float, 'xyxy': [x1, y1, x2, y2]}.
        Coordinates are defensively clamped to [0, W] and [0, H].
        Degenerate zero-area boxes are discarded.
        """
        if not self.is_loaded:
            self.load_model()

        img_h, img_w = img.shape[:2]
        results = self.model(
            img,
            conf=conf_thresh,
            imgsz=imgsz,
            verbose=False,
        )

        best_detections: Dict[str, Dict[str, Any]] = {}
        if not results or len(results[0].boxes) == 0:
            return best_detections

        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            cls_name = results[0].names[cls_id]
            conf = float(box.conf[0])

            if cls_name not in EXPECTED_CLASSES:
                continue

            # Defensive bounding box validation & boundary clipping
            coords = box.xyxy[0].cpu().numpy()
            bx1, by1 = max(0.0, float(coords[0])), max(0.0, float(coords[1]))
            bx2, by2 = min(float(img_w), float(coords[2])), min(float(img_h), float(coords[3]))

            # Discard zero-area or inverted boxes
            if bx2 <= bx1 or by2 <= by1:
                logger.warning(f"Discarding invalid zero-area detection for '{cls_name}': [{bx1}, {by1}, {bx2}, {by2}]")
                continue

            if cls_name not in best_detections or conf > best_detections[cls_name]["conf"]:
                best_detections[cls_name] = {
                    "conf": conf,
                    "xyxy": [bx1, by1, bx2, by2],
                }

        return best_detections
