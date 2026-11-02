import os
os.environ.setdefault("FLAGS_use_onednn", "0")

import cv2
import numpy as np
from pathlib import Path
from ultralytics import YOLO
from paddleocr import PaddleOCR

# Expected classes defined during training
EXPECTED_CLASSES = {"enrolment_no", "subject_code", "grand_total"}


def detect_red_divider_x(crop_bgr: np.ndarray) -> tuple[int, float]:
    """
    Locates the vertical red divider line separating the printed 'GRAND TOTAL' label
    from the handwritten total-marks region (benchmarked on the 146-page dataset).
    """
    if crop_bgr is None or crop_bgr.size == 0 or crop_bgr.shape[1] < 30:
        return 0, 0.0
    h, w = crop_bgr.shape[:2]
    b, g, r = cv2.split(crop_bgr.astype(np.float32))
    redness = np.clip(r - 0.5 * (g + b), 0, 255)
    s1, s2 = int(0.20 * w), int(0.42 * w)
    if s2 <= s1:
        return 0, 0.0
    col_profile = redness[:, s1:s2].mean(axis=0)
    best_offset = int(np.argmax(col_profile))
    div_x = s1 + best_offset
    return min(w - 20, div_x + 6), div_x / float(w)


def get_grand_total_and_companion_crops(
    img: np.ndarray,
    gt_box_xyxy: tuple[float, float, float, float] | None = None,
    existing_gt_crop: np.ndarray | None = None,
) -> dict:
    """
    Generates the tightened grand_total crop (right of the vertical red divider)
    and the deterministic marks_in_words companion crop immediately to the left of
    grand_total with vertical padding for cursive ascenders and descenders.
    """
    img_h, img_w = img.shape[:2]
    used_fallback = False

    if gt_box_xyxy is not None:
        x1, y1, x2, y2 = [float(v) for v in gt_box_xyxy]
        if not (0.62 * img_h <= y1 <= 0.88 * img_h and x1 >= 0.40 * img_w):
            x1, y1, x2, y2 = 0.527 * img_w, 0.755 * img_h, 0.945 * img_w, 0.795 * img_h
            used_fallback = True
    else:
        x1, y1, x2, y2 = 0.527 * img_w, 0.755 * img_h, 0.945 * img_w, 0.795 * img_h
        used_fallback = True

    bh = max(80.0, y2 - y1)

    if existing_gt_crop is not None and existing_gt_crop.size > 0:
        gt_crop = existing_gt_crop
    else:
        gt_y1 = max(0, int(y1 - 0.08 * bh))
        gt_y2 = min(img_h, int(y2 + 0.12 * bh))
        gt_x1 = max(0, int(x1))
        gt_x2 = min(img_w, int(x2))
        gt_crop = img[gt_y1:gt_y2, gt_x1:gt_x2]

    cut_x, ratio = detect_red_divider_x(gt_crop)
    gt_tight = gt_crop[:, cut_x:] if gt_crop.size > 0 else gt_crop

    mw_y1 = max(0, int(y1 - 0.20 * bh))
    mw_y2 = min(img_h, int(y2 + 0.45 * bh))
    mw_x1 = max(0, int(0.21 * img_w))
    mw_x2 = max(mw_x1 + 1, min(img_w, int(x1)))
    mw_crop = img[mw_y1:mw_y2, mw_x1:mw_x2]

    return {
        "grand_total_tightened": gt_tight,
        "marks_in_words": mw_crop,
        "divider_ratio": round(ratio, 4),
        "used_fallback_box": used_fallback,
    }


