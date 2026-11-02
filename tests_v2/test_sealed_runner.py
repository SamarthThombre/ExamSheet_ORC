"""
tests_v2.test_sealed_runner:
Unit tests for run_sealed_once.py and score_sealed.py on a mock tune dataset.
Verifies:
1. Refuses to run without --code-is-frozen.
2. Code manifest verification passes.
3. Successful single run creates lock file and outputs predictions CSV with effective settings.
4. Second run refuses to execute (single-run lock enforcement).
5. score_sealed.py evaluates layout accuracy against GT layout column and criteria JSON.
6. Absolutely nothing was executed against any v4 dataset.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_sealed_single_run_and_scoring_on_mock_tune():
    mock_dir = ROOT / "experiments" / "m8" / "mock_sealed_run"
    img_dir = mock_dir / "images"
    if mock_dir.exists():
        shutil.rmtree(mock_dir)
    img_dir.mkdir(parents=True, exist_ok=True)

    # Copy 5 tune sheets
    sheets_a = ["page_000009.png", "page_000013.png", "page_000014.png"]
    sheets_b = ["page_000001.png", "page_000017.png"]

    for fn in sheets_a:
        shutil.copy2(ROOT / "data" / fn, img_dir / fn)
    for fn in sheets_b:
        shutil.copy2(ROOT / "data" / "data_v2_images" / fn, img_dir / fn)

    # Build GT CSV with layout column
    gt_rows = [
        {"layout": "format_original", "image_filename": "page_000009.png", "enrollment_no": "0801CA251009", "subject_code": "CT10718", "grand_total": "45", "q1": "10", "q2": "9", "q3": "8", "q4": "9", "q5": "9", "marks_status": ""},
        {"layout": "format_original", "image_filename": "page_000013.png", "enrollment_no": "0801CA251013", "subject_code": "CT10718", "grand_total": "50", "q1": "10", "q2": "10", "q3": "10", "q4": "10", "q5": "10", "marks_status": ""},
        {"layout": "format_original", "image_filename": "page_000014.png", "enrollment_no": "0801CA251014", "subject_code": "CT10718", "grand_total": "40", "q1": "8", "q2": "8", "q3": "8", "q4": "8", "q5": "8", "marks_status": ""},
        {"layout": "format_v2", "image_filename": "page_000001.png", "enrollment_no": "0801CA251001", "subject_code": "CT10718", "grand_total": "42", "q1": "9", "q2": "9", "q3": "8", "q4": "8", "q5": "8", "marks_status": ""},
        {"layout": "format_v2", "image_filename": "page_000017.png", "enrollment_no": "0801CA251017", "subject_code": "CT10718", "grand_total": "38", "q1": "7", "q2": "8", "q3": "8", "q4": "8", "q5": "7", "marks_status": ""},
    ]
    gt_csv = mock_dir / "gt_mock.csv"
    pd.DataFrame(gt_rows).to_csv(gt_csv, index=False)

    pred_csv = mock_dir / "preds_mock.csv"
    score_json = mock_dir / "score_mock.json"
    lock_file = mock_dir / "mock_dataset.lock"

    # Step 1: Run without --code-is-frozen -> Must fail with code 1
    p_no_freeze = subprocess.run(
        [sys.executable, str(ROOT / "run_sealed_once.py"), "--dataset", "mock_dataset", "--images-dir", str(img_dir), "--output-csv", str(pred_csv)],
        capture_output=True, text=True,
    )
    assert p_no_freeze.returncode == 1
    assert "without --code-is-frozen" in p_no_freeze.stderr

    # Step 2: First run with --code-is-frozen -> Must succeed and write lock
    p_ok = subprocess.run(
        [sys.executable, str(ROOT / "run_sealed_once.py"), "--dataset", "mock_dataset", "--images-dir", str(img_dir), "--output-csv", str(pred_csv), "--code-is-frozen"],
        capture_output=True, text=True,
    )
    assert p_ok.returncode == 0, f"run_sealed_once failed: {p_ok.stdout}\n{p_ok.stderr}"
    assert pred_csv.exists()
    assert lock_file.exists()

    df_p = pd.read_csv(pred_csv, comment="#")
    assert len(df_p) == 5
    assert "latency_ms" in df_p.columns
    assert "layout_confidence" in df_p.columns

    # Step 3: Second run on same dataset -> Must be REFUSED by lock file
    p_rerun = subprocess.run(
        [sys.executable, str(ROOT / "run_sealed_once.py"), "--dataset", "mock_dataset", "--images-dir", str(img_dir), "--output-csv", str(pred_csv), "--code-is-frozen"],
        capture_output=True, text=True,
    )
    assert p_rerun.returncode == 1
    assert "Single-run lock violation" in p_rerun.stderr

    # Step 4: Run score_sealed.py
    p_score = subprocess.run(
        [
            sys.executable, str(ROOT / "score_sealed.py"),
            "--dataset", "mock_dataset",
            "--predictions-csv", str(pred_csv),
            "--gt-csv", str(gt_csv),
            "--output-json", str(score_json),
            "--criteria", str(ROOT / "experiments" / "m8" / "v4_criteria.json"),
        ],
        capture_output=True, text=True,
    )
    assert p_score.returncode == 0, f"score_sealed failed: {p_score.stdout}\n{p_score.stderr}"
    assert score_json.exists()

    summary = json.loads(score_json.read_text(encoding="utf-8"))
    assert summary["dataset"] == "mock_dataset"
    assert summary["total_evaluated_sheets"] == 5
    assert summary["run_happened_once"] is True
    assert summary["layout_metrics"]["has_gt_layout"] is True
    assert summary["layout_metrics"]["layout_accuracy_pct"] == 100.0
    assert summary["layout_metrics"]["wrong_layout_count"] == 0
    assert "latency" in summary["overall"]

    # Step 5: Verify v4 was not executed and no sealed run or predictions exist
    assert not (ROOT / "v4.lock").exists()
    assert not (ROOT / "canonical_labels_v4.csv").exists()
    assert not (ROOT / "v4_predictions.csv").exists()
    assert not (ROOT / "experiments" / "m8" / "v4_predictions.csv").exists()
