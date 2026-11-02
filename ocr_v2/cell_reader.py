"""
ocr_v2.cell_reader: Shared cell reader and question-marks parser.
Implements:
1. Exact preprocessing: RGB conversion, height=48, ceil(48 * ratio), configurable minimum batch width.
2. Exact CTC collapse decoding: blank token 0 ignored, repeated character collapse across frames.
3. Spike 8 validated parser rules with zero-padded grammar and per-question maximum cap check.
4. Four-status sum verification (AGREE / MISMATCH / POSSIBLE_GRACE / UNAVAILABLE).
"""

import math
import json
import re
from typing import List, Tuple, Dict, Any, Optional
from pathlib import Path
import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class SharedCellReader:
    """Shared ONNX cell recognition reader with exact PaddleX preprocessing and decoding parity."""

    def __init__(self, character_dict_path: Optional[str] = None):
        if character_dict_path is None:
            dict_path = PROJECT_ROOT / "ocr_v2" / "assets" / "character_dict.json"
        else:
            dict_path = Path(character_dict_path)
            if not dict_path.is_absolute():
                dict_path = PROJECT_ROOT / dict_path

        with open(dict_path, "r", encoding="utf-8") as f:
            self.character_dict = json.load(f)

    def preprocess_crops(self, crops: List[np.ndarray], min_batch_width: int = 320) -> np.ndarray:
        """
        Exact PaddleX PP-OCRv6 preprocessing and batching parity:
        - Keeps BGR format
        - Per-crop resize and normalization matching OCRReisizeNormImg
        - Batch zero-padding matching ToBatch
        """
        if not crops:
            return np.empty((0, 3, 48, min_batch_width), dtype=np.float32)

        imgC, imgH, default_w = 3, 48, min_batch_width
        resized_list = []
        for img in crops:
            if img is None or img.size == 0 or img.shape[0] == 0 or img.shape[1] == 0:
                img = np.zeros((imgH, default_w, 3), dtype=np.uint8)
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
            elif img.ndim == 3 and img.shape[2] == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            h, w = img.shape[:2]
            wh_ratio = (w * 1.0) / float(max(h, 1))
            max_wh_ratio = max(default_w / float(imgH), wh_ratio)
            target_w = int(imgH * max_wh_ratio)
            ratio = w / float(max(h, 1))
            resized_w = max(1, int(math.ceil(imgH * ratio)))
            if resized_w > target_w:
                resized_w = target_w
            resized_image = cv2.resize(img, (resized_w, imgH)).astype(np.float32)
            resized_image = resized_image.transpose((2, 0, 1)) / 255.0
            resized_image -= 0.5
            resized_image /= 0.5
            pad_im = np.zeros((imgC, imgH, target_w), dtype=np.float32)
            pad_im[:, :, :resized_w] = resized_image
            resized_list.append(pad_im)

        max_w = max(im.shape[2] for im in resized_list)
        padded_batch = []
        for im in resized_list:
            pad_w = max_w - im.shape[2]
            if pad_w > 0:
                padded = np.pad(im, ((0, 0), (0, 0), (0, pad_w)), mode="constant", constant_values=0)
            else:
                padded = im
            padded_batch.append(padded)

        return np.ascontiguousarray(np.stack(padded_batch, axis=0), dtype=np.float32)

    def decode_predictions(self, preds_prob_tensor: np.ndarray) -> List[Tuple[str, float]]:
        """
        Exact CTC decoding:
        - Argmax along character vocabulary axis
        - Blank token index 0 discarded
        - Consecutive duplicate character indices collapsed
        - Mean confidence of selected character frames
        """
        preds_idx = preds_prob_tensor.argmax(axis=-1)
        preds_prob = preds_prob_tensor.max(axis=-1)
        results = []

        for b in range(len(preds_idx)):
            text_index = preds_idx[b]
            text_prob = preds_prob[b]

            selection = np.ones(len(text_index), dtype=bool)
            selection[1:] = text_index[1:] != text_index[:-1]
            selection &= (text_index != 0)

            selected_indices = text_index[selection]
            chars = [self.character_dict[idx] for idx in selected_indices if idx < len(self.character_dict)]
            conf_list = text_prob[selection]
            conf = float(np.mean(conf_list)) if len(conf_list) > 0 else 0.0
            results.append(("".join(chars), conf))

        return results


