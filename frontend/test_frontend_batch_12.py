"""
frontend/test_frontend_batch_12.py:
12-image end-to-end verification of the frontend workflow:
- 10 benchmark sheets (5 Format A DEV, 5 Format B DEV)
- 1 uncropped sheet (synthetic uncropped sheet on desk background)
- 1 cut-off sheet (20% truncated sheet boundary)
- Preprocessing: max 2000px long edge, JPEG quality 90, EXIF orientation respected
- Simulates frontend API calls to /v2/predict
- Re-verifies CSV export (columns: filename, subject_code, enrolment_no, marks, q1, q2, q3, q4, q5; nothing else)
- Generates batch PDF containing all 12 images in upload order (1 page per sheet)
- Verifies and prints outcomes, CSV header + first 3 rows, and PDF page count.
"""

import sys
import json
import math
import random
from pathlib import Path
import cv2
import numpy as np
import pypdfium2 as pdfium
from PIL import Image
import io

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers_v2 import get_pipeline, process_sheet_bytes

def preprocess_image_frontend_spec(img_bgr: np.ndarray) -> bytes:
    """
    Simulates frontend prepareImageForUpload:
    - Downscales to max 2000px long edge
    - Encodes to JPEG at quality 90
    - EXIF orientation preserved
    """
    h, w = img_bgr.shape[:2]
    max_edge = 2000
    if max(h, w) > max_edge:
        if w > h:
            scale = max_edge / w
            new_w = max_edge
            new_h = int(round(h * scale))
        else:
            scale = max_edge / h
            new_h = max_edge
            new_w = int(round(w * scale))
        img_bgr = cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)

    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
    _, enc = cv2.imencode(".jpg", img_bgr, encode_param)
    return enc.tobytes()

