"""
ocr_v2.table: Dual-anchor table detectors with configuration-driven parameters
and fast downscaled Hough rotation deskew for Format A and Format B.
"""

from typing import List, Tuple, Dict, Any, Optional
from pathlib import Path
import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class DualAnchorTableDetector:
    """
    Configuration-driven table detector for exam cover sheets (Format A and Format B).
    Uses top header anchor and bottom grand-total anchor.
    Local deskew via Hough transform restricted to +/- 10 degrees on downscaled ROI.
    """

    def __init__(self, template_cache: Optional[Dict[str, np.ndarray]] = None):
        self.templates: Dict[str, np.ndarray] = template_cache or {}

    def _get_template(self, rel_path: str) -> Optional[np.ndarray]:
        if rel_path in self.templates:
            return self.templates[rel_path]
        full_path = PROJECT_ROOT / rel_path
        if full_path.exists():
            tmpl = cv2.imread(str(full_path))
            self.templates[rel_path] = tmpl
            return tmpl
        return None

    def estimate_rotation(self, img_can: np.ndarray, hough_cfg: Dict[str, Any]) -> float:
        """
        Estimates table rotation angle using downscaled ROI (longest side <= max_side)
        and HoughLines restricted to angle range [min_theta, max_theta].
        """
        h, w = img_can.shape[:2]
        roi_frac = hough_cfg.get("roi", [0.35, 0.85, 0.60, 0.98])
        y1, y2 = int(roi_frac[0] * h), int(roi_frac[1] * h)
        x1, x2 = int(roi_frac[2] * w), int(roi_frac[3] * w)
        roi = img_can[y1:y2, x1:x2]
        if roi.size == 0:
            return 0.0

        rh, rw = roi.shape[:2]
        max_side = hough_cfg.get("max_side", 800)
        scale = max_side / float(max(rh, rw)) if max(rh, rw) > max_side else 1.0
        if scale < 1.0:
            small_roi = cv2.resize(roi, (int(round(rw * scale)), int(round(rh * scale))))
        else:
            small_roi = roi

        gray = cv2.cvtColor(small_roi, cv2.COLOR_BGR2GRAY) if small_roi.ndim == 3 else small_roi
        c_low = hough_cfg.get("canny_low", 50)
        c_high = hough_cfg.get("canny_high", 150)
        edges = cv2.Canny(gray, c_low, c_high)

        min_theta = np.deg2rad(hough_cfg.get("min_theta_deg", 80.0))
        max_theta = np.deg2rad(hough_cfg.get("max_theta_deg", 100.0))
        threshold = hough_cfg.get("threshold", 80)

        lines = cv2.HoughLines(
            edges, 1, np.pi / 1800, threshold,
            min_theta=min_theta, max_theta=max_theta
        )
        if lines is None:
            return 0.0

        angles = [-(np.rad2deg(theta) - 90.0) for theta in lines[:, 0, 1]]
        if not angles:
            return 0.0
        return float(np.median(angles))

    def detect_format_a(
        self,
        c_can: np.ndarray,
        q_cfg: Dict[str, Any]
    ) -> Tuple[List[np.ndarray], List[Tuple[int, int, int, int]], Dict[str, Any]]:
        """
        Format A dual-anchor extraction with horizontal & vertical snapping.
        """
        h, w = c_can.shape[:2]
        hough_cfg = q_cfg.get("hough_rotation", {})
        est_rot = self.estimate_rotation(c_can, hough_cfg)

        cx, cy = w / 2.0, h * 0.60
        M = cv2.getRotationMatrix2D((cx, cy), -est_rot, 1.0)
        deskewed = cv2.warpAffine(c_can, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

        # 1. Top Header Anchor
        tmpl_hdr = self._get_template(q_cfg["templates"]["header"])
        if tmpl_hdr is None:
            return [], [], {"status": "UNAVAILABLE", "reason": "MISSING_HEADER_TEMPLATE"}
        th_h, th_w = tmpl_hdr.shape[:2]
        win_hdr_cfg = q_cfg["search_windows"]["header"]
        win_hdr = deskewed[win_hdr_cfg[0]:win_hdr_cfg[1], win_hdr_cfg[2]:min(w, win_hdr_cfg[3])]
        res_hdr = cv2.matchTemplate(win_hdr, tmpl_hdr, cv2.TM_CCOEFF_NORMED)
        _, mv_hdr, _, ml_hdr = cv2.minMaxLoc(res_hdr)
        if mv_hdr < q_cfg["thresholds"]["header_min_val"]:
            return [], [], {"status": "UNAVAILABLE", "reason": "HEADER_ANCHOR_NOT_FOUND", "score": float(mv_hdr)}
        hdr_x = win_hdr_cfg[2] + ml_hdr[0]
        hdr_y = win_hdr_cfg[0] + ml_hdr[1]

        # 2. Grand Total Anchor
        tmpl_gt = self._get_template(q_cfg["templates"]["grand_total"])
        if tmpl_gt is None:
            return [], [], {"status": "UNAVAILABLE", "reason": "MISSING_GT_TEMPLATE"}
        win_gt_cfg = q_cfg["search_windows"]["grand_total"]
        gy1, gy2 = int(win_gt_cfg[0] * h), int(win_gt_cfg[1] * h)
        gx1, gx2 = int(win_gt_cfg[2] * w), int(win_gt_cfg[3] * w)
        win_gt = deskewed[gy1:gy2, gx1:gx2]
        res_gt = cv2.matchTemplate(win_gt, tmpl_gt, cv2.TM_CCOEFF_NORMED)
        _, mv_gt, _, ml_gt = cv2.minMaxLoc(res_gt)
        if mv_gt < q_cfg["thresholds"]["gt_min_val"]:
            return [], [], {"status": "UNAVAILABLE", "reason": "GT_ANCHOR_NOT_FOUND", "score": float(mv_gt)}
        gt_x = gx1 + ml_gt[0]
        gt_y = gy1 + ml_gt[1]

        # Span between bottom of header and top of grand total row
        top_line_nom = hdr_y + th_h + 10
        bot_line_nom = gt_y
        span = bot_line_nom - top_line_nom
        span_min = q_cfg["nominal"]["span_min"]
        span_max = q_cfg["nominal"]["span_max"]
        if span < span_min or span > span_max:
            pitch = float(q_cfg["nominal"]["pitch"])
            bot_line_nom = top_line_nom + q_cfg["row_count"] * pitch
        else:
            pitch = span / float(q_cfg["row_count"])

        # Vertical line snapping for Total column
        col_x1_nom = hdr_x + q_cfg["nominal"]["col_x1_offset"]
        col_x2_nom = hdr_x + q_cfg["nominal"]["col_x2_offset"]
        v_tol = q_cfg["snapping_tolerances"]["v_line_tol_px"]

        roi_v = deskewed[max(0, int(top_line_nom)):min(h, int(bot_line_nom)), max(0, col_x1_nom - 30):min(w, col_x2_nom + 30)]
        snapped_x1, snapped_x2 = col_x1_nom, col_x2_nom
        if roi_v.size > 0:
            gray_v = cv2.cvtColor(roi_v, cv2.COLOR_BGR2GRAY)
            th_v = cv2.adaptiveThreshold(gray_v, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 5)
            kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
            lines_v = cv2.morphologyEx(th_v, cv2.MORPH_OPEN, kernel_v)
            proj_v = np.sum(lines_v > 0, axis=0)
            offset_base = max(0, col_x1_nom - 30)

            rel_x1 = col_x1_nom - offset_base
            win_x1 = proj_v[max(0, rel_x1 - v_tol):min(len(proj_v), rel_x1 + v_tol + 1)]
            if len(win_x1) > 0 and max(win_x1) > 30:
                snapped_x1 = offset_base + max(0, rel_x1 - v_tol) + int(np.argmax(win_x1))

            rel_x2 = col_x2_nom - offset_base
            win_x2 = proj_v[max(0, rel_x2 - v_tol):min(len(proj_v), rel_x2 + v_tol + 1)]
            if len(win_x2) > 0 and max(win_x2) > 30:
                snapped_x2 = offset_base + max(0, rel_x2 - v_tol) + int(np.argmax(win_x2))

        # Horizontal row divider snapping
        h_frac = q_cfg["snapping_tolerances"]["h_pitch_fraction"]
        q_lines = []
        roi_h = deskewed[max(0, int(top_line_nom - 25)):min(h, int(bot_line_nom + 25)), max(0, snapped_x1 - 100):min(w, snapped_x2 + 20)]
        if roi_h.size > 0:
            gray_h = cv2.cvtColor(roi_h, cv2.COLOR_BGR2GRAY)
            th_h_img = cv2.adaptiveThreshold(gray_h, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 5)
            kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
            lines_h = cv2.morphologyEx(th_h_img, cv2.MORPH_OPEN, kernel_h)
            proj_h = np.sum(lines_h > 0, axis=1)
            base_y = max(0, int(top_line_nom - 25))

            for j in range(q_cfg["row_count"] + 1):
                nom_y = top_line_nom + j * pitch
                rel_y = int(round(nom_y - base_y))
                snap_win = int(round(h_frac * pitch))
                y_start = max(0, rel_y - snap_win)
                y_end = min(len(proj_h), rel_y + snap_win + 1)
                if y_end > y_start:
                    sub_proj = proj_h[y_start:y_end]
                    if len(sub_proj) > 0 and max(sub_proj) > 40:
                        best_y = base_y + y_start + int(np.argmax(sub_proj))
                        q_lines.append(best_y)
                    else:
                        q_lines.append(int(round(nom_y)))
                else:
                    q_lines.append(int(round(nom_y)))
        else:
            q_lines = [int(round(top_line_nom + j * pitch)) for j in range(q_cfg["row_count"] + 1)]

        # Check divider consistency
        min_h_px = q_cfg["snapping_tolerances"]["min_row_height_px"]
        for j in range(q_cfg["row_count"]):
            if q_lines[j+1] - q_lines[j] < min_h_px:
                return [], [], {"status": "UNAVAILABLE", "reason": "ROW_DIVIDER_INCONSISTENT", "q_lines": q_lines}

        crops = []
        bboxes = []
        for j in range(q_cfg["row_count"]):
            cy1 = q_lines[j] + 5
            cy2 = q_lines[j+1] - 5
            cx1 = snapped_x1 + 8
            cx2 = snapped_x2 - 8
            crop = deskewed[max(0, cy1):min(h, cy2), max(0, cx1):min(w, cx2)]
            crops.append(crop)
            bboxes.append((cx1, cy1, cx2, cy2))

        gc_ok, gc_reason, gc_details = check_grid_consistency(
            q_lines, gt_y, q_cfg.get("grid_consistency")
        )
        meta = {
            "status": "OK" if gc_ok else "POOR_GRID_ALIGNMENT",
            "reason": "OK" if gc_ok else gc_reason,
            "poor_grid_alignment": not gc_ok,
            "grid_consistency": gc_details,
            "mv_hdr": float(mv_hdr),
            "mv_gt": float(mv_gt),
            "hdr_pt": (hdr_x, hdr_y),
            "gt_pt": (gt_x, gt_y),
            "pitch": float(pitch),
            "span": float(span),
            "snapped_x": (snapped_x1, snapped_x2),
            "q_lines": q_lines,
            "est_rot": est_rot
        }
        return crops, bboxes, meta

    def detect_format_b(
        self,
        c_can: np.ndarray,
        q_cfg: Dict[str, Any]
    ) -> Tuple[List[np.ndarray], List[Tuple[int, int, int, int]], Dict[str, Any]]:
        """
        Format B dual-anchor extraction with morphological snapping.
        """
        h, w = c_can.shape[:2]
        hough_cfg = q_cfg.get("hough_rotation", {})
        est_rot = self.estimate_rotation(c_can, hough_cfg)

        cx, cy = w / 2.0, h * 0.55
        M = cv2.getRotationMatrix2D((cx, cy), -est_rot, 1.0)
        deskewed = cv2.warpAffine(c_can, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

        # 1. Header search
        tmpl_hdr = self._get_template(q_cfg["templates"]["header"])
        if tmpl_hdr is None:
            return [], [], {"status": "UNAVAILABLE", "reason": "MISSING_HEADER_TEMPLATE"}
        th_h, th_w = tmpl_hdr.shape[:2]
        win_hdr_cfg = q_cfg["search_windows"]["header"]
        hy1, hy2 = int(win_hdr_cfg[0] * h), int(win_hdr_cfg[1] * h)
        hx1, hx2 = int(win_hdr_cfg[2] * w), int(win_hdr_cfg[3] * w)
        win_hdr = deskewed[hy1:hy2, hx1:hx2]
        res_hdr = cv2.matchTemplate(win_hdr, tmpl_hdr, cv2.TM_CCOEFF_NORMED)
        _, mv_hdr, _, ml_hdr = cv2.minMaxLoc(res_hdr)
        if mv_hdr < q_cfg["thresholds"]["header_min_val"]:
            return [], [], {"status": "UNAVAILABLE", "reason": "HEADER_ANCHOR_NOT_FOUND", "score": float(mv_hdr)}
        hdr_x = hx1 + ml_hdr[0]
        hdr_y = hy1 + ml_hdr[1]

        # 2. GT search
        tmpl_gt = self._get_template(q_cfg["templates"]["grand_total"])
        if tmpl_gt is None:
            return [], [], {"status": "UNAVAILABLE", "reason": "MISSING_GT_TEMPLATE"}
        win_gt_cfg = q_cfg["search_windows"]["grand_total"]
        gy1, gy2 = int(win_gt_cfg[0] * h), int(win_gt_cfg[1] * h)
        gx1, gx2 = int(win_gt_cfg[2] * w), int(win_gt_cfg[3] * w)
        win_gt = deskewed[gy1:gy2, gx1:gx2]
        res_gt = cv2.matchTemplate(win_gt, tmpl_gt, cv2.TM_CCOEFF_NORMED)
        _, mv_gt, _, ml_gt = cv2.minMaxLoc(res_gt)
        if mv_gt < q_cfg["thresholds"]["gt_min_val"]:
            return [], [], {"status": "UNAVAILABLE", "reason": "GT_ANCHOR_NOT_FOUND", "score": float(mv_gt)}
        gt_x = gx1 + ml_gt[0]
        gt_y = gy1 + ml_gt[1]

        span = gt_y - (hdr_y + th_h)

        # Vertical line snapping for Total column
        col_x1_nom = hdr_x + q_cfg["nominal"]["col_x1_offset"]
        col_x2_nom = hdr_x + q_cfg["nominal"]["col_x2_offset"]
        v_tol = q_cfg["snapping_tolerances"]["v_line_tol_px"]

        roi_v = deskewed[hdr_y:min(h, gt_y), max(0, col_x1_nom - 30):min(w, col_x2_nom + 30)]
        if roi_v.size > 0:
            gray_v = cv2.cvtColor(roi_v, cv2.COLOR_BGR2GRAY)
            th_v = cv2.adaptiveThreshold(gray_v, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 5)
            kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
            lines_v = cv2.morphologyEx(th_v, cv2.MORPH_OPEN, kernel_v)
            proj_v = np.sum(lines_v > 0, axis=0)

            offset_base = max(0, col_x1_nom - 30)
            rel_x1 = col_x1_nom - offset_base
            win_x1 = proj_v[max(0, rel_x1 - v_tol):min(len(proj_v), rel_x1 + v_tol + 1)]
            snapped_x1 = offset_base + max(0, rel_x1 - v_tol) + int(np.argmax(win_x1)) if len(win_x1) > 0 and max(win_x1) > 50 else col_x1_nom

            rel_x2 = col_x2_nom - offset_base
            win_x2 = proj_v[max(0, rel_x2 - v_tol):min(len(proj_v), rel_x2 + v_tol + 1)]
            snapped_x2 = offset_base + max(0, rel_x2 - v_tol) + int(np.argmax(win_x2)) if len(win_x2) > 0 and max(win_x2) > 50 else col_x2_nom
        else:
            snapped_x1, snapped_x2 = col_x1_nom, col_x2_nom

        # Horizontal line snapping
        top_line_nom = hdr_y + th_h
        bot_line_nom = gt_y

        roi_h = deskewed[max(0, top_line_nom - 20):min(h, bot_line_nom + 20), max(0, snapped_x1 - 120):min(w, snapped_x2 + 20)]
        q_lines = None
        if roi_h.size > 0:
            gray_h = cv2.cvtColor(roi_h, cv2.COLOR_BGR2GRAY)
            th_h_img = cv2.adaptiveThreshold(gray_h, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 5)
            kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
            lines_h = cv2.morphologyEx(th_h_img, cv2.MORPH_OPEN, kernel_h)
            proj_h = np.sum(lines_h > 0, axis=1)

            base_y = max(0, top_line_nom - 20)
            h_peaks = []
            for y in range(3, len(proj_h)-3):
                if proj_h[y] > 50 and proj_h[y] >= max(proj_h[y-3:y+4]):
                    h_peaks.append(base_y + y)

            merged = []
            for p in h_peaks:
                if not merged:
                    merged.append(p)
                else:
                    if p - merged[-1] >= 40:
                        merged.append(p)
                    else:
                        if proj_h[p - base_y] > proj_h[merged[-1] - base_y]:
                            merged[-1] = p

            d_min = q_cfg["snapping_tolerances"]["h_diff_min"]
            d_max = q_cfg["snapping_tolerances"]["h_diff_max"]
            for i in range(len(merged) - q_cfg["row_count"]):
                diffs = [merged[i+j+1] - merged[i+j] for j in range(q_cfg["row_count"])]
                if all(d_min <= d <= d_max for d in diffs):
                    q_lines = merged[i : i + q_cfg["row_count"] + 1]
                    break

        if q_lines is None:
            pitch = float(q_cfg["nominal"]["pitch"])
            q_lines = [int(round(top_line_nom + j * pitch)) for j in range(q_cfg["row_count"] + 1)]

        crops = []
        bboxes = []
        for j in range(q_cfg["row_count"]):
            cy1 = q_lines[j] + 4
            cy2 = q_lines[j+1] - 3
            crop = deskewed[cy1:cy2, snapped_x1:snapped_x2]
            crops.append(crop)
            bboxes.append((snapped_x1, cy1, snapped_x2, cy2))

        gc_ok, gc_reason, gc_details = check_grid_consistency(
            q_lines, gt_y, q_cfg.get("grid_consistency")
        )
        meta = {
            "status": "OK" if gc_ok else "POOR_GRID_ALIGNMENT",
            "reason": "OK" if gc_ok else gc_reason,
            "poor_grid_alignment": not gc_ok,
            "grid_consistency": gc_details,
            "est_rot": est_rot,
            "mv_hdr": float(mv_hdr),
            "mv_gt": float(mv_gt),
            "hdr_pt": (hdr_x, hdr_y),
            "gt_pt": (gt_x, gt_y),
            "span": float(span),
            "snapped_x": (snapped_x1, snapped_x2),
            "q_lines": q_lines
        }
        return crops, bboxes, meta

    def extract_table_cells(
        self,
        c_can: np.ndarray,
        format_id: str,
        format_config: Dict[str, Any]
    ) -> Tuple[List[np.ndarray], List[Tuple[int, int, int, int]], Dict[str, Any]]:
        """
        Dispatches table cell extraction based on format configuration.
        """
        q_cfg = format_config.get("fields", {}).get("question_marks", {})
        if not q_cfg or q_cfg.get("status") != "active":
            return [], [], {"status": "INACTIVE"}

        if format_id == "format_original":
            return self.detect_format_a(c_can, q_cfg)
        elif format_id == "format_v2":
            return self.detect_format_b(c_can, q_cfg)
        else:
            return [], [], {"status": "UNAVAILABLE", "reason": "UNKNOWN_FORMAT"}


def check_grid_consistency(
    q_lines: List[int],
    gt_y: int,
    gc_cfg: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Generic grid-consistency check (Milestone 7c Part 3):
    Checks whether:
    1. The pitch of each row is within max_pitch_dev_px of the median row pitch.
    2. The bottom of row 5 (q_lines[5]) meets the top of the Grand Total anchor (gt_y) within max_bottom_gap_px.
    On failure returns (False, "POOR_GRID_ALIGNMENT", details).
    """
    if not gc_cfg or not gc_cfg.get("enabled", True):
        return True, "OK", {}
    if len(q_lines) < 6:
        return False, "POOR_GRID_ALIGNMENT", {"reason": "INSUFFICIENT_LINES"}

    pitches = [int(q_lines[i + 1] - q_lines[i]) for i in range(5)]
    med_pitch = float(np.median(pitches))
    max_pitch_dev = float(max(abs(p - med_pitch) for p in pitches))
    max_pitch_dev_tol = float(gc_cfg.get("max_pitch_dev_px", 35.0))

    expected_bot_offset = float(gc_cfg.get("expected_bottom_offset_px", 0.0))
    bot_gap = float(abs((gt_y - q_lines[5]) - expected_bot_offset))
    max_bot_gap_tol = float(gc_cfg.get("max_bottom_gap_px", 40.0))
    check_bot_gap = bool(gc_cfg.get("check_bottom_gap", True))
    require_both = bool(gc_cfg.get("require_both", True))

    pitch_bad = max_pitch_dev > max_pitch_dev_tol
    gap_bad = check_bot_gap and (bot_gap > max_bot_gap_tol)

    if require_both and check_bot_gap:
        failed = (pitch_bad and gap_bad) or (max_pitch_dev > 50.0)
    else:
        failed = pitch_bad or gap_bad

    details = {
        "pitches": pitches,
        "median_pitch": med_pitch,
        "max_pitch_dev": max_pitch_dev,
        "max_pitch_dev_tol": max_pitch_dev_tol,
        "bot_gap": bot_gap,
        "max_bot_gap_tol": max_bot_gap_tol,
        "pitch_bad": pitch_bad,
        "gap_bad": gap_bad,
    }
    if failed:
        return False, "POOR_GRID_ALIGNMENT", details
    return True, "OK", details