def is_digit_like_qcell(s: str) -> bool:
    """Returns True only if token is digit-like (bounded length, no multi-letter words, >= 50% digit-like characters)."""
    if not s or len(s) > 10:
        return False
    if re.search(r"[A-Za-z]{2,}", s):
        return False
    allowed = set("0123456789OoYySs+.:/#- ")
    non_ws = [c for c in s if not c.isspace()]
    if not non_ws:
        return False
    valid_count = sum(1 for c in non_ws if c in allowed)
    return (valid_count / len(non_ws)) >= 0.5


def parse_question_cell(
    raw_text: str,
    conf: float = 1.0,
    max_marks: float = 14.0,
    conf_threshold: float = 0.60
) -> Tuple[Optional[float], float, List[str]]:
    """
    Parses a single handwritten question mark cell with Spike 8 grammar and validation rules:
    - Zero-padded grammar: '00' -> 0.0, '05.5' -> 5.5, '01' -> 1.0, '02' -> 2.0, '00.5' -> 0.5.
    - Standard lookalikes: O/o -> 0, S/s -> 5, I/l/| -> 1.
    - Addition handling: e.g. 10+2 -> 12.0.
    - Trailing tick marks & dangling dots: e.g. '.57' -> '.5', '12.' -> '12.5'.
    - Trailing slash/decimal 0: '7o5' -> '7.5'.
    - Flagged if > max_marks or < 0.0 (OUT_OF_RANGE, flagged never overwritten).
    - Flagged if not multiple of 0.5 (NOT_HALF_MARK).
    - Flagged if low confidence < conf_threshold (LOW_CONFIDENCE).
    """
    flags = []
    if conf < conf_threshold:
        flags.append("LOW_CONFIDENCE")

    if not raw_text or not raw_text.strip():
        flags.append("EMPTY_CELL")
        return None, conf, flags

    s = raw_text.strip()

    # Empty / dash markers
    if s in ["-", "--", "---", "_", ".", "Nil", "nil", "NIL"]:
        flags.append("DASH_OR_BLANK")
        return None, conf, flags

    # Noise tokens
    if s in ["?", "??", "e", "in", "Hna"]:
        flags.append("UNREADABLE")
        return None, conf, flags

    # Lookalike characters (retained in Spike 8)
    if not is_digit_like_qcell(s):
        flags.extend(["NON_NUMERIC", "needs_review"])
        return None, conf, flags
    s = s.replace("o", "0").replace("O", "0").replace("S", "5").replace("s", "5")
    s = s.replace("l", "1").replace("I", "1").replace("|", "1")
    s = s.replace(":", "=").replace(";", "=")
    s = s.replace("-", ".")

    # Addition expressions (retained in Spike 8)
    if "+" in s:
        try:
            parts = [p.strip() for p in s.split("+") if p.strip()]
            if len(parts) >= 2:
                val = float(sum(float(p) for p in parts))
                if val > max_marks or val < 0.0:
                    flags.append("OUT_OF_RANGE")
                return val, conf, flags
            elif len(parts) == 1:
                flags.append("INCOMPLETE_EXPRESSION")
                s = parts[0]
        except Exception:
            flags.append("INCOMPLETE_EXPRESSION")

    # Trailing tick marks e.g. 6.57 -> 6.5, 097 -> 09 (retained in Spike 8)
    if s.endswith(".57"):
        s = s[:-1]
    elif s.endswith("7") and len(s) == 3 and s.startswith("0"):
        s = s[:-1]

    # Dangling dot e.g. '12.' -> '12.5' (retained in Spike 8)
    if s.endswith("."):
        s = s + "5"

    # Decimal dot misread as '0' e.g. '705' where middle is 0 -> 7.5
    if len(s) == 3 and s[1] == "0" and s[0].isdigit() and s[2] == "5":
        s = f"{s[0]}.5"

    # Strip extraneous border labels
    s = s.lstrip("T").lstrip("_").strip()

    # Check zero-padded numbers e.g. '00' -> 0.0, '05.5' -> 5.5, '00.5' -> 0.5
    try:
        val = float(s)
        # Check per-question maximum
        if val > max_marks or val < 0.0:
            flags.append("OUT_OF_RANGE")
            return val, conf, flags

        # Check half mark granularity
        if abs((val * 2) - round(val * 2)) > 1e-4:
            flags.append("NOT_HALF_MARK")
            return val, conf, flags

        return val, conf, flags
    except Exception:
        flags.append("PARSE_FAILED")
        return None, conf, flags


