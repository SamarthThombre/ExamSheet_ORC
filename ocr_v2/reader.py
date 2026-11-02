"""
ocr_v2.reader: Batched ONNX recognition-only inference over enrolment comb strip
and subject-code crop using PP-OCRv6_medium_rec_onnx.
Strict validation flags: flags mismatches, never overwrites raw values.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
import math
import re
import cv2
import numpy as np

from .cell_reader import SharedCellReader, get_ort_session


DIGIT_LOOKALIKE_MAP = {
    "O": "0", "o": "0", "D": "0", "C": "0", "c": "0", "Q": "0", "a": "0",
    "○": "0", "。": "0", "°": "0", "①": "0",
    "I": "1", "l": "1", "L": "1", "t": "1", "T": "1", "J": "1", "j": "1",
    "⊥": "1", "上": "1", "±": "1", "土": "1", "之": "1", "」": "1",
    "(": "1", ")": "1", "/": "1", "\\": "1", "|": "1",
    "一": "1", "—": "1", "–": "1", "−": "1", "－": "1",
    "Z": "2", "z": "2", "r": "2",
    "S": "5", "s": "5",
    "G": "6", "b": "6",
    "=": "7", "≠": "7", "+": "7", "F": "7",
    "B": "8",
    "g": "9", "q": "9",
}

UPSIDE_DOWN_MAP = {
    "0": "0", "O": "0", "o": "0", "Q": "0", "a": "0",
    "8": "8", "B": "8",
    "1": "1", "I": "1", "l": "1", "T": "1", "(": "1", ")": "1",
    "2": "2", "Z": "2", "G": "2", "R": "2",
    "5": "5", "S": "5", "s": "5",
    "6": "9", "9": "6", "E": "9",
}


def _strip_enrollment_label(raw_text: str) -> str:
    s = str(raw_text)
    s = s.replace("\u4e00", "1").replace("\u2014", "-").replace("\u2013", "-").replace("\u2212", "-")
    s = re.sub(r"(?i)\b(?:SR|S\.?R\.?)\s*(?:NO|N0)?\.?\s*\d*", " ", s)
    s = re.sub(r"(?i)\b\d{5}\b\s*(?:SR|S\.?R\.?)", " ", s)
    s = re.sub(r"(?i)\b(?:M\.?E\.?|M\.?TECH|M\.?PHARMA|M\.?SC|MCA|MBA)\b", " ", s)
    s = re.sub(r"(?i)\b(?:in\s*words|in\s*figures)\b.*", " ", s)
    s = re.sub(r"(?i)\b(?:zero|one|two|three|four|five|six|seven|eight|nine|zeso|zere|zern|eignt|youn|tou|clf|ounc)\b", " ", s)
    s = re.sub(
        r"(?i)\b(?:e|é)?n\s*r\s*(?:o|0)?\s*[li1)t]*\s*m?\s*e?\s*n?\s*t?\s*n\s*(?:o|0)\.?",
        " ",
        s,
    )
    s = re.sub(r"(?i)\b(?:enrlt|énrl|énrt|enrl|enroiment)\s*no\.?", " ", s)
    return s.strip()


def legacy_fix_enrollment_no(text: Any) -> Any:
    if text is None:
        return None
    s_raw = str(text).strip()
    if not s_raw:
        return None
    if re.search(r"\b(?:instructions|examination|btech|pages|sgsits|nomenclature|subject)\b", s_raw, re.IGNORECASE):
        return None
    if not re.search(r"\d", s_raw):
        return None
    val = re.sub(
        r"(?i)enrol+ment\s*no\.?|enrlt\s*no\.?|enroiment\s*no\.?|enrl\s*no\.?|énrt\s*no\.?",
        "",
        s_raw,
    )
    val = re.sub(r"[^A-Za-z0-9]", "", val)
    val = re.sub(r"(?i)no$", "", val)
    if len(val) < 4:
        return None
    suffix = val[-4:]
    sub_map = {
        "S": "5", "s": "5", "C": "0", "c": "0", "g": "9", "q": "9", "Q": "9",
        "l": "1", "I": "1", "L": "1", "t": "1", "T": "1", "D": "0", "B": "8",
        "o": "0", "O": "0", "a": "0", "J": "1",
    }
    fixed_suffix = "".join([sub_map.get(c, c) for c in suffix])
    if not fixed_suffix.isdigit():
        return None
    return "0801CA25" + fixed_suffix


def fix_enrollment_no(text: Any) -> Optional[str]:
    """Strategy B student enrollment/roll number normalizer with CA25 anchor."""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    if re.search(r"\b(?:instructions|examination|btech|pages|sgsits|nomenclature|subject)\b", raw, re.IGNORECASE):
        return None
    cleaned = _strip_enrollment_label(raw)
    compact = re.sub(r"\s+", "", cleaned)
    if not compact:
        res = legacy_fix_enrollment_no(text)
        return str(res) if res else None

    # 1. Detect 180-degree inverted OCR reads
    has_forward_anchor = bool(re.search(r"[C\(G0O][A4R][2Zr][5S]", compact, re.IGNORECASE))
    ends_with_reversed_080 = bool(re.search(r"[0OQ][8B][0OQ5]$", compact, re.IGNORECASE))

    if not has_forward_anchor and ends_with_reversed_080 and len(compact) >= 8:
        rev_serial_chars = list(reversed(compact[:4]))
        serial_digits = "".join(
            UPSIDE_DOWN_MAP.get(c, DIGIT_LOOKALIKE_MAP.get(c, c)) for c in rev_serial_chars
        )
        if len(serial_digits) == 4 and serial_digits.isdigit():
            return "0801CA25" + serial_digits

    # 2. Extract 4-digit suffix immediately following CA25 anchor
    anchor_match = re.search(
        r"[C\(G0O][A4R][2Zr][5S](.+)$",
        compact,
        flags=re.IGNORECASE,
    )
    tail = anchor_match.group(1).strip() if anchor_match else compact[-4:]
    tail = re.sub(r"1/1", "1", tail)

    mapped = []
    for ch in tail:
        if ch.isdigit():
            mapped.append(ch)
        elif ch in DIGIT_LOOKALIKE_MAP:
            mapped.append(DIGIT_LOOKALIKE_MAP[ch])

    digits = "".join(mapped)
    if len(digits) >= 4:
        candidate = digits[:4]
        if anchor_match and candidate[0] in {"2", "3", "5"} and candidate[1] in {"0", "1"}:
            candidate = "1" + candidate[1:]
        return "0801CA25" + candidate

    # 3. Check for suffix appearing before the 0801CA25 prefix (e.g. multi-line OCR read: '1019 0801CA25')
    rev_anchor = re.search(r"(\d{4})0?801[C\(G0O][A4R][2Zr][5S]?", compact, flags=re.IGNORECASE)
    if rev_anchor:
        return "0801CA25" + rev_anchor.group(1)

    res = legacy_fix_enrollment_no(text)
    return str(res) if res else None


def extract_comb_box_deskewed(crop: np.ndarray, is_format_b: bool = False) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], str]:
    """
    Detects the 12-cell comb box in the enrolment crop using color mask + minAreaRect deskew.
    Returns: (aligned_comb_image, overlay_image, status_str)
    """
    if crop is None or crop.size == 0:
        return None, None, "COMB_NOT_FOUND"
    h, w = crop.shape[:2]
    r = crop[:, :, 2].astype(float)
    g = crop[:, :, 1].astype(float)
    b = crop[:, :, 0].astype(float)

    if is_format_b:
        mask = (r > 110) & (g > 50) & (g < 200) & (b < 130) & ((r - b) > 30)
    else:
        mask = (r > 100) & (r > 1.15 * g) & (r > 1.15 * b)

    mask = mask.astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 5))
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best_rect = None
    max_area = 0

    for cnt in contours:
        rect = cv2.minAreaRect(cnt)
        (cx, cy), (bw, bh), angle = rect
        if bw < bh:
            bw, bh = bh, bw
            angle += 90
        aspect = bw / float(bh) if bh > 0 else 0
        area = bw * bh
        if bw > 0.45 * w and 5.5 <= aspect <= 14.5 and 0.08 * h < bh < 0.45 * h:
            if area > max_area:
                max_area = area
                best_rect = ((cx, cy), (bw, bh), angle)

    if best_rect is None:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        thresh = cv2.adaptiveThreshold(~gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, -2)
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (int(w * 0.15), 1))
        h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, h_kernel)
        closed_edge = cv2.morphologyEx(h_lines, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25)))
        contours, _ = cv2.findContours(closed_edge, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            rect = cv2.minAreaRect(cnt)
            (cx, cy), (bw, bh), angle = rect
            if bw < bh:
                bw, bh = bh, bw
                angle += 90
            aspect = bw / float(bh) if bh > 0 else 0
            area = bw * bh
            if bw > 0.45 * w and 5.5 <= aspect <= 14.5 and 0.08 * h < bh < 0.45 * h:
                if area > max_area:
                    max_area = area
                    best_rect = ((cx, cy), (bw, bh), angle)

    if best_rect is None:
        return None, None, "COMB_NOT_FOUND"

    (cx, cy), (bw, bh), angle = best_rect
    rot_angle = angle if angle < 45 else angle - 180
    if rot_angle > 45:
        rot_angle -= 90
    elif rot_angle < -45:
        rot_angle += 90

    if abs(rot_angle) > 15.0:
        return None, None, f"EXCESSIVE_SKEW_{rot_angle:.1f}"

    M = cv2.getRotationMatrix2D((cx, cy), rot_angle, 1.0)
    rotated = cv2.warpAffine(crop, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    x1 = int(round(cx - bw / 2.0))
    y1 = int(round(cy - bh / 2.0))
    x2 = int(round(cx + bw / 2.0))
    y2 = int(round(cy + bh / 2.0))

    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)

    comb = rotated[y1:y2, x1:x2]
    if comb.shape[0] < 20 or comb.shape[1] < 200:
        return None, None, "DEGENERATE_BOX"

    overlay = rotated.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 0, 255), 2)
    return comb, overlay, "OK"


@dataclass
class FieldRecognitionResult:
    field_name: str
    raw_text: str
    parsed_value: Optional[str]
    confidence: float
    validation_flags: Dict[str, bool] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    needs_review: bool = False
    review_reasons: List[str] = field(default_factory=list)


@dataclass
class PageRecognitionResult:
    fields: Dict[str, FieldRecognitionResult]
    needs_review: bool
    review_reasons: List[str] = field(default_factory=list)


def levenshtein_distance(s1: str, s2: str) -> int:
    """Computes Levenshtein edit distance between two strings."""
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    distances = range(len(s1) + 1)
    for i2, c2 in enumerate(s2):
        distances_ = [i2 + 1]
        for i1, c1 in enumerate(s1):
            if c1 == c2:
                distances_.append(distances[i1])
            else:
                distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
        distances = distances_
    return distances[-1]


class BatchedONNXReader:
    """Executes single batched ONNX forward pass for enrolment strip and subject code."""

    def __init__(self, model_name: str = "PP-OCRv6_medium_rec", model_path: Optional[str] = None):
        self.cell_reader = SharedCellReader()
        self.session = get_ort_session(model_path=model_path)
        self.input_name = self.session.get_inputs()[0].name
        # Backward compatibility proxy so self.model.predict(...) works identically
        self.model = self

    def predict(self, crops: List[np.ndarray]) -> List[Dict[str, Any]]:
        """Inference parity helper replacing paddlex model.predict."""
        if not crops:
            return []
        x = self.cell_reader.preprocess_crops(crops)
        ort_outs = self.session.run(None, {self.input_name: x})
        preds = self.cell_reader.decode_predictions(ort_outs[0])
        return [{"rec_text": text, "rec_score": score} for text, score in preds]

    def prepare_enrolment_strip(self, crop: np.ndarray, is_format_b: bool) -> Tuple[Optional[np.ndarray], float]:
        """
        Extracts deskewed 12-cell comb box and applies red-channel line removal.
        Returns: (strip_bgr, quality_score)
        """
        if crop is None or crop.size == 0:
            return None, 0.0

        comb, _, status = extract_comb_box_deskewed(crop, is_format_b=is_format_b)
        if comb is None:
            # Fallback to direct red-channel on crop
            red = cv2.cvtColor(crop[:, :, 2], cv2.COLOR_GRAY2BGR)
            return red, 0.50

        # Red channel dropout: comb lines vanish into white background
        red_ch = comb[:, :, 2]
        strip_bgr = cv2.cvtColor(red_ch, cv2.COLOR_GRAY2BGR)
        return strip_bgr, 1.0

    def prepare_subject_strip(self, crop: np.ndarray) -> np.ndarray:
        """Applies red-channel dropout to isolate ink strokes from colored underlines/borders."""
        if crop is None or crop.size == 0:
            return np.zeros((48, 160, 3), dtype=np.uint8)
        red_ch = crop[:, :, 2]
        return cv2.cvtColor(red_ch, cv2.COLOR_GRAY2BGR)

    def read_fields(
        self,
        enrol_crop: Optional[np.ndarray],
        subj_crop: Optional[np.ndarray],
        format_id: str,
        format_config: Dict[str, Any],
        enrol_crop_status: str = "OK",
        subj_crop_status: str = "OK",
    ) -> PageRecognitionResult:
        """
        Executes batched ONNX recognition over enrolment comb strip and subject code crop.
        Validates prefix, roll range, patterns, and known subject codes.
        """
        is_b = (format_id == "format_v2")
        fields_cfg = format_config.get("fields", {})

        # Prepare both strips
        strip_e, q_e = self.prepare_enrolment_strip(enrol_crop, is_format_b=is_b) if enrol_crop is not None else (None, 0.0)
        strip_s = self.prepare_subject_strip(subj_crop) if subj_crop is not None else None

        batch_inputs = []
        indices = {}

        if strip_e is not None:
            indices["enrollment_no"] = len(batch_inputs)
            batch_inputs.append(strip_e)

        if strip_s is not None:
            indices["subject_code"] = len(batch_inputs)
            batch_inputs.append(strip_s)

        # Execute batched inference
        if batch_inputs:
            predictions = list(self.model.predict(batch_inputs))
        else:
            predictions = []

        field_results: Dict[str, FieldRecognitionResult] = {}
        page_reasons: List[str] = []

        # ---------------------------------------------------------------------
        # 1. PROCESS ENROLMENT NO
        # ---------------------------------------------------------------------
        if "enrollment_no" in indices:
            idx = indices["enrollment_no"]
            pred = predictions[idx]
            raw_e = str(pred.get("rec_text", ""))
            score_e = float(pred.get("rec_score", 0.0))

            cleaned_e = fix_enrollment_no(raw_e) or ""

            e_cfg = fields_cfg.get("enrollment_no", {})
            exp_prefix = e_cfg.get("expected_prefix", "")
            roll_range = e_cfg.get("roll_range", None)
            pattern = e_cfg.get("pattern", None)

            # Extract tail 4 digits (last 4 characters)
            tail = cleaned_e[-4:] if len(cleaned_e) >= 4 else ""
            tail_valid = len(tail) == 4 and tail.isdigit()
            enforced = (exp_prefix + tail) if (tail_valid and exp_prefix) else cleaned_e

            # Validation flags
            prefix_valid = enforced.startswith(exp_prefix) if exp_prefix else True
            expected_len = (len(exp_prefix) + 4) if exp_prefix else 12
            length_valid = (len(enforced) == expected_len)
            pattern_valid = bool(re.match(pattern, enforced)) if pattern else True

            tail_num = int(tail) if tail_valid else None
            if roll_range is not None and tail_num is not None:
                roll_range_valid = (roll_range[0] <= tail_num <= roll_range[1])
            else:
                roll_range_valid = True

            e_flags = {
                "prefix_valid": prefix_valid,
                "length_valid": length_valid,
                "pattern_valid": pattern_valid,
                "roll_range_valid": roll_range_valid,
            }

            e_reasons = []
            if enrol_crop_status != "OK":
                e_reasons.append(f"CROP_STATUS_{enrol_crop_status}")
                if enrol_crop_status in ["FALLBACK_NOMINAL_ROI", "COMB_NOT_FULLY_DETECTED", "COMB_TOUCHES_PAGE_EDGE", "CROP_EMPTY"]:
                    e_reasons.append(f"RESCAN_RECOMMENDED: {enrol_crop_status}")

            if not prefix_valid:
                e_reasons.append("INVALID_PREFIX")
            if not length_valid:
                e_reasons.append("INVALID_LENGTH")
            if not roll_range_valid:
                e_reasons.append("ROLL_OUT_OF_RANGE")
            if score_e < 0.85:
                e_reasons.append(f"LOW_CONFIDENCE_{score_e:.2f}")

            needs_review_e = len(e_reasons) > 0
            if needs_review_e:
                page_reasons.extend([f"ENROL_{r}" for r in e_reasons])

            field_results["enrollment_no"] = FieldRecognitionResult(
                field_name="enrollment_no",
                raw_text=raw_e,
                parsed_value=enforced if (length_valid and pattern_valid) else cleaned_e,
                confidence=score_e,
                validation_flags=e_flags,
                metadata={"tail_4": tail, "enforced_value": enforced},
                needs_review=needs_review_e,
                review_reasons=e_reasons,
            )

        # ---------------------------------------------------------------------
        # 2. PROCESS SUBJECT CODE
        # ---------------------------------------------------------------------
        if "subject_code" in indices:
            idx = indices["subject_code"]
            pred = predictions[idx]
            raw_s = str(pred.get("rec_text", ""))
            score_s = float(pred.get("rec_score", 0.0))

            s_cfg = fields_cfg.get("subject_code", {})
            known_codes = s_cfg.get("known_codes", [])
            s_pattern = s_cfg.get("pattern", r"^[A-Z]{2}\d{5}$")

            # Clean raw candidate (alphanumeric uppercase)
            cand = re.sub(r"(?i)subject\s*code|subject|code", "", raw_s)
            cand = re.sub(r"[^A-Za-z0-9]", "", cand).upper()

            # Normalize OCR lookalikes in candidate
            norm = cand.replace("O", "0").replace("I", "1").replace("S", "5").replace("Z", "2")

            # Direct regex search for standard code
            m_code = re.search(r"[A-Z]{2}\d{5}", norm)
            extracted = m_code.group(0) if m_code else cand

            # Distance match against known codes list
            best_code = None
            min_d = 999
            if known_codes:
                for probe in [extracted, norm, cand]:
                    for kc in known_codes:
                        d = levenshtein_distance(probe, kc)
                        if d < min_d:
                            min_d = d
                            best_code = kc

            matched_code = best_code if min_d <= 2 else None

            pattern_valid = bool(re.match(s_pattern, extracted)) if s_pattern else True
            known_match = (matched_code is not None)

            s_flags = {
                "pattern_valid": pattern_valid,
                "known_match": known_match,
                "exact_match": (extracted == matched_code) if matched_code else False,
            }

            s_reasons = []
            if min_d > 2:
                s_reasons.append("NO_KNOWN_CODE_MATCH")
            if score_s < 0.60:
                s_reasons.append(f"LOW_CONFIDENCE_{score_s:.2f}")

            needs_review_s = len(s_reasons) > 0
            if needs_review_s:
                page_reasons.extend([f"SUBJ_{r}" for r in s_reasons])

            field_results["subject_code"] = FieldRecognitionResult(
                field_name="subject_code",
                raw_text=raw_s,
                parsed_value=extracted,
                confidence=score_s,
                validation_flags=s_flags,
                metadata={
                    "matched_code": matched_code,
                    "edit_distance": min_d,
                    "candidate": cand,
                },
                needs_review=needs_review_s,
                review_reasons=s_reasons,
            )

        page_needs_review = len(page_reasons) > 0

        return PageRecognitionResult(
            fields=field_results,
            needs_review=page_needs_review,
            review_reasons=page_reasons,
        )

    def read_total_marks(self, total_crop: Optional[np.ndarray]) -> Dict[str, Any]:
        """Runs PP-OCR on total marks crop and parses with arithmetic rounding rules."""
        if total_crop is None or total_crop.size == 0:
            return {
                "value": None,
                "raw_text": "",
                "confidence": 0.0,
                "flags": ["EMPTY_CROP", "needs_review"],
            }
        preds = list(self.model.predict([total_crop]))
        if not preds:
            return {
                "value": None,
                "raw_text": "",
                "confidence": 0.0,
                "flags": ["PREDICT_EMPTY", "needs_review"],
            }
        raw_text = str(preds[0].get("rec_text", ""))
        conf = float(preds[0].get("rec_score", 0.0))
        val, flags = parse_total_marks(raw_text, conf)
        return {
            "value": val,
            "raw_text": raw_text,
            "confidence": round(conf, 4),
            "flags": flags,
        }

    def read_total_marks_m7(
        self,
        total_crop: Optional[np.ndarray],
        is_clipped: bool = False,
        is_format_b: bool = False,
        max_total: float = 70.0,
    ) -> Dict[str, Any]:
        """Runs PP-OCR on M7 Grand Total crop (with right-shifted fallback for Format A) and parses with M7 equation grammar."""
        if total_crop is None or total_crop.size == 0:
            return {
                "value": None,
                "suggestion": None,
                "raw_text": "",
                "confidence": 0.0,
                "flags": ["ANCHOR_NOT_FOUND", "needs_review"],
                "rescan_recommended": True,
            }

        batch = [total_crop]
        has_sub = (not is_format_b) and (not is_clipped) and (total_crop.shape[1] > 155)
        if has_sub:
            batch.append(total_crop[:, 82:])

        preds = list(self.model.predict(batch))
        raw_text = str(preds[0].get("rec_text", "")).strip()
        conf = float(preds[0].get("rec_score", 0.0))
        res = parse_grand_total_m7(raw_text, conf, is_clipped=is_clipped, max_total=max_total)

        if has_sub and len(preds) > 1 and (res["value"] is None or res["value"] < 10):
            sub_txt = str(preds[1].get("rec_text", "")).strip()
            sub_conf = float(preds[1].get("rec_score", 0.0))
            sub_res = parse_grand_total_m7(sub_txt, sub_conf, is_clipped=False, max_total=max_total)
            if sub_res["value"] is not None and sub_res["value"] >= 10:
                res = sub_res

        return res

    def read_subject_code_m7(
        self,
        left_crop: np.ndarray,
        right_crop: Optional[np.ndarray] = None,
        declared_code: Optional[str] = None,
        is_format_b: bool = False,
        cfg: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Reads single-line subject code crop(s) using BGR and red-channel dropout,
        validates against shape grammar 'CT' + 5 digits, and never overwrites declared_code.
        """
        inputs = [left_crop, self.prepare_subject_strip(left_crop)]
        if is_format_b and right_crop is not None and right_crop.size > 0:
            inputs.extend([right_crop, self.prepare_subject_strip(right_crop)])

        preds = list(self.model.predict(inputs))
        raw_l1, conf_l1 = str(preds[0].get("rec_text", "")).strip(), float(preds[0].get("rec_score", 0.0))
        raw_l2, conf_l2 = str(preds[1].get("rec_text", "")).strip(), float(preds[1].get("rec_score", 0.0))
        c_l1, v_l1 = parse_subject_code_shape_grammar(raw_l1, cfg=cfg)
        c_l2, v_l2 = parse_subject_code_shape_grammar(raw_l2, cfg=cfg)
        if v_l1 and (not v_l2 or conf_l1 >= conf_l2):
            code_l, valid_l, conf_l, raw_l = c_l1, v_l1, conf_l1, raw_l1
        elif v_l2:
            code_l, valid_l, conf_l, raw_l = c_l2, v_l2, conf_l2, raw_l2
        else:
            code_l, valid_l, conf_l, raw_l = c_l1, False, conf_l1, raw_l1

        flags = []
        two_copy_agree = False
        code_r = None
        valid_r = False

        if is_format_b and len(preds) >= 4:
            raw_r1, conf_r1 = str(preds[2].get("rec_text", "")).strip(), float(preds[2].get("rec_score", 0.0))
            raw_r2, conf_r2 = str(preds[3].get("rec_text", "")).strip(), float(preds[3].get("rec_score", 0.0))
            c_r1, v_r1 = parse_subject_code_shape_grammar(raw_r1, cfg=cfg)
            c_r2, v_r2 = parse_subject_code_shape_grammar(raw_r2, cfg=cfg)
            if v_r1 and (not v_r2 or conf_r1 >= conf_r2):
                code_r, valid_r, conf_r = c_r1, v_r1, conf_r1
            elif v_r2:
                code_r, valid_r, conf_r = c_r2, v_r2, conf_r2
            else:
                code_r, valid_r, conf_r = c_r1, False, conf_r1

            two_copy_agree = (valid_l and valid_r and code_l == code_r)
            if two_copy_agree:
                chosen_code = code_l
                chosen_conf = max(conf_l, conf_r)
            elif valid_l and valid_r:
                chosen_code = code_l if conf_l >= conf_r else code_r
                chosen_conf = max(conf_l, conf_r)
            else:
                chosen_code = code_l if valid_l else (code_r if valid_r else code_l)
                chosen_conf = conf_l if valid_l else (conf_r if valid_r else conf_l)
            shape_valid = valid_l or valid_r
            enable_disagrees = False
            if cfg:
                sc_cfg = cfg.get("fields", {}).get("subject_code", {}) or cfg.get("m7_single_line_crop", {})
                enable_disagrees = bool(
                    sc_cfg.get("enable_subject_code_disagrees", False)
                    or cfg.get("enable_subject_code_disagrees", False)
                )
            if enable_disagrees and declared_code and two_copy_agree and chosen_code != declared_code and conf_l >= 0.85 and conf_r >= 0.85:
                flags.append("SUBJECT_CODE_DISAGREES")
        else:
            chosen_code = code_l
            chosen_conf = conf_l
            shape_valid = valid_l
            enable_disagrees = False
            if cfg:
                sc_cfg = cfg.get("fields", {}).get("subject_code", {}) or cfg.get("m7_single_line_crop", {})
                enable_disagrees = bool(
                    sc_cfg.get("enable_subject_code_disagrees", False)
                    or cfg.get("enable_subject_code_disagrees", False)
                )
            if enable_disagrees and declared_code and shape_valid and chosen_code != declared_code:
                diff_c = sum(1 for a, b in zip(chosen_code or "", declared_code) if a != b)
                if conf_l >= 0.96 and diff_c >= 3:
                    flags.append("SUBJECT_CODE_DISAGREES")

        if not shape_valid:
            if "INVALID_SHAPE" not in flags:
                flags.append("INVALID_SHAPE")
            if "needs_review" not in flags:
                flags.append("needs_review")
            final_val = declared_code if declared_code else None
        else:
            final_val = declared_code if declared_code else chosen_code

        return {
            "declared_code": declared_code,
            "value": final_val,
            "advisory_read": chosen_code,
            "raw_text": raw_l,
            "confidence": round(float(chosen_conf), 4),
            "shape_valid": shape_valid,
            "copy2_read": code_r,
            "two_copy_agreement": two_copy_agree,
            "flags": flags,
        }


