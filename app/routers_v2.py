"""
app.routers_v2: FastAPI router for OCR v2 pipeline.
Provides /v2/predict and /v2/batch endpoints using ocr_v2 package.
"""

from typing import List, Optional, Dict, Any
from pathlib import Path
from dataclasses import asdict
import time
import logging
import os
import base64
import cv2

from fastapi import APIRouter, File, UploadFile, Form, HTTPException, Depends, Request, status
import numpy as np

from app.config import settings
from app.auth import KeyInfo, get_current_key
from app.validators import (
    validate_content_type,
    validate_magic_bytes,
    validate_file_size,
    validate_image_dimensions_and_decode,
    validate_batch_file_count,
    rate_limiter,
)
from ocr_v2.normalise import PageNormaliser
from ocr_v2.page_localiser import PageLocaliser
from ocr_v2.formats import FormatDetector
from ocr_v2.fields import FieldCropper, extract_total_crop_m7, check_total_clipped, crop_subject_code_single_line
from ocr_v2.reader import BatchedONNXReader
from ocr_v2.batch import BatchSubjectCodeConsensus
from ocr_v2.review import BatchReviewManager, classify_flags
from ocr_v2.table import DualAnchorTableDetector
from ocr_v2.cell_reader import (
    SharedCellReader,
    parse_question_cell,
    compute_sum_status,
    compute_sum_based_suggestion,
    compute_q_cell_suggestions,
    compute_total_suggestion_from_cells,
    get_ort_session,
    detect_visual_stacked_fraction,
    detect_crossed_out_cell,
    parse_question_cell_m7,
    compute_ctc_top2_margin,
    check_unreadable_signals,
    apply_crop_remedy,
)

import yaml


logger = logging.getLogger("api.v2")

router = APIRouter(prefix="/v2", tags=["OCR v2"])

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


class OCRv2Pipeline:
    """Holds singleton instances for OCR v2 processing."""

    def __init__(self):
        logger.info("Initializing OCR v2 pipeline components...")
        self.normaliser = PageNormaliser()
        self.localiser = PageLocaliser()
        self.detector = FormatDetector()
        self.configs = {}
        config_dir = Path("configs/formats")
        for f in config_dir.glob("*.yaml"):
            with open(f, "r", encoding="utf-8") as fp:
                data = yaml.safe_load(fp)
                if "format_id" in data:
                    self.configs[data["format_id"]] = data
        self.cropper = FieldCropper()
        self.reader = BatchedONNXReader()
        self.consensus = BatchSubjectCodeConsensus()
        self.review_manager = BatchReviewManager()
        self.table_detector = DualAnchorTableDetector()
        self.cell_reader = SharedCellReader()
        self.ort_session = get_ort_session()
        logger.info("OCR v2 pipeline components initialized successfully.")



_pipeline_instance: Optional[OCRv2Pipeline] = None


def get_pipeline() -> OCRv2Pipeline:
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = OCRv2Pipeline()
    return _pipeline_instance