def compute_sum_status(
    q_vals: List[Optional[float]],
    q_flags: List[List[str]],
    total_val: Optional[float],
    total_flags: List[str]
) -> Tuple[str, Optional[float], Optional[float], Optional[float]]:
    """
    Computes sum status using Spike 10 pre-registered definitions:
    - POSSIBLE_GRACE: All 5 cells and total unflagged, and total - round_half_up(sum) in {1.0, 2.0}.
    - AGREE: All 5 cells and total unflagged, and round_half_up(sum) == total.
    - MISMATCH: Numeric disagreement (not in {0, 1, 2}) when unflagged, or total disagreement.
    - UNAVAILABLE: Any cell or total flagged, empty, or unparsable.
    Returns: (status, sum_q, total_val, diff)
    """
    # Exclude non-fatal DASH_OR_BLANK or EMPTY_CELL if treated as 0?
    # In Spike 10: Any cell with None value or active flag -> UNAVAILABLE
    has_unparsed = any(v is None for v in q_vals) or (total_val is None)
    has_flags = any(len(f) > 0 for f in q_flags) or any(
        f in (
            "needs_review",
            "OUT_OF_RANGE",
            "RHS_MISSING",
            "NON_NUMERIC",
            "RECOVERED_FROM_CELL_CONSENSUS",
            "SUGGESTED_FROM_CELLS",
            "TOTAL_DERIVED_FROM_CELLS",
            "SUM_GATE_CIRCULAR_PREVENTED",
        )
        for f in total_flags
    )

    if has_unparsed or has_flags:
        # Sum is unavailable or unverified
        sum_q = sum(v for v in q_vals if v is not None) if not has_unparsed else None
        diff = (total_val - sum_q) if (total_val is not None and sum_q is not None) else None
        return "UNAVAILABLE", sum_q, total_val, diff

    sum_q = float(sum(q_vals))
    sum_rounded = float(math.floor(sum_q + 0.5))
    diff = float(total_val - sum_rounded)

    if abs(diff) < 1e-5:
        return "AGREE", sum_q, total_val, diff
    elif diff in (1.0, 2.0):
        # POSSIBLE_GRACE is an alert, never an accept
        return "POSSIBLE_GRACE", sum_q, total_val, diff
    else:
        return "MISMATCH", sum_q, total_val, diff


def get_ort_session(threads: int = 4, model_path: Optional[str] = None):
    """Factory helper to obtain an ONNX Runtime InferenceSession for PP-OCRv6."""
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    if model_path is None:
        vendored = PROJECT_ROOT / "models" / "PP-OCRv6_medium_rec_onnx" / "inference.onnx"
        if vendored.exists():
            model_path = str(vendored)
        else:
            model_path = str(Path.home() / ".paddlex" / "official_models" / "PP-OCRv6_medium_rec_onnx" / "inference.onnx")
    return ort.InferenceSession(model_path, sess_options=opts, providers=["CPUExecutionProvider"])


# -----------------------------------------------------------------------------
# MILESTONE 7 PORTED CELL-READING RULES (Config-Driven)
# -----------------------------------------------------------------------------

