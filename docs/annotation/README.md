# Step 1 — Annotate field boundaries

Goal: draw a tight box around each of the 3 fields (`enrolment_no`,
`subject_code`, `grand_total`) on every cover-page photo, so YOLO can
learn to find them regardless of tilt/lighting.

## Tool: LabelImg (free, open-source, MIT license)

Install:
```bash
pip install labelImg
```

Run:
```bash
labelImg
```

Setup inside the app (one-time):
1. `View → Auto Save mode` — on, so you don't lose work.
2. Click the format toggle button (left toolbar) until it says **YOLO**
   (it cycles PascalVOC / YOLO / CreateML).
3. `Open Dir` → point it at `data/raw/images/` (put your source photos there).
4. `Change Save Dir` → point it at `data/raw/labels/` (create this folder).
5. Copy `classes.txt` into `data/raw/labels/classes.txt` so LabelImg
   loads the same 3 class names/order every session.

## Annotating each image
- Press `W` to start drawing a box, drag around the field, then pick
  the class name from the popup.
- Draw the box **tight to the printed cell border** you're extracting
  (the boxed-digit grid for enrolment_no, the Subject Code cell, the
  Grand Total cell) — not the whole table row.
- If a field wraps onto two lines (e.g. subject code spilling to a
  second line), draw one box that covers both lines.
- `A` / `D` = previous / next image. `Ctrl+S` = save.
- This produces one `.txt` file per image (same filename, YOLO format:
  `class_id x_center y_center width height`, all normalized 0–1).

## How many images to start with
- 5 samples is enough to smoke-test the pipeline end-to-end, but not
  enough to train something reliable. Aim for **50–100 annotated
  cover pages** (mix of both known templates, various lighting/tilt)
  for a first real training run — YOLOv8 fine-tunes from pretrained
  COCO weights, so it doesn't need thousands of images for a
  3-class, fixed-layout detection task like this.
- Prioritize variety (different phones, angles, lighting) over sheer
  count — a small varied set beats a large uniform one.

## Next
Once `data/raw/images/` + `data/raw/labels/` are populated, run
`scripts/prepare_dataset.py` to split them into the
`data/dataset/images/{train,val}` and `data/dataset/labels/{train,val}`
structure `data.yaml` expects.
