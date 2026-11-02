"""
Field detection module: YOLOv8 detector and geometric layout fallbacks.
"""

from ocr.detection.fallbacks import (
    get_enrolment_no_crop,
    get_grand_total_fallback_box,
)
from ocr.detection.detector import YOLOFieldDetector, EXPECTED_CLASSES

__all__ = [
    "get_enrolment_no_crop",
    "get_grand_total_fallback_box",
    "YOLOFieldDetector",
    "EXPECTED_CLASSES",
]
