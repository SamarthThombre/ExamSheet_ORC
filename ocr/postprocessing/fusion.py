"""
Dual-source total marks fusion engine reconciling numeric grand_total candidates
and marks_in_words companion crop candidates.
"""

import re
from typing import Dict, Any, Optional
import pandas as pd

from ocr.postprocessing.cleaning import fix_total_marks, parse_tightened_gt
from ocr.postprocessing.word_parser import parse_marks_in_words


def has_leading_zero_single_digit(text: Any) -> bool:
    """Detects whether text has explicit leading zero (e.g. '05')."""
    if text is None or pd.isna(text):
        return False
    return bool(re.search(r"\b0[1-9]\b", str(text)))


def _attach_review_flag(
    result_dict: Dict[str, Any],
    raw_gt_orig: Any,
    raw_gt_tight: Any,
) -> Dict[str, Any]:
    """Evaluates whether fusion results require manual human review."""
    final_val = result_dict.get("final")
    status = result_dict.get("status", "")
    cand_orig = result_dict.get("cand_orig")
    cand_tight = result_dict.get("cand_tight")
    cand_words = result_dict.get("cand_words")

    dangling_eq_conflict = (
        cand_words is not None
        and final_val is not None
        and cand_words != final_val
        and not pd.isna(raw_gt_orig)
        and bool(re.search(r"=\s*(?:grand|ran|$)", str(raw_gt_orig), re.IGNORECASE))
    )

    needs_review = (
        final_val is None
        or status in {"BOTH_MISSING", "DISAGREE_KEEP_GT"}
        or dangling_eq_conflict
        or (
            isinstance(final_val, (int, float))
            and final_val < 10
            and not has_leading_zero_single_digit(raw_gt_orig)
            and not has_leading_zero_single_digit(raw_gt_tight)
            and status != "AGREE_EXACT"
        )
        or (status == "GT_ONLY" and cand_orig != cand_tight)
    )

    result_dict["needs_review"] = bool(needs_review)
    return result_dict


