"""
Run the trained YOLO model on new cover-sheet photos, crop out each
detected field, and write a manifest CSV that the next stage (OCR)
will read.

Usage:
    python scripts/infer_crop.py \
        --weights runs/exam_fields/weights/best.pt \
        --images new_photos \
        --out crops

Output:
    crops/<image_stem>__<class_name>.jpg   — one crop per detected field
    crops/manifest.csv                     — image, field, crop_path, confidence, box
"""

import argparse
import csv
from pathlib import Path

import cv2
from ultralytics import YOLO

IMG_EXTS = {".jpg", ".jpeg", ".png"}
PAD_FRAC = 0.04  # small padding around each box so OCR doesn't clip strokes


def pad_box(x1, y1, x2, y2, w, h, pad_frac):
    pad_x = int((x2 - x1) * pad_frac) + 2
    pad_y = int((y2 - y1) * pad_frac) + 2
    return (
        max(0, x1 - pad_x),
        max(0, y1 - pad_y),
        min(w, x2 + pad_x),
        min(h, y2 + pad_y),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--images", required=True, help="folder of new photos to process")
    ap.add_argument("--out", default="crops")
    ap.add_argument("--conf", type=float, default=0.35, help="min detection confidence")
    args = ap.parse_args()

    model = YOLO(args.weights)
    class_names = model.names  # {0: 'enrolment_no', 1: 'subject_code', 2: 'grand_total'}

    images_dir = Path(args.images)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows = []

    image_paths = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMG_EXTS)
    if not image_paths:
        raise SystemExit(f"No images found in {images_dir}")

    results = model.predict(source=[str(p) for p in image_paths], conf=args.conf, verbose=False)

    for img_path, result in zip(image_paths, results):
        img = cv2.imread(str(img_path))
        h, w = img.shape[:2]

        # keep only the highest-confidence detection per class —
        # each field should appear exactly once on a cover sheet
        best_per_class = {}
        for box in result.boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            if cls_id not in best_per_class or conf > best_per_class[cls_id][0]:
                best_per_class[cls_id] = (conf, box.xyxy[0].tolist())

        if not best_per_class:
            print(f"  [warn] no fields detected in {img_path.name}")
            continue

        for cls_id, (conf, (x1, y1, x2, y2)) in best_per_class.items():
            cls_name = class_names[cls_id]
            x1, y1, x2, y2 = pad_box(int(x1), int(y1), int(x2), int(y2), w, h, PAD_FRAC)
            crop = img[y1:y2, x1:x2]

            crop_name = f"{img_path.stem}__{cls_name}.jpg"
            crop_path = out_dir / crop_name
            cv2.imwrite(str(crop_path), crop)

            manifest_rows.append(
                {
                    "source_image": img_path.name,
                    "field": cls_name,
                    "crop_path": str(crop_path),
                    "confidence": round(conf, 3),
                    "box_x1y1x2y2": f"{x1},{y1},{x2},{y2}",
                }
            )

    manifest_path = out_dir / "manifest.csv"
    with open(manifest_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["source_image", "field", "crop_path", "confidence", "box_x1y1x2y2"]
        )
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"\n{len(manifest_rows)} field crops written to {out_dir}/")
    print(f"Manifest: {manifest_path}  (feed this into the OCR stage next)")


if __name__ == "__main__":
    main()
