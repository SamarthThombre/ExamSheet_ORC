"""
QuestionMarksExtractor — geometric/table-based extraction of per-question marks
from the 'Total' column of the exam cover sheet question table.

Design principles:
  - Completely additive; does NOT touch any existing extraction logic.
  - No YOLO retraining: uses geometric analysis of the cover-sheet layout.
  - Guided by the grand_total bounding box (when detected) to cleanly isolate question rows.
  - Null marks (not zero) for unreadable OCR rows.
  - Validates sum(question_marks) == grand_total and sets needs_review on mismatch.
  - Number of questions is NOT assumed to be fixed (auto-detected via table rows).
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple, Dict, Any

import cv2
import numpy as np

logger = logging.getLogger("ocr.postprocessing.question_marks")


# ---------------------------------------------------------------------------
# Geometric constants calibrated from cover sheet dataset
# ---------------------------------------------------------------------------
# Fraction of image height where table search begins (above header row)
TABLE_Y_START_FRAC = 0.48
# Fallback end fraction when grand_total box is not detected
TABLE_Y_END_FALLBACK_FRAC = 0.75

# Total column horizontal fraction boundaries (rightmost column)
TOTAL_COL_X_START_FRAC = 0.78
TOTAL_COL_X_END_FRAC   = 0.98

# Minimum row height in pixels to reject line noise
MIN_ROW_HEIGHT_PX = 15

# OCR confidence threshold below which marks are flagged uncertain
OCR_CONF_THRESH = 0.30

# Regex pattern for valid numeric marks (integers or decimals e.g. 0, 1, 5.5, 05.5)
_MARKS_PATTERN = re.compile(r"^(\d{1,3}(?:\.\d{1,2})?)$")

# Common cursive zero representations produced by OCR on handwritten '00' or '0'
_ZERO_TOKENS = {"cso", "so", "cs", "co", "oo", "o", "0", "00", "000", "cso-", "so-", "oo-"}


def _parse_marks_text(raw_text: str) -> Tuple[Optional[float], str]:
    """
    Parses raw OCR text from a 'Total' cell into a numeric marks value.

    Returns:
        (marks_value, status)
        marks_value: float if parseable, None if unreadable
        status: 'ok' | 'uncertain'
    """
    text = raw_text.strip()
    if not text:
        return None, "uncertain"

    # Strip tally marks and boundary noise
    cleaned = text.strip("-_=~/\\|:; ").rstrip("-_=~/\\|:; ")
    if not cleaned:
        return None, "uncertain"

    # Check for recognized cursive zero loops (e.g. connected '00' handwritten loops)
    if cleaned.lower() in _ZERO_TOKENS:
        return 0.0, "ok"

    # Normalize common digit and decimal confusions in exam handwriting
    norm = cleaned.replace(":", ".").replace(",", ".").replace(" ", "")
    norm = norm.replace("S", "5").replace("s", "5")
    norm = norm.replace("O", "0").replace("o", "0")
    norm = norm.replace("l", "1").replace("I", "1")
    norm = norm.replace("B", "8")
    norm = norm.rstrip("-_=~/\\|:;")

    m = _MARKS_PATTERN.match(norm)
    if m:
        try:
            val = float(m.group(1))
            return val, "ok"
        except ValueError:
            pass

    return None, "uncertain"


def _detect_row_boundaries_from_bgr(
    img_bgr: np.ndarray,
    y_start: int,
    y_end: int,
) -> List[int]:
    """
    Detects horizontal red table-row divider y-positions within [y_start, y_end].
    Uses color-filtered redness profile with morphological smoothing.
    """
    roi = img_bgr[y_start:y_end, :]
    h, w = roi.shape[:2]
    if h < 10 or w < 10:
        return []

    # Calculate redness profile
    b, g, r = cv2.split(roi.astype(np.float32))
    redness = np.clip(r - 0.5 * (g + b), 0, 255).astype(np.uint8)

    x_margin = max(1, int(0.10 * w))
    row_redness = redness[:, x_margin : w - x_margin].mean(axis=1)

    max_r = float(np.max(row_redness))
    if max_r < 10.0:
        return []

    # Detect lines where redness peaks above adaptive threshold
    row_norm = (row_redness / max_r * 255).astype(np.uint8)
    line_mask = (row_norm > (0.35 * 255)).astype(np.uint8)

    kernel = np.ones((3,), np.uint8)
    line_mask_closed = cv2.morphologyEx(
        line_mask.reshape(-1, 1), cv2.MORPH_CLOSE, kernel.reshape(-1, 1)
    ).flatten()

    line_centers = []
    in_run = False
    run_start = 0
    for y in range(len(line_mask_closed)):
        if line_mask_closed[y] and not in_run:
            in_run = True
            run_start = y
        elif not line_mask_closed[y] and in_run:
            in_run = False
            line_centers.append(y_start + (run_start + y) // 2)
    if in_run:
        line_centers.append(y_start + (run_start + len(line_mask_closed)) // 2)

    return _merge_close_lines(line_centers, min_gap=12)


def _merge_close_lines(lines: List[int], min_gap: int = 12) -> List[int]:
    """Merges detected line positions within min_gap pixels of each other."""
    if not lines:
        return []
    merged = [lines[0]]
    for y in lines[1:]:
        if y - merged[-1] < min_gap:
            merged[-1] = (merged[-1] + y) // 2
        else:
            merged.append(y)
    return merged


class QuestionMarksExtractor:
    """
    Extracts individual question marks from the 'Total' column of the question table.
    """

    def __init__(self, ocr_engine):
        self.ocr_engine = ocr_engine

    def extract_question_marks(
        self,
        img_bgr: np.ndarray,
        grand_total_box_xyxy: Optional[Tuple[float, float, float, float]] = None,
        grand_total_value: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Extracts per-question marks from the Total column of the question table.

        Args:
            img_bgr:              Full exam cover-sheet image (BGR format).
            grand_total_box_xyxy: Bounding box of grand_total if detected by YOLO.
            grand_total_value:    Extracted grand total marks for sum consistency check.

        Returns a dictionary containing:
            question_marks:  List of dicts: {question_no, marks, raw_text, confidence, status}
            sum_extracted:   Sum of successfully parsed question marks (or None)
            sum_matches_gt:  Boolean consistency check with grand_total
            needs_review:    True if sum mismatches or unreadable rows exist
            uncertain_count: Count of rows with unreadable marks
            method:          'geometric_table'
            debug_info:      Internal diagnostic metadata
        """
        if img_bgr is None or img_bgr.size == 0:
            return self._empty_result("invalid_image")

        img_h, img_w = img_bgr.shape[:2]

        # 1. Determine vertical search range for question table
        y_start = max(0, int(TABLE_Y_START_FRAC * img_h))

        if grand_total_box_xyxy is not None:
            gt_y1 = float(grand_total_box_xyxy[1])
            # The grand_total box top boundary marks the bottom of the question table
            y_end = min(img_h, int(gt_y1 + 25))
        else:
            y_end = min(img_h, int(TABLE_Y_END_FALLBACK_FRAC * img_h))

        if y_end <= y_start:
            return self._empty_result("invalid_geometry")

        # 2. Detect table divider lines within the table ROI
        lines = _detect_row_boundaries_from_bgr(img_bgr, y_start, y_end)

        # Build row intervals
        intervals = []
        for i in range(len(lines) - 1):
            t, b = lines[i], lines[i + 1]
            if b - t >= MIN_ROW_HEIGHT_PX:
                intervals.append((t, b))

        # 3. Filter question rows:
        # If at least 2 intervals detected, interval[0] is the header row ('Q.No. ... Total')
        # All subsequent intervals up to the grand_total border are question rows
        if len(intervals) >= 2:
            question_intervals = intervals[1:]
        elif len(intervals) == 1:
            question_intervals = intervals
        else:
            # Fallback uniform 5 rows between y_start and y_end
            row_h = (y_end - y_start) / 6.0
            question_intervals = [
                (int(y_start + (i + 1) * row_h), int(y_start + (i + 2) * row_h))
                for i in range(5)
            ]

        # 4. Total column horizontal range
        x1 = max(0, int(TOTAL_COL_X_START_FRAC * img_w))
        x2 = min(img_w, int(TOTAL_COL_X_END_FRAC * img_w))

        # 5. Extract and OCR each question cell
        question_marks = []
        for q_idx, (t, b) in enumerate(question_intervals, start=1):
            pad_v = max(1, int((b - t) * 0.05))
            crop = img_bgr[t + pad_v : b - pad_v, x1:x2]

            if crop.size == 0 or crop.shape[0] < 5 or crop.shape[1] < 5:
                question_marks.append({
                    "question_no": q_idx,
                    "marks": None,
                    "raw_text": "",
                    "confidence": None,
                    "status": "uncertain",
                })
                continue

            raw_txt, conf = self.ocr_engine.ocr_crop(crop)
            marks_val, status = _parse_marks_text(raw_txt)

            if conf < OCR_CONF_THRESH and marks_val is not None:
                marks_val = None
                status = "uncertain"

            question_marks.append({
                "question_no": q_idx,
                "marks": marks_val,
                "raw_text": raw_txt.strip(),
                "confidence": round(conf, 3) if conf else None,
                "status": status,
            })

        # 6. Validate sum against grand_total
        readable_marks = [qm["marks"] for qm in question_marks if qm["marks"] is not None]
        uncertain_count = sum(1 for qm in question_marks if qm["status"] == "uncertain")

        sum_extracted = round(sum(readable_marks), 2) if readable_marks else None
        sum_matches_gt: Optional[bool] = None
        needs_review = uncertain_count > 0

        if grand_total_value is not None and sum_extracted is not None:
            try:
                gt_float = float(grand_total_value)
                sum_matches_gt = abs(sum_extracted - gt_float) <= 0.01
                if not sum_matches_gt:
                    needs_review = True
                    logger.info(
                        f"Question marks sum ({sum_extracted}) does not match grand_total ({gt_float}) -> needs_review=True"
                    )
            except (ValueError, TypeError):
                sum_matches_gt = None

        return {
            "question_marks": question_marks,
            "sum_extracted": sum_extracted,
            "sum_matches_gt": sum_matches_gt,
            "needs_review": needs_review,
            "uncertain_count": uncertain_count,
            "method": "geometric_table",
            "debug_info": {
                "y_start": y_start,
                "y_end": y_end,
                "x_range": [x1, x2],
                "lines_detected": len(lines),
                "question_rows_found": len(question_intervals),
            },
        }

    @staticmethod
    def _empty_result(reason: str) -> Dict[str, Any]:
        return {
            "question_marks": [],
            "sum_extracted": None,
            "sum_matches_gt": None,
            "needs_review": False,
            "uncertain_count": 0,
            "method": "geometric_table",
            "debug_info": {"error": reason},
        }
