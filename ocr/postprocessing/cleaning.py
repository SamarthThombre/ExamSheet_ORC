"""
Strategy B cleaning and normalization for enrollment_no, subject_code, and total_marks.
"""

import math
import re
from typing import Optional, Union, Any
import pandas as pd


def round_half_up(n: float) -> int:
    return int(math.floor(n + 0.5))


# Legacy fallback parsers preserved for compatibility
def legacy_fix_total_marks(text: Any) -> Optional[int]:
    if pd.isna(text):
        return None
    text_str = str(text)
    if "=" in text_str:
        text_str = text_str.split("=")[-1]
    matches = re.findall(r"\d+(?:\.\d+)?", text_str)
    if matches:
        return round_half_up(float(matches[0]))
    return None


def legacy_fix_enrollment_no(text: Any) -> Any:
    if pd.isna(text) or text is None:
        return None
    s_raw = str(text).strip()
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
    # Normalize unicode dashes and Chinese 'one'
    s = s.replace("\u4e00", "1").replace("\u2014", "-").replace("\u2013", "-").replace("\u2212", "-")
    # Strip pre-printed booklet serial numbers (e.g., 'SR No. 13814', '16793 SR No.')
    s = re.sub(r"(?i)\b(?:SR|S\.?R\.?)\s*(?:NO|N0)?\.?\s*\d*", " ", s)
    s = re.sub(r"(?i)\b\d{5}\b\s*(?:SR|S\.?R\.?)", " ", s)
    # Strip degree titles (e.g., 'M.E./M.TECH./M.PHARMA/M.SC./MCA/MBA')
    s = re.sub(r"(?i)\b(?:M\.?E\.?|M\.?TECH|M\.?PHARMA|M\.?SC|MCA|MBA)\b", " ", s)
    # Strip (in words) / (in figures) and number words
    s = re.sub(r"(?i)\b(?:in\s*words|in\s*figures)\b.*", " ", s)
    s = re.sub(r"(?i)\b(?:zero|one|two|three|four|five|six|seven|eight|nine|zeso|zere|zern|eignt|youn|tou|clf|ounc)\b", " ", s)
    # Strip enrollment labels
    s = re.sub(
        r"(?i)\b(?:e|é)?n\s*r\s*(?:o|0)?\s*[li1)t]*\s*m?\s*e?\s*n?\s*t?\s*n\s*(?:o|0)\.?",
        " ",
        s,
    )
    s = re.sub(r"(?i)\b(?:enrlt|énrl|énrt|enrl|enroiment)\s*no\.?", " ", s)
    return s.strip()


