"""
ocr_v2.batch: Batch-level subject_code consensus voting across exam bundles.
Operates on batches without mutating or altering individual per-sheet records.
Distinguishes subject_code_declared (teacher-provided) from subject_code_read (per-sheet, advisory).
Enforces minimum-evidence rules (at least 5 readable readings and >= 70% agreement).
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from collections import Counter


@dataclass
class BatchVoteResult:
    consensus_code: Optional[str]
    agreement_ratio: float
    total_sheets: int
    valid_votes: int
    vote_counts: Dict[str, int]
    disagreeing_sheets: List[str]
    unreadable_sheets: List[str] = field(default_factory=list)
    subject_code_declared: Optional[str] = None
    status: str = "OK"  # "OK" | "UNDETERMINED" | "EMPTY_BATCH" | "DECLARED_MISMATCH"
    evidence: Dict[str, Any] = field(default_factory=dict)


class BatchSubjectCodeConsensus:
    """Computes batch consensus vote for subject_code across cover sheets."""

    def __init__(
        self,
        min_agreement_threshold: float = 0.70,
        min_readable_readings: int = 5,
    ):
        self.min_agreement = min_agreement_threshold
        self.min_readable = min_readable_readings

    def compute_consensus(
        self,
        sheet_records: List[Dict[str, Any]],
        known_codes: Optional[List[str]] = None,
        subject_code_declared: Optional[str] = None,
    ) -> BatchVoteResult:
        """
        Calculates consensus subject code by majority vote across sheet records.
        Enforces minimum-evidence rule (>= 5 readable readings and >= 70% agreement).
        Does NOT alter or mutate per-sheet records.
        """
        if not sheet_records:
            return BatchVoteResult(
                consensus_code="UNDETERMINED",
                agreement_ratio=0.0,
                total_sheets=0,
                valid_votes=0,
                vote_counts={},
                disagreeing_sheets=[],
                unreadable_sheets=[],
                subject_code_declared=subject_code_declared,
                status="EMPTY_BATCH",
                evidence={"status": "EMPTY_BATCH", "readable_readings": 0},
            )

        known = set(known_codes) if known_codes else {"CT10718", "CT10715"}
        votes: List[str] = []
        sheet_votes: Dict[str, Optional[str]] = {}
        unreadable: List[str] = []

        for idx, rec in enumerate(sheet_records):
            s_name = rec.get("sheet_name", f"sheet_{idx}")
            code_val = None

            # Check metadata or field results
            if "fields" in rec and "subject_code" in rec["fields"]:
                s_res = rec["fields"]["subject_code"]
                if isinstance(s_res, dict):
                    code_val = s_res.get("metadata", {}).get("matched_code") or s_res.get("parsed_value")
                elif hasattr(s_res, "metadata"):
                    code_val = s_res.metadata.get("matched_code") or s_res.parsed_value
            elif "matched_code" in rec and rec["matched_code"]:
                code_val = rec["matched_code"]
            elif "subj_matched" in rec and rec["subj_matched"]:
                code_val = rec["subj_matched"]
            elif "subject_code" in rec and rec["subject_code"]:
                code_val = rec["subject_code"]

            sheet_votes[s_name] = code_val
            if code_val and code_val in known:
                votes.append(code_val)
            else:
                unreadable.append(s_name)

        # Minimum evidence check: at least 5 readable readings
        if len(votes) < self.min_readable:
            return BatchVoteResult(
                consensus_code="UNDETERMINED",
                agreement_ratio=0.0,
                total_sheets=len(sheet_records),
                valid_votes=len(votes),
                vote_counts=dict(Counter(votes)),
                disagreeing_sheets=[],
                unreadable_sheets=unreadable,
                subject_code_declared=subject_code_declared,
                status="UNDETERMINED",
                evidence={
                    "status": "UNDETERMINED_INSUFFICIENT_EVIDENCE",
                    "readable_readings": len(votes),
                    "min_required": self.min_readable,
                },
            )

        counts = Counter(votes)
        top_code, top_count = counts.most_common(1)[0]
        agreement_ratio = top_count / float(len(votes))
        batch_coverage = top_count / float(len(sheet_records))

        # Check agreement threshold (>= 70%)
        if agreement_ratio < self.min_agreement:
            return BatchVoteResult(
                consensus_code="UNDETERMINED",
                agreement_ratio=float(agreement_ratio),
                total_sheets=len(sheet_records),
                valid_votes=len(votes),
                vote_counts=dict(counts),
                disagreeing_sheets=[],
                unreadable_sheets=unreadable,
                subject_code_declared=subject_code_declared,
                status="UNDETERMINED",
                evidence={
                    "status": "UNDETERMINED_LOW_AGREEMENT",
                    "agreement_ratio": agreement_ratio,
                    "min_required": self.min_agreement,
                },
            )

        # Check against declared code if provided
        target_code = subject_code_declared if subject_code_declared else top_code
        status = "OK"
        if subject_code_declared and top_code != subject_code_declared:
            status = "DECLARED_MISMATCH"

        disagreements = [
            s_name
            for s_name, voted in sheet_votes.items()
            if voted is not None and voted in known and voted != target_code
        ]

        evidence = {
            "top_code": top_code,
            "target_code": target_code,
            "consensus_votes": top_count,
            "valid_votes": len(votes),
            "unreadable_count": len(unreadable),
            "total_sheets": len(sheet_records),
            "vote_distribution": dict(counts),
            "agreement_ratio": agreement_ratio,
            "batch_coverage": batch_coverage,
            "disagreement_count": len(disagreements),
            "status": status,
        }

        return BatchVoteResult(
            consensus_code=target_code,
            agreement_ratio=float(agreement_ratio),
            total_sheets=len(sheet_records),
            valid_votes=len(votes),
            vote_counts=dict(counts),
            disagreeing_sheets=disagreements,
            unreadable_sheets=unreadable,
            subject_code_declared=subject_code_declared,
            status=status,
            evidence=evidence,
        )


# Re-export batch review components for backward compatibility
from ocr_v2.review import BatchReviewManager, BatchReviewResult


def check_batch_sanity(sheet_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Checks batch-level consistency to detect catastrophic template or layout mismatch (Spike 14).
    Returns warning 'TEMPLATE_MISMATCH_SUSPECTED' if:
    - More than 50% of sheets return the same grand total (non-null), OR
    - More than 80% of question cells are unavailable/null/flagged.
    """
    if not sheet_records:
        return {"warning": None, "warnings": [], "reasons": [], "total_sheets": 0}

    total_sheets = len(sheet_records)
    warnings: List[str] = []
    reasons: List[str] = []

    # 1. Grand total concentration
    totals: List[float] = []
    for r in sheet_records:
        val = None
        if "grand_total" in r:
            gt = r["grand_total"]
            if isinstance(gt, dict):
                val = gt.get("value")
            elif hasattr(gt, "value"):
                val = gt.value
            else:
                val = gt
        elif "total_marks" in r:
            tm = r["total_marks"]
            if isinstance(tm, dict):
                val = tm.get("value")
            elif hasattr(tm, "value"):
                val = tm.value
            else:
                val = tm

        if val is not None and str(val).strip() not in ("", "nan", "null", "None"):
            try:
                totals.append(float(val))
            except (ValueError, TypeError):
                pass

    if totals and total_sheets > 0:
        counts = Counter(totals)
        most_common_val, count = counts.most_common(1)[0]
        concentration = count / float(total_sheets)
        if concentration > 0.50:
            warnings.append("TEMPLATE_MISMATCH_SUSPECTED")
            reasons.append(f"TOTAL_CONCENTRATION_{concentration:.1%}_VALUE_{most_common_val}")

    # 2. Unavailable question cells share
    total_q_cells = 0
    unavailable_q_cells = 0
    for r in sheet_records:
        q_list = r.get("q_marks") or r.get("question_marks")
        if isinstance(q_list, list):
            for q in q_list:
                total_q_cells += 1
                q_val = q.get("value") if isinstance(q, dict) else getattr(q, "value", None)
                q_flags = q.get("flags", []) if isinstance(q, dict) else getattr(q, "flags", [])
                if q_val is None or "UNAVAILABLE" in q_flags or "needs_review" in q_flags:
                    unavailable_q_cells += 1
        else:
            for i in range(1, 6):
                qk = f"q{i}"
                if qk in r:
                    total_q_cells += 1
                    val = r[qk]
                    if val is None or str(val).strip() in ("", "nan", "null", "None"):
                        unavailable_q_cells += 1

    if total_q_cells > 0:
        unavail_ratio = unavailable_q_cells / float(total_q_cells)
        if unavail_ratio > 0.80:
            if "TEMPLATE_MISMATCH_SUSPECTED" not in warnings:
                warnings.append("TEMPLATE_MISMATCH_SUSPECTED")
            reasons.append(f"Q_CELLS_UNAVAILABLE_{unavail_ratio:.1%}")

    return {
        "warning": warnings[0] if warnings else None,
        "warnings": warnings,
        "reasons": reasons,
        "total_sheets": total_sheets,
    }