def detect_visual_stacked_fraction(crop: np.ndarray, cfg: Optional[Dict[str, Any]] = None) -> Tuple[bool, np.ndarray]:
    """
    Visual stacked-fraction detector at the right end of the cell:
    Looks for a top component (numerator '1') and a bottom component (denominator '2')
    vertically aligned in x with vertical separation >= min_y_sep_frac * h,
    positioned to the right of at least one main digit component.
    """
    if crop is None or crop.size == 0:
        return False, crop
    h, w = crop.shape[:2]
    if w < 40 or h < 25:
        return False, crop

    vf_cfg = (cfg or {}).get("visual_fraction", {}) if cfg else {}
    top_cy_max = float(vf_cfg.get("top_cy_max_frac", 0.43))
    bot_cy_min = float(vf_cfg.get("bot_cy_min_frac", 0.64))
    max_x_diff = float(vf_cfg.get("max_x_align_diff_px", 22.0))
    min_y_sep = float(vf_cfg.get("min_y_sep_frac", 0.30))
    min_area = int(vf_cfg.get("min_component_area", 25))

    if crop is None or crop.size == 0 or crop.shape[0] == 0 or crop.shape[1] == 0:
        return {"sig_unparse": True, "sig_contrast": True, "sig_disagree": False, "sig_margin": True, "combined_flag": True}

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 8)
    th[:4, :] = 0
    th[-3:, :] = 0
    th[:, :4] = 0
    th[:, -4:] = 0

    num_labels, _, stats, centroids = cv2.connectedComponentsWithStats(th)
    comps = []
    for i in range(1, num_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area >= min_area:
            comps.append((
                i,
                float(centroids[i][0]),
                float(centroids[i][1]),
                int(stats[i, cv2.CC_STAT_LEFT]),
                int(stats[i, cv2.CC_STAT_TOP]),
                int(stats[i, cv2.CC_STAT_WIDTH]),
                int(stats[i, cv2.CC_STAT_HEIGHT]),
                area,
            ))

    for tc in comps:
        if tc[2] < top_cy_max * h and tc[6] <= 0.65 * h and tc[1] > 0.35 * w:
            for bc in comps:
                if bc[0] != tc[0] and bc[2] > bot_cy_min * h and bc[6] <= 0.48 * h:
                    if abs(tc[1] - bc[1]) <= max_x_diff and (bc[2] - tc[2]) >= min_y_sep * h:
                        left_ink = [
                            mc for mc in comps
                            if mc[0] not in (tc[0], bc[0]) and mc[1] < (tc[1] - 16.0) and mc[7] >= 55
                        ]
                        if left_ink:
                            aligned_stack = [
                                c for c in comps
                                if abs(c[1] - 0.5 * (tc[1] + bc[1])) <= 20.0 and c[3] > max(m[1] for m in left_ink)
                            ]
                            min_x = min([tc[3], bc[3]] + [c[3] for c in aligned_stack])
                            cut_x = max(int(0.32 * w), min_x - 3)
                            stripped = crop.copy()
                            paper_col = np.median(crop, axis=(0, 1)).astype(np.uint8)
                            stripped[:, cut_x:] = paper_col
                            return True, stripped

    return False, crop


def detect_crossed_out_cell(crop: np.ndarray, cfg: Optional[Dict[str, Any]] = None) -> bool:
    """
    Detects strike-through / crossed-out cells:
    1. Long horizontal or diagonal strike bar crossing the central digit zone, OR
    2. Heavy scribbled ink blob covering a wide central span with high stroke density.
    """
    if crop is None or crop.size == 0:
        return False
    h, w = crop.shape[:2]
    if h < 20 or w < 30:
        return False

    co_cfg = (cfg or {}).get("crossed_out", {}) if cfg else {}
    y_band = co_cfg.get("inner_y_band", [0.20, 0.80])
    x_band = co_cfg.get("inner_x_band", [0.10, 0.90])
    h_min_ink = float(co_cfg.get("horiz_min_ink_ratio", 0.14))
    s_min_ink = float(co_cfg.get("scribble_min_ink_ratio", 0.23))

    if crop is None or crop.size == 0 or crop.shape[0] == 0 or crop.shape[1] == 0:
        return {"sig_unparse": True, "sig_contrast": True, "sig_disagree": False, "sig_margin": True, "combined_flag": True}

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    iy1, iy2 = int(y_band[0] * h), int(y_band[1] * h)
    ix1, ix2 = int(x_band[0] * w), int(x_band[1] * w)
    inner = gray[iy1:iy2, ix1:ix2]
    if inner.size == 0:
        return False

    ih, iw = inner.shape[:2]
    th = cv2.adaptiveThreshold(inner, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 10)
    ink_ratio = float(np.sum(th > 0)) / float(max(1, th.size))

    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, int(0.45 * iw)), 1))
    horiz_lines = cv2.morphologyEx(th, cv2.MORPH_OPEN, horiz_kernel)
    if np.sum(horiz_lines > 0) > 30 and ink_ratio > h_min_ink:
        vert_check = np.sum(th > 0, axis=0)
        active_cols = np.sum(vert_check > int(0.25 * ih))
        if active_cols > int(0.30 * iw):
            return True

    if ink_ratio > s_min_ink:
        num_labels, _, stats, _ = cv2.connectedComponentsWithStats(th)
        for i in range(1, num_labels):
            cw = stats[i, cv2.CC_STAT_WIDTH]
            ch = stats[i, cv2.CC_STAT_HEIGHT]
            area = stats[i, cv2.CC_STAT_AREA]
            if cw > 0.58 * iw and ch > 0.50 * ih and area > 0.16 * (iw * ih):
                return True

    return False


