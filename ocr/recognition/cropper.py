"""
Field and companion crop generator for exam cover sheet regions.
"""

from typing import Dict, Any, Optional, Tuple
import numpy as np

from ocr.recognition.divider import detect_red_divider_x
from ocr.detection.fallbacks import get_grand_total_fallback_box


class FieldCropper:
    """
    Handles image slicing, padding expansion, boundary safety,
    red-divider tightening for grand_total, and marks_in_words companion extraction.
    """

    @staticmethod
    def crop_padded_box(
        img: np.ndarray,
        xyxy: Tuple[float, float, float, float],
        padding_ratio: float = 0.05,
    ) -> np.ndarray:
        """Extracts a bounding box with proportional padding clamped to image bounds."""
        img_h, img_w = img.shape[:2]
        x1, y1, x2, y2 = xyxy
        bw = max(1.0, x2 - x1)
        bh = max(1.0, y2 - y1)
        px = int(bw * padding_ratio)
        py = int(bh * padding_ratio)

        cx1 = max(0, int(x1 - px))
        cy1 = max(0, int(y1 - py))
        cx2 = min(img_w, int(x2 + px))
        cy2 = min(img_h, int(y2 + py))

        return img[cy1:cy2, cx1:cx2]

    @staticmethod
    def get_grand_total_and_companion_crops(
        img: np.ndarray,
        gt_box_xyxy: Optional[Tuple[float, float, float, float]] = None,
        existing_gt_crop: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Generates the tightened grand_total crop (right of the vertical red divider)
        and the deterministic marks_in_words companion crop immediately to the left
        of grand_total with vertical padding for cursive ascenders and descenders.
        """
        img_h, img_w = img.shape[:2]
        used_fallback = False

        if gt_box_xyxy is not None:
            x1, y1, x2, y2 = [float(v) for v in gt_box_xyxy]
            if not (0.62 * img_h <= y1 <= 0.88 * img_h and x1 >= 0.40 * img_w):
                x1, y1, x2, y2 = get_grand_total_fallback_box(img_w, img_h)
                used_fallback = True
        else:
            x1, y1, x2, y2 = get_grand_total_fallback_box(img_w, img_h)
            used_fallback = True

        bh = max(80.0, y2 - y1)

        if existing_gt_crop is not None and existing_gt_crop.size > 0:
            gt_crop = existing_gt_crop
        else:
            gt_y1 = max(0, int(y1 - 0.08 * bh))
            gt_y2 = min(img_h, int(y2 + 0.12 * bh))
            gt_x1 = max(0, int(x1))
            gt_x2 = min(img_w, int(x2))
            gt_crop = img[gt_y1:gt_y2, gt_x1:gt_x2]

        cut_x, ratio = detect_red_divider_x(gt_crop)
        gt_tight = gt_crop[:, cut_x:] if gt_crop.size > 0 else gt_crop

        mw_y1 = max(0, int(y1 - 0.20 * bh))
        mw_y2 = min(img_h, int(y2 + 0.45 * bh))
        mw_x1 = max(0, int(0.21 * img_w))
        mw_x2 = max(mw_x1 + 1, min(img_w, int(x1)))
        mw_crop = img[mw_y1:mw_y2, mw_x1:mw_x2]

        return {
            "grand_total_tightened": gt_tight,
            "marks_in_words": mw_crop,
            "divider_ratio": round(ratio, 4),
            "used_fallback_box": used_fallback,
        }