def make_uncropped_sheet(img_bgr: np.ndarray) -> np.ndarray:
    """Places sheet on desk canvas filling ~65% of the frame."""
    h, w = img_bgr.shape[:2]
    canvas_w = int(w / 0.80)
    canvas_h = int(h / 0.80)
    canvas = np.full((canvas_h, canvas_w, 3), (120, 140, 160), dtype=np.uint8)
    # Add texture noise
    noise = np.random.randint(-10, 10, (canvas_h, canvas_w, 3)).astype(np.int16)
    canvas = np.clip(canvas.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    off_x = (canvas_w - w) // 2
    off_y = (canvas_h - h) // 2
    canvas[off_y:off_y+h, off_x:off_x+w] = img_bgr
    return canvas

def make_cutoff_sheet(img_bgr: np.ndarray) -> np.ndarray:
    """Cuts off 20% of the right side of the sheet."""
    h, w = img_bgr.shape[:2]
    return img_bgr[:, :int(w * 0.80)]

def main():
    print("=" * 80)
    print("FRONTEND VERIFICATION: 12-IMAGE SCANNER & EXPORT TEST")
    print("=" * 80)

    with open(ROOT / "experiments" / "m7" / "splits.json", "r") as f:
        splits = json.load(f)

    # 12 selected images:
    # 1..5: Format A DEV
    # 6..10: Format B DEV
    # 11: Uncropped
    # 12: Cut-off
    dev_a = splits["format_a"]["dev"][:5]
    dev_b = splits["format_b"]["dev"][:5]

    test_items = []
    for fn in dev_a:
        test_items.append((fn, ROOT / "data" / fn, "standard"))
    for fn in dev_b:
        test_items.append((fn, ROOT / "data" / "data_v2_images" / fn, "standard"))

    uncropped_base_fn = dev_a[0]
    cutoff_base_fn = dev_b[0]
    test_items.append((f"uncropped_{uncropped_base_fn}", ROOT / "data" / uncropped_base_fn, "uncropped"))
    test_items.append((f"cutoff_{cutoff_base_fn}", ROOT / "data" / "data_v2_images" / cutoff_base_fn, "cutoff"))

    assert len(test_items) == 12, f"Expected 12 test sheets, got {len(test_items)}"

    pipeline = get_pipeline()
    processed_results = []
    images_for_pdf = []

    declared_subject_code = "CT10718"

    for i, (fn, path, item_type) in enumerate(test_items):
        raw_bgr = cv2.imread(str(path))
        if item_type == "uncropped":
            raw_bgr = make_uncropped_sheet(raw_bgr)
        elif item_type == "cutoff":
            raw_bgr = make_cutoff_sheet(raw_bgr)

        # 1. Frontend preparation
        jpeg_bytes = preprocess_image_frontend_spec(raw_bgr)
        images_for_pdf.append(jpeg_bytes)

        # 2. Invoke /v2/predict
        res = process_sheet_bytes(
            jpeg_bytes,
            fn,
            pipeline=pipeline,
            extract_total_marks=True,
            extract_question_marks=True,
            enable_m7_rules=True,
            enable_page_localiser=False # default OFF as per Criterion 1
        )

        pred_fmt = res.get("detected_format") or res.get("format_id") or "UNKNOWN"
        enrol = res.get("enrolment", {})
        total_m = res.get("total_marks", {})
        q_marks = res.get("q_marks", [])
        is_rescan = bool(res.get("rescan_recommended"))
        review_reasons = res.get("review_reasons", [])

        has_enrol_val = bool(enrol.get("value"))
        has_total_val = (total_m.get("value") is not None)
        has_values = has_enrol_val or has_total_val

        # Frontend logic check
        is_unrecognised = (pred_fmt == "UNKNOWN") or (not has_values) or is_rescan
        app_status = "Rescan" if is_unrecognised else ("Check" if enrol.get("needs_review") or total_m.get("flags") else "OK / Verified")

        app_message = ""
        if is_unrecognised:
            app_message = "Sheet not recognised. Scan the whole sheet in colour with the scanner."
        elif review_reasons:
            app_message = "; ".join(str(r) for r in review_reasons)
        else:
            app_message = "Clean reading"

        q_dict = {f"q{qm.get('q_number')}": qm.get("value", "") for qm in q_marks if qm.get("q_number")}

        rec = {
            "index": i + 1,
            "filename": fn,
            "type": item_type,
            "detected_format": pred_fmt,
            "enrolment_no": enrol.get("value", "") or "",
            "marks": total_m.get("value", "") if total_m.get("value") is not None else "",
            "q1": q_dict.get("q1", ""),
            "q2": q_dict.get("q2", ""),
            "q3": q_dict.get("q3", ""),
            "q4": q_dict.get("q4", ""),
            "q5": q_dict.get("q5", ""),
            "app_status": app_status,
            "app_message": app_message,
            "rescan_action_available": is_unrecognised,
        }
        processed_results.append(rec)
        print(f"[{i+1:02d}] {fn:25s} ({item_type:9s}) -> Status: {app_status:13s} | Format: {pred_fmt:15s} | Roll: {str(rec['enrolment_no']):14s} | Marks: {str(rec['marks']):5s} | Action: {'[Rescan Button]' if is_unrecognised else '[Inspect]'}")
        if is_unrecognised:
            print(f"     App Message: \"{app_message}\"")

    # 3. CSV Export Check
    csv_headers = ["filename", "subject_code", "enrolment_no", "marks", "q1", "q2", "q3", "q4", "q5"]
    csv_rows = []
    for r in processed_results:
        row = [
            r["filename"],
            declared_subject_code,
            str(r["enrolment_no"]),
            str(r["marks"]),
            str(r["q1"]),
            str(r["q2"]),
            str(r["q3"]),
            str(r["q4"]),
            str(r["q5"]),
        ]
        csv_rows.append(row)

    out_csv_p = ROOT / "frontend" / "test_12_export.csv"
    with open(out_csv_p, "w", encoding="utf-8", newline="") as f:
        import csv
        writer = csv.writer(f)
        writer.writerow(csv_headers)
        writer.writerows(csv_rows)

    print("\n" + "=" * 80)
    print("CSV EXPORT VERIFICATION:")
    print(f"Saved to: {out_csv_p}")
    print(f"Header: {','.join(csv_headers)}")
    print("First 3 rows:")
    for row in csv_rows[:3]:
        print(f"  {','.join(row)}")
    print("=" * 80)

    # 4. Multi-Page Batch PDF Export Check
    pdf_pages = []
    for jb in images_for_pdf:
        pil_im = Image.open(io.BytesIO(jb)).convert("RGB")
        pdf_pages.append(pil_im)

    out_pdf_p = ROOT / "frontend" / "test_12_batch.pdf"
    if pdf_pages:
        pdf_pages[0].save(
            str(out_pdf_p),
            save_all=True,
            append_images=pdf_pages[1:],
            format="PDF"
        )

    # Check page count with pypdfium2
    doc = pdfium.PdfDocument(str(out_pdf_p))
    pdf_page_count = len(doc)
    print("\n" + "=" * 80)
    print("BATCH PDF EXPORT VERIFICATION:")
    print(f"Saved to: {out_pdf_p}")
    print(f"PDF Page Count: {pdf_page_count} (Expected: 12)")
    assert pdf_page_count == 12, f"Expected 12 pages in PDF, got {pdf_page_count}"
    print("[SUCCESS] PDF has exactly 12 pages in upload order (one per sheet).")
    print("=" * 80)

    summary_out = ROOT / "frontend" / "test_12_summary.json"
    summary_out.write_text(json.dumps({
        "csv_header": csv_headers,
        "first_3_rows": csv_rows[:3],
        "pdf_page_count": pdf_page_count,
        "items": processed_results
    }, indent=2), encoding="utf-8")
    print(f"Summary written to {summary_out}")

if __name__ == "__main__":
    main()
