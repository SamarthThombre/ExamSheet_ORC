"""
English number-in-words parser for marks_in_words companion crop OCR text.
Maps handwritten English cursive tokens to numeric scores.
"""

import re
import difflib
from typing import Dict, Any, Optional, Tuple
import pandas as pd

ONES_TEENS_VOCAB = {
    "zero": 0, "nil": 0,
    "one": 1, "ane": 1, "onee": 1, "ones": 1, "anes": 1,
    "two": 2, "trio": 2, "treo": 2, "tuo": 2, "too": 2, "tw0": 2, "trin": 2,
    "three": 3, "thre": 3, "thee": 3, "tharee": 3,
    "four": 4, "fowr": 4, "faur": 4, "fou": 4, "for": 4, "fos": 4,
    "five": 5, "fiue": 5, "fve": 5, "fiv": 5, "live": 5,
    "six": 6, "sie": 6, "sik": 6, "sin": 6, "siv": 6, "sixe": 6, "sive": 6,
    "seven": 7, "seuen": 7, "sevn": 7, "sven": 7,
    "eight": 8, "eigh": 8, "eigth": 8, "eigt": 8, "aight": 8, "cigt": 8, "ciget": 8, "cight": 8,
    "nine": 9, "nime": 9, "ninc": 9, "nince": 9, "mine": 9, "pine": 9, "nint": 9,
    "ten": 10,
    "eleven": 11, "elven": 11,
    "twelve": 12, "twelue": 12, "twleve": 12, "twoelve": 12,
    "thirteen": 13, "thirten": 13,
    "fourteen": 14, "fourten": 14, "forteen": 14,
    "fifteen": 15, "fiften": 15, "afteen": 15,
    "sixteen": 16, "sixten": 16,
    "seventeen": 17, "seventen": 17,
    "eighteen": 18, "eighten": 18,
    "nineteen": 19, "nineten": 19, "nintren": 19,
}

TENS_VOCAB = {
    "twenty": 20, "twety": 20, "twenly": 20, "twonty": 20, "tventy": 20,
    "toenty": 20, "wenty": 20, "teaty": 20, "tiweaty": 20, "tioenty": 20, "stewenty": 20,
    "thirty": 30, "thisty": 30, "thinty": 30, "thignty": 30, "thrty": 30, "thiry": 30,
    "thirly": 30, "thiatly": 30, "thivity": 30, "thiul": 30, "tharty": 30,
    "forty": 40, "fourty": 40, "focaty": 40, "focoaty": 40, "fowrity": 40, "fowsty": 40,
    "fowity": 40, "fowrty": 40, "forly": 40, "forti": 40, "farty": 40, "foty": 40,
    "fowatyy": 40, "fowly": 40, "fowibly": 40, "founty": 40, "foity": 40, "towly": 40, "bouate": 40,
    "fifty": 50, "fift": 50, "fifly": 50, "fify": 50, "fitty": 50, "flfty": 50, "fity": 50, "filey": 50,
    "sixty": 60, "sixly": 60, "sirty": 60, "rity": 60,
}

STOPWORDS = {
    "marks", "obtained", "in", "words", "word", "ords", "rds", "ds", "ods", "ros", "wors", "wards", "wrs", "wonts", "rednwrds",
    "only", "onl", "oly", "anly", "ouly", "nly", "full", "signature", "of", "examiner", "iner", "cand", "total", "grand", "do", "ns", "fi",
}


def match_word_token(tok: str) -> Tuple[Optional[str], Optional[int], float]:
    """Matches an individual token against tens and ones/teens vocabularies with fuzzy similarity."""
    t = re.sub(r"[^a-z]", "", str(tok).lower())
    if len(t) < 2 or t in STOPWORDS:
        return None, None, 0.0

    for suffix in ("anly", "only", "oly"):
        if t.endswith(suffix) and len(t) > len(suffix) + 2:
            t = t[: -len(suffix)]
    for prefix in ("ws", "ds", "rds", "ords"):
        if t.startswith(prefix) and len(t) > len(prefix) + 3:
            t = t[len(prefix) :]

    if t in TENS_VOCAB:
        return "tens", TENS_VOCAB[t], 1.0
    if t in ONES_TEENS_VOCAB:
        return "ones", ONES_TEENS_VOCAB[t], 1.0

    best_cat, best_val, best_score = None, None, 0.0
    for k, v in TENS_VOCAB.items():
        score = difflib.SequenceMatcher(None, t, k).ratio() + (0.08 if t[0] == k[0] else 0.0)
        if score > best_score:
            best_cat, best_val, best_score = "tens", v, score
    for k, v in ONES_TEENS_VOCAB.items():
        score = difflib.SequenceMatcher(None, t, k).ratio() + (0.08 if t[0] == k[0] else 0.0)
        if score > best_score:
            best_cat, best_val, best_score = "ones", v, score

    if best_score >= 0.70:
        return best_cat, best_val, min(1.0, best_score)
    return None, None, 0.0


def parse_marks_in_words(ocr_text: Any) -> Dict[str, Any]:
    """
    Parses noisy OCR text from the marks_in_words companion crop into a numeric candidate.

    Returns:
      {'value': int | None, 'tens': int | None, 'ones': int | None, 'conf': float, 'matched': str}
    """
    if ocr_text is None or pd.isna(ocr_text) or not str(ocr_text).strip():
        return {"value": None, "tens": None, "ones": None, "conf": 0.0, "matched": ""}

    raw_tokens = re.findall(r"[A-Za-z]+", str(ocr_text))
    tens_val, tens_conf = None, 0.0
    ones_val, ones_conf = None, 0.0
    matched_parts = []

    for tok in raw_tokens:
        cat, val, conf = match_word_token(tok)
        if cat == "tens" and conf > tens_conf:
            tens_val, tens_conf = val, conf
            matched_parts.append(f"{tok}->{val}({conf:.2f})")
        elif cat == "ones" and conf > ones_conf:
            ones_val, ones_conf = val, conf
            matched_parts.append(f"{tok}->{val}({conf:.2f})")

    if tens_val is not None and ones_val is not None and ones_val < 10:
        return {
            "value": tens_val + ones_val,
            "tens": tens_val,
            "ones": ones_val,
            "conf": round((tens_conf + ones_conf) / 2.0, 3),
            "matched": " + ".join(matched_parts),
        }
    if tens_val is not None and ones_val is None:
        return {
            "value": tens_val,
            "tens": tens_val,
            "ones": None,
            "conf": round(tens_conf * 0.85, 3),
            "matched": " + ".join(matched_parts),
        }
    if tens_val is None and ones_val is not None:
        return {
            "value": ones_val,
            "tens": None,
            "ones": ones_val,
            "conf": round(ones_conf * 0.85, 3),
            "matched": " + ".join(matched_parts),
        }
    return {"value": None, "tens": None, "ones": None, "conf": 0.0, "matched": ""}
