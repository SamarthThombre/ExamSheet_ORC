"""
Split raw annotated images + YOLO-format label .txt files into the
train/val folder structure that dataset/data.yaml expects.

Usage:
    python scripts/prepare_dataset.py \
        --images raw_images \
        --labels raw_labels \
        --out dataset \
        --val-split 0.15

Expects: for every image file in --images, a same-named .txt file in
--labels (LabelImg produces this automatically when saved as YOLO).
Images with no matching label file are skipped with a warning —
that usually means annotation was missed for that file.
"""

import argparse
import random
import shutil
from pathlib import Path

IMG_EXTS = {".jpg", ".jpeg", ".png"}


def find_pairs(images_dir: Path, labels_dir: Path):
    pairs = []
    for img_path in sorted(images_dir.iterdir()):
        if img_path.suffix.lower() not in IMG_EXTS:
            continue
        label_path = labels_dir / f"{img_path.stem}.txt"
        if not label_path.exists():
            print(f"  [skip] no label for {img_path.name}")
            continue
        pairs.append((img_path, label_path))
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, help="folder of raw photos")
    ap.add_argument("--labels", required=True, help="folder of YOLO .txt labels")
    ap.add_argument("--out", default="dataset", help="output dataset root")
    ap.add_argument("--val-split", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    images_dir = Path(args.images)
    labels_dir = Path(args.labels)
    out_root = Path(args.out)

    pairs = find_pairs(images_dir, labels_dir)
    if not pairs:
        raise SystemExit(
            "No annotated image/label pairs found — check paths. "
            "This script expects same-named .txt label files next to each image file. "
            "If your labels are in a CSV or another format, convert them to YOLO .txt files first."
        )

    random.seed(args.seed)
    random.shuffle(pairs)

    n_val = max(1, int(len(pairs) * args.val_split)) if len(pairs) > 4 else 1
    val_pairs = pairs[:n_val]
    train_pairs = pairs[n_val:]

    for split_name, split_pairs in [("train", train_pairs), ("val", val_pairs)]:
        img_out = out_root / "images" / split_name
        lbl_out = out_root / "labels" / split_name
        img_out.mkdir(parents=True, exist_ok=True)
        lbl_out.mkdir(parents=True, exist_ok=True)
        for img_path, label_path in split_pairs:
            shutil.copy2(img_path, img_out / img_path.name)
            shutil.copy2(label_path, lbl_out / f"{img_path.stem}.txt")

    print(f"Done. {len(train_pairs)} train images, {len(val_pairs)} val images.")
    print(f"Dataset ready at: {out_root}/  (matches data.yaml)")


if __name__ == "__main__":
    main()