def parse_question_cell_m7(
    raw_text: str,
    conf: float = 1.0,
    max_marks: float = 14.0,
    conf_threshold: float = 0.60,
    mode: str = "grammar_and_overmax",
    visual_fraction_detected: bool = False,
) -> Tuple[Optional[float], float, List[str], Optional[float]]:
    """
    Milestone 7 enhanced question-cell parser:
    Returns (value, confidence, flags, suggested_value).
    """
    flags = []
    if conf < conf_threshold:
        flags.append("LOW_CONFIDENCE")

    s = str(raw_text or "").strip()
    if not s or s in ("-", "--", "---", "Nil", "nil", "NIL", "N/A", "na", ".", "_"):
        if visual_fraction_detected:
            return 0.5, conf, flags + ["SUGGESTED_FRACTION"], 0.5
        flags.append("EMPTY_CELL")
        return None, conf, flags, None

    if s in ("?", "??", "e", "in", "Hna"):
        flags.append("UNREADABLE")
        return None, conf, flags, None

    if mode in ("grammar", "grammar_and_overmax"):
        if s in ("1/2", "/2", "#"):
            return 0.5, conf, flags + ["SUGGESTED_FRACTION"], 0.5
        m_hash = re.match(r"^0*(\d{1,2})\s*(?:#|1\s*/\s*2|1\s+2|/\s*2)$", s)
        if m_hash:
            p_val = float(m_hash.group(1))
            if p_val + 0.5 <= max_marks:
                return p_val + 0.5, conf, flags + ["SUGGESTED_FRACTION"], p_val + 0.5

    if not is_digit_like_qcell(s):
        flags.extend(["NON_NUMERIC", "needs_review"])
        return None, conf, flags, None

    # Single-character lookalike map (only entries firing on >= 3 DEV cells retained):
    # 'O'->'0' (4 DEV cells, 28 DEV total), 'o'->'0' (4 DEV cells, 61 DEV total),
    # 'Y'->'4' (7 DEV cells), 'y'->'4' (4 DEV cells),
    # 'S'->'5' (35 DEV cells), 's'->'5' (12 DEV cells), ':'->'.' (7 DEV cells)
    trans = str.maketrans({
        "O": "0", "o": "0",
        "Y": "4", "y": "4",
        "S": "5", "s": "5",
        ":": ".",
    })
    cleaned = s.translate(trans).strip()
    cleaned = cleaned.lstrip("T").lstrip("_").strip()

    cleaned = re.sub(r"(\.5)[-\.]+$", r"\1", cleaned)
    cleaned = cleaned.replace("-", ".").replace(" ", "")
    cleaned = re.sub(r"\.+", ".", cleaned)

    if "+" in cleaned:
        try:
            parts = [p.strip() for p in cleaned.split("+") if p.strip()]
            if len(parts) >= 2:
                val_sum = float(sum(float(p) for p in parts))
                if val_sum > max_marks or val_sum < 0.0:
                    flags.append("OUT_OF_RANGE")
                return val_sum, conf, flags, val_sum
        except Exception:
            flags.append("INCOMPLETE_EXPRESSION")

    if cleaned.endswith(".57"):
        cleaned = cleaned[:-1]
    elif cleaned.endswith("7") and len(cleaned) == 3 and cleaned.startswith("0"):
        cleaned = cleaned[:-1]
    if cleaned.endswith("."):
        cleaned = cleaned + "5"
    if len(cleaned) == 3 and cleaned[1] == "0" and cleaned[0].isdigit() and cleaned[2] == "5":
        cleaned = f"{cleaned[0]}.5"

    if mode in ("grammar", "grammar_and_overmax"):
        if re.match(r"^\d\.\d\.5$", cleaned):
            cleaned = cleaned[0] + cleaned[2:]
        elif re.match(r"^0?\d\.[12346789]$", cleaned):
            cand_nodot = float(cleaned.replace(".", ""))
            if 0.0 <= cand_nodot <= max_marks:
                cleaned = str(int(cand_nodot))

    if re.match(r"^0+\d+(?:\.\d+)?$", cleaned):
        cleaned = re.sub(r"^0+(\d)", r"\1", cleaned)

    m_num = re.match(r"^-?\d+(?:\.\d+)?$", cleaned)
    if not m_num:
        if visual_fraction_detected:
            m_lead = re.match(r"^0*(\d{1,2})", cleaned)
            if m_lead and float(m_lead.group(1)) + 0.5 <= max_marks:
                v_sug = float(m_lead.group(1)) + 0.5
                return v_sug, conf, flags + ["SUGGESTED_FRACTION"], v_sug
            return 0.5, conf, flags + ["SUGGESTED_FRACTION"], 0.5
        flags.extend(["PARSE_FAILED", "needs_review"])
        return None, conf, flags, None

    try:
        val = float(m_num.group(0))
    except ValueError:
        flags.extend(["PARSE_FAILED", "needs_review"])
        return None, conf, flags, None

    if visual_fraction_detected and abs(val - round(val)) < 1e-4 and 0.0 <= (val + 0.5) <= max_marks:
        val = val + 0.5
        if "SUGGESTED_FRACTION" not in flags:
            flags.append("SUGGESTED_FRACTION")
        return val, conf, flags, val

    digits_only = m_num.group(0)
    if mode in ("overmax", "grammar_and_overmax") and val > max_marks and "." not in digits_only and digits_only.endswith("2"):
        cand_prefix = None
        if len(digits_only) >= 3 and digits_only.endswith("12"):
            p12 = float(digits_only[:-2])
            if 0.0 <= p12 <= (max_marks - 0.5):
                cand_prefix = p12
        if cand_prefix is None and len(digits_only) >= 2:
            p2 = float(digits_only[:-1])
            if 0.0 <= p2 <= (max_marks - 0.5):
                cand_prefix = p2

        if cand_prefix is not None:
            suggested = cand_prefix + 0.5
            flags.append("SUGGESTED_FRACTION")
            return suggested, conf, flags, suggested

    if mode in ("grammar", "grammar_and_overmax") and val > max_marks and "." not in digits_only and digits_only.endswith("5") and len(digits_only) >= 2:
        p5 = float(digits_only[:-1])
        if 0.0 <= p5 <= (max_marks - 0.5):
            suggested = p5 + 0.5
            flags.append("SUGGESTED_FRACTION")
            return suggested, conf, flags, suggested

    if val < 0.0 or val > max_marks:
        flags.append("OUT_OF_RANGE")

    rem = abs((val * 2.0) - round(val * 2.0))
    if rem > 1e-3:
        flags.append("NON_HALF_MULTIPLE")

    return val, conf, flags, val


