"""
Diagnostic sanity validation for extracted exam cover sheet fields.
Detects suspicious values and triggers needs_review without altering extracted data.
"""

import re
import logging
from typing import Optional, Union, Tuple, List, Any

logger = logging.getLogger("ocr.validation.sanity")


class SanityValidator:
    """
    Lightweight, deterministic sanity validator.
    Rules identify anomalies without guessing replacements or silently clamping values.
    """

    @staticmethod
    def validate_fields(
        enrollment_no: Optional[str],
        subject_code: Optional[str],
        total_marks_corrected: Optional[Union[int, float, str]],
        fusion_needs_review: bool = False,
    ) -> Tuple[bool, List[str]]:
        """
        Validates extracted fields against known domain invariants:
          1. enrollment_no: Must be non-empty and match institutional pattern ^0801CA25\\d{4}$
          2. subject_code: Must be non-empty and match pattern ^C[A-Z0-9]{1,2}\\d{4,5}$
          3. total_marks_corrected: Must be numeric within valid exam bounds [0, 70]

        Returns:
          (needs_review: bool, sanity_reasons: List[str])
        """
        reasons: List[str] = []
        needs_review = bool(fusion_needs_review)

        # 1. Enrolment sanity check
        if enrollment_no is None or not str(enrollment_no).strip():
            needs_review = True
            reasons.append("Missing enrolment_no")
        elif not re.match(r"^0801CA25\d{4}$", str(enrollment_no).strip()):
            needs_review = True
            reasons.append(f"Suspicious enrolment_no format: '{enrollment_no}'")

        # 2. Subject code sanity check
        if not subject_code or not str(subject_code).strip():
            needs_review = True
            reasons.append("Missing subject_code")
        elif not re.match(r"^C[A-Z0-9]{1,2}\d{4,5}$", str(subject_code).strip()):
            needs_review = True
            reasons.append(f"Suspicious subject_code format: '{subject_code}'")

        # 3. Total marks sanity check (max 70 marks)
        if total_marks_corrected is None:
            needs_review = True
            reasons.append("Missing total_marks_corrected")
        else:
            try:
                numeric_marks = float(total_marks_corrected)
                if not (0 <= numeric_marks <= 70):
                    needs_review = True
                    reasons.append(f"Out of bounds total_marks: {numeric_marks}")
            except (ValueError, TypeError):
                needs_review = True
                reasons.append(f"Non-numeric total_marks: {total_marks_corrected}")

        if reasons:
            logger.info(f"Sanity check flagged needs_review: {'; '.join(reasons)}")

        return needs_review, reasons