def get_enrolment_no_crop(
    img: np.ndarray,
    enrolment_box_xyxy: tuple[float, float, float, float] | None = None,
    padding_ratio: float = 0.05,
) -> tuple[np.ndarray, bool]:
    """
    Extracts the enrolment_no image crop.
    When a valid YOLO detection box is provided (within expected layout bounds:
    0.20*H <= y1 <= 0.42*H and 0.40*W <= x1 <= 0.75*W), extracts the padded crop.
    Otherwise, applies a deterministic geometric fallback crop based on the cover-sheet
    layout geometry (x1=0.520*W, y1=0.260*H, x2=0.985*W, y2=0.360*H).
    Returns (crop, used_fallback).
    """
    img_h, img_w = img.shape[:2]
    used_fallback = False

    if enrolment_box_xyxy is not None:
        x1, y1, x2, y2 = [float(v) for v in enrolment_box_xyxy]
        if (
            0.20 * img_h <= y1 <= 0.42 * img_h
            and 0.40 * img_w <= x1 <= 0.75 * img_w
            and x2 > x1
            and y2 > y1
        ):
            bw = max(1.0, x2 - x1)
            bh = max(1.0, y2 - y1)
            px = int(bw * padding_ratio)
            py = int(bh * padding_ratio)
            cx1 = max(0, int(x1 - px))
            cy1 = max(0, int(y1 - py))
            cx2 = min(img_w, int(x2 + px))
            cy2 = min(img_h, int(y2 + py))
            crop = img[cy1:cy2, cx1:cx2]
            if crop.size > 0:
                return crop, False

    # Geometric fallback crop
    used_fallback = True
    cx1 = max(0, int(0.520 * img_w))
    cy1 = max(0, int(0.260 * img_h))
    cx2 = min(img_w, int(0.985 * img_w))
    cy2 = min(img_h, int(0.360 * img_h))
    crop = img[cy1:cy2, cx1:cx2]
    return crop, True


def init_pipeline(model_path: str):
    """
    Validates model paths and initializes YOLO and PaddleOCR.
    """
    model_file = Path(model_path)
    if not model_file.is_file():
        raise FileNotFoundError(f"[CHECK FAILED] YOLO model not found at: {model_file.resolve()}")

    print(f"[CHECK PASSED] Model weights found: {model_file.name}")
    
    # Load YOLO
    yolo_model = YOLO(str(model_file))
    
    # Initialize PaddleOCR using the current API.
    ocr = PaddleOCR(use_textline_orientation=True, lang='en')
    
    return yolo_model, ocr