def compute_ctc_top2_margin(probs_slice: np.ndarray) -> float:
    """Computes minimum frame-level probability margin between top-1 and top-2 classes across non-blank frames."""
    if probs_slice is None or probs_slice.size == 0:
        return 1.0
    top1_idx = probs_slice.argmax(axis=-1)
    non_blank = top1_idx != 0
    if not np.any(non_blank):
        return 0.0
    active_probs = probs_slice[non_blank]
    sorted_p = np.sort(active_probs, axis=-1)
    margins = sorted_p[:, -1] - sorted_p[:, -2]
    return float(np.min(margins))


def check_unreadable_signals(
    crop: np.ndarray,
    parsed_val: Optional[float],
    parse_flags: List[str],
    conf: float,
    px_val: Optional[float] = None,
    top2_margin: float = 1.0,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, bool]:
    """Evaluates generic uncertainty / unreadability signals on a cell."""
    u_cfg = (cfg or {}).get("unreadable_signals", {}) if cfg else {}
    min_std = float(u_cfg.get("min_contrast_std", 13.5))
    min_marg = float(u_cfg.get("min_top2_margin", 0.20))
    min_conf = float(u_cfg.get("min_conf_threshold", 0.60))

    if crop is None or crop.size == 0 or crop.shape[0] == 0 or crop.shape[1] == 0:
        return {"sig_unparse": True, "sig_contrast": True, "sig_disagree": False, "sig_margin": True, "combined_flag": True}

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    h, w = gray.shape[:2]
    inner = gray[int(0.15 * h):int(0.85 * h), int(0.10 * w):int(0.90 * w)]
    std_val = float(np.std(inner)) if inner.size > 0 else 0.0

    sig_unparse = any(f in ("PARSE_FAILED", "OUT_OF_RANGE", "NON_HALF_MULTIPLE") for f in parse_flags)
    sig_contrast = std_val < min_std
    sig_disagree = (px_val is not None or parsed_val is not None) and (px_val != parsed_val)
    sig_margin = (top2_margin < min_marg) or (conf < (min_conf + 0.05))

    return {
        "empty_or_unparseable": sig_unparse,
        "low_contrast": sig_contrast,
        "decoder_disagree": sig_disagree,
        "low_top2_margin": sig_margin,
        "combined_flag": sig_unparse or sig_disagree or (sig_contrast and sig_margin) or (conf < min_conf),
    }


