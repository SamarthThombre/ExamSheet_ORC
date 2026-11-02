"""
tests_v2/test_m7_rules.py: Unit tests for Milestone 7 / 7b generic reading rules ported into ocr_v2/.
All test fixtures are strictly tune-derived or synthetic (zero v3-derived literals):
1. Zero-padded and decimal cells: "02.5", "00", "05.5".
2. Stacked-fraction cell (parser grammar + visual stacked-fraction detector).
3. Over-maximum "N2" cell ("92" -> 9.5, "82" -> 8.5 with SUGGESTED_FRACTION, from Format A DEV page_000079).
4. Crossed-out cell (detect_crossed_out_cell -> True, CROSSED_OUT, value=None).
5. Grand total equation grammar: "55.5=56" and "55.5256" -> 56.
6. Circled right-hand side with single-char lookalike: "43.5=(44)" -> 44 (Format A DEV page_000082) and "34.5=(3S)" -> 35.
7. "57.5=" (Format A DEV page_000023) with page edge reached (TOTAL_CLIPPED, value=None, rescan_recommended=True) and unclipped (RHS_MISSING, SUGGESTION_ONLY, suggestion=58, value=None).
8. Subject code shape grammar ("CT" + 5 digits with config-driven pattern and single-char lookalikes, no snapping).
9. Single-line subject code crop (Format A and Format B dual-copy).
10. Parameter-free sum-based suggestion (SUGGESTED_FROM_SUM in "suggestion", never in "value", sheet status stays UNAVAILABLE).
11. 5-sheet default /v2/predict test (M7 rules enabled by default, rollback switch supported).
12. 5-sheet dry-run of experiments/m7b/run_v3_once.py with production defaults and effective settings output.
"""

import cv2
import numpy as np
import pytest
import yaml

from ocr_v2.cell_reader import (
    parse_question_cell_m7,
    detect_visual_stacked_fraction,
    detect_crossed_out_cell,
    compute_ctc_top2_margin,
    check_unreadable_signals,
    apply_crop_remedy,
    compute_sum_status,
    compute_sum_based_suggestion,
)
from ocr_v2.fields import (
    extract_total_crop_m7,
    check_total_clipped,
    crop_subject_code_single_line,
)
from ocr_v2.reader import (
    parse_grand_total_m7,
    parse_subject_code_shape_grammar,
)
from ocr_v2.normalise import PageNormaliser


def test_zero_padded_and_decimal_cells():
    v1, _, fl1, _ = parse_question_cell_m7("02.5", 0.95, max_marks=14.0)
    assert v1 == 2.5
    assert fl1 == []

    v2, _, fl2, _ = parse_question_cell_m7("00", 0.98, max_marks=14.0)
    assert v2 == 0.0
    assert fl2 == []

    v3, _, fl3, _ = parse_question_cell_m7("05.5", 0.92, max_marks=14.0)
    assert v3 == 5.5
    assert fl3 == []


def test_stacked_fraction_cell_grammar_and_visual():
    # Parser grammar fixtures
    v1, _, fl1, sug1 = parse_question_cell_m7("08 1/2", 0.90, max_marks=14.0)
    assert v1 == 8.5
    assert sug1 == 8.5
    assert "SUGGESTED_FRACTION" in fl1

    v2, _, fl2, _ = parse_question_cell_m7("1/2", 0.88, max_marks=14.0)
    assert v2 == 0.5
    assert "SUGGESTED_FRACTION" in fl2

    # Visual stacked-fraction synthetic cell fixture (main digit on left + stacked '1' over '2' on right)
    crop = np.full((70, 140, 3), 240, dtype=np.uint8)
    cv2.rectangle(crop, (35, 18), (58, 55), (20, 20, 20), -1)
    cv2.rectangle(crop, (92, 8), (100, 24), (20, 20, 20), -1)
    cv2.rectangle(crop, (90, 46), (104, 60), (20, 20, 20), -1)

    detected, stripped = detect_visual_stacked_fraction(crop)
    assert detected is True
    assert stripped.shape == crop.shape
    assert np.mean(stripped[:, 90:]) > 230.0

    v_vis, _, fl_vis, _ = parse_question_cell_m7("08", 0.95, max_marks=14.0, visual_fraction_detected=True)
    assert v_vis == 8.5
    assert "SUGGESTED_FRACTION" in fl_vis


