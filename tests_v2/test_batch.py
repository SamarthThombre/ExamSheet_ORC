"""
Unit tests for ocr_v2.batch.
"""

import pytest
from ocr_v2.batch import BatchSubjectCodeConsensus, BatchVoteResult


def test_batch_consensus_empty():
    consensus = BatchSubjectCodeConsensus()
    res = consensus.compute_consensus([])
    assert res.consensus_code == "UNDETERMINED"
    assert res.total_sheets == 0
    assert res.agreement_ratio == 0.0
    assert res.status == "EMPTY_BATCH"


def test_batch_consensus_insufficient_evidence():
    consensus = BatchSubjectCodeConsensus(min_readable_readings=5)
    # Only 4 readable sheets
    records = [{"sheet_name": f"sheet_{i}", "matched_code": "CT10718"} for i in range(4)]
    res = consensus.compute_consensus(records, known_codes=["CT10718", "CT10715"])
    assert res.consensus_code == "UNDETERMINED"
    assert res.status == "UNDETERMINED"


def test_batch_consensus_majority_vote_and_declared():
    consensus = BatchSubjectCodeConsensus(min_agreement_threshold=0.70, min_readable_readings=5)

    # 10 sheets: 8 say CT10718, 1 says CT10715, 1 is unreadable
    records = [
        {"sheet_name": f"sheet_{i}", "matched_code": "CT10718"} for i in range(8)
    ]
    records.append({"sheet_name": "sheet_8", "matched_code": "CT10715"})
    records.append({"sheet_name": "sheet_9", "matched_code": None})

    # Test with declared code CT10718
    res = consensus.compute_consensus(
        records,
        known_codes=["CT10718", "CT10715"],
        subject_code_declared="CT10718",
    )

    assert res.consensus_code == "CT10718"
    assert res.total_sheets == 10
    assert res.valid_votes == 9
    assert res.vote_counts["CT10718"] == 8
    assert res.vote_counts["CT10715"] == 1
    assert abs(res.agreement_ratio - 8/9) < 1e-4
    assert res.evidence["batch_coverage"] == 0.80
    assert "sheet_8" in res.disagreeing_sheets
    assert "sheet_9" in res.unreadable_sheets
    assert "sheet_9" not in res.disagreeing_sheets
    assert "sheet_0" not in res.disagreeing_sheets


def test_batch_immutability():
    consensus = BatchSubjectCodeConsensus()
    records = [
        {"sheet_name": "sheet_0", "matched_code": "CT10715", "original_val": 42}
    ]
    copy_val = records[0]["matched_code"]
    res = consensus.compute_consensus(records, known_codes=["CT10718", "CT10715"])

    assert records[0]["matched_code"] == copy_val
    assert "consensus_code" not in records[0]