def process_sheet_bytes(
    content: bytes,
    filename: str,
    pipeline: OCRv2Pipeline,
    extract_total_marks: bool = True,
    extract_question_marks: bool = False,
    phase: Optional[str] = "full",
    enable_m7_rules: Optional[bool] = None,
    enable_page_localiser: Optional[bool] = None,
    subject_code_declared: Optional[str] = None,
) -> Dict[str, Any]:
    """Processes raw image bytes through full OCR v2 pipeline and returns structured result."""
    # 1. Validation
    if len(content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB}MB.",
        )
    if len(content) < 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file payload is empty or corrupted.",
        )

    # 2. Decode
    t0 = time.perf_counter()
    img = pipeline.normaliser.decode(content)
    if img is None or img.size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file could not be decoded as a valid image. Ensure image is not corrupted.",
        )
    t_decode = (time.perf_counter() - t0) * 1000.0

    # 2b. Page localisation & boundary validation (OFF by default unless configured or requested)
    use_localiser = settings.ENABLE_PAGE_LOCALISER if enable_page_localiser is None else enable_page_localiser
    if use_localiser:
        t0_loc = time.perf_counter()
        loc_res = pipeline.localiser.localise(img)
        t_loc = (time.perf_counter() - t0_loc) * 1000.0
        page_status_val = loc_res.page_status
        page_conf_val = round(float(loc_res.page_confidence), 4)
        page_quad_val = loc_res.page_quad.tolist() if loc_res.page_quad is not None else None
    else:
        t_loc = 0.0
        loc_res = None
        page_status_val = "NOT_RUN"
        page_conf_val = None
        page_quad_val = None

    if loc_res is not None and loc_res.page_status in ("CUT_OFF", "NOT_FOUND"):
        all_raw_reasons = ["PAGE_CUT_OFF_OR_UNRECOGNISED"]
        rescan_rec, needs_rev, all_clean = classify_flags(all_raw_reasons)
        resp_dict = {
            "filename": filename,
            "format_id": "UNKNOWN",
            "detected_format": "UNKNOWN",
            "layout_confidence": 0.0,
            "page_status": page_status_val,
            "page_confidence": page_conf_val,
            "page_quad": page_quad_val,
            "rescan_recommended": True,
            "needs_review": True,
            "review_reasons": all_clean,
            "overall_needs_review": True,
            "enrolment": {
                "value": None,
                "raw_text": "",
                "confidence": 0.0,
                "char_confidences": [],
                "needs_review": True,
                "rescan_recommended": True,
                "review_reasons": ["PAGE_CUT_OFF_OR_UNRECOGNISED"],
            },
            "subject_code": {
                "value": None,
                "raw_text": "",
                "confidence": 0.0,
                "matched_code": None,
                "needs_review": True,
                "rescan_recommended": True,
                "review_reasons": ["PAGE_CUT_OFF_OR_UNRECOGNISED"],
            },
            "total_marks": {
                "value": None,
                "raw_text": "",
                "confidence": 0.0,
                "flags": ["PAGE_CUT_OFF_OR_UNRECOGNISED"],
            } if extract_total_marks else {"status": "SKIPPED"},
            "alignment": {
                "dx": 0.0,
                "dy": 0.0,
                "rot_deg": round(float(loc_res.estimated_rotation), 3),
                "quality_score": 0.0,
                "needs_review": True,
                "rescan_recommended": True,
                "review_reasons": ["PAGE_CUT_OFF_OR_UNRECOGNISED"],
            },
            "latency_ms": {
                "decode": round(t_decode, 2),
                "page_localise": round(t_loc, 2),
                "format_detect": 0.0,
                "normalise": 0.0,
                "crop": 0.0,
                "read": 0.0,
                "total": round(t_decode + t_loc, 2),
            },
        }
        if extract_question_marks:
            resp_dict["q_marks"] = [
                {
                    "q": j + 1,
                    "value": None,
                    "raw_text": "",
                    "confidence": 0.0,
                    "flags": ["PAGE_CUT_OFF_OR_UNRECOGNISED"],
                }
                for j in range(5)
            ]
            resp_dict["marks_sum"] = {
                "status": "UNAVAILABLE",
                "sum": None,
                "total": None,
                "difference": None,
            }
        return resp_dict

    if loc_res is not None and loc_res.normalised_image is not None:
        img = loc_res.normalised_image

    # 3. Format detection
    t1 = time.perf_counter()
    fmt_res = pipeline.detector.identify(img)
    format_id = fmt_res.format_id
    fmt_cfg = pipeline.configs.get(format_id)
    t_fmt = (time.perf_counter() - t1) * 1000.0

    if format_id == "UNKNOWN" or fmt_cfg is None:
        all_raw_reasons = ["UNKNOWN_FORMAT"] + fmt_res.reasons
        rescan_rec, needs_rev, all_clean = classify_flags(all_raw_reasons)
        if any("INVALID_ASPECT_RATIO" in r for r in fmt_res.reasons):
            rescan_rec = True
            if "PARTIAL_SHEET" not in all_clean:
                all_clean.append("PARTIAL_SHEET")
        resp_dict = {
            "filename": filename,
            "format_id": "UNKNOWN",
            "detected_format": "UNKNOWN",
            "layout_confidence": round(float(fmt_res.confidence), 4),
            "page_status": page_status_val,
            "page_confidence": page_conf_val,
            "page_quad": page_quad_val,
            "rescan_recommended": rescan_rec,
            "needs_review": needs_rev,
            "review_reasons": all_clean,
            "overall_needs_review": needs_rev,
            "enrolment": {
                "value": None,
                "raw_text": "",
                "confidence": 0.0,
                "char_confidences": [],
                "needs_review": True,
                "rescan_recommended": True,
                "review_reasons": ["UNKNOWN_FORMAT", "PARTIAL_SHEET"] if "PARTIAL_SHEET" in all_clean else ["UNKNOWN_FORMAT"],
            },
            "subject_code": {
                "value": None,
                "raw_text": "",
                "confidence": 0.0,
                "matched_code": None,
                "needs_review": True,
                "rescan_recommended": True,
                "review_reasons": ["UNKNOWN_FORMAT", "PARTIAL_SHEET"] if "PARTIAL_SHEET" in all_clean else ["UNKNOWN_FORMAT"],
            },
            "total_marks": {
                "value": None,
                "raw_text": "",
                "confidence": 0.0,
                "flags": ["UNKNOWN_FORMAT", "PARTIAL_SHEET"] if "PARTIAL_SHEET" in all_clean else ["UNKNOWN_FORMAT"],
            } if extract_total_marks else {"status": "SKIPPED"},
            "alignment": {
                "dx": 0.0,
                "dy": 0.0,
                "rot_deg": 0.0,
                "quality_score": 0.0,
                "needs_review": True,
                "rescan_recommended": True,
                "review_reasons": ["UNKNOWN_FORMAT"],
            },
            "latency_ms": {
                "decode": round(t_decode, 2),
                "page_localise": round(t_loc, 2),
                "format_detect": round(t_fmt, 2),
                "normalise": 0.0,
                "crop": 0.0,
                "read": 0.0,
                "total": round(t_decode + t_loc + t_fmt, 2),
            },
        }
        return resp_dict

    use_m7 = (
        bool(fmt_cfg.get("m7_rules_enabled", True))
        if (enable_m7_rules is None and fmt_cfg is not None)
        else (True if enable_m7_rules is None else bool(enable_m7_rules))
    )

    # 4. Alignment
    t2 = time.perf_counter()
    align_res = pipeline.normaliser.align_page(
        img,
        format_id=format_id,
        format_config=fmt_cfg,
        align_mode="comb_center",
    )
    t_align = (time.perf_counter() - t2) * 1000.0

    # 5. Field cropping
    t3 = time.perf_counter()
    crops = pipeline.cropper.crop_fields(
        align_res.image,
        format_id=format_id,
        format_config=fmt_cfg,
        comb_box=align_res.comb_box,
        alignment_score=align_res.quality_score,
    )
    t_crop = (time.perf_counter() - t3) * 1000.0

    # 6. Reading
    t4 = time.perf_counter()
    e_crop_res = crops.get("enrollment_no")
    s_crop_res = crops.get("subject_code")
    e_crop = e_crop_res.crop if e_crop_res else None
    s_crop = s_crop_res.crop if s_crop_res else None
    e_status = e_crop_res.status if e_crop_res else "MISSING"
    s_status = s_crop_res.status if s_crop_res else "MISSING"
    read_res = pipeline.reader.read_fields(
        e_crop,
        s_crop,
        format_id,
        fmt_cfg,
        enrol_crop_status=e_status,
        subj_crop_status=s_status,
    )
    e_res = read_res.fields.get("enrollment_no")
    s_res = read_res.fields.get("subject_code")

    s_m7_res = None
    if use_m7 and fmt_cfg and "subject_code" in fmt_cfg.get("fields", {}):
        c_can_s, _ = pipeline.normaliser.resize_to_canonical_width(img)
        sc_l, _, sc_r, _ = crop_subject_code_single_line(c_can_s, format_id, cfg=fmt_cfg)
        s_m7_res = pipeline.reader.read_subject_code_m7(
            sc_l, sc_r, is_format_b=(format_id == "format_v2"), cfg=fmt_cfg
        )
    t_read = (time.perf_counter() - t4) * 1000.0

    e_raw_reasons = e_res.review_reasons if e_res else ["MISSING_ENROLMENT_FIELD"]
    s_raw_reasons = s_res.review_reasons if s_res else ["MISSING_SUBJECT_CODE_FIELD"]
    if s_m7_res is not None and s_m7_res.get("shape_valid"):
        s_raw_reasons = list(s_m7_res.get("flags", []))
    a_raw_reasons = align_res.review_reasons

    # Propagate tilt skew flags to enrolment and total marks so tilted reads are never unflagged
    has_skew = any("SKEW" in r for r in a_raw_reasons)
    if has_skew:
        skew_flag = next((r for r in a_raw_reasons if "SKEW" in r), "EXCESSIVE_SKEW")
        if skew_flag not in e_raw_reasons:
            e_raw_reasons.append(skew_flag)

    a_rescan, a_review, a_clean = classify_flags(a_raw_reasons)
    e_rescan, e_review, e_clean = classify_flags(e_raw_reasons)
    s_rescan, s_review, s_clean = classify_flags(s_raw_reasons)

    # 7. Total marks reading
    tm_res = None
    gt_crop = None
    match_score = 1.0
    if extract_total_marks:
        if use_m7:
            c_can_gt, _ = pipeline.normaliser.resize_to_canonical_width(img)
            gt_crop, match_score, (_, _, gx2, _) = extract_total_crop_m7(
                c_can_gt, format_id, tmpl_a=pipeline.cropper.tmpl_a, tmpl_b=pipeline.cropper.tmpl_b, cfg=fmt_cfg
            )
            is_b = (format_id == "format_v2")
            ic = check_total_clipped(gt_crop, touched_page_edge=(gx2 >= int(0.99 * c_can_gt.shape[1])), cfg=fmt_cfg) if not is_b else False
            tm_res = pipeline.reader.read_total_marks_m7(gt_crop, is_clipped=ic, is_format_b=is_b)
            if tm_res is not None:
                if (gt_crop is None or match_score < 0.40):
                    if "LOW_TEMPLATE_CONFIDENCE" not in tm_res.get("flags", []):
                        tm_res.setdefault("flags", []).append("LOW_TEMPLATE_CONFIDENCE")
                if has_skew:
                    if "EXCESSIVE_SKEW" not in tm_res.get("flags", []):
                        tm_res.setdefault("flags", []).append("EXCESSIVE_SKEW")
        else:
            gt_crop_res = crops.get("grand_total")
            gt_crop = gt_crop_res.crop if gt_crop_res else None
            tm_res = pipeline.reader.read_total_marks(gt_crop)
            if has_skew and tm_res is not None:
                if "EXCESSIVE_SKEW" not in tm_res.get("flags", []):
                    tm_res.setdefault("flags", []).append("EXCESSIVE_SKEW")

    # 8. Question marks extraction (Phase 2)
    q_marks_list = None
    marks_sum_dict = None
    t_qmarks = 0.0
    if extract_question_marks and phase in ("full", "phase2") and fmt_cfg and "question_marks" in fmt_cfg.get("fields", {}):
        t_q0 = time.perf_counter()
        c_can, _ = pipeline.normaliser.resize_to_canonical_width(img)
        q_crops, q_bboxes, q_meta = pipeline.table_detector.extract_table_cells(c_can, format_id, fmt_cfg)
        
        q_vals = []
        q_flags_list = []
        q_marks_list = []
        
        if q_meta.get("status") == "OK" and len(q_crops) == 5:
            max_m = fmt_cfg["fields"]["question_marks"].get("max_marks_per_question", 14.0)
            m7_c_cfg = fmt_cfg["fields"]["question_marks"].get("m7_cell_rules", {})
            is_b = (format_id == "format_v2")
            q_crops_rec = (
                [apply_crop_remedy(c, pad_pct=0.0, remove_border=True) for c in q_crops]
                if (use_m7 and m7_c_cfg.get("remove_border", False))
                else q_crops
            )
            bw = m7_c_cfg.get("min_batch_width", 256) if use_m7 else 320
            q_inp = pipeline.cell_reader.preprocess_crops(q_crops_rec, min_batch_width=bw)
            q_out = pipeline.ort_session.run(None, {"x": q_inp})[0]
            q_preds = pipeline.cell_reader.decode_predictions(q_out)
            for j in range(5):
                raw_text, conf = q_preds[j]
                if use_m7:
                    crop_j = q_crops[j]
                    if detect_crossed_out_cell(crop_j, cfg=m7_c_cfg):
                        val, c_conf, flags = None, conf, ["CROSSED_OUT"]
                    else:
                        vis_det = False
                        if not is_b and m7_c_cfg.get("enable_visual_stacked_fraction", True):
                            vis_det, s_crop = detect_visual_stacked_fraction(crop_j, cfg=m7_c_cfg)
                            if vis_det:
                                s_inp = pipeline.cell_reader.preprocess_crops([s_crop], min_batch_width=160)
                                s_out = pipeline.ort_session.run(None, {"x": s_inp})[0]
                                raw_text, conf = pipeline.cell_reader.decode_predictions(s_out)[0]
                        val, c_conf, flags, _ = parse_question_cell_m7(
                            raw_text, conf, max_marks=max_m, mode="grammar_and_overmax", visual_fraction_detected=vis_det
                        )
                        if not is_b and m7_c_cfg.get("enable_unreadable_signals", True):
                            marg = compute_ctc_top2_margin(q_out[j])
                            sigs = check_unreadable_signals(crop_j, val, flags, conf, px_val=val, top2_margin=marg, cfg=m7_c_cfg)
                            if sigs["combined_flag"] and "UNCERTAIN_READ" not in flags:
                                flags.append("UNCERTAIN_READ")
                else:
                    val, c_conf, flags = parse_question_cell(raw_text, conf, max_marks=max_m)
                q_vals.append(val)
                q_flags_list.append(flags)
                q_marks_list.append({
                    "q": j + 1,
                    "value": val,
                    "raw_text": raw_text,
                    "confidence": round(float(c_conf), 4),
                    "flags": flags
                })
        elif q_meta.get("status") == "POOR_GRID_ALIGNMENT":
            for j in range(5):
                q_marks_list.append({
                    "q": j + 1,
                    "value": None,
                    "raw_text": "",
                    "confidence": 0.0,
                    "flags": ["POOR_GRID_ALIGNMENT"]
                })
            q_vals = [None] * 5
            q_flags_list = [["POOR_GRID_ALIGNMENT"]] * 5
        else:
            for j in range(5):
                q_marks_list.append({
                    "q": j + 1,
                    "value": None,
                    "raw_text": "",
                    "confidence": 0.0,
                    "flags": ["TABLE_DETECTION_FAILED", q_meta.get("reason", "UNAVAILABLE")]
                })
            q_vals = [None] * 5
            q_flags_list = [["TABLE_DETECTION_FAILED"]] * 5
            
        tot_v = tm_res.get("value") if tm_res else None
        tot_flags = tm_res.get("flags", []) if tm_res else []
        st, s_q, t_v, diff = compute_sum_status(q_vals, q_flags_list, tot_v, tot_flags)
        if use_m7:
            max_m_q = fmt_cfg["fields"]["question_marks"].get("max_marks_per_question", 14.0)
            q_sugs = compute_q_cell_suggestions(q_vals, q_flags_list, tot_v, tot_flags, max_marks=max_m_q)
            if q_sugs is not None:
                sug_idx, sug_cands = q_sugs
                q_marks_list[sug_idx]["suggestions"] = sug_cands
                q_marks_list[sug_idx]["suggestion"] = sug_cands[0]
                if "SUGGESTED_FROM_SUM" not in q_marks_list[sug_idx]["flags"]:
                    q_marks_list[sug_idx]["flags"].append("SUGGESTED_FROM_SUM")
                st = "UNAVAILABLE"

            tot_sug = compute_total_suggestion_from_cells(q_vals, q_flags_list, tot_v, tot_flags)
            if tot_sug is not None:
                if tm_res is None:
                    tm_res = {"value": None, "raw_text": "", "confidence": 0.0, "flags": ["SUGGESTED_FROM_CELLS"]}
                else:
                    if "SUGGESTED_FROM_CELLS" not in tm_res.get("flags", []):
                        tm_res.setdefault("flags", []).append("SUGGESTED_FROM_CELLS")
                tm_res["suggestion"] = tot_sug
                if tm_res.get("value") is None:
                    # Decision DEPLOY-2c: A total derived from cells is a suggestion, NEVER the value.
                    # grand_total.value holds only a value read from the grand-total field.
                    # When it is null and the cells are readable, put the derived number in suggestion,
                    # set needs_review = true, keep sum status UNAVAILABLE (never AGREE).
                    for rec_flg in (
                        "RECOVERED_FROM_CELL_CONSENSUS",
                        "TOTAL_DERIVED_FROM_CELLS",
                        "SUM_GATE_CIRCULAR_PREVENTED",
                        "needs_review",
                    ):
                        if rec_flg not in tm_res.get("flags", []):
                            tm_res.setdefault("flags", []).append(rec_flg)
            if tm_res and any(
                f in tm_res.get("flags", [])
                for f in (
                    "RECOVERED_FROM_CELL_CONSENSUS",
                    "SUGGESTED_FROM_CELLS",
                    "TOTAL_DERIVED_FROM_CELLS",
                    "SUM_GATE_CIRCULAR_PREVENTED",
                )
            ):
                if st == "AGREE":
                    st = "UNAVAILABLE"
                if "SUM_GATE_CIRCULAR_PREVENTED" not in tm_res.get("flags", []):
                    tm_res.setdefault("flags", []).append("SUM_GATE_CIRCULAR_PREVENTED")
        marks_sum_dict = {
            "status": "UNAVAILABLE"
            if (
                tm_res
                and any(
                    f in tm_res.get("flags", [])
                    for f in (
                        "RECOVERED_FROM_CELL_CONSENSUS",
                        "SUGGESTED_FROM_CELLS",
                        "TOTAL_DERIVED_FROM_CELLS",
                        "SUM_GATE_CIRCULAR_PREVENTED",
                    )
                )
            )
            else st,
            "sum": round(float(s_q), 2) if s_q is not None else None,
            "total": round(float(t_v), 2) if t_v is not None else None,
            "difference": round(float(diff), 2) if diff is not None else None,
        }
        t_qmarks = (time.perf_counter() - t_q0) * 1000.0

    all_raw_reasons = a_raw_reasons + e_raw_reasons + s_raw_reasons
    if tm_res and ("needs_review" in tm_res.get("flags", [])):
        all_raw_reasons.append(f"TOTAL_MARKS_REVIEW_{','.join(tm_res.get('flags', []))}")
    if marks_sum_dict and marks_sum_dict.get("status") in ("MISMATCH", "POSSIBLE_GRACE"):
        all_raw_reasons.append(f"MARKS_SUM_{marks_sum_dict.get('status')}")
    rescan_rec, needs_rev, all_clean = classify_flags(all_raw_reasons)

    t_total = t_decode + t_loc + t_fmt + t_align + t_crop + t_read + t_qmarks

    if s_m7_res is not None and s_m7_res.get("shape_valid") and s_m7_res.get("value") is not None:
        known_codes = fmt_cfg.get("fields", {}).get("subject_code", {}).get("known_codes", []) if fmt_cfg else []
        s_m7_val = s_m7_res["value"]
        s_res_match = s_res.metadata.get("matched_code") if s_res else None
        s_matched = s_m7_val if s_m7_val in known_codes else s_res_match
        s_final_val = s_matched if s_matched else s_m7_val
        s_raw_txt = s_m7_res.get("raw_text", "")
        s_conf_val = round(float(s_m7_res.get("confidence", 0.0)), 4)
    else:
        s_matched = s_res.metadata.get("matched_code") if s_res else None
        s_final_val = s_matched if s_matched else (s_res.parsed_value if s_res else None)
        s_raw_txt = s_res.raw_text if s_res else ""
        s_conf_val = round(s_res.confidence, 4) if s_res else 0.0

    resp_dict = {
        "filename": filename,
        "format_id": format_id,
        "detected_format": format_id,
        "layout_confidence": round(float(fmt_res.confidence), 4),
        "page_status": page_status_val,
        "page_confidence": page_conf_val,
        "page_quad": page_quad_val,
        "rescan_recommended": rescan_rec,
        "needs_review": needs_rev,
        "review_reasons": all_clean,
        "overall_needs_review": needs_rev,
        "enrolment": {
            "value": e_res.parsed_value if e_res else None,
            "raw_text": e_res.raw_text if e_res else "",
            "confidence": round(e_res.confidence, 4) if e_res else 0.0,
            "char_confidences": [round(c, 4) for c in e_res.metadata.get("char_confidences", [])] if e_res else [],
            "needs_review": e_review,
            "rescan_recommended": e_rescan,
            "review_reasons": e_clean,
        },
        "subject_code": {
            "value": s_final_val,
            "raw_text": s_raw_txt,
            "confidence": s_conf_val,
            "matched_code": s_matched,
            "needs_review": s_review,
            "rescan_recommended": s_rescan,
            "review_reasons": s_clean,
        },
        "total_marks": {
            "value": tm_res["value"],
            "raw_text": tm_res["raw_text"],
            "confidence": tm_res["confidence"],
            "flags": tm_res["flags"],
        } if tm_res is not None else {
            "status": "SKIPPED"
        },
        "alignment": {
            "dx": round(align_res.transform.dx, 2),
            "dy": round(align_res.transform.dy, 2),
            "rot_deg": round(align_res.transform.rot_deg, 3),
            "quality_score": round(align_res.quality_score, 4),
            "needs_review": a_review,
            "rescan_recommended": a_rescan,
            "review_reasons": a_clean,
        },
        "latency_ms": {
            "decode": round(t_decode, 2),
            "page_localise": round(t_loc, 2),
            "format_detect": round(t_fmt, 2),
            "normalise": round(t_align, 2),
            "crop": round(t_crop, 2),
            "read": round(t_read, 2),
            "total": round(t_total, 2),
        },
    }
    if use_m7 and tm_res is not None and "suggestion" in tm_res:
        resp_dict["total_marks"]["suggestion"] = tm_res["suggestion"]
    if extract_question_marks and q_marks_list is not None:
        resp_dict["q_marks"] = q_marks_list
        resp_dict["question_marks"] = q_marks_list
        resp_dict["marks_sum"] = marks_sum_dict
        resp_dict["latency_ms"]["question_marks"] = round(t_qmarks, 2)

    # -------------------------------------------------------------------------
    # PARTIAL SHEET DETECTION (DEPLOY-1 CRITERION 3)
    # Detect if enrolment comb, marks table, or grand-total anchor is missing.
    # -------------------------------------------------------------------------
    comb_missing = (
        (align_res.comb_box is None)
        or (e_crop is None)
        or (e_status in ("MISSING", "FAILED"))
        or any(r.endswith("COMB_NOT_FOUND") or r.endswith("COMB_DETECTION_FAILED") for r in align_res.review_reasons)
        or (any("COMB_NOT_FULLY_DETECTED" in r for r in align_res.review_reasons) and not (e_res and e_res.parsed_value))
    )
    gt_missing = (tm_res is not None and "ANCHOR_NOT_FOUND" in tm_res.get("flags", [])) or (extract_total_marks and (gt_crop is None or match_score < 0.35))

    tbl_missing = False
    if fmt_cfg and "question_marks" in fmt_cfg.get("fields", {}):
        c_can_tbl, _ = pipeline.normaliser.resize_to_canonical_width(img)
        _, _, q_meta_chk = pipeline.table_detector.extract_table_cells(c_can_tbl, format_id, fmt_cfg)
        if q_meta_chk.get("status") in ("UNAVAILABLE", "TABLE_NOT_FOUND", "MISSING") and q_meta_chk.get("reason") in ("HDR_ANCHOR_NOT_FOUND", "GT_ANCHOR_NOT_FOUND", "INSUFFICIENT_LINES"):
            tbl_missing = True

    is_partial = comb_missing or gt_missing or tbl_missing
    if is_partial:
        resp_dict["rescan_recommended"] = True
        resp_dict["needs_review"] = True
        resp_dict["overall_needs_review"] = True
        if "PARTIAL_SHEET" not in resp_dict["review_reasons"]:
            resp_dict["review_reasons"].append("PARTIAL_SHEET")

        if "enrolment" in resp_dict and isinstance(resp_dict["enrolment"], dict):
            if "PARTIAL_SHEET" not in resp_dict["enrolment"]["review_reasons"]:
                resp_dict["enrolment"]["review_reasons"].append("PARTIAL_SHEET")
            resp_dict["enrolment"]["rescan_recommended"] = True
            resp_dict["enrolment"]["needs_review"] = True

        if "subject_code" in resp_dict and isinstance(resp_dict["subject_code"], dict):
            if "PARTIAL_SHEET" not in resp_dict["subject_code"]["review_reasons"]:
                resp_dict["subject_code"]["review_reasons"].append("PARTIAL_SHEET")
            resp_dict["subject_code"]["rescan_recommended"] = True
            resp_dict["subject_code"]["needs_review"] = True

        if "total_marks" in resp_dict and isinstance(resp_dict["total_marks"], dict):
            if "flags" in resp_dict["total_marks"]:
                if "PARTIAL_SHEET" not in resp_dict["total_marks"]["flags"]:
                    resp_dict["total_marks"]["flags"].append("PARTIAL_SHEET")
            resp_dict["total_marks"]["rescan_recommended"] = True
            resp_dict["total_marks"]["needs_review"] = True

        if "q_marks" in resp_dict and isinstance(resp_dict["q_marks"], list):
            for qm in resp_dict["q_marks"]:
                if isinstance(qm, dict) and "flags" in qm:
                    if "PARTIAL_SHEET" not in qm["flags"]:
                        qm["flags"].append("PARTIAL_SHEET")

    # -------------------------------------------------------------------------
    # DECLARED SUBJECT CODE (DEPLOY-1 CRITERION 4)
    # -------------------------------------------------------------------------
    if subject_code_declared is not None and str(subject_code_declared).strip():
        decl = str(subject_code_declared).strip()
        ocr_val = resp_dict["subject_code"]["value"]
        resp_dict["subject_code"]["value"] = decl
        resp_dict["subject_code"]["source"] = "declared"
        resp_dict["subject_code"]["subject_code_read"] = ocr_val
    else:
        resp_dict["subject_code"]["source"] = "ocr"

    # -------------------------------------------------------------------------
    # DESKEWED WEB PREVIEW FOR BROWSER INSPECTOR
    # -------------------------------------------------------------------------
    if align_res is not None and align_res.image is not None and align_res.image.size > 0:
        prev_h, prev_w = align_res.image.shape[:2]
        if prev_w > 1200:
            scale = 1200.0 / prev_w
            prev_mat = cv2.resize(align_res.image, (1200, int(prev_h * scale)), interpolation=cv2.INTER_AREA)
        else:
            prev_mat = align_res.image
        success, buf = cv2.imencode(".jpg", prev_mat, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if success:
            resp_dict["image_preview"] = f"data:image/jpeg;base64,{base64.b64encode(buf).decode('ascii')}"

    # Explicitly release buffers and trim Linux glibc heap to keep RAM < 350 MB
    import gc
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass

    return resp_dict



@router.post("/predict")
async def predict_v2(
    request: Request,
    file: UploadFile = File(...),
    subject_code_declared: Optional[str] = Form(None),
    extract_total_marks: bool = Form(True),
    extract_question_marks: bool = Form(False),
    phase: Optional[str] = Form("full"),
    enable_m7_rules: Optional[bool] = Form(None),
    enable_page_localiser: Optional[bool] = Form(None),
    current_key: KeyInfo = Depends(get_current_key),
):
    """Single-sheet OCR v2 prediction endpoint."""
    if not extract_question_marks and request.query_params.get("extract_question_marks", "").lower() in ("true", "1"):
        extract_question_marks = True
    rate_limiter.check_rate_limit(current_key.key_id, current_key.rate_limit_rpm)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Allowed extensions: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    pipeline = get_pipeline()
    content = await file.read()
    filename = file.filename or "unknown"
    size_kb = len(content) / 1024.0
    
    recv_log = (
        f"\n{'='*60}\n"
        f">>> [PREDICT RECEIVED] File: {filename} | Size: {size_kb:.2f} KB | ContentType: {file.content_type}\n"
        f"    Caller Key: {current_key.key_id} ({current_key.name})\n"
        f"{'='*60}"
    )
    logger.info(recv_log)
    print(recv_log, flush=True)

    t0 = time.time()
    try:
        result = process_sheet_bytes(
            content,
            filename,
            pipeline,
            extract_total_marks=extract_total_marks,
            extract_question_marks=extract_question_marks,
            phase=phase,
            enable_m7_rules=enable_m7_rules,
            enable_page_localiser=enable_page_localiser,
            subject_code_declared=subject_code_declared,
        )
    except Exception as exc:
        err_log = f"\n{'='*60}\n!!! [PREDICT ERROR] for {filename}: {exc}\n{'='*60}"
        logger.error(err_log, exc_info=True)
        print(err_log, flush=True)
        raise exc
    elapsed_ms = (time.time() - t0) * 1000.0

    enrolment = result.get("enrolment", {}).get("value") if isinstance(result.get("enrolment"), dict) else None
    conf = result.get("enrolment", {}).get("confidence") if isinstance(result.get("enrolment"), dict) else None
    total = result.get("total_marks", {}).get("value") if isinstance(result.get("total_marks"), dict) else None
    sum_info = result.get("marks_sum", {})
    sum_status = sum_info.get("status") if isinstance(sum_info, dict) else None
    q_marks = result.get("q_marks", [])
    q_summary = [f"Q{q.get('q')}: {q.get('value')}" for q in q_marks if isinstance(q, dict)] if q_marks else []

    complete_log = (
        f"\n{'='*60}\n"
        f"<<< [PREDICT COMPLETE] File: {filename} in {elapsed_ms:.2f} ms\n"
        f"    [OUTPUT GENERATED]:\n"
        f"    * Enrolment: {enrolment} (confidence: {conf})\n"
        f"    * Total Marks: {total}\n"
        f"    * Sum Agreement Status: {sum_status}\n"
        f"    * Question Marks: {q_summary}\n"
        f"    * Needs Review: {result.get('needs_review')} (Reasons: {result.get('review_reasons')})\n"
        f"    * Rescan Recommended: {result.get('rescan_recommended')}\n"
        f"{'='*60}"
    )
    logger.info(complete_log)
    print(complete_log, flush=True)

    return result


@router.post("/batch")
async def batch_v2(
    request: Request,
    files: List[UploadFile] = File(...),
    subject_code_declared: Optional[str] = Form(None),
    roster: Optional[str] = Form(None),
    extract_total_marks: bool = Form(True),
    extract_question_marks: bool = Form(False),
    phase: Optional[str] = Form("full"),
    enable_m7_rules: Optional[bool] = Form(None),
    enable_page_localiser: Optional[bool] = Form(None),
    current_key: KeyInfo = Depends(get_current_key),
):
    """Batch OCR v2 prediction endpoint with bundle-level subject_code consensus and batch review signals."""
    if not extract_question_marks and request.query_params.get("extract_question_marks", "").lower() in ("true", "1"):
        extract_question_marks = True
    rate_limiter.check_rate_limit(current_key.key_id, current_key.rate_limit_rpm)
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided for batch processing.",
        )

    pipeline = get_pipeline()
    results = []
    sheet_records = []

    for file in files:
        ext = Path(file.filename or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File '{file.filename}' has unsupported format '{ext}'.",
            )
        content = await file.read()
        sheet_res = process_sheet_bytes(
            content,
            file.filename or "unknown",
            pipeline,
            extract_total_marks=extract_total_marks,
            extract_question_marks=extract_question_marks,
            phase=phase,
            enable_m7_rules=enable_m7_rules,
            enable_page_localiser=enable_page_localiser,
            subject_code_declared=subject_code_declared,
        )
        results.append(sheet_res)


        read_code = sheet_res["subject_code"].get("subject_code_read") or sheet_res["subject_code"].get("matched_code") or sheet_res["subject_code"].get("value")
        sheet_records.append({
            "sheet_name": file.filename or f"sheet_{len(sheet_records)}",
            "matched_code": read_code,
            "fields": {
                "subject_code": {
                    "parsed_value": read_code,
                    "matched_code": sheet_res["subject_code"].get("matched_code"),
                    "raw_text": sheet_res["subject_code"]["raw_text"],
                    "confidence": sheet_res["subject_code"]["confidence"],
                }
            }
        })

    # Consensus calculation
    vote_res = pipeline.consensus.compute_consensus(
        sheet_records=sheet_records,
        subject_code_declared=subject_code_declared,
    )

    # Optional roster parsing
    parsed_roster = None
    if roster:
        try:
            import json
            val = json.loads(roster)
            if isinstance(val, list):
                parsed_roster = [str(x).strip() for x in val]
            else:
                parsed_roster = [str(roster).strip()]
        except Exception:
            parsed_roster = [x.strip() for x in roster.split(",") if x.strip()]

    # Batch review evaluation
    review_res = pipeline.review_manager.evaluate_batch(
        sheets=results,
        roster=parsed_roster,
    )

    return {
        "total_sheets": len(results),
        "sheets": review_res.sheets,
        "batch_consensus": asdict(vote_res),
        "batch_review": {
            "total_sheets": review_res.total_sheets,
            "flagged_sheets": review_res.flagged_sheets,
            "rescan_count": review_res.rescan_count,
            "duplicate_enrolments": review_res.duplicate_enrolments,
            "roster_provided": review_res.roster_provided,
            "missing_from_batch": review_res.missing_from_batch,
        },
    }


