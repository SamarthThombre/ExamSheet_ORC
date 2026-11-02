"""
ocr_v2.review: Batch review signals and rescan vs review classification semantics.
Operates on batches of cover sheets for a single exam/format.
Supports duplicate enrolment detection, optional roster validation,
missing-from-batch tracking, and strict distinction between rescan_recommended
(physical scan failure) and needs_review (advisory review).
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, Tuple
from collections import Counter
import re


# -----------------------------------------------------------------------------
# SEMANTIC FLAG CLASSIFICATION RULES
# -----------------------------------------------------------------------------
# Based on tune-set empirical evidence:
# 1. Physical scan defect (accuracy <= 25% on tune):
#    - COMB_TOUCHES_PAGE_EDGE (0/1 = 0% accuracy)
#    - COMB_DETECTION_FAILED (0% accuracy)
#    - CROP_EMPTY (0% accuracy)
#    - EXCESSIVE_SKEW > 15.0 deg (severe scan distortion)
#    -> RESCAN_RECOMMENDED = True (and needs_review = True)
#
# 2. Advisory review (accuracy >= 75% on tune, or validation check):
#    - COMB_NOT_FULLY_DETECTED (4/4 = 100% accuracy on tune)
#    - LOW_COMB_QUALITY (4/4 = 100% accuracy on tune)
#    - EXCESSIVE_SKEW (4.0 to 15.0 deg, 3/4 = 75% accuracy on tune)
#    - LOW_CONFIDENCE (< 0.85, 15/18 = 83.3% accuracy on tune)
#    - INVALID_PREFIX
#    - INVALID_LENGTH
#    - ROLL_OUT_OF_RANGE
#    - DUPLICATE_ENROLMENT
#    - READ_NOT_IN_ROSTER
#    -> needs_review = True, rescan_recommended = False
# -----------------------------------------------------------------------------

RESCAN_FLAG_PATTERNS = [
    r"COMB_TOUCHES_PAGE_EDGE",
    r"COMB_DETECTION_FAILED",
    r"CROP_EMPTY",
    r"EXCESSIVE_SKEW_(?:1[5-9]|[2-9]\d|\d{3,})",  # Skew > 15 deg
    r"PAGE_CUT_OFF_OR_UNRECOGNISED",
]

ADVISORY_FLAG_PATTERNS = [
    r"COMB_NOT_FULLY_DETECTED",
    r"LOW_COMB_QUALITY",
    r"EXCESSIVE_SKEW",
    r"PAGE_ROTATED_180",
    r"LOW_CONFIDENCE",
    r"INVALID_PREFIX",
    r"INVALID_LENGTH",
    r"ROLL_OUT_OF_RANGE",
    r"ROLL_OUTLIER",
    r"DUPLICATE_ENROLMENT",
    r"READ_NOT_IN_ROSTER",
]


def classify_flags(reasons: List[str]) -> Tuple[bool, bool, List[str]]:
    """
    Separates a list of review reasons into:
      (rescan_recommended, needs_review, cleaned_reasons)
    """
    if not reasons:
        return False, False, []

    # Clean and deduplicate reasons, removing legacy 'RESCAN_RECOMMENDED: ' prefixes
    cleaned_reasons = []
    seen = set()
    for r in reasons:
        norm = re.sub(r"^RESCAN_RECOMMENDED:\s*", "", str(r).strip())
        if norm and norm not in seen:
            seen.add(norm)
            cleaned_reasons.append(norm)

    is_rescan = False
    for r in cleaned_reasons:
        for pat in RESCAN_FLAG_PATTERNS:
            if re.search(pat, r):
                is_rescan = True
                break
        if is_rescan:
            break

    is_review = is_rescan or (len(cleaned_reasons) > 0)
    return is_rescan, is_review, cleaned_reasons


@dataclass
class BatchReviewResult:
    """Batch-level review output."""
    total_sheets: int
    flagged_sheets: int
    rescan_count: int
    duplicate_enrolments: Dict[str, List[str]] = field(default_factory=dict)
    roster_provided: bool = False
    missing_from_batch: List[str] = field(default_factory=list)
    sheets: List[Dict[str, Any]] = field(default_factory=list)


class BatchReviewManager:
    """Applies bundle-level review signals: duplicate enrolment and optional roster checks."""

    def __init__(self):
        pass

    def evaluate_batch(
        self,
        sheets: List[Dict[str, Any]],
        roster: Optional[List[str]] = None,
        roll_range: Optional[Tuple[int, int]] = None,
    ) -> BatchReviewResult:
        """
        Evaluates batch-level review signals:
        1. Duplicate enrolment: sheets sharing identical predicted enrolment get DUPLICATE_ENROLMENT.
        2. Roll plausibility check: roll serial whose leading digit differs from batch majority (>= 90%)
           or falls outside configured roll_range gets ROLL_OUTLIER.
        3. Optional roster: sheets not in roster get READ_NOT_IN_ROSTER.
           Roster entries not seen on any sheet are reported as missing_from_batch.
        4. Updates per-sheet rescan_recommended, needs_review, and review_reasons.
        """
        if not sheets:
            return BatchReviewResult(
                total_sheets=0,
                flagged_sheets=0,
                rescan_count=0,
                duplicate_enrolments={},
                roster_provided=bool(roster),
                missing_from_batch=list(roster) if roster else [],
                sheets=[],
            )

        # Deep/shallow copy sheets to avoid unexpected mutation
        updated_sheets: List[Dict[str, Any]] = []
        enrol_map: Dict[str, List[int]] = {}

        # 1. Collect predicted enrolments
        for idx, s in enumerate(sheets):
            s_copy = dict(s)
            updated_sheets.append(s_copy)

            # Extract enrolment value
            enrol_val = None
            if "enrolment" in s_copy and isinstance(s_copy["enrolment"], dict):
                enrol_val = s_copy["enrolment"].get("value")
            elif "pred_enrol" in s_copy:
                enrol_val = s_copy["pred_enrol"]
            elif "enrollment_no" in s_copy:
                enrol_val = s_copy["enrollment_no"]

            enrol_str = str(enrol_val).strip() if enrol_val is not None else ""
            if enrol_str:
                enrol_map.setdefault(enrol_str, []).append(idx)

        # 2. Duplicate detection
        duplicate_map: Dict[str, List[str]] = {}
        for enrol_str, idx_list in enrol_map.items():
            if len(idx_list) > 1:
                sheet_names = [
                    updated_sheets[i].get("filename") or updated_sheets[i].get("sheet_name") or f"sheet_{i}"
                    for i in idx_list
                ]
                duplicate_map[enrol_str] = sheet_names
                for i in idx_list:
                    s = updated_sheets[i]
                    # Append DUPLICATE_ENROLMENT
                    self._add_sheet_reason(s, "DUPLICATE_ENROLMENT")

        # 3. Batch roll plausibility check (ROLL_OUTLIER)
        serials: List[str] = []
        sheet_serials: Dict[int, str] = {}
        for idx, s in enumerate(updated_sheets):
            enrol_val = None
            if "enrolment" in s and isinstance(s["enrolment"], dict):
                enrol_val = s["enrolment"].get("value")
            elif "pred_enrol" in s:
                enrol_val = s.get("pred_enrol")
            elif "enrollment_no" in s:
                enrol_val = s.get("enrollment_no")
            if enrol_val:
                m = re.search(r"(\d{4})$", str(enrol_val).strip())
                if m:
                    ser = m.group(1)
                    serials.append(ser)
                    sheet_serials[idx] = ser

        if len(serials) >= 3:
            leading_digits = [ser[0] for ser in serials]
            lead_counts = Counter(leading_digits)
            top_digit, top_count = lead_counts.most_common(1)[0]
            lead_ratio = top_count / float(len(serials))

            for idx, ser in sheet_serials.items():
                is_outlier = False
                if lead_ratio >= 0.90 and ser[0] != top_digit:
                    is_outlier = True
                if roll_range and len(roll_range) == 2:
                    try:
                        val_int = int(ser)
                        if val_int < roll_range[0] or val_int > roll_range[1]:
                            is_outlier = True
                    except ValueError:
                        pass
                if is_outlier:
                    self._add_sheet_reason(updated_sheets[idx], "ROLL_OUTLIER")
                    if "enrolment" in updated_sheets[idx] and isinstance(updated_sheets[idx]["enrolment"], dict):
                        e_reasons = updated_sheets[idx]["enrolment"].setdefault("review_reasons", [])
                        if "ROLL_OUTLIER" not in e_reasons:
                            e_reasons.append("ROLL_OUTLIER")

        # 4. Optional roster check
        roster_set: Optional[Set[str]] = set(roster) if roster else None
        seen_roster_entries: Set[str] = set()

        if roster_set is not None:
            for s in updated_sheets:
                enrol_val = None
                if "enrolment" in s and isinstance(s["enrolment"], dict):
                    enrol_val = s["enrolment"].get("value")
                elif "pred_enrol" in s:
                    enrol_val = s.get("pred_enrol")

                enrol_str = str(enrol_val).strip() if enrol_val is not None else ""
                if enrol_str:
                    if enrol_str in roster_set:
                        seen_roster_entries.add(enrol_str)
                    else:
                        self._add_sheet_reason(s, "READ_NOT_IN_ROSTER")
                else:
                    self._add_sheet_reason(s, "READ_NOT_IN_ROSTER")

            missing_from_batch = sorted(list(roster_set - seen_roster_entries))
        else:
            missing_from_batch = []

        # 4. Finalize per-sheet rescan_recommended vs needs_review
        flagged_count = 0
        rescan_count = 0

        for s in updated_sheets:
            reasons = self._get_sheet_reasons(s)
            rescan, review, clean_reasons = classify_flags(reasons)

            s["rescan_recommended"] = rescan
            s["needs_review"] = review
            s["review_reasons"] = clean_reasons

            if "enrolment" in s and isinstance(s["enrolment"], dict):
                e_reasons = s["enrolment"].get("review_reasons", [])
                e_rescan, e_review, e_clean = classify_flags(e_reasons)
                s["enrolment"]["rescan_recommended"] = e_rescan
                s["enrolment"]["needs_review"] = e_review
                s["enrolment"]["review_reasons"] = e_clean

            if "alignment" in s and isinstance(s["alignment"], dict):
                a_reasons = s["alignment"].get("review_reasons", [])
                a_rescan, a_review, a_clean = classify_flags(a_reasons)
                s["alignment"]["rescan_recommended"] = a_rescan
                s["alignment"]["needs_review"] = a_review
                s["alignment"]["review_reasons"] = a_clean

            if review:
                flagged_count += 1
            if rescan:
                rescan_count += 1

        return BatchReviewResult(
            total_sheets=len(updated_sheets),
            flagged_sheets=flagged_count,
            rescan_count=rescan_count,
            duplicate_enrolments=duplicate_map,
            roster_provided=bool(roster),
            missing_from_batch=missing_from_batch,
            sheets=updated_sheets,
        )

    def _get_sheet_reasons(self, s: Dict[str, Any]) -> List[str]:
        reasons = list(s.get("review_reasons", []))
        if "alignment" in s and isinstance(s["alignment"], dict):
            reasons.extend(s["alignment"].get("review_reasons", []))
        if "enrolment" in s and isinstance(s["enrolment"], dict):
            reasons.extend(s["enrolment"].get("review_reasons", []))
        if "subject_code" in s and isinstance(s["subject_code"], dict):
            reasons.extend(s["subject_code"].get("review_reasons", []))
        return reasons

    def _add_sheet_reason(self, s: Dict[str, Any], reason: str) -> None:
        reasons = s.setdefault("review_reasons", [])
        if reason not in reasons:
            reasons.append(reason)
        if "enrolment" in s and isinstance(s["enrolment"], dict):
            e_reasons = s["enrolment"].setdefault("review_reasons", [])
            if reason not in e_reasons:
                e_reasons.append(reason)
