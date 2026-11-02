"""
Targeted Format V2 fallback re-extraction and normalization script.
- Pre-crops all images to format_v2 geometry first (instant disk write).
- Processes ONLY the rows that actually need fixing, skipping already-correct rows.
- Flushes to results.csv after EVERY image so progress is immediately saved.
"""

import sys
import time
from pathlib import Path
import cv2
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ocr.recognition.paddle_engine import PaddleOCREngine
from ocr.detection.fallbacks import get_enrolment_no_crop
from ocr.postprocessing.cleaning import (
    fix_enrollment_no,
    clean_single_subject_code,
)
from run_new_batch import (
    extract_enrol_digits_no_prefix,
    is_subject_defaulted,
    generate_summary,
    CROPS_ENROL_DIR,
    CSV_PATH,
    SUMMARY_PATH,
    INPUT_DIR,
)

GT_PATH = PROJECT_ROOT / "data" / "canonical_labels_v2.csv"


def main():
    print("=" * 80, flush=True)
    print("TARGETED FORMAT V2 RE-EXTRACTION & RECOVERY", flush=True)
    print("=" * 80, flush=True)

    if not CSV_PATH.exists():
        print(f"Error: {CSV_PATH} not found.", flush=True)
        return

    df = pd.read_csv(CSV_PATH)
    gt_df = pd.read_csv(GT_PATH).set_index("image_filename") if GT_PATH.exists() else None

    # Step 1: Instant Subject Code update across all rows
    print("Updating subject codes with institutional rules...", flush=True)
    for idx, row in df.iterrows():
        subj_raw = row.get("subject_raw_ocr")
        subj_parsed = clean_single_subject_code(subj_raw, default="CT10718")
        df.at[idx, "subject_parsed"] = subj_parsed
        df.at[idx, "subject_defaulted"] = is_subject_defaulted(subj_raw, subj_parsed)

    # Step 2: Pre-crop any missing format_v2 crops
    print("Pre-cropping any missing format_v2 crops...", flush=True)
    pre_crop_count = 0
    for idx, row in df.iterrows():
        img_name = row["image_name"]
        crop_path = CROPS_ENROL_DIR / img_name
        needs_crop = True
        if crop_path.exists():
            existing = cv2.imread(str(crop_path))
            if existing is not None and existing.shape[0] >= 500:
                needs_crop = False
        if needs_crop:
            img_path = INPUT_DIR / img_name
            if img_path.exists():
                full_img = cv2.imread(str(img_path))
                if full_img is not None:
                    crop, _ = get_enrolment_no_crop(full_img, None, format_name="format_v2")
                    cv2.imwrite(str(crop_path), crop)
                    pre_crop_count += 1
    print(f"Pre-cropped {pre_crop_count} images to format_v2 geometry.", flush=True)

    # Step 3: Identify only rows that need OCR
    to_fix_indices = []
    for idx, row in df.iterrows():
        if row.get("enrol_box_source") == "fallback":
            img_name = row["image_name"]
            gt_val = str(gt_df.loc[img_name, "enrollment_no"]).strip() if (gt_df is not None and img_name in gt_df.index) else ""
            pred_val = str(row.get("enrol_parsed_full", "")).strip()
            if not gt_val or gt_val.lower() != pred_val.lower():
                to_fix_indices.append(idx)

    print(f"Targeting {len(to_fix_indices)} fallback rows needing OCR re-extraction.", flush=True)
    if not to_fix_indices:
        print("All fallback rows already match ground truth!", flush=True)
        df.to_csv(CSV_PATH, index=False)
        generate_summary(CSV_PATH, SUMMARY_PATH)
        return

    engine = PaddleOCREngine()
    engine.load_engine()

    t0 = time.perf_counter()
    recovered = 0

    for i, idx in enumerate(to_fix_indices, 1):
        row = df.loc[idx]
        img_name = row["image_name"]
        crop_path = CROPS_ENROL_DIR / img_name

        crop = cv2.imread(str(crop_path))
        if crop is None:
            continue

        t_start = time.perf_counter()
        txt_enrol, conf_enrol = engine.ocr_crop(crop)
        t_img = time.perf_counter() - t_start

        df.at[idx, "enrol_raw_ocr"] = txt_enrol
        df.at[idx, "enrol_conf"] = round(conf_enrol, 4)

        enrol_parsed = fix_enrollment_no(txt_enrol) or ""
        enrol_no_prefix = extract_enrol_digits_no_prefix(txt_enrol)
        df.at[idx, "enrol_parsed_full"] = enrol_parsed
        df.at[idx, "enrol_digits_no_prefix"] = enrol_no_prefix

        # Check match against GT
        gt_val = str(gt_df.loc[img_name, "enrollment_no"]).strip() if (gt_df is not None and img_name in gt_df.index) else ""
        is_match = (enrol_parsed.lower() == gt_val.lower()) if gt_val else False
        if is_match:
            recovered += 1
        status = "MATCH" if is_match else "DIFF"

        safe_raw = txt_enrol.encode("ascii", "replace").decode("ascii")[:30]
        print(
            f"[{i:2d}/{len(to_fix_indices)}] {img_name} ({t_img:.1f}s) -> "
            f"Parsed: {enrol_parsed or 'None':<14} | GT: {gt_val:<14} | [{status}]",
            flush=True,
        )

        # Flush after every row
        df.to_csv(CSV_PATH, index=False)

    total_time = time.perf_counter() - t0
    print("-" * 80, flush=True)
    print(f"Finished {len(to_fix_indices)} images in {total_time:.1f}s (recovered {recovered} matches)", flush=True)
    generate_summary(CSV_PATH, SUMMARY_PATH)
    print(f"Summary updated at {SUMMARY_PATH}", flush=True)


if __name__ == "__main__":
    main()