def parse_total_marks(raw_text: str, score: float) -> Tuple[Optional[int], List[str]]:
    """
    Parses handwritten grand total marks with strict arithmetic rules:
    - When '=' and readable right-hand side exist, use right-hand side.
    - When string ends with '=' or contains '.5' with no readable RHS, return None with RHS_MISSING and needs_review.
    - Honest validation: no ground-truth sum check.
    - Flag values > 70 or < 0, low confidence < 0.85, non-numeric.
    """
    flags = []
    if not raw_text or not raw_text.strip():
        return None, ["EMPTY_READ", "needs_review"]

    txt = raw_text.strip()
    txt = txt.replace("O", "0").replace("o", "0")
    txt = re.sub(r"[:;]+", "=", txt)

    if score < 0.85:
        flags.append(f"LOW_CONF_{score:.2f}")

    if "=" in txt:
        parts = txt.split("=")
        lhs = parts[0].strip()
        rhs = parts[-1].strip()

        # Check if RHS is missing / empty
        if not rhs:
            flags.extend(["RHS_MISSING", "needs_review"])
            return None, flags

        # Check if RHS contains valid digits
        rhs_digits = re.findall(r"-?\d+(?:\.\d+)?", rhs)
        if rhs_digits:
            # Handle addition in RHS e.g. 27+1
            if "+" in rhs:
                try:
                    val = sum(float(x) for x in rhs_digits)
                    int_val = int(math.floor(val + 0.5))
                    if int_val > 70 or int_val < 0:
                        flags.extend(["OUT_OF_RANGE", "needs_review"])
                        return None, flags
                    return int_val, flags
                except Exception:
                    pass

            # Extract the last integer in RHS
            rhs_str = rhs_digits[-1]
            try:
                val = float(rhs_str)
                int_val = int(math.floor(val + 0.5))
                if int_val > 70 or int_val < 0:
                    flags.extend(["OUT_OF_RANGE", "needs_review"])
                    return None, flags
                return int_val, flags
            except Exception:
                pass

        # RHS had no readable digits
        flags.extend(["RHS_MISSING", "needs_review"])
        return None, flags

    # No '=' present: if string contains '.5' with no RHS, flag RHS_MISSING
    if ".5" in txt or ",5" in txt:
        flags.extend(["RHS_MISSING", "needs_review"])
        return None, flags

    # Check for arithmetic addition without '=', e.g. 39+2
    if "+" in txt:
        add_parts = re.findall(r"-?\d+(?:\.\d+)?", txt)
        if len(add_parts) >= 2:
            val = sum(float(x) for x in add_parts)
            int_val = int(math.floor(val + 0.5))
            if int_val > 70 or int_val < 0:
                flags.extend(["OUT_OF_RANGE", "needs_review"])
                return None, flags
            return int_val, flags

    # Plain number
    m = re.findall(r"-?\d+(?:\.\d+)?", txt)
    if not m:
        flags.extend(["NON_NUMERIC", "needs_review"])
        return None, flags

    val = float(m[0])
    int_val = int(math.floor(val + 0.5))
    if int_val > 70 or int_val < 0:
        flags.extend(["OUT_OF_RANGE", "needs_review"])
        return None, flags

    if len(flags) > 0:
        flags.append("needs_review")
    return int_val, flags


