"""
Interactive CLI Labeling Tool for Benchmark B (data_v2_images).
Enables human annotators to record verified ground-truth values into data/canonical_labels_v2.csv.

Features:
  1. Displays image filename, image dimensions, and OCR hints from results.csv.
  2. Prompts for true enrollment_no, true subject_code, and optional total_marks.
  3. Resumes automatically from the first unlabeled image.
  4. Never overwrites existing verified labels without explicit confirmation.
  5. Saves after every single labeled image (safe against interruption).

Usage:
    python scripts/label_benchmark_b.py
    python scripts/label_benchmark_b.py --image page_000001.png
    python scripts/label_benchmark_b.py --allow-overwrite
"""

import sys
import os
import re
import csv
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = PROJECT_ROOT / "data" / "data_v2_images"
GT_CSV_PATH = PROJECT_ROOT / "data" / "canonical_labels_v2.csv"
PREDICTIONS_CSV_PATH = PROJECT_ROOT / "new_set_output" / "results.csv"

FIELDNAMES = ["image_filename", "enrollment_no", "subject_code", "total_marks", "status"]


def load_existing_gt(csv_path: Path) -> Dict[str, Dict[str, str]]:
    """Loads existing ground-truth records indexed by image_filename."""
    records = {}
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fname = row.get("image_filename")
                if fname:
                    records[fname.strip()] = row
    return records


def save_single_record(csv_path: Path, record: Dict[str, str]):
    """Appends or updates a record and flushes to CSV."""
    records = load_existing_gt(csv_path)
    records[record["image_filename"]] = record

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for k in sorted(records.keys()):
            writer.writerow(records[k])


def load_predictions(pred_path: Path) -> Dict[str, Dict[str, str]]:
    """Loads extracted predictions from run_new_batch results.csv for annotator reference."""
    preds = {}
    if pred_path.exists():
        with open(pred_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fname = row.get("image_name")
                if fname:
                    preds[fname.strip()] = row
    return preds


def label_image(
    img_name: str,
    img_path: Path,
    existing: Optional[Dict[str, str]],
    pred: Optional[Dict[str, str]],
    open_image: bool = False,
) -> Optional[Dict[str, str]]:
    """Interactive prompt for a single image."""
    print("\n" + "=" * 70)
    print(f"LABELING: {img_name}")
    print(f"Path:     {img_path}")
    if existing:
        print(f"Current Verified Ground Truth: Roll='{existing.get('enrollment_no')}', Subj='{existing.get('subject_code')}'")

    if pred:
        print(f"OCR Prediction Reference:")
        print(f"  Enrolment:   '{pred.get('enrol_parsed_full', '')}' (Raw: '{pred.get('enrol_raw_ocr', '')}') [conf: {pred.get('enrol_conf', '')}]")
        print(f"  Subject:     '{pred.get('subject_parsed', '')}' (Raw: '{pred.get('subject_raw_ocr', '')}') [conf: {pred.get('subject_conf', '')}]")
    print("-" * 70)
    print("Commands: Enter values, press ENTER to accept default/existing, or type 'q' to quit.")

    if open_image and sys.platform.startswith("win"):
        try:
            os.startfile(str(img_path))
        except Exception as e:
            print(f"  (Could not open system image viewer: {e})")

    # 1. Enrollment Number
    default_enrol = existing.get("enrollment_no") if existing else (pred.get("enrol_parsed_full", "") if pred else "")
    while True:
        prompt = f"True Enrollment No [{default_enrol}]: "
        val_enrol = input(prompt).strip()
        if val_enrol.lower() == "q":
            return None
        if not val_enrol:
            val_enrol = default_enrol

        if not val_enrol:
            print("  [!] Enrollment number cannot be empty. Please enter value or 'q' to quit.")
            continue

        # Warning if non-standard format, but allow annotator confirmation
        if not re.match(r"^0801CA25\d{4}$", val_enrol):
            confirm = input(f"  [?] Value '{val_enrol}' does not match standard '0801CA25xxxx'. Keep this value? (y/n): ")
            if confirm.lower().startswith("y"):
                break
        else:
            break

    # 2. Subject Code (Computer Networks default for this batch is CT10715)
    suggested_subj = "CT10715"
    default_subj = existing.get("subject_code") if existing else suggested_subj
    prompt_subj = f"True Subject Code [{default_subj}]: "
    val_subj = input(prompt_subj).strip()
    if val_subj.lower() == "q":
        return None
    if not val_subj:
        val_subj = default_subj

    # 3. Total Marks (Optional / Leave blank if not verified)
    default_marks = existing.get("total_marks", "") if existing else ""
    prompt_marks = f"True Total Marks (press ENTER to leave empty) [{default_marks}]: "
    val_marks = input(prompt_marks).strip()
    if val_marks.lower() == "q":
        return None
    if not val_marks:
        val_marks = default_marks

    return {
        "image_filename": img_name,
        "enrollment_no": val_enrol.strip(),
        "subject_code": val_subj.strip(),
        "total_marks": val_marks.strip(),
        "status": "verified",
    }


def main():
    parser = argparse.ArgumentParser(description="Interactive Labeling Utility for Benchmark B")
    parser.add_argument("--image", type=str, default=None, help="Label a specific image name (e.g. page_000001.png)")
    parser.add_argument("--allow-overwrite", action="store_true", help="Re-prompt even if image is already verified")
    parser.add_argument("--open-viewer", action="store_true", help="Automatically launch default image viewer for each sheet")
    args = parser.parse_args()

    if not IMAGES_DIR.exists():
        print(f"[FATAL] Images directory not found: {IMAGES_DIR}")
        sys.exit(1)

    all_images = sorted([f for f in os.listdir(IMAGES_DIR) if f.lower().endswith((".png", ".jpg", ".jpeg"))])
    total_images = len(all_images)

    existing_gt = load_existing_gt(GT_CSV_PATH)
    predictions = load_predictions(PREDICTIONS_CSV_PATH)

    print("=" * 70)
    print("BENCHMARK B GROUND-TRUTH LABELING UTILITY")
    print(f"Target CSV: {GT_CSV_PATH}")
    print(f"Progress:   {len(existing_gt)} / {total_images} images currently labeled")
    print("=" * 70)

    if args.image:
        target_name = Path(args.image).name
        if target_name not in all_images:
            print(f"[ERROR] Image '{target_name}' not found in {IMAGES_DIR}")
            sys.exit(1)
        images_to_label = [target_name]
    else:
        images_to_label = all_images

    labeled_this_session = 0

    for idx, img_name in enumerate(images_to_label, start=1):
        existing = existing_gt.get(img_name)
        if existing and not args.allow_overwrite and not args.image:
            continue

        img_path = IMAGES_DIR / img_name
        pred = predictions.get(img_name)

        record = label_image(
            img_name=img_name,
            img_path=img_path,
            existing=existing,
            pred=pred,
            open_image=args.open_viewer,
        )

        if record is None:
            print("\nLabeling paused by user. Progress saved.")
            break

        save_single_record(GT_CSV_PATH, record)
        existing_gt[img_name] = record
        labeled_this_session += 1
        print(f"--> Saved '{img_name}' [{record['enrollment_no']} | {record['subject_code']}]")

    print("\n" + "=" * 70)
    print(f"Session finished. Total labeled in dataset: {len(existing_gt)} / {total_images}")
    print("=" * 70)


if __name__ == "__main__":
    main()