def apply_crop_remedy(crop: np.ndarray, pad_pct: float = 0.0, remove_border: bool = False) -> np.ndarray:
    """Applies generic crop border removal and context padding."""
    if crop is None or crop.size == 0:
        return crop
    out = crop.copy()
    h, w = out.shape[:2]
    paper_col = np.median(out, axis=(0, 1)).astype(np.uint8)

    if remove_border and h > 20 and w > 30:
        gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY) if out.ndim == 3 else out
        th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 8)
        h_kern = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, int(0.35 * w)), 1))
        h_lines = cv2.morphologyEx(th, cv2.MORPH_OPEN, h_kern)
        for y in range(int(0.16 * h)):
            if np.sum(h_lines[y, :] > 0) > 0.30 * w:
                out[max(0, y - 1):min(h, y + 2), :] = paper_col
        for y in range(int(0.84 * h), h):
            if np.sum(h_lines[y, :] > 0) > 0.30 * w:
                out[max(0, y - 1):min(h, y + 2), :] = paper_col

        v_kern = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, int(0.45 * h))))
        v_lines = cv2.morphologyEx(th, cv2.MORPH_OPEN, v_kern)
        for x in range(int(0.10 * w)):
            if np.sum(v_lines[:, x] > 0) > 0.40 * h:
                out[:, max(0, x - 1):min(w, x + 2)] = paper_col
        for x in range(int(0.90 * w), w):
            if np.sum(v_lines[:, x] > 0) > 0.40 * h:
                out[:, max(0, x - 1):min(w, x + 2)] = paper_col

    if pad_pct > 0.0:
        py = int(round(pad_pct * h))
        px = int(round(pad_pct * w))
        out = cv2.copyMakeBorder(out, py, py, px, px, cv2.BORDER_CONSTANT, value=paper_col.tolist())

    return out


