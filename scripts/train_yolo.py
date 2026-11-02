"""
Fine-tune YOLOv8 (nano) to detect the 3 cover-sheet fields.

Usage:
    python train_yolo.py --data data --epochs 100

The dataset can be passed as either a YAML file or a folder containing
one. This project stores its config in the project root as data.yaml,
so --data data works when the data folder lives beside the script.

Starts from Ultralytics' pretrained COCO weights (yolov8n.pt, auto-
downloaded on first run) rather than training from scratch — this is
what makes a 50-100 image dataset workable for a 3-class task.

Augmentation is tuned for a single, clean, pre-cropped and
color-corrected template — light jitter only, since the inputs are
already fairly consistent and heavy distortion would just teach the
model to handle conditions it won't see at inference. Mosaic is
turned off — it can hurt fixed-layout document detection by
stitching unrelated crops together, which doesn't match real-world
inputs here.

If you later add a second template, or start feeding in raw/tilted
phone photos instead of pre-cropped ones, bump degrees/perspective/
hsv back up (see commented alternative values below) and reintroduce
a template-detection step before this stage.
"""

import argparse
from pathlib import Path

from ultralytics import YOLO


def resolve_data_path(data_arg: str) -> str:
    """Accept either a YAML file or a folder containing a dataset config."""
    supplied = Path(data_arg)
    project_root = Path(__file__).resolve().parent

    candidates = []
    if supplied.exists():
        if supplied.is_file():
            return str(supplied)
        candidates.extend([
            supplied / "data.yaml",
            supplied / "dataset.yaml",
        ])

    if not supplied.is_absolute():
        candidates.extend([
            project_root / data_arg / "data.yaml" if data_arg else None,
            project_root / "data.yaml",
            project_root / "dataset" / "data.yaml",
            project_root / supplied.name / "data.yaml" if supplied.name else None,
        ])

    for candidate in candidates:
        if candidate and candidate.exists():
            return str(candidate)

    raise FileNotFoundError(
        f"Dataset config not found for '{data_arg}'. "
        "Pass a .yaml file or a folder that contains data.yaml (for example: --data data)."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data", help="dataset YAML file or folder containing one")
    ap.add_argument("--model", default="yolov8n.pt", help="pretrained base weights")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=1280, help="phone photos are high-res; keep detail")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--project", default="runs", help="where to save training runs")
    ap.add_argument("--name", default="exam_fields")
    args = ap.parse_args()

    data_path = resolve_data_path(args.data)
    print(f"Using dataset config: {data_path}")

    model = YOLO(args.model)

    model.train(
        data=data_path,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        project=args.project,
        name=args.name,
        patience=20,
        mosaic=0.0,
        degrees=5.0,
        perspective=0.0,
        hsv_h=0.01,
        hsv_s=0.3,
        hsv_v=0.2,
        translate=0.05,
        scale=0.15,
        fliplr=0.0,
        flipud=0.0,
    )

    print(f"\nBest weights saved to: {args.project}/{args.name}/weights/best.pt")


if __name__ == "__main__":
    main()