def fix_total_marks(text: Any, max_marks: int = 70) -> Optional[int]:
    """Strategy B numerical marks parser with LHS=RHS rounding validation."""
    if text is None or pd.isna(text) or not str(text).strip():
        return None

    raw = str(text)
    if re.search(r"\b(?:instructions|examination|btech|pages|sgsits|nomenclature)\b", raw, re.IGNORECASE):
        return None
    raw_before_gt = re.split(r"(?i)grand\s*total|ran\s*otal", raw)[0].strip()
    if raw_before_gt and re.search(r"\d", raw_before_gt):
        s = raw_before_gt
    else:
        s = re.sub(r"(?i)\b(?:grand|ran|ra)?\s*(?:total|otal|tal|raal)\b\.?", " ", raw)
        s = re.sub(r"(?i)\bth\b", " ", s)

    s = s.replace("·", ".").replace("€", "=")
    s = re.sub(r"(?<=\d)\s*[Ss]\b", ".5", s)
    s = re.sub(r"(?<=\d)\.[Ss]\b", ".5", s)
    s = re.sub(r"\b[Ss](?=\d)", "5", s)
    s = re.sub(r"\b[Qq](?=\d)", "2", s)
    s = re.sub(r"(?<=\d)[gg]", "9", s)
    s = re.sub(r"(?<=\d)[zz](?==)", ".5", s)
    s = re.sub(r"=\s*\((\d)\b", r"=1\1", s)

    s_clean = s.strip()
    if re.fullmatch(r"\d\s+\d", s_clean):
        return int(s_clean.replace(" ", ""))

    # 1. Explicit addition expressions (e.g. '39+2=', '34+1=35', '37.5=38+3=9')
    add_match = re.search(r"(\d+(?:\.\d+)?)\s*\+\s*(\d+(?:\.\d+)?)", s)
    if add_match:
        a = float(add_match.group(1))
        b = float(add_match.group(2))
        add_sum = round_half_up(a + b)
        if "=" in s:
            rhs_part = s.split("=")[-1]
            rhs_nums = [round_half_up(float(x)) for x in re.findall(r"\d+(?:\.\d+)?", rhs_part)]
            if rhs_nums and abs(rhs_nums[0] - add_sum) <= 10 and rhs_nums[0] >= a:
                return rhs_nums[0]
        if 0 < add_sum <= max_marks:
            return add_sum

    # 2. Equations with '=': validate LHS rounding vs RHS
    if "=" in s or re.search(r"\b[1-6]\d[52]\s*-\s*\d", s):
        parts = re.split(r"=|-", s)
        lhs_nums = re.findall(r"\d+(?:\.\d+)?", parts[0].strip())
        rhs_nums = re.findall(r"\d+(?:\.\d+)?", parts[-1].strip())

        lhs_val = float(lhs_nums[-1]) if lhs_nums else None
        rhs_val = round_half_up(float(rhs_nums[0])) if rhs_nums else None

        if lhs_val is not None:
            if lhs_val > max_marks and 100 <= lhs_val <= 699:
                lhs_val = int(lhs_val // 10) + 0.5

            if 10 <= lhs_val <= max_marks:
                expected_from_lhs = int(math.floor(lhs_val)) + 1
                if rhs_val is None:
                    return expected_from_lhs
                if rhs_val < 10 and expected_from_lhs >= 10:
                    return expected_from_lhs
                if (rhs_val // 10) == (expected_from_lhs // 10) and rhs_val != expected_from_lhs:
                    if not (lhs_val < 20 and rhs_val == int(math.floor(lhs_val))):
                        return expected_from_lhs

        if rhs_val is not None and 0 <= rhs_val <= max_marks:
            return rhs_val

    # 3. No '=' sign: handle standard numbers or circle-border digits
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    if nums:
        raw_num_str = nums[0]
        val = float(raw_num_str)
        if val <= max_marks:
            return round_half_up(val)

        digits_only = re.sub(r"\D", "", raw_num_str)
        if len(digits_only) >= 4:
            last_two = int(digits_only[-2:])
            prev_two = int(digits_only[-4:-2])
            if 0 < last_two <= max_marks and (
                last_two == prev_two + 1 or (last_two % 10) == ((prev_two % 10) + 1)
            ):
                return last_two

        if len(digits_only) == 3:
            first_two = int(digits_only[:2])
            if 0 < first_two <= max_marks:
                return first_two

    return legacy_fix_total_marks(text)


def fix_enrollment_no(text: Any) -> Optional[str]:
    """Strategy B student enrollment/roll number normalizer with CA25 anchor."""
    if text is None or pd.isna(text) or not str(text).strip():
        return None

    raw = str(text)
    if re.search(r"\b(?:instructions|examination|btech|pages|sgsits|nomenclature|subject)\b", raw, re.IGNORECASE):
        return None
    cleaned = _strip_enrollment_label(raw)
    compact = re.sub(r"\s+", "", cleaned)
    if not compact:
        res = legacy_fix_enrollment_no(text)
        return str(res) if res and not pd.isna(res) else None

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

    res = legacy_fix_enrollment_no(cleaned)
    return str(res) if res and not pd.isna(res) else None


def clean_single_subject_code(raw_text: Optional[str], default: str = "CT10718") -> str:
    """Normalizes raw OCR text from subject_code crop to institutional code format."""
    if not raw_text or str(raw_text).strip().lower() in {"", "nan", "none"}:
        return default
    s = str(raw_text)
    # Strip booklet cover-page header and metadata
    s = re.sub(r"(?i)\b(?:main\s*answer\s*book|total\s*\d+\s*pages|exclusive\s*of\s*cover\s*page|cover\s*page)\b", " ", s)
    s = re.sub(r"(?i)\b(?:subject\s*nomenclature|nomenclature|branch|date|exam|suppl|answer\s*books|signature|invigilator)\b.*", " ", s)
    s = re.sub(r"(?i)\b(?:sub|subj|subject)?\s*code\b\.?", " ", s)

    # Map lookalike characters BEFORE stripping non-alphanumerics
    s = s.replace("+", "7").replace("/", "1").replace("|", "1")
    s = s.replace("(", "C").replace("[", "C").replace("{", "C")

    compact = re.sub(r"[^A-Za-z0-9]", "", s).upper()
    if not compact or len(compact) < 3:
        return default

    # Direct evidence checks for known exam codes
    if any(k in compact for k in ["CT10715", "C710715", "CTJ0715", "CT1071S", "C71071S", "CTLO71S", "CTJOFIS", "10715", "10915", "1075"]):
        return "CT10715"
    if any(k in compact for k in ["CT10718", "C710718", "CT1071B", "10718"]):
        return "CT10718"

    # General institutional code pattern C[A-Z0-9]{1,2}\d{4,5} with lookalike repair
    m = re.search(r"C[A-Z0-9]{1,2}[0-9A-Z]{4,5}", compact)
    if m:
        cand = m.group(0)
        prefix = cand[:2]
        digits = cand[2:]
        l_map = {"S": "5", "B": "8", "O": "0", "I": "1", "L": "1", "J": "1", "+": "7", "Z": "2", "G": "6"}
        norm_digits = "".join(l_map.get(ch, ch) for ch in digits)
        norm_code = prefix + norm_digits
        if norm_code in {"CT10715", "CT16715"}:
            return "CT10715"
        if norm_code == "CT10718":
            return "CT10718"
        if re.match(r"^C[A-Z0-9]{1,2}\d{4,5}$", norm_code):
            return norm_code

    return default


def fix_subject_code(df: pd.DataFrame, column_name: str = "subject_code") -> pd.DataFrame:
    """
    Batch mode extraction for subject_code across an exam batch.
    Extracts the most frequent valid code across the batch and populates f'{column_name}_corrected'.
    """
    if column_name not in df.columns:
        return df

    valid_texts = df[column_name].dropna().astype(str)
    cleaned_texts = valid_texts.str.replace(r"(?i)subject\s*code", "", regex=True)
    cleaned_texts = cleaned_texts.str.replace(r"[^A-Za-z0-9]", "", regex=True)

    if cleaned_texts.empty or cleaned_texts.mode().empty:
        df[f"{column_name}_corrected"] = "CT10718"
        return df

    batch_mode = cleaned_texts.mode()[0]
    df[f"{column_name}_corrected"] = batch_mode
    return df



def parse_tightened_gt(raw_gt_tight: Any) -> Optional[int]:
    """Parses tightened grand_total OCR, supporting parenthesized totals and consecutive rounding."""
    if raw_gt_tight is None or pd.isna(raw_gt_tight) or not str(raw_gt_tight).strip():
        return None
    s = str(raw_gt_tight).strip()

    m_paren = re.search(r"\((\d{2})\)\s*$", s)
    if m_paren:
        v = int(m_paren.group(1))
        if 10 <= v <= 65:
            return v

    m_consec = re.search(r"(\d{2})\D*1?(\d{2})\s*$", s)
    if m_consec:
        v1, v2 = int(m_consec.group(1)), int(m_consec.group(2))
        if v2 == v1 + 1 and 10 <= v2 <= 65:
            return v2

    val = fix_total_marks(s)
    if val is not None and val > 65:
        s_digits = str(val)
        if len(s_digits) == 4:
            first_two = int(s_digits[:2])
            if 10 <= first_two <= 65:
                return first_two
        return None
    return val