def test_over_maximum_n2_cell():
    # Tune-derived from Format A DEV page_000079 ("92" -> 9.5, "82" -> 8.5)
    v1, _, fl1, sug1 = parse_question_cell_m7("92", 0.91, max_marks=14.0)
    assert v1 == 9.5
    assert sug1 == 9.5
    assert "SUGGESTED_FRACTION" in fl1

    v2, _, fl2, sug2 = parse_question_cell_m7("82", 0.89, max_marks=14.0)
    assert v2 == 8.5
    assert sug2 == 8.5
    assert "SUGGESTED_FRACTION" in fl2


def test_crossed_out_cell():
    crop = np.full((70, 140, 3), 240, dtype=np.uint8)
    cv2.putText(crop, "08", (35, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (20, 20, 20), 3)
    cv2.line(crop, (15, 32), (125, 36), (15, 15, 15), 5)
    cv2.line(crop, (15, 42), (125, 28), (15, 15, 15), 5)
    assert detect_crossed_out_cell(crop) is True

    clean_crop = np.full((70, 140, 3), 240, dtype=np.uint8)
    cv2.putText(clean_crop, "08", (40, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (20, 20, 20), 2)
    assert detect_crossed_out_cell(clean_crop) is False


def test_grand_total_equation_and_circled_rhs():
    # "55.5=56" -> 56
    res1 = parse_grand_total_m7("55.5=56", 0.96, is_clipped=False)
    assert res1["value"] == 56
    assert res1["flags"] == []

    # "=" misread as "2" between .5 decimal and integer: "55.5256" -> 56
    res2 = parse_grand_total_m7("55.5256", 0.94, is_clipped=False)
    assert res2["value"] == 56

    # Circled RHS from Format A DEV page_000082 ("43.5=(44)" -> 44) and single-char S->5 lookalike ("34.5=(3S)" -> 35)
    res3 = parse_grand_total_m7("43.5=(44)", 0.91, is_clipped=False)
    assert res3["value"] == 44
    assert res3["flags"] == []

    res4 = parse_grand_total_m7("34.5=(3S)", 0.90, is_clipped=False)
    assert res4["value"] == 35
    assert res4["flags"] == []


def test_grand_total_lhs_equals_clipped_and_missing():
    # Tune-derived from Format A DEV page_000023 ("57.5=")
    clipped_crop = np.full((50, 180, 3), 235, dtype=np.uint8)
    clipped_crop[18:32, 176:180] = 20
    assert check_total_clipped(clipped_crop, touched_page_edge=True) is True

    res_clipped = parse_grand_total_m7("57.5=", 0.88, is_clipped=True)
    assert res_clipped["value"] is None
    assert "TOTAL_CLIPPED" in res_clipped["flags"]
    assert res_clipped["rescan_recommended"] is True

    # "57.5=" unclipped -> value=None, suggestion=58, flags include RHS_MISSING and SUGGESTION_ONLY
    res_unclipped = parse_grand_total_m7("57.5=", 0.90, is_clipped=False)
    assert res_unclipped["value"] is None
    assert res_unclipped["suggestion"] == 58
    assert "RHS_MISSING" in res_unclipped["flags"]
    assert "SUGGESTION_ONLY" in res_unclipped["flags"]


def test_subject_code_shape_grammar():
    with open("configs/formats/format_original.yaml", "r", encoding="utf-8") as f:
        cfg_a = yaml.safe_load(f)
    s_cfg = cfg_a["fields"]["subject_code"]["m7_single_line_crop"]
    assert "shape_pattern" in s_cfg

    code1, valid1 = parse_subject_code_shape_grammar("CT10718", cfg=s_cfg)
    assert valid1 is True
    assert code1 == "CT10718"

    # Single-char lookalike mapping: O->0, I->1, S->5
    code2, valid2 = parse_subject_code_shape_grammar("CTIO71S", cfg=s_cfg)
    assert valid2 is True
    assert code2 == "CT10715"

    # Arbitrary valid CT + 5 digits code not in any known list (proves no snapping)
    code3, valid3 = parse_subject_code_shape_grammar("CT99421", cfg=s_cfg)
    assert valid3 is True
    assert code3 == "CT99421"

    # Invalid shape
    _, valid4 = parse_subject_code_shape_grammar("SUBJ12", cfg=s_cfg)
    assert valid4 is False


def test_single_line_subject_code_crop_both_formats():
    norm = PageNormaliser(1600)
    img_a = cv2.imread("data/page_000009.png")
    c_can_a, _ = norm.resize_to_canonical_width(img_a)
    crop_a, bbox_a, crop_ar, _ = crop_subject_code_single_line(c_can_a, "format_original")
    assert crop_a is not None and crop_a.size > 0
    assert (bbox_a[3] - bbox_a[1]) <= 110
    assert crop_a.shape[0] <= 110
    assert crop_ar is None

    img_b = cv2.imread("data/data_v2_images/page_000010.png")
    c_can_b, _ = norm.resize_to_canonical_width(img_b)
    crop_bl, bbox_bl, crop_br, bbox_br = crop_subject_code_single_line(c_can_b, "format_v2")
    assert crop_bl is not None and crop_bl.size > 0
    assert (bbox_bl[3] - bbox_bl[1]) <= 110
    assert crop_bl.shape[0] <= 110
    assert crop_br is not None and crop_br.size > 0
    assert (bbox_br[3] - bbox_br[1]) <= 110
    assert crop_br.shape[0] <= 110


def test_sum_based_suggestion_parameter_free():
    # Case 1: Exactly 1 cell is CROSSED_OUT (value=None), other 4 are clean [10.0, 9.5, None, 11.0, 8.0] = 38.5, grand total = 48.0 -> suggestion = 9.5
    q_vals = [10.0, 9.5, None, 11.0, 8.0]
    q_flags = [[], [], ["CROSSED_OUT"], [], []]
    st, _, _, _ = compute_sum_status(q_vals, q_flags, 48.0, [])
    assert st == "UNAVAILABLE"
    res = compute_sum_based_suggestion(q_vals, q_flags, 48.0, [], max_marks=14.0)
    assert res == (2, 9.5)

    # Case 2: Suggestion exceeds max_marks (14.0) -> None
    res_over = compute_sum_based_suggestion([2.0, 2.0, None, 2.0, 2.0], [[], [], ["CROSSED_OUT"], [], []], 30.0, [], max_marks=14.0)
    assert res_over is None

    # Case 3: Grand total is flagged -> None
    res_flg = compute_sum_based_suggestion(q_vals, q_flags, 48.0, ["LOW_CONFIDENCE"], max_marks=14.0)
    assert res_flg is None

    # Case 4: Two cells flagged -> None
    res_two = compute_sum_based_suggestion([10.0, 9.5, None, 11.0, 8.0], [["SUGGESTED_FRACTION"], [], ["CROSSED_OUT"], [], []], 48.0, [], max_marks=14.0)
    assert res_two is None


def test_5_sheet_default_predict_and_rollback():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    test_sheets = [
        ("data/page_000009.png", "page_000009.png"),
        ("data/page_000013.png", "page_000013.png"),
        ("data/page_000014.png", "page_000014.png"),
        ("data/data_v2_images/page_000010.png", "page_000010.png"),
        ("data/data_v2_images/page_000012.png", "page_000012.png"),
    ]
    expected_top_keys = {
        "filename",
        "format_id",
        "detected_format",
        "layout_confidence",
        "rescan_recommended",
        "needs_review",
        "review_reasons",
        "overall_needs_review",
        "enrolment",
        "subject_code",
        "total_marks",
        "alignment",
        "page_quad",
        "page_confidence",
        "page_status",
        "latency_ms",
    }
    for path, fname in test_sheets:
        with open(path, "rb") as f:
            raw = f.read()
        r_omit = client.post("/v2/predict", files={"file": (fname, raw, "image/png")})
        r_m7_true = client.post(
            "/v2/predict",
            files={"file": (fname, raw, "image/png")},
            data={"extract_total_marks": "true", "extract_question_marks": "false", "phase": "full", "enable_m7_rules": "true"},
        )
        r_rollback = client.post(
            "/v2/predict",
            files={"file": (fname, raw, "image/png")},
            data={"extract_total_marks": "true", "extract_question_marks": "false", "phase": "full", "enable_m7_rules": "false"},
        )
        assert r_omit.status_code == 200
        assert r_m7_true.status_code == 200
        assert r_rollback.status_code == 200
        j_omit, j_m7 = r_omit.json(), r_m7_true.json()
        assert set(j_omit.keys()) == expected_top_keys
        for k in expected_top_keys - {"latency_ms"}:
            assert j_omit[k] == j_m7[k], f"Default /v2/predict did not match enable_m7_rules=True on {fname} key {k}"


def test_run_v3_once_and_score_v3_on_5_tune_sheets():
    import csv
    import json
    import shutil
    import subprocess
    import sys
    from pathlib import Path
    import pandas as pd

    ROOT = Path(__file__).resolve().parents[1]
    dry_dir = ROOT / "experiments" / "m7b" / "dry_run_5_tune"
    img_dir = dry_dir / "images"
    if dry_dir.exists():
        shutil.rmtree(dry_dir)
    img_dir.mkdir(parents=True, exist_ok=True)

    sheets_a = ["page_000009.png", "page_000013.png", "page_000014.png"]
    sheets_b = ["page_000001.png", "page_000017.png"]
    for fn in sheets_a:
        shutil.copy2(ROOT / "data" / fn, img_dir / fn)
    for fn in sheets_b + ["page_000010.png"]:
        shutil.copy2(ROOT / "data" / "data_v2_images" / fn, img_dir / fn)

    gts_a = {}
    with open(ROOT / "data" / "canonical_labels.csv", "r", encoding="utf-8", errors="replace") as f:
        r = csv.reader(f)
        h = next(r)
        hm = {c.strip(): i for i, c in enumerate(h[:13])}
        for row in r:
            if row:
                gts_a[row[hm["image_filename"]].strip()] = {c: row[i].strip() for c, i in hm.items()}
    df_b = pd.read_csv(ROOT / "data" / "canonical_labels_v2.csv").set_index("image_filename")

    gt_rows = []
    for fn in sheets_a:
        g = gts_a[fn]
        gt_rows.append({
            "format": "format_original",
            "image_filename": fn,
            "enrollment_no": g.get("enrollment_no", ""),
            "subject_code": g.get("subject_code", ""),
            "grand_total": g.get("total_marks") or g.get("grand_total", ""),
            "q1": g.get("q1", ""), "q2": g.get("q2", ""), "q3": g.get("q3", ""), "q4": g.get("q4", ""), "q5": g.get("q5", ""),
        })
    for fn in sheets_b:
        r = df_b.loc[fn]
        gt_rows.append({
            "format": "format_v2",
            "image_filename": fn,
            "enrollment_no": str(r.get("enrollment_no", "")),
            "subject_code": str(r.get("subject_code", "")),
            "grand_total": str(r.get("grand_total", "")),
            "q1": str(r.get("q1", "")), "q2": str(r.get("q2", "")), "q3": str(r.get("q3", "")), "q4": str(r.get("q4", "")), "q5": str(r.get("q5", "")),
        })
    gt_csv = dry_dir / "gt_5_tune.csv"
    pd.DataFrame(gt_rows).to_csv(gt_csv, index=False)
    pred_csv = dry_dir / "preds_5_tune.csv"
    score_json = dry_dir / "score_5_tune.json"

    # 1. Without --code-is-frozen -> must exit with code 1
    p_fail = subprocess.run(
        [sys.executable, str(ROOT / "experiments" / "m7b" / "run_v3_once.py"), "--images-dir", str(img_dir), "--output-csv", str(pred_csv)],
        capture_output=True, text=True,
    )
    assert p_fail.returncode == 1

    # 2. With --code-is-frozen -> must verify manifest, skip page_000010.png, use production defaults, and write effective settings into output
    p_ok = subprocess.run(
        [sys.executable, str(ROOT / "experiments" / "m7b" / "run_v3_once.py"), "--images-dir", str(img_dir), "--output-csv", str(pred_csv), "--code-is-frozen"],
        capture_output=True, text=True,
    )
    assert p_ok.returncode == 0, f"run_v3_once failed: {p_ok.stdout}\n{p_ok.stderr}"
    df_p = pd.read_csv(pred_csv, comment="#")
    assert len(df_p) == 5
    assert "page_000010.png" not in set(df_p["image_filename"])
    assert "effective_settings_json" in df_p.columns
    first_line = pred_csv.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("# EFFECTIVE_SETTINGS:")
    fmt_map = dict(zip(df_p["image_filename"], df_p["format"]))
    for fn in sheets_a:
        assert fmt_map[fn] == "format_original"
    for fn in sheets_b:
        assert fmt_map[fn] == "format_v2"

    # 3. Run score_v3.py
    p_sc = subprocess.run(
        [sys.executable, str(ROOT / "experiments" / "m7b" / "score_v3.py"), "--predictions-csv", str(pred_csv), "--gt-csv", str(gt_csv), "--output-json", str(score_json)],
        capture_output=True, text=True,
    )
    assert p_sc.returncode == 0, f"score_v3 failed: {p_sc.stdout}\n{p_sc.stderr}"
    summary = json.loads(score_json.read_text(encoding="utf-8"))
    assert summary.get("total_evaluated_sheets", summary.get("overall", {}).get("evaluated_sheets")) == 5
    assert "page_000010.png" in summary["excluded_filenames"]
    assert "effective_settings" in summary


def test_m7c_dual_q_cell_and_total_suggestions():
    from ocr_v2.cell_reader import compute_q_cell_suggestions, compute_total_suggestion_from_cells

    # Q-cell dual candidates: total=48.0, others sum=38.5 -> cand1 = 48.0 - 38.5 = 9.5, cand2 = 9.5 - 0.5 = 9.0
    q_vals = [10.0, 9.5, None, 11.0, 8.0]
    q_flags = [[], [], ["CROSSED_OUT"], [], []]
    res_q = compute_q_cell_suggestions(q_vals, q_flags, 48.0, [], max_marks=14.0)
    assert res_q is not None
    sug_idx, cands = res_q
    assert sug_idx == 2
    assert cands == [9.5, 9.0]

    # Total suggestion: all 5 q cells unflagged [10.0, 9.5, 9.0, 11.0, 8.0] sum=47.5 -> round_half_up=48.0
    q_vals_clean = [10.0, 9.5, 9.0, 11.0, 8.0]
    q_flags_clean = [[], [], [], [], []]
    res_tot = compute_total_suggestion_from_cells(q_vals_clean, q_flags_clean, None, ["LOW_CONFIDENCE"])
    assert res_tot == 48.0

    # Total suggestion when total is valid and unflagged -> None (no suggestion needed)
    res_tot_none = compute_total_suggestion_from_cells(q_vals_clean, q_flags_clean, 48.0, [])
    assert res_tot_none is None


def test_m7c_poor_grid_alignment_detection():
    from ocr_v2.table import check_grid_consistency

    cfg = {"enabled": True, "max_pitch_dev_px": 35.0, "expected_bottom_offset_px": 0.0, "max_bottom_gap_px": 40.0, "require_both": True, "check_bottom_gap": True}

    # Clean grid: equal pitches 88 px, bottom meets gt_y=1700
    clean_ql = [1260, 1348, 1436, 1524, 1612, 1700]
    ok_clean, reason_clean, _ = check_grid_consistency(clean_ql, 1700, cfg)
    assert ok_clean is True
    assert reason_clean == "OK"

    # Row-shifted grid (Format A DEV page_000023 pitches=[73, 110, 72, 126, 61], max_dev=53.0 px, bot_gap=264 px)
    rs_ql = [1300, 1373, 1483, 1555, 1681, 1742]
    ok_rs, reason_rs, _ = check_grid_consistency(rs_ql, 2006, cfg)
    assert ok_rs is False
    assert reason_rs == "POOR_GRID_ALIGNMENT"


def test_m7c_format_auto_detect_check():
    from app.routers_v2 import get_pipeline, process_sheet_bytes
    from pathlib import Path

    pipeline = get_pipeline()
    ROOT = Path(__file__).resolve().parents[1]

    # Test 6 mixed tune sheets (3 format_original, 3 format_v2) without passing format argument
    sheets = [
        ("format_original", ROOT / "data" / "page_000001.png"),
        ("format_original", ROOT / "data" / "page_000002.png"),
        ("format_original", ROOT / "data" / "page_000003.png"),
        ("format_v2", ROOT / "data" / "data_v2_images" / "page_000001.png"),
        ("format_v2", ROOT / "data" / "data_v2_images" / "page_000002.png"),
        ("format_v2", ROOT / "data" / "data_v2_images" / "page_000003.png"),
    ]
    for exp_fmt, p in sheets:
        res = process_sheet_bytes(p.read_bytes(), p.name, pipeline)
        assert res["format_id"] == exp_fmt
        assert res["detected_format"] == exp_fmt

    # Blank page returns UNKNOWN and skips q marks stage
    blank_img = np.ones((2000, 1400, 3), dtype=np.uint8) * 255
    _, blank_bytes = cv2.imencode(".png", blank_img)
    res_blank = process_sheet_bytes(blank_bytes.tobytes(), "blank.png", pipeline)
    assert res_blank["format_id"] == "UNKNOWN"
    assert res_blank["detected_format"] == "UNKNOWN"
    assert res_blank.get("q_marks") is None

    # Rotated page (90 deg clockwise) returns UNKNOWN and skips q marks stage
    img_a = cv2.imread(str(ROOT / "data" / "page_000001.png"))
    rot_img = cv2.rotate(img_a, cv2.ROTATE_90_CLOCKWISE)
    _, rot_bytes = cv2.imencode(".png", rot_img)
    res_rot = process_sheet_bytes(rot_bytes.tobytes(), "rot90.png", pipeline)
    assert res_rot["format_id"] == "UNKNOWN"
    assert res_rot["detected_format"] == "UNKNOWN"
    assert res_rot.get("q_marks") is None

