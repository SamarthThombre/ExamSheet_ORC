"""
Red divider boundary detector separating printed 'GRAND TOTAL' label
from the handwritten score region.
"""

from typing import Tuple
import cv2
import numpy as np


def detect_red_divider_x(crop_bgr: np.ndarray) -> Tuple[int, float]:
    """
    Locates the vertical red divider line separating the printed 'GRAND TOTAL' label
    from the handwritten total-marks region (benchmarked on the 146-page dataset).

    Returns:
      (cut_x: int, divider_ratio: float)
    """
    if crop_bgr is None or crop_bgr.size == 0 or crop_bgr.shape[1] < 30:
        return 0, 0.0

    h, w = crop_bgr.shape[:2]
    b, g, r = cv2.split(crop_bgr.astype(np.float32))
    redness = np.clip(r - 0.5 * (g + b), 0, 255)

    s1, s2 = int(0.20 * w), int(0.42 * w)
    if s2 <= s1:
        return 0, 0.0

    col_profile = redness[:, s1:s2].mean(axis=0)
    best_offset = int(np.argmax(col_profile))
    div_x = s1 + best_offset

    cut_x = min(w - 20, div_x + 6)
    ratio = div_x / float(w)
    return cut_x, ratio