def compute_q_cell_suggestions(
    q_vals: List[Optional[float]],
    q_flags_list: List[List[str]],
    total_val: Optional[float],
    total_flags: List[str],
    max_marks: float = 14.0,
) -> Optional[Tuple[int, List[float]]]:
    """
    Milestone 7c Part 2 Q-cell suggestion:
    total_marks is round_half_up(sum of q cells).
    When exactly one q cell is flagged or null and the total is valid and unflagged,
    offer BOTH candidates {total - sum(others), total - sum(others) - 0.5}
    (only multiples of 0.5 within [0, per-question maximum]).
    Returns (cell_index_0_based, [candidate1, candidate2, ...]) or None.
    """
    if len(q_vals) != 5 or len(q_flags_list) != 5:
        return None
    tot_active = [f for f in total_flags if f != "EMPTY_CELL"]
    if total_val is None or len(tot_active) > 0:
        return None

    flagged_indices = [
        j for j in range(5)
        if q_vals[j] is None or len([f for f in q_flags_list[j] if f != "EMPTY_CELL"]) > 0
    ]
    if len(flagged_indices) != 1:
        return None

    k = flagged_indices[0]
    other_sum = sum(float(q_vals[j]) for j in range(5) if j != k)
    c1 = round(float(total_val - other_sum), 2)
    c2 = round(float(total_val - other_sum - 0.5), 2)

    valid_cands = []
    for c in [c1, c2]:
        if 0.0 <= c <= max_marks and abs((c * 2.0) - round(c * 2.0)) < 1e-3:
            val_half = round(c * 2.0) / 2.0
            if val_half not in valid_cands:
                valid_cands.append(val_half)

    if not valid_cands:
        return None
    return k, valid_cands


def compute_sum_based_suggestion(
    q_vals: List[Optional[float]],
    q_flags_list: List[List[str]],
    total_val: Optional[float],
    total_flags: List[str],
    max_marks: float = 14.0,
) -> Optional[Tuple[int, float]]:
    """
    Parameter-free sum-based suggestion (Milestone 7b Part 4):
    Returns (cell_index_0_based, first_suggested_value) or None.
    """
    res = compute_q_cell_suggestions(q_vals, q_flags_list, total_val, total_flags, max_marks=max_marks)
    if res is None:
        return None
    return res[0], res[1][0]


def compute_total_suggestion_from_cells(
    q_vals: List[Optional[float]],
    q_flags_list: List[List[str]],
    total_val: Optional[float],
    total_flags: List[str],
) -> Optional[float]:
    """
    Milestone 7c Part 2 Total suggestion:
    When total is null or flagged and all five q cells are unflagged,
    offer suggestion = round_half_up(sum of the cells); flag SUGGESTED_FROM_CELLS; never in "value".
    """
    if len(q_vals) != 5 or len(q_flags_list) != 5:
        return None
    tot_active = [f for f in total_flags if f != "EMPTY_CELL"]
    if total_val is not None and len(tot_active) == 0:
        return None
    all_unflagged = all(
        q_vals[j] is not None and len([f for f in q_flags_list[j] if f not in ("EMPTY_CELL", "SUGGESTED_FRACTION")]) == 0
        for j in range(5)
    )
    if not all_unflagged:
        return None
    sum_q = sum(float(q_vals[j]) for j in range(5))
    return float(int(math.floor(sum_q + 0.5)))