# -----------------------------------------------------------------------------
# MILESTONE 7 PORTED GRAND TOTAL & SUBJECT CODE PARSERS
# -----------------------------------------------------------------------------

# Single-character lookalike map for Grand Total RHS (only entries with >= 3 DEV cell/total hits retained):
# 'O'->'0' (4 DEV cells, 28 DEV total), 'o'->'0' (4 DEV cells, 61 DEV total),
# 'S'->'5' (4 DEV totals, 35 DEV cells), 's'->'5' (1 DEV total, 12 DEV cells)
RHS_LOOKALIKE_MAP = str.maketrans({
    "O": "0", "o": "0",
    "S": "5", "s": "5",
})


def _eval_lhs_expr(lhs_str: str) -> Optional[float]:
    if any(ch in lhs_str for ch in ("%", "#")):
        return None
    lhs_clean = lhs_str.translate(RHS_LOOKALIKE_MAP)
    if "+" in lhs_clean:
        m_parts = re.findall(r"\d{1,2}(?:\.5)?", lhs_clean)
        if len(m_parts) >= 2:
            try:
                return sum(float(x) for x in m_parts)
            except ValueError:
                pass
    m_lhs = re.search(r"^[^\d]*(\d{1,2}(?:\.5)?)", lhs_clean)
    return float(m_lhs.group(1)) if m_lhs else None


