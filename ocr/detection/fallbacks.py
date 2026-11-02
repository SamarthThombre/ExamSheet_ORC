"""
Deterministic geometric layout fallbacks for fields when YOLO detector misses detections.
Derived from empirical distribution across the 146 exam cover sheet benchmark dataset.
"""

from typing import Tuple, Optional
import numpy as np


def get_grand_total_fallback_box(img_w: int, img_h: int) -> Tuple[float, float, float, float]:
    """
    Returns the deterministic empirical coordinates for grand_total:
    (x1, y1, x2, y2) = (0.527 * W, 0.755 * H, 0.945 * W, 0.795 * H)
    """
    return (0.527 * img_w, 0.755 * img_h, 0.945 * img_w, 0.795 * img_h)


def get_subject_code_fallback_box(
    img_w: int,
    img_h: int,
    format_name: str = "format_original",
) -> Tuple[float, float, float, float]:
    """
    Returns deterministic empirical coordinates for subject_code:
      - format_original: (0.05 * W, 0.24 * H, 0.45 * W, 0.35 * H)
      - format_v2:       (0.04 * W, 0.20 * H, 0.48 * W, 0.35 * H)
    """
    if format_name == "format_v2":
        return (0.04 * img_w, 0.20 * img_h, 0.48 * img_w, 0.35 * img_h)
    return (0.05 * img_w, 0.24 * img_h, 0.45 * img_w, 0.35 * img_h)


def get_enrolment_no_crop(
    img: np.ndarray,
    enrolment_box_xyxy: Optional[Tuple[float, float, float, float]] = None,
    padding_ratio: float = 0.05,
    format_name: str = "format_original",
) -> Tuple[np.ndarray, bool]:
    """
    Extracts the enrolment_no image crop.
    When a valid YOLO detection box is provided within expected layout bounds:
      0.20 * H <= y1 <= 0.45 * H  and  0.40 * W <= x1 <= 0.85 * W,
    extracts the padded crop.
    Otherwise, applies a deterministic geometric fallback crop:
      - format_original: x1 = 0.520 * W, y1 = 0.260 * H, x2 = 0.985 * W, y2 = 0.360 * H.
      - format_v2:       x1 = 0.550 * W, y1 = 0.250 * H, x2 = 0.990 * W, y2 = 0.410 * H.

    Returns:
      (crop_image, used_fallback: bool)
    """
    img_h, img_w = img.shape[:2]
    used_fallback = False

    if enrolment_box_xyxy is not None:
        x1, y1, x2, y2 = [float(v) for v in enrolment_box_xyxy]
        y_max = 0.45 * img_h if format_name == "format_v2" else 0.42 * img_h
        x_max = 0.85 * img_w if format_name == "format_v2" else 0.75 * img_w
        if (
            0.20 * img_h <= y1 <= y_max
            and 0.40 * img_w <= x1 <= x_max
            and x2 > x1
            and y2 > y1
        ):
            bw = max(1.0, x2 - x1)
            bh = max(1.0, y2 - y1)
            px = int(bw * padding_ratio)
            py = int(bh * padding_ratio)
            cx1 = max(0, int(x1 - px))
            cy1 = max(0, int(y1 - py))
            cx2 = min(img_w, int(x2 + px))
            cy2 = min(img_h, int(y2 + py))
            crop = img[cy1:cy2, cx1:cx2]
            if crop.size > 0:
                return crop, False

    # Deterministic geometric fallback crop
    used_fallback = True
    if format_name == "format_v2":
        cx1 = max(0, int(0.550 * img_w))
        cy1 = max(0, int(0.250 * img_h))
        cx2 = min(img_w, int(0.990 * img_w))
        cy2 = min(img_h, int(0.410 * img_h))
    else:
        cx1 = max(0, int(0.520 * img_w))
        cy1 = max(0, int(0.260 * img_h))
        cx2 = min(img_w, int(0.985 * img_w))
        cy2 = min(img_h, int(0.360 * img_h))

    crop = img[cy1:cy2, cx1:cx2]
    return crop, True