@router.post("/convert-pdf")
async def convert_pdf_endpoint(
    request: Request,
    file: UploadFile = File(..., description="PDF file containing exam sheets"),
    scale: float = Form(2.0),
    output_dir: Optional[str] = Form(None),
    current_key: KeyInfo = Depends(get_current_key),
):
    """
    Extracts all pages from an uploaded PDF document and renders each as a high-resolution JPEG image.
    Supports writing directly to a local output directory or returning base64 images.
    """
    rate_limiter.check_rate_limit(current_key.key_id, current_key.rate_limit_rpm)
    ext = Path(file.filename or "").suffix.lower()
    if ext != ".pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Expected a .pdf document.",
        )

    import io
    import base64
    import pypdfium2 as pdfium

    content = await file.read()
    if len(content) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded PDF file is empty or corrupted.",
        )

    try:
        pdf = pdfium.PdfDocument(content)
    except Exception as exc:
        logger.error(f"Failed to open PDF document '{file.filename}': {exc}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not parse PDF document: {exc}",
        )

    total_pages = len(pdf)
    if total_pages == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF document contains 0 pages.",
        )

    # Check output directory
    target_dir = None
    if output_dir and os.path.isdir(output_dir):
        target_dir = Path(output_dir)

    base_stem = Path(file.filename or "sheet").stem
    unique_prefix = f"pdf-{int(time.time()*1000)}-{os.urandom(4).hex()}"
    pages_data = []

    for idx, page in enumerate(pdf):
        page_num = idx + 1
        pil_img = page.render(scale=scale).to_pil()
        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")

        page_filename = f"{unique_prefix}-p{page_num:03d}.jpg"
        page_info = {
            "page_number": page_num,
            "filename": page_filename,
            "original_name": f"{base_stem} (Page {page_num})",
            "width": pil_img.width,
            "height": pil_img.height,
        }

        if target_dir:
            dest_path = target_dir / page_filename
            pil_img.save(dest_path, "JPEG", quality=92)
            page_info["file_path"] = str(dest_path.resolve())
            page_info["size_bytes"] = os.path.getsize(dest_path)
        else:
            buf = io.BytesIO()
            pil_img.save(buf, "JPEG", quality=92)
            raw_bytes = buf.getvalue()
            page_info["base64_data"] = base64.b64encode(raw_bytes).decode("utf-8")
            page_info["size_bytes"] = len(raw_bytes)

        pages_data.append(page_info)

    logger.info(f"Successfully converted PDF '{file.filename}' ({total_pages} pages) to images.")
    return {
        "success": True,
        "filename": file.filename,
        "total_pages": total_pages,
        "pages": pages_data,
    }