def is_digit_like_total(s: str) -> bool:
    """Returns True only if token could represent a valid grand total mark or equation."""
    if not s or len(s) > 16:
        return False
    if re.search(r"\b[A-Za-z]{2,}\b", s):
        return False
    allowed = set("0123456789OoSs+=.:()- /\\")
    non_ws = [c for c in s if not c.isspace()]
    if not non_ws:
        return False
    valid_count = sum(1 for c in non_ws if c in allowed)
    has_digit = any(c.isdigit() for c in non_ws)
    return has_digit and ((valid_count / len(non_ws)) >= 0.5)


def parse_grand_total_m7(
    raw_text: str,
    conf: float = 1.0,
    is_clipped: bool = False,
    max_total: float = 70.0,
) -> Dict[str, Any]:
    """
    Milestone 7 generic Grand Total parser:
    - Clipped check -> TOTAL_CLIPPED, value=None, rescan_recommended=True.
    - Equation grammar -> normalizes '=' (':', '-', '2', 'z'), strips circles/parens, maps lookalikes on RHS.
    - Round-half-up suggestion -> when LHS ends in '.5' and RHS is missing -> value=None, suggestion=round_half_up(LHS), flag SUGGESTION_ONLY.
    """
    flags = []
    if is_clipped:
        return {
            "value": None,
            "suggestion": None,
            "raw_text": raw_text,
            "confidence": round(float(conf), 4),
            "flags": ["TOTAL_CLIPPED", "needs_review"],
            "rescan_recommended": True,
        }

    s = str(raw_text or "").strip()
    if not s:
        return {
            "value": None,
            "suggestion": None,
            "raw_text": raw_text,
            "confidence": round(float(conf), 4),
            "flags": ["EMPTY", "RHS_MISSING", "needs_review"],
            "rescan_recommended": False,
        }

    if not is_digit_like_total(s):
        return {
            "value": None,
            "suggestion": None,
            "raw_text": raw_text,
            "confidence": round(float(conf), 4),
            "flags": ["NON_NUMERIC", "needs_review"],
            "rescan_recommended": False,
        }

    s_norm = s.replace(",", ".")
    if not re.search(r"\d", s_norm):
        return {
            "value": None,
            "suggestion": None,
            "raw_text": raw_text,
            "confidence": round(float(conf), 4),
            "flags": ["NO_DIGIT_FOUND", "needs_review"],
            "rescan_recommended": False,
        }
    def _fix_half_rounded_sep(m):
        lhs_f = float(m.group(1))
        rhs_i = int(m.group(2))
        if abs(rhs_i - lhs_f) <= 1.0 or rhs_i == int(math.floor(lhs_f + 0.5)):
            return f"{m.group(1)}={m.group(2)}"
        return m.group(0)

    s_norm = re.sub(r"(\d{1,2}\.5)[127zZ\-/|](\d{1,2})\b", _fix_half_rounded_sep, s_norm)
    s_norm = re.sub(r"(\d{1,2}):5\s*=", r"\1.5=", s_norm)
    s_norm = s_norm.replace(":", "=")

    if "=" not in s_norm:
        m_paren = re.search(r"\(([0-9A-Za-z]{2})\)[A-Za-z]*$", s_norm)
        if m_paren:
            cand_p = m_paren.group(1).translate(RHS_LOOKALIKE_MAP)
            if re.match(r"^\d{2}$", cand_p) and 0 <= int(cand_p) <= max_total:
                s_norm = s_norm[:m_paren.start()] + "=" + cand_p

    if "=" in s_norm:
        parts = s_norm.split("=")
        lhs_str = parts[0].strip()
        rhs_str = parts[-1].strip()
        lhs_val = _eval_lhs_expr(lhs_str)

        rhs_stripped = re.sub(r"[\(\)\[\]\{\}/\\]", "", rhs_str).strip()
        rhs_mapped = rhs_stripped.translate(RHS_LOOKALIKE_MAP)
        if re.search(r"[a-zA-Z]", rhs_mapped):
            flags.append("UNMAPPED_ALPHA")
            flags.append("needs_review")
        m_rhs = re.findall(r"\d+(?:\.\d+)?", rhs_mapped)

        if m_rhs:
            try:
                r_val = float(m_rhs[-1])
                # Check for stray leading digit when r_val > max_total (e.g. '128' with LHS 27.5 -> '28')
                if r_val > max_total and len(m_rhs[-1]) >= 3:
                    tail_val = float(m_rhs[-1][-2:])
                    if 0.0 < tail_val <= max_total and lhs_val is not None and abs(tail_val - lhs_val) <= 2.0:
                        r_val = tail_val
                if r_val <= 0.0:
                    return {
                        "value": None,
                        "suggestion": None,
                        "raw_text": raw_text,
                        "confidence": round(float(conf), 4),
                        "flags": ["ZERO_TOTAL_REJECTED", "needs_review"],
                        "rescan_recommended": False,
                    }
                if 0.0 < r_val <= max_total and abs(r_val - round(r_val)) < 1e-4:
                    if lhs_val is not None and 10.0 <= lhs_val <= max_total and abs(r_val - lhs_val) > 2.0:
                        sug = int(math.floor(lhs_val + 0.5))
                        if len(m_rhs[-1]) == 1 and int(r_val) == (sug // 10) and abs(lhs_val - math.floor(lhs_val) - 0.5) < 1e-4:
                            flags.append("RHS_TRUNCATED_RECOVERED")
                            flags.append("needs_review")
                            return {
                                "value": sug,
                                "suggestion": sug,
                                "raw_text": raw_text,
                                "confidence": round(float(conf), 4),
                                "flags": flags,
                                "rescan_recommended": False,
                            }
                        return {
                            "value": None,
                            "suggestion": sug,
                            "raw_text": raw_text,
                            "confidence": round(float(conf), 4),
                            "flags": ["RHS_MISSING", "SUGGESTION_ONLY", "needs_review"],
                            "rescan_recommended": False,
                        }
                    if lhs_val is None:
                        flags.append("LHS_UNPARSED")
                        flags.append("needs_review")
                    if conf < 0.55:
                        flags.append("LOW_CONFIDENCE")
                        flags.append("needs_review")
                    return {
                        "value": int(round(r_val)),
                        "suggestion": int(round(r_val)),
                        "raw_text": raw_text,
                        "confidence": round(float(conf), 4),
                        "flags": flags,
                        "rescan_recommended": False,
                    }
            except ValueError:
                pass

        if lhs_val is not None and abs((lhs_val - math.floor(lhs_val)) - 0.5) < 1e-4:
            sug = int(math.floor(lhs_val + 0.5))
            return {
                "value": None,
                "suggestion": sug,
                "raw_text": raw_text,
                "confidence": round(float(conf), 4),
                "flags": ["RHS_MISSING", "SUGGESTION_ONLY", "needs_review"],
                "rescan_recommended": False,
            }

        return {
            "value": None,
            "suggestion": int(math.floor(lhs_val + 0.5)) if lhs_val is not None else None,
            "raw_text": raw_text,
            "confidence": round(float(conf), 4),
            "flags": ["RHS_MISSING", "needs_review"],
            "rescan_recommended": False,
        }

    s_mapped = re.sub(r"[\(\)\[\]\{\}]", "", s_norm).translate(RHS_LOOKALIKE_MAP)
    m_all = re.findall(r"\d+(?:\.\d+)?", s_mapped)
    if not m_all:
        return {
            "value": None,
            "suggestion": None,
            "raw_text": raw_text,
            "confidence": round(float(conf), 4),
            "flags": ["NON_NUMERIC", "RHS_MISSING", "needs_review"],
            "rescan_recommended": False,
        }

    if len(m_all) >= 2:
        try:
            v_first = float(m_all[0])
            v_last = float(m_all[-1])
            if abs(v_last - round(v_last)) < 1e-4 and 0 <= v_last <= max_total and abs(v_last - v_first) <= 2.0:
                return {
                    "value": int(round(v_last)),
                    "suggestion": int(round(v_last)),
                    "raw_text": raw_text,
                    "confidence": round(float(conf), 4),
                    "flags": flags,
                    "rescan_recommended": False,
                }
        except ValueError:
            pass

    val_single = float(m_all[0])
    if abs((val_single - math.floor(val_single)) - 0.5) < 1e-4:
        sug = int(math.floor(val_single + 0.5))
        return {
            "value": None,
            "suggestion": sug,
            "raw_text": raw_text,
            "confidence": round(float(conf), 4),
            "flags": ["RHS_MISSING", "SUGGESTION_ONLY", "needs_review"],
            "rescan_recommended": False,
        }

    if val_single <= 0.0:
        return {
            "value": None,
            "suggestion": None,
            "raw_text": raw_text,
            "confidence": round(float(conf), 4),
            "flags": ["ZERO_TOTAL_REJECTED", "needs_review"],
            "rescan_recommended": False,
        }

    if 0.0 < val_single <= max_total and abs(val_single - round(val_single)) < 1e-4:
        if conf < 0.55:
            flags.append("LOW_CONFIDENCE")
            flags.append("needs_review")
        return {
            "value": int(round(val_single)),
            "suggestion": int(round(val_single)),
            "raw_text": raw_text,
            "confidence": round(float(conf), 4),
            "flags": flags,
            "rescan_recommended": False,
        }

    return {
        "value": None,
        "suggestion": None,
        "raw_text": raw_text,
        "confidence": round(float(conf), 4),
        "flags": ["OUT_OF_RANGE", "needs_review"],
        "rescan_recommended": False,
    }


# Single-character lookalike map for Subject Code 5-digit tail (only entries with >= 3 DEV Subject Code hits retained):
# 'O'->'0' (24 DEV), 'o'->'0' (57 DEV), 'C'->'0' (116 DEV), 'U'->'0' (5 DEV),
# 'I'->'1' (34 DEV), 'l'->'1' (11 DEV), 'i'->'1' (62 DEV), 't'->'1' (63 DEV), 'L'->'1' (14 DEV), 'J'->'1' (5 DEV), 'T'->'1' (128 DEV),
# 'Z'->'2' (20 DEV), 'z'->'2' (51 DEV), 'E'->'3' (26 DEV), 'A'->'4' (9 DEV), 'h'->'4' (57 DEV),
# 'S'->'5' (28 DEV), 's'->'5' (9 DEV), 'G'->'6' (9 DEV), 'g'->'9' (57 DEV)
SUBJ_DIGIT_MAP = str.maketrans({
    "O": "0", "o": "0", "C": "0", "U": "0",
    "I": "1", "l": "1", "i": "1", "t": "1", "L": "1", "J": "1", "T": "1",
    "Z": "2", "z": "2",
    "E": "3",
    "A": "4", "h": "4",
    "S": "5", "s": "5",
    "G": "6",
    "g": "9",
})


def parse_subject_code_shape_grammar(
    raw_text: str,
    cfg: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], bool]:
    """
    Shape grammar 'CT' + 5 digits with a generic single-character lookalike map.
    Shape pattern, prefix, and digit count come from format config.
    Does NOT snap to a list of known codes.
    Returns (parsed_code, is_shape_valid).
    """
    if not raw_text:
        return None, False
    s_raw = str(raw_text).strip()
    if re.search(r"\b(?:instructions|examination|btech|total|pages|sgsits|nomenclature|subject)\b", s_raw, re.IGNORECASE):
        return None, False
    clean = re.sub(r"[^A-Za-z0-9]", "", raw_text).upper()
    if len(clean) < 5:
        return None, False

    if cfg and "fields" in cfg:
        sc_cfg = cfg.get("fields", {}).get("subject_code", {}).get("m7_single_line_crop", {})
    else:
        sc_cfg = cfg or {}
    prefix = str(sc_cfg.get("shape_grammar_prefix", "CT"))
    n_digits = int(sc_cfg.get("shape_grammar_digits", 5))
    shape_pat = str(sc_cfg.get("shape_pattern", rf"[CGO0][TI1L7]([A-Z0-9]{{{n_digits}}})"))
    digit_pat = rf"^\d{{{n_digits}}}$"

    m = re.search(shape_pat, clean)
    if m:
        tail_raw = m.group(1) if m.lastindex and m.lastindex >= 1 else clean[-n_digits:]
        tail_digits = tail_raw.translate(SUBJ_DIGIT_MAP)
        if re.match(digit_pat, tail_digits):
            return prefix + tail_digits, True

    if len(clean) >= (n_digits + 1) and clean[0] in ("C", "G", "O"):
        tail_raw = clean[-n_digits:]
        tail_digits = tail_raw.translate(SUBJ_DIGIT_MAP)
        if re.match(digit_pat, tail_digits):
            return prefix + tail_digits, True

    return None, False



