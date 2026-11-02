"""
Interactive CLI Labeling Tool for exam cover sheets.
Allows human annotators to record verified ground-truth values into the canonical dataset.

Usage:
    python scripts/label_cover_sheet.py --image data/raw/images/page_000001.png
    python scripts/label_cover_sheet.py --images-dir data/raw/images
"""

import argparse
import re
import csv
import logging
from pathlib import Path
from typing import Optional, Dict

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("label_cover_sheet")

DEFAULT_CSV = Path("data/canonical_labels.csv")
FIELDNAMES = ["image_filename", "enrollment_no", "subject_code", "total_marks", "sheet_no", "status"]


def load_existing_labels(csv_path: Path) -> Dict[str, Dict[str, str]]:
    """Loads existing labels indexed by image_filename."""
    records = {}
    if csv_path.exists():
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records[row["image_filename"]] = row
    return records


def save_labels(csv_path: Path, records: Dict[str, Dict[str, str]]):
    """Saves records dictionary to CSV preserving standard fieldnames."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for k in sorted(records.keys()):
            writer.writerow(records[k])


def label_single_image(
    image_path: Path,
    records: Dict[str, Dict[str, str]],
    default_subject: str = "CT10718",
    allow_overwrite: bool = False,
) -> bool:
    """Prompts the user to label a single exam cover sheet image."""
    img_name = image_path.name
    existing = records.get(img_name)

    if existing and not allow_overwrite:
        logger.info(f"[SKIP] '{img_name}' is already labeled: {existing['enrollment_no']} | {existing['subject_code']} | {existing['total_marks']}")
        return False

    print("\n" + "=" * 60)
    print(f"LABELING: {img_name}")
    if existing:
        print(f"Current values: {existing}")
    print("=" * 60)

    # 1. Prompt Enrollment Number
    while True:
        prompt_str = f"Enrollment No (e.g. 0801CA251001) [{existing['enrollment_no'] if existing else ''}]: "
        val_enroll = input(prompt_str).strip() or (existing["enrollment_no"] if existing else "")
        if re.match(r"^0801CA25\d{4}$", val_enroll):
            break
        print("  [!] Invalid format: Must match '0801CA25xxxx' (12 alphanumeric characters). Try again.")

    # 2. Prompt Subject Code
    prompt_subj = f"Subject Code [{existing['subject_code'] if existing else default_subject}]: "
    val_subj = input(prompt_subj).strip() or (existing["subject_code"] if existing else default_subject)

    # 3. Prompt Total Marks
    while True:
        prompt_marks = f"Total Marks (0-70) [{existing['total_marks'] if existing else ''}]: "
        val_marks = input(prompt_marks).strip() or (existing["total_marks"] if existing else "")
        try:
            int_marks = int(val_marks)
            if 0 <= int_marks <= 70:
                break
            print("  [!] Marks out of range: Must be between 0 and 70.")
        except ValueError:
            print("  [!] Must be an integer value. Try again.")

    sheet_no = existing.get("sheet_no", "") if existing else ""

    records[img_name] = {
        "image_filename": img_name,
        "enrollment_no": val_enroll,
        "subject_code": val_subj,
        "total_marks": str(val_marks),
        "sheet_no": sheet_no,
        "status": "verified",
    }
    logger.info(f"Saved: {img_name} -> [{val_enroll}, {val_subj}, {val_marks}]")
    return True


def main():
    parser = argparse.ArgumentParser(description="Label exam cover sheets.")
    parser.add_argument("--image", type=Path, help="Single image file to label")
    parser.add_argument("--images-dir", type=Path, help="Directory of images to label sequentially")
    parser.add_argument("--csv", default=DEFAULT_CSV, type=Path, help="Path to canonical CSV ground truth")
    parser.add_argument("--overwrite", action="store_true", help="Allow updating already-labeled images")
    args = parser.parse_args()

    records = load_existing_labels(args.csv)

    if args.image:
        if not args.image.is_file():
            raise FileNotFoundError(f"Image not found: {args.image}")
        label_single_image(args.image, records, allow_overwrite=args.overwrite)
        save_labels(args.csv, records)
    elif args.images_dir:
        if not args.images_dir.is_dir():
            raise NotADirectoryError(f"Directory not found: {args.images_dir}")
        img_files = sorted(p for p in args.images_dir.glob("*.png"))
        logger.info(f"Found {len(img_files)} images in {args.images_dir}")
        for p in img_files:
            try:
                changed = label_single_image(p, records, allow_overwrite=args.overwrite)
                if changed:
                    save_labels(args.csv, records)
            except KeyboardInterrupt:
                logger.info("\nSession paused. Progress saved to CSV.")
                break
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
