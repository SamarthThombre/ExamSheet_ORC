"""
ocr_v2.fields: Field cropping from aligned canonical cover sheets.
Anchors subject_code ROI relative to detected enrolment comb band with moderate margin.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
import cv2
import numpy as np

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


@dataclass
class FieldCropResult:
    field_name: str
    crop: np.ndarray
    roi_pixels: Tuple[int, int, int, int]           # (x1, y1, x2, y2)
    roi_fraction: Tuple[float, float, float, float]  # (x1, y1, x2, y2)
    alignment_score: float
    status: str                                      # "OK" | "ROI_TO_BE_MEASURED" | "FALLBACK"


def extract_total_crop_tmpl(
    aligned_img: np.ndarray,
    format_id: str,
    tmpl_a: Optional[np.ndarray] = None,
    tmpl_b: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, float, Tuple[int, int, int, int]]:
    """
    Extracts handwritten total marks digit crop using template matching.
    Returns: (crop, match_score, (x1, y1, x2, y2))
    """
    h, w = aligned_img.shape[:2]
    if format_id == "format_original":
        if tmpl_a is None:
            tmpl_path = TEMPLATE_DIR / "tmpl_gt_a.png"
            tmpl_a = cv2.imread(str(tmpl_path)) if tmpl_path.exists() else None
        if tmpl_a is None:
            c = aligned_img[int(0.735 * h):int(0.800 * h), int(0.650 * w):min(w, int(0.995 * w))]
            return c, 0.0, (int(0.650 * w), int(0.735 * h), min(w, int(0.995 * w)), int(0.800 * h))
        search_y1, search_y2 = int(0.70 * h), int(0.90 * h)
        search_x1, search_x2 = int(0.35 * w), int(0.85 * w)
        search = aligned_img[search_y1:search_y2, search_x1:search_x2]
        res = cv2.matchTemplate(search, tmpl_a, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        tx, ty = max_loc
        th, tw = tmpl_a.shape[:2]
        abs_x = search_x1 + tx
        abs_y = search_y1 + ty
        cy1, cy2 = max(0, abs_y - 6), min(h, abs_y + th + 12)
        cx1, cx2 = abs_x + tw + 2, min(w, int(0.995 * w))
        crop = aligned_img[cy1:cy2, cx1:cx2]
        return crop, float(max_val), (cx1, cy1, cx2, cy2)
    else:
        if tmpl_b is None:
            tmpl_path = TEMPLATE_DIR / "tmpl_gt_b.png"
            tmpl_b = cv2.imread(str(tmpl_path)) if tmpl_path.exists() else None
        if tmpl_b is None:
            c = aligned_img[int(0.680 * h):int(0.780 * h), int(0.380 * w):int(0.580 * w)]
            return c, 0.0, (int(0.380 * w), int(0.680 * h), int(0.580 * w), int(0.780 * h))
        search_y1, search_y2 = int(0.68 * h), int(0.80 * h)
        search_x1, search_x2 = int(0.18 * w), int(0.50 * w)
        search = aligned_img[search_y1:search_y2, search_x1:search_x2]
        res = cv2.matchTemplate(search, tmpl_b, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        tx, ty = max_loc
        th, tw = tmpl_b.shape[:2]
        abs_x = search_x1 + tx
        abs_y = search_y1 + ty
        cy1, cy2 = max(0, abs_y - 6), min(h, abs_y + th + 12)
        cx1, cx2 = abs_x + tw + 2, min(w, abs_x + tw + 250)
        crop = aligned_img[cy1:cy2, cx1:cx2]
        return crop, float(max_val), (cx1, cy1, cx2, cy2)


class FieldCropper:
    """Extracts field crops from aligned canonical cover sheets."""

    def __init__(self, moderate_margin_h: float = 0.040):
        # Moderate margin around subject code line (~180-220 px height at 1600 canonical width)
        self.moderate_margin_h = moderate_margin_h
        tmpl_a_path = TEMPLATE_DIR / "tmpl_gt_a.png"
        tmpl_b_path = TEMPLATE_DIR / "tmpl_gt_b.png"
        self.tmpl_a = cv2.imread(str(tmpl_a_path)) if tmpl_a_path.exists() else None
        self.tmpl_b = cv2.imread(str(tmpl_b_path)) if tmpl_b_path.exists() else None

    def crop_fields(
        self,
        aligned_img: np.ndarray,
        format_id: str,
        format_config: Dict[str, Any],
        comb_box: Optional[Tuple[Tuple[float, float], Tuple[float, float], float]] = None,
        alignment_score: float = 1.0,
    ) -> Dict[str, FieldCropResult]:
        """
        Crops all configured fields from the aligned page.
        Positions subject_code relative to the detected enrolment comb band.
        """
        h, w = aligned_img.shape[:2]
        fields_config = (format_config or {}).get("fields", {})
        results: Dict[str, FieldCropResult] = {}

        is_b = (format_id == "format_v2")

        # ---------------------------------------------------------------------
        # 1. ENROLMENT NO CROP
        # ---------------------------------------------------------------------
        if "enrollment_no" in fields_config:
            e_cfg = fields_config["enrollment_no"]
            roi_frac = e_cfg.get("roi", [0.520, 0.260, 0.985, 0.360] if not is_b else [0.550, 0.250, 0.990, 0.410])

            if comb_box is not None and alignment_score >= 0.30:
                comb_cx, comb_cy = comb_box[0]
                comb_w, comb_h = comb_box[1]
                cell_w = comb_w / 12.0

                # Crop window at least 0.5 comb cell wider than detected comb on each side
                margin_x = max(int(round(0.60 * cell_w)), 30)
                margin_y = max(int(round(0.40 * comb_h)), 25)

                x1 = int(round(comb_cx - comb_w / 2.0 - margin_x))
                x2 = int(round(comb_cx + comb_w / 2.0 + margin_x))
                y1 = int(round(comb_cy - comb_h / 2.0 - margin_y))
                y2 = int(round(comb_cy + comb_h / 2.0 + margin_y))

                pad_left = max(0, -x1)
                pad_top = max(0, -y1)
                pad_right = max(0, x2 - w)
                pad_bottom = max(0, y2 - h)

                valid_x1 = max(0, x1)
                valid_x2 = min(w, x2)
                valid_y1 = max(0, y1)
                valid_y2 = min(h, y2)

                valid_crop = aligned_img[valid_y1:valid_y2, valid_x1:valid_x2]
                if valid_crop.size == 0:
                    crop_e = np.empty((0, 0, 3), dtype=np.uint8)
                    status_e = "CROP_EMPTY"
                else:
                    paper_color = np.median(valid_crop, axis=(0, 1)).astype(np.uint8).tolist()
                    crop_e = cv2.copyMakeBorder(
                        valid_crop,
                        pad_top,
                        pad_bottom,
                        pad_left,
                        pad_right,
                        cv2.BORDER_CONSTANT,
                        value=paper_color,
                    )
                    comb_x1 = comb_cx - comb_w / 2.0
                    comb_x2 = comb_cx + comb_w / 2.0
                    if comb_x1 < 10.0 or comb_x2 > (w - 10.0):
                        status_e = "COMB_TOUCHES_PAGE_EDGE"
                    else:
                        status_e = "OK"
            else:
                x1 = max(0, int(round(roi_frac[0] * w)))
                y1 = max(0, int(round(roi_frac[1] * h)))
                x2 = min(w, int(round(roi_frac[2] * w)))
                y2 = min(h, int(round(roi_frac[3] * h)))
                crop_e = aligned_img[y1:y2, x1:x2].copy()
                status_e = "FALLBACK_NOMINAL_ROI"

            roi_frac_e = (x1 / float(w), y1 / float(h), x2 / float(w), y2 / float(h))

            results["enrollment_no"] = FieldCropResult(
                field_name="enrollment_no",
                crop=crop_e,
                roi_pixels=(x1, y1, x2, y2),
                roi_fraction=tuple(roi_frac_e),
                alignment_score=alignment_score,
                status=status_e,
            )

        # ---------------------------------------------------------------------
        # 2. SUBJECT CODE CROP (Anchored relative to comb band)
        # ---------------------------------------------------------------------
        if "subject_code" in fields_config:
            s_cfg = fields_config["subject_code"]
            base_roi = s_cfg.get("roi", [0.040, 0.280, 0.460, 0.355] if not is_b else [0.040, 0.255, 0.490, 0.330])

            # Determine vertical center:
            if comb_box is not None and alignment_score >= 0.30:
                comb_cy = comb_box[0][1]
                v_offset = 0.0 if not is_b else (-0.031 * h)
                subj_cy = comb_cy + v_offset
                status_s = "OK"
            else:
                subj_cy = (base_roi[1] + base_roi[3]) / 2.0 * h
                status_s = "FALLBACK_NOMINAL_ROI"

            # Moderate vertical margin
            half_span = self.moderate_margin_h * h
            sy1 = max(0, int(round(subj_cy - half_span)))
            sy2 = min(h, int(round(subj_cy + half_span)))
            sx1 = max(0, int(round(base_roi[0] * w)))
            sx2 = min(w, int(round(base_roi[2] * w)))

            crop_s = aligned_img[sy1:sy2, sx1:sx2].copy()
            roi_frac_s = (sx1 / float(w), sy1 / float(h), sx2 / float(w), sy2 / float(h))

            results["subject_code"] = FieldCropResult(
                field_name="subject_code",
                crop=crop_s,
                roi_pixels=(sx1, sy1, sx2, sy2),
                roi_fraction=roi_frac_s,
                alignment_score=alignment_score,
                status=status_s,
            )

        # ---------------------------------------------------------------------
        # 3. GRAND TOTAL CROP (Template-matched ROI with wide boundary)
        # ---------------------------------------------------------------------
        if "grand_total" in fields_config:
            gt_cfg = fields_config["grand_total"]
            if gt_cfg.get("status") == "deferred_phase2":
                results["grand_total"] = FieldCropResult(
                    field_name="grand_total",
                    crop=np.empty((0, 0, 3), dtype=np.uint8),
                    roi_pixels=(0, 0, 0, 0),
                    roi_fraction=(0.0, 0.0, 0.0, 0.0),
                    alignment_score=alignment_score,
                    status="ROI_TO_BE_MEASURED",
                )
            else:
                gt_crop, tmpl_score, (gx1, gy1, gx2, gy2) = extract_total_crop_tmpl(
                    aligned_img,
                    format_id,
                    tmpl_a=self.tmpl_a,
                    tmpl_b=self.tmpl_b,
                )
                status_gt = "OK" if tmpl_score >= 0.30 else "LOW_TEMPLATE_SCORE"
                results["grand_total"] = FieldCropResult(
                    field_name="grand_total",
                    crop=gt_crop,
                    roi_pixels=(gx1, gy1, gx2, gy2),
                    roi_fraction=(gx1 / float(w), gy1 / float(h), gx2 / float(w), gy2 / float(h)),
                    alignment_score=tmpl_score,
                    status=status_gt,
                )

        # ---------------------------------------------------------------------
        # 4. QUESTION MARKS (Deferred Phase 2)
        # ---------------------------------------------------------------------
        if "question_marks" in fields_config:
            results["question_marks"] = FieldCropResult(
                field_name="question_marks",
                crop=np.empty((0, 0, 3), dtype=np.uint8),
                roi_pixels=(0, 0, 0, 0),
                roi_fraction=(0.0, 0.0, 0.0, 0.0),
                alignment_score=alignment_score,
                status="ROI_TO_BE_MEASURED",
            )

        return results


# -----------------------------------------------------------------------------
# MILESTONE 7 PORTED FIELD CROPPERS (Config-Driven)
# -----------------------------------------------------------------------------

_SUBJ_TEMPLATES: Dict[str, Optional[np.ndarray]] = {}


def _get_subj_template(name: str) -> Optional[np.ndarray]:
    if name not in _SUBJ_TEMPLATES:
        p = TEMPLATE_DIR / f"{name}.png"
        _SUBJ_TEMPLATES[name] = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p.exists() else None
    return _SUBJ_TEMPLATES[name]


def extract_total_crop_m7(
    c_can: np.ndarray,
    format_id: str,
    tmpl_a: Optional[np.ndarray] = None,
    tmpl_b: Optional[np.ndarray] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Tuple[np.ndarray, float, Tuple[int, int, int, int]]:
    """
    M7 enhanced Grand Total cropper (config-driven):
    - Format A: matches tmpl_a in [0.70*h..0.90*h, 0.35*w..0.85*w], takes right cell up to page edge.
    - Format B: matches tmpl_b in [0.55*h..0.85*h, 0.15*w..0.65*w], takes [ax + tw + 14 : ax + tw + 360].
    """
    h, w = c_can.shape[:2]
    gray = cv2.cvtColor(c_can, cv2.COLOR_BGR2GRAY) if c_can.ndim == 3 else c_can
    m7_cfg = ((cfg or {}).get("fields", {}).get("grand_total", {}).get("m7_rules", {})) if cfg else {}

    if format_id == "format_original":
        if tmpl_a is None:
            tp = TEMPLATE_DIR / "tmpl_gt_a.png"
            tmpl_a = cv2.imread(str(tp)) if tp.exists() else None
        if tmpl_a is not None:
            t_a = cv2.cvtColor(tmpl_a, cv2.COLOR_BGR2GRAY) if tmpl_a.ndim == 3 else tmpl_a
            sw = m7_cfg.get("search_window", [0.70, 0.90, 0.35, 0.85])
            sy1, sy2 = int(h * sw[0]), int(h * sw[1])
            sx1, sx2 = int(w * sw[2]), int(w * sw[3])
            roi = gray[sy1:sy2, sx1:sx2]
            th, tw = t_a.shape[:2]
            if roi.shape[0] >= th and roi.shape[1] >= tw:
                best_val = -1.0
                best_loc = (0, 0)
                best_rot = 0.0
                for rot_t in [-3.5, -2.0, 0.0, 2.0, 3.5]:
                    if rot_t == 0.0:
                        rtmpl = t_a
                    else:
                        Mt = cv2.getRotationMatrix2D((tw / 2.0, th / 2.0), rot_t, 1.0)
                        rtmpl = cv2.warpAffine(t_a, Mt, (tw, th), borderMode=cv2.BORDER_REPLICATE)
                    res = cv2.matchTemplate(roi, rtmpl, cv2.TM_CCOEFF_NORMED)
                    _, mv, _, ml = cv2.minMaxLoc(res)
                    if mv > best_val:
                        best_val = mv
                        best_loc = ml
                        best_rot = rot_t

                if best_val > float(m7_cfg.get("min_match_score", 0.30)):
                    ax = sx1 + best_loc[0]
                    ay = sy1 + best_loc[1]
                    cx1 = ax + tw + int(m7_cfg.get("x1_offset_px", 2))
                    cx2 = min(w, int(0.995 * w))
                    cy1 = max(0, ay + int(m7_cfg.get("y1_offset_px", -6)))
                    cy2 = min(h, ay + th + int(m7_cfg.get("y2_offset_px", 12)))
                    crop = c_can[cy1:cy2, cx1:cx2].copy()
                    if abs(best_rot) > 0.5 and crop.size > 0:
                        ch, cw = crop.shape[:2]
                        Mc = cv2.getRotationMatrix2D((cw / 2.0, ch / 2.0), -best_rot, 1.0)
                        crop = cv2.warpAffine(crop, Mc, (cw, ch), borderMode=cv2.BORDER_REPLICATE)
                    return crop, float(best_val), (cx1, cy1, cx2, cy2)
                return None, float(best_val), (0, 0, 0, 0)

    elif format_id == "format_v2":
        if tmpl_b is None:
            tp = TEMPLATE_DIR / "tmpl_gt_b.png"
            tmpl_b = cv2.imread(str(tp)) if tp.exists() else None
        if tmpl_b is not None:
            t_b = cv2.cvtColor(tmpl_b, cv2.COLOR_BGR2GRAY) if tmpl_b.ndim == 3 else tmpl_b
            sw = m7_cfg.get("search_window", [0.55, 0.85, 0.15, 0.65])
            sy1, sy2 = int(h * sw[0]), int(h * sw[1])
            sx1, sx2 = int(w * sw[2]), int(w * sw[3])
            roi = gray[sy1:sy2, sx1:sx2]
            th, tw = t_b.shape[:2]
            if roi.shape[0] >= th and roi.shape[1] >= tw:
                best_val = -1.0
                best_loc = (0, 0)
                best_rot = 0.0
                for rot_t in [-3.5, -2.0, 0.0, 2.0, 3.5]:
                    if rot_t == 0.0:
                        rtmpl = t_b
                    else:
                        Mt = cv2.getRotationMatrix2D((tw / 2.0, th / 2.0), rot_t, 1.0)
                        rtmpl = cv2.warpAffine(t_b, Mt, (tw, th), borderMode=cv2.BORDER_REPLICATE)
                    res = cv2.matchTemplate(roi, rtmpl, cv2.TM_CCOEFF_NORMED)
                    _, mv, _, ml = cv2.minMaxLoc(res)
                    if mv > best_val:
                        best_val = mv
                        best_loc = ml
                        best_rot = rot_t

                if best_val > float(m7_cfg.get("min_match_score", 0.35)):
                    ax = sx1 + best_loc[0]
                    ay = sy1 + best_loc[1]
                    cx1 = ax + tw + int(m7_cfg.get("x1_offset_px", 14))
                    cx2 = min(w, ax + tw + int(m7_cfg.get("x2_offset_px", 360)))
                    cy1 = max(0, ay + int(m7_cfg.get("y1_offset_px", -24)))
                    cy2 = min(h, ay + th + int(m7_cfg.get("y2_offset_px", 24)))
                    crop = c_can[cy1:cy2, cx1:cx2].copy()
                    if abs(best_rot) > 0.5 and crop.size > 0:
                        ch, cw = crop.shape[:2]
                        Mc = cv2.getRotationMatrix2D((cw / 2.0, ch / 2.0), -best_rot, 1.0)
                        crop = cv2.warpAffine(crop, Mc, (cw, ch), borderMode=cv2.BORDER_REPLICATE)
                    return crop, float(best_val), (cx1, cy1, cx2, cy2)
                return None, float(best_val), (0, 0, 0, 0)

    return None, 0.0, (0, 0, 0, 0)


def check_total_clipped(crop: np.ndarray, touched_page_edge: bool = False, cfg: Optional[Dict[str, Any]] = None) -> bool:
    """
    Checks if handwritten ink touches the right border of the grand total crop
    (indicating a clipped right-hand side total), while ignoring full-height vertical table border lines.
    """
    if crop is None or crop.size == 0:
        return True
    h, w = crop.shape[:2]
    if w < 15 or h < 15:
        return True
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    paper_med = float(np.median(gray))
    thresh_val = paper_med - 45.0

    full_right = gray[:, max(0, w - 5):w]
    row_dark = np.any(full_right < thresh_val, axis=1)
    if np.sum(row_dark) >= int(0.65 * h):
        return False

    ry1, ry2 = int(0.25 * h), int(0.75 * h)
    right_strip = gray[ry1:ry2, max(0, w - 4):w]
    if right_strip.size == 0:
        return False
    dark_pixels = int(np.sum(right_strip < thresh_val))
    if touched_page_edge and dark_pixels >= 28:
        return True
    if dark_pixels >= 32:
        return True
    return False


def crop_subject_code_single_line(
    c_can: np.ndarray,
    format_id: str,
    comb_box: Optional[Any] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Tuple[np.ndarray, Tuple[int, int, int, int], Optional[np.ndarray], Optional[Tuple[int, int, int, int]]]:
    """
    Extracts strictly the single handwritten Subject Code line above its underline
    by template-anchoring to the printed 'Subject Code' label on the canonical image.
    Returns (left_crop, left_bbox, right_crop, right_bbox).
    """
    from ocr_v2.cell_reader import apply_crop_remedy
    h, w = c_can.shape[:2]
    gray = cv2.cvtColor(c_can, cv2.COLOR_BGR2GRAY) if c_can.ndim == 3 else c_can
    is_b = (format_id == "format_v2")

    if not is_b:
        tmpl_a = _get_subj_template("tmpl_subj_a")
        sx1, sy1, sx2, sy2 = int(0.175 * w), int(0.285 * h), int(0.455 * w), int(0.325 * h)
        if tmpl_a is not None:
            ry1, ry2 = int(0.18 * h), int(0.44 * h)
            rx1, rx2 = int(0.02 * w), int(0.28 * w)
            roi = gray[ry1:ry2, rx1:rx2]
            th, tw = tmpl_a.shape[:2]
            if roi.shape[0] >= th and roi.shape[1] >= tw:
                res = cv2.matchTemplate(roi, tmpl_a, cv2.TM_CCOEFF_NORMED)
                _, mv, _, ml = cv2.minMaxLoc(res)
                if mv > 0.35:
                    ax, ay = rx1 + ml[0], ry1 + ml[1]
                    sx1 = ax + tw + 4
                    sx2 = min(w, ax + tw + 315)
                    sy1 = max(0, ay - 22)
                    sy2 = min(h, ay + th + 10)
        crop_a = c_can[sy1:sy2, sx1:sx2].copy()
        crop_a = apply_crop_remedy(crop_a, pad_pct=0.0, remove_border=True)
        return crop_a, (sx1, sy1, sx2, sy2), None, None

    else:
        tmpl_bl = _get_subj_template("tmpl_subj_b_left")
        tmpl_br = _get_subj_template("tmpl_subj_b_right")

        sx1, sy1, sx2, sy2 = int(0.180 * w), int(0.265 * h), int(0.475 * w), int(0.305 * h)
        if tmpl_bl is not None:
            ry1, ry2 = int(0.18 * h), int(0.42 * h)
            rx1, rx2 = int(0.01 * w), int(0.25 * w)
            roi = gray[ry1:ry2, rx1:rx2]
            th, tw = tmpl_bl.shape[:2]
            if roi.shape[0] >= th and roi.shape[1] >= tw:
                res = cv2.matchTemplate(roi, tmpl_bl, cv2.TM_CCOEFF_NORMED)
                _, mv, _, ml = cv2.minMaxLoc(res)
                if mv > 0.35:
                    ax, ay = rx1 + ml[0], ry1 + ml[1]
                    sx1 = max(0, ax + tw - 8)
                    sx2 = min(w, ax + tw + 310)
                    sy1 = max(0, ay - 20)
                    sy2 = min(h, ay + th + 4)
        crop_left = c_can[sy1:sy2, sx1:sx2].copy()
        crop_left = apply_crop_remedy(crop_left, pad_pct=0.0, remove_border=True)

        rx1_b, ry1_b, rx2_b, ry2_b = int(0.695 * w), int(0.345 * h), int(0.965 * w), int(0.385 * h)
        if tmpl_br is not None:
            sry1, sry2 = int(0.22 * h), int(0.48 * h)
            srx1, srx2 = int(0.45 * w), int(0.76 * w)
            roi_r = gray[sry1:sry2, srx1:srx2]
            th_r, tw_r = tmpl_br.shape[:2]
            if roi_r.shape[0] >= th_r and roi_r.shape[1] >= tw_r:
                res_r = cv2.matchTemplate(roi_r, tmpl_br, cv2.TM_CCOEFF_NORMED)
                _, mv_r, _, ml_r = cv2.minMaxLoc(res_r)
                if mv_r > 0.35:
                    ax_r, ay_r = srx1 + ml_r[0], sry1 + ml_r[1]
                    rx1_b = ax_r + tw_r + 2
                    rx2_b = min(w - 15, ax_r + tw_r + 295)
                    ry1_b = max(0, ay_r - 24)
                    ry2_b = min(h, ay_r + th_r + 10)
        crop_right = c_can[ry1_b:ry2_b, rx1_b:rx2_b].copy()
        crop_right = apply_crop_remedy(crop_right, pad_pct=0.0, remove_border=True)

        return crop_left, (sx1, sy1, sx2, sy2), crop_right, (rx1_b, ry1_b, rx2_b, ry2_b)