def combine_grand_total_and_words(
    raw_gt_orig: Any,
    raw_gt_tight: Any,
    raw_words: Any,
) -> Dict[str, Any]:
    """
    Fuses Strategy B grand_total, tightened grand_total, and marks_in_words candidates
    with zero-regression guards and diagnostic needs_review flagging.
    """
    cand_orig = fix_total_marks(raw_gt_orig)
    cand_tight = parse_tightened_gt(raw_gt_tight)
    word_info = parse_marks_in_words(raw_words)
    cand_words = word_info["value"]
    w_tens = word_info["tens"]
    w_ones = word_info["ones"]
    w_conf = word_info["conf"]

    if cand_words is not None and cand_words in {cand_orig, cand_tight}:
        return _attach_review_flag({
            "final": cand_words,
            "status": "AGREE_EXACT",
            "cand_orig": cand_orig,
            "cand_tight": cand_tight,
            "cand_words": cand_words,
        }, raw_gt_orig, raw_gt_tight)

    if cand_orig is not None and cand_orig == cand_tight:
        if cand_orig >= 10 or has_leading_zero_single_digit(raw_gt_orig) or has_leading_zero_single_digit(raw_gt_tight):
            return _attach_review_flag({
                "final": cand_orig,
                "status": "AGREE_ORIG_AND_TIGHT_GT",
                "cand_orig": cand_orig,
                "cand_tight": cand_tight,
                "cand_words": cand_words,
            }, raw_gt_orig, raw_gt_tight)

    if (
        cand_orig is not None
        and cand_tight == 0
        and cand_words is not None
        and cand_words % 10 == 0
        and cand_orig % 10 == 0
        and "only" in str(raw_words).lower()
    ):
        return _attach_review_flag({
            "final": cand_words,
            "status": "ROUND_TENS_RESOLVED_BY_WORDS_AND_TIGHT_ZERO",
            "cand_orig": cand_orig,
            "cand_tight": cand_tight,
            "cand_words": cand_words,
        }, raw_gt_orig, raw_gt_tight)

    if cand_orig is not None and cand_orig >= 10:
        cand_num = cand_orig
    elif cand_tight is not None and cand_tight >= 10:
        cand_num = cand_tight
    elif cand_orig is not None:
        cand_num = cand_orig
    elif cand_tight is not None:
        cand_num = cand_tight
    else:
        cand_num = None

    if cand_num is None:
        if cand_words is not None and w_conf >= 0.72:
            return _attach_review_flag({
                "final": cand_words,
                "status": "RECOVERED_BY_WORDS",
                "cand_orig": cand_orig,
                "cand_tight": cand_tight,
                "cand_words": cand_words,
            }, raw_gt_orig, raw_gt_tight)
        return _attach_review_flag({
            "final": None,
            "status": "BOTH_MISSING",
            "cand_orig": cand_orig,
            "cand_tight": cand_tight,
            "cand_words": cand_words,
        }, raw_gt_orig, raw_gt_tight)

    if cand_num < 10 and not has_leading_zero_single_digit(raw_gt_orig):
        if cand_tight is not None and cand_tight >= 10 and (cand_tight // 10 == cand_num or cand_tight % 10 == cand_num):
            return _attach_review_flag({
                "final": cand_tight,
                "status": "RECOVERED_BY_TIGHT_GT",
                "cand_orig": cand_orig,
                "cand_tight": cand_tight,
                "cand_words": cand_words,
            }, raw_gt_orig, raw_gt_tight)
        if cand_words is not None and 10 <= cand_words <= 65:
            if (cand_words // 10) == cand_num or (cand_words % 10) == cand_num or w_conf >= 0.82:
                return _attach_review_flag({
                    "final": cand_words,
                    "status": "COMPLETED_BY_WORDS",
                    "cand_orig": cand_orig,
                    "cand_tight": cand_tight,
                    "cand_words": cand_words,
                }, raw_gt_orig, raw_gt_tight)
        if w_tens is None and w_ones is not None and 0 <= w_ones <= 9 and 1 <= cand_num <= 6 and w_conf >= 0.75:
            combined_val = cand_num * 10 + w_ones
            return _attach_review_flag({
                "final": combined_val,
                "status": "FUSED_TENS_GT_ONES_WORDS",
                "cand_orig": cand_orig,
                "cand_tight": cand_tight,
                "cand_words": cand_words,
            }, raw_gt_orig, raw_gt_tight)

    if (cand_orig is None or cand_orig < 10) and cand_tight is not None and 10 <= cand_tight <= 65:
        if (
            cand_words is not None
            and 10 <= cand_words <= 65
            and cand_orig is not None
            and (cand_words // 10 == cand_orig)
            and (cand_tight // 10 == cand_orig)
            and w_conf >= 0.88
        ):
            return _attach_review_flag({
                "final": cand_words,
                "status": "DISAGREE_RESOLVED_BY_WORDS",
                "cand_orig": cand_orig,
                "cand_tight": cand_tight,
                "cand_words": cand_words,
            }, raw_gt_orig, raw_gt_tight)
        return _attach_review_flag({
            "final": cand_tight,
            "status": "RECOVERED_BY_TIGHT_GT",
            "cand_orig": cand_orig,
            "cand_tight": cand_tight,
            "cand_words": cand_words,
        }, raw_gt_orig, raw_gt_tight)

    if cand_words is not None and cand_tight == cand_words and cand_words != cand_orig:
        return _attach_review_flag({
            "final": cand_words,
            "status": "DISAGREE_RESOLVED_BY_TIGHT_AND_WORDS",
            "cand_orig": cand_orig,
            "cand_tight": cand_tight,
            "cand_words": cand_words,
        }, raw_gt_orig, raw_gt_tight)

    return _attach_review_flag({
        "final": cand_num,
        "status": "GT_ONLY",
        "cand_orig": cand_orig,
        "cand_tight": cand_tight,
        "cand_words": cand_words,
    }, raw_gt_orig, raw_gt_tight)
