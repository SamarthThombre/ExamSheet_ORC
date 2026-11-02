"""
Recognition module: cropping, red divider detection, and PaddleOCR engine.
"""

from ocr.recognition.divider import detect_red_divider_x
from ocr.recognition.cropper import FieldCropper
from ocr.recognition.paddle_engine import PaddleOCREngine

__all__ = [
    "detect_red_divider_x",
    "FieldCropper",
    "PaddleOCREngine",
]
