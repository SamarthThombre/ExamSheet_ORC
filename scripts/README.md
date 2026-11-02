# Scripts

This directory contains the main project pipeline scripts.

## Files

- `prepare_dataset.py` — splits raw annotated images and labels into YOLO train/val folders.
- `train_yolo.py` — trains the YOLOv8 model using `data.yaml`.
- `infer_crop.py` — runs object detection on new cover-sheet photos and saves cropped fields.
- `image_croping.py` — crop-based extraction workflow with OCR.
- `convert_xml_to_yolo.py` — converts XML annotations to YOLO text format.

## Usage

```powershell
python .\scripts\prepare_dataset.py --images .\data\raw\images --labels .\data\raw\labels --out .\data\dataset --val-split 0.15
python .\scripts\train_yolo.py --data .\data.yaml --epochs 100 --imgsz 1280 --batch 8
python .\scripts\infer_crop.py --weights .\models\best.pt --images .\data\raw\images --out .\artifacts\crops --conf 0.35
```

## Notes

- All paths are intended to be relative to the project root.
- Generated outputs should normally go into `data/` and `artifacts/` rather than the project root.