def extract_exam_data(
    image_path: str,
    yolo_model: YOLO,
    ocr: PaddleOCR,
    yolo_conf_thresh: float = 0.30,
    ocr_conf_thresh: float = 0.60,
    padding_ratio: float = 0.05,
    save_debug_crops: bool = True,
    debug_dir: str = "debug_crops"
) -> dict:
    """
    Extracts exam fields with end-to-end troubleshooting checks.
    """
    # 1. Image File Check
    img_file = Path(image_path)
    if not img_file.is_file():
        raise FileNotFoundError(f"[CHECK FAILED] Image file does not exist: {img_file.resolve()}")
    
    img = cv2.imread(str(img_file))
    if img is None or img.size == 0:
        raise ValueError(f"[CHECK FAILED] Image file is corrupt or unreadable: {image_path}")

    img_h, img_w = img.shape[:2]
    if img_h < 100 or img_w < 100:
        print(f"[WARNING] Image resolution is unusually low: {img_w}x{img_h}px")

    if save_debug_crops:
        debug_path = Path(debug_dir)
        debug_path.mkdir(parents=True, exist_ok=True)

    # 2. YOLO Inference Check
    results = yolo_model(str(img_file), conf=yolo_conf_thresh, imgsz=1280, verbose=False)
    if not results or len(results[0].boxes) == 0:
        print(f"[CHECK WARNING] No bounding boxes detected above confidence {yolo_conf_thresh}.")
        return {
            cls: {"status": "NOT_DETECTED", "text": "", "yolo_conf": 0.0, "ocr_conf": 0.0}
            for cls in EXPECTED_CLASSES
        }

    result = results[0]
    best_detections = {}

    # 3. Detection Disambiguation Check (Highest confidence per class)
    for box in result.boxes:
        cls_id = int(box.cls[0])
        cls_name = result.names[cls_id]
        conf = float(box.conf[0])

        if cls_name not in EXPECTED_CLASSES:
            print(f"[WARNING] Ignored unexpected detected class: '{cls_name}'")
            continue

        if cls_name not in best_detections or conf > best_detections[cls_name]["conf"]:
            if cls_name in best_detections:
                print(f"[INFO] Multiple detections for '{cls_name}'. Keeping higher confidence ({conf:.2f} > {best_detections[cls_name]['conf']:.2f}).")
            best_detections[cls_name] = {"box": box, "conf": conf}

    # 4. Missing Classes Check
    missing_classes = EXPECTED_CLASSES - set(best_detections.keys())
    if missing_classes:
        print(f"[CHECK WARNING] The following target fields were not found: {missing_classes}")

    extracted_output = {}
    gt_crop_img = None

    # Process all expected classes
    for target_class in EXPECTED_CLASSES:
        if target_class not in best_detections:
            extracted_output[target_class] = {
                "status": "NOT_DETECTED",
                "text": "",
                "yolo_conf": 0.0,
                "ocr_conf": 0.0,
                "crop_saved": None
            }
            continue

        det = best_detections[target_class]
        box = det["box"]
        yolo_conf = det["conf"]

        # 5. Crop Geometry and Padding Clamping
        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
        box_w = max(1, x2 - x1)
        box_h = max(1, y2 - y1)

        pad_x = int(box_w * padding_ratio)
        pad_y = int(box_h * padding_ratio)

        crop_x1 = max(0, x1 - pad_x)
        crop_y1 = max(0, y1 - pad_y)
        crop_x2 = min(img_w, x2 + pad_x)
        crop_y2 = min(img_h, y2 + pad_y)

        crop = img[crop_y1:crop_y2, crop_x1:crop_x2]

        # Ensure valid non-empty slice
        if crop.size == 0 or crop.shape[0] == 0 or crop.shape[1] == 0:
            print(f"[CHECK FAILED] Cropped region for '{target_class}' collapsed to zero pixels.")
            extracted_output[target_class] = {
                "status": "INVALID_CROP",
                "text": "",
                "yolo_conf": round(yolo_conf, 3),
                "ocr_conf": 0.0,
                "crop_saved": None
            }
            continue

        if target_class == "grand_total":
            gt_crop_img = crop

        crop_save_path = None
        if save_debug_crops:
            crop_save_path = str(debug_path / f"{target_class}.png")
            cv2.imwrite(crop_save_path, crop)

        # 6. PaddleOCR Inference Check
        ocr_result = ocr.ocr(crop)

        text_content = ""
        ocr_conf = 0.0
        status = "OK"

        if not ocr_result or not ocr_result[0]:
            status = "OCR_EMPTY"
            print(f"[CHECK WARNING] OCR returned no text for '{target_class}'. Check debug image: {crop_save_path}")
        else:
            lines = ocr_result[0]
            texts = []
            confs = []

            for line in lines:
                if isinstance(line, (list, tuple)) and len(line) >= 2:
                    item = line[1]
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        text = str(item[0]).strip()
                        conf = float(item[1])
                    else:
                        text = str(item).strip()
                        conf = 0.0
                elif isinstance(line, dict):
                    text = str(line.get("text", "")).strip()
                    conf = float(line.get("confidence", 0.0) or 0.0)
                else:
                    text = str(line).strip()
                    conf = 0.0

                if text:
                    texts.append(text)
                    confs.append(conf)

            if not texts:
                status = "OCR_EMPTY"
            else:
                text_content = " ".join(texts)
                ocr_conf = sum(confs) / len(confs) if confs else 0.0

                if ocr_conf < ocr_conf_thresh:
                    status = "LOW_CONFIDENCE"
                    print(f"[CHECK WARNING] Low OCR confidence ({ocr_conf:.2f}) for '{target_class}': '{text_content}'")

        extracted_output[target_class] = {
            "status": status,
            "text": text_content,
            "yolo_conf": round(yolo_conf, 3),
            "ocr_conf": round(ocr_conf, 3),
            "crop_saved": crop_save_path
        }

    # 7. Companion extraction: Tightened grand_total and deterministic marks_in_words
    gt_box = best_detections.get("grand_total", {}).get("box")
    gt_xyxy = gt_box.xyxy[0].cpu().numpy().tolist() if gt_box is not None else None

    companion_crops = get_grand_total_and_companion_crops(
        img=img,
        gt_box_xyxy=gt_xyxy,
        existing_gt_crop=gt_crop_img,
    )

    for comp_field in ("grand_total_tightened", "marks_in_words"):
        c_img = companion_crops.get(comp_field)
        c_save_path = None
        if save_debug_crops and c_img is not None and c_img.size > 0:
            c_save_path = str(debug_path / f"{comp_field}.png")
            cv2.imwrite(c_save_path, c_img)

        c_text = ""
        c_conf = 0.0
        c_status = "OK"

        if c_img is None or c_img.size == 0:
            c_status = "INVALID_CROP"
        else:
            try:
                c_ocr_res = ocr.ocr(c_img)
                if not c_ocr_res or not c_ocr_res[0]:
                    c_status = "OCR_EMPTY"
                else:
                    lines = c_ocr_res[0]
                    c_texts, c_confs = [], []
                    for line in lines:
                        if isinstance(line, (list, tuple)) and len(line) >= 2:
                            item = line[1]
                            if isinstance(item, (list, tuple)) and len(item) >= 2:
                                txt, cf = str(item[0]).strip(), float(item[1])
                            else:
                                txt, cf = str(item).strip(), 0.0
                        elif isinstance(line, dict):
                            txt = str(line.get("text", "")).strip()
                            cf = float(line.get("confidence", 0.0) or 0.0)
                        else:
                            txt, cf = str(line).strip(), 0.0
                        if txt:
                            c_texts.append(txt)
                            c_confs.append(cf)
                    c_text = " ".join(c_texts)
                    c_conf = sum(c_confs) / len(c_confs) if c_confs else 0.0
            except Exception as e:
                c_status = f"ERROR: {e}"

        extracted_output[comp_field] = {
            "status": c_status,
            "text": c_text,
            "yolo_conf": round(best_detections.get("grand_total", {}).get("conf", 0.0), 3),
            "ocr_conf": round(c_conf, 3),
            "crop_saved": c_save_path,
        }

    return extracted_output


if __name__ == "__main__":
    # Configure paths
    MODEL_PATH = "best.pt"  # Or "best.onnx"
    IMAGE_CANDIDATES = ["sample_cover.png", "sample_cover.jpg", "sample_cover.jpeg"]
    TEST_IMAGE = next((candidate for candidate in IMAGE_CANDIDATES if Path(candidate).is_file()), IMAGE_CANDIDATES[0])

    try:
        # Step 1: Initialize engines
        yolo_engine, ocr_engine = init_pipeline(MODEL_PATH)

        # Step 2: Run extraction with full verification
        results = extract_exam_data(
            image_path=TEST_IMAGE,
            yolo_model=yolo_engine,
            ocr=ocr_engine,
            yolo_conf_thresh=0.30,
            ocr_conf_thresh=0.60,
            padding_ratio=0.06,
            save_debug_crops=True
        )

        print("\n" + "=" * 40)
        print("EXTRACTION RESULTS SUMMARY")
        print("=" * 40)
        for field, meta in results.items():
            print(f"[{meta['status']}] {field.upper()}")
            print(f"  Text:      '{meta['text']}'")
            print(f"  YOLO Conf: {meta['yolo_conf']}")
            print(f"  OCR Conf:  {meta['ocr_conf']}")
            if meta['crop_saved']:
                print(f"  Crop Ref:  {meta['crop_saved']}")
            print("-" * 40)

    except Exception as err:
        print(f"\n[FATAL PIPELINE ERROR] {err}")