"""
End-to-end OCR Engine orchestrator coordinating YOLO field detection,
geometric fallbacks, PaddleOCR recognition, Strategy B cleaning,
dual-source fusion, and sanity validation.
"""

import time
import logging
from pathlib import Path
from typing import Dict, Any, Union, Optional
import cv2
import numpy as np

from ocr.detection.detector import YOLOFieldDetector
from ocr.detection.fallbacks import get_enrolment_no_crop
from ocr.recognition.cropper import FieldCropper
from ocr.recognition.paddle_engine import PaddleOCREngine
from ocr.postprocessing.cleaning import (
    fix_enrollment_no,
    fix_total_marks,
    clean_single_subject_code,
)
from ocr.postprocessing.fusion import combine_grand_total_and_words
from ocr.postprocessing.question_marks import QuestionMarksExtractor
from ocr.validation.sanity import SanityValidator

logger = logging.getLogger("ocr.pipeline")


class OCREngine:
    """
    Unified, modular OCR pipeline orchestrator.
    """

    def __init__(
        self,
        detector_path: Union[str, Path] = "models/best.pt",
        ocr_lang: str = "en",
        conf_thresh: float = 0.35,
        imgsz: int = 1280,
        padding_ratio: float = 0.05,
    ):
        self.detector = YOLOFieldDetector(model_path=detector_path)
        self.ocr_engine = PaddleOCREngine(lang=ocr_lang)
        self.question_marks_extractor = QuestionMarksExtractor(ocr_engine=self.ocr_engine)
        self.conf_thresh = conf_thresh
        self.imgsz = imgsz
        self.padding_ratio = padding_ratio
        self.is_initialized = False

    def initialize(self):
        """Pre-loads YOLO and PaddleOCR models into memory."""
        if self.is_initialized:
            return

        t0 = time.perf_counter()
        logger.info("Initializing OCREngine components...")
        self.detector.load_model()
        self.ocr_engine.load_engine()
        self.is_initialized = True
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(f"OCREngine fully initialized in {elapsed_ms:.1f}ms.")

    def process_image(self, image_input: Union[str, Path, np.ndarray]) -> Dict[str, Any]:
        """
        Executes end-to-end extraction on a single exam cover-sheet image:
          1. Defensive validation & normalization of image array
          2. YOLOv8 field detection with boundary clipping
          3. Padded cropping + deterministic layout fallback for missing enrolment
          4. Companion cropping: red-divider tightened grand_total & marks_in_words
          5. PaddleOCR text recognition on all crops
          6. Strategy B cleaning & normalization
          7. Dual-source total marks fusion
          8. Sanity validation & diagnostic review decision
        """
        if not self.is_initialized:
            self.initialize()

        # 1. Load and defensively validate input image
        if isinstance(image_input, (str, Path)):
            img_path = Path(image_input)
            if not img_path.is_file():
                raise FileNotFoundError(f"Input image file does not exist: {img_path}")
            img = cv2.imread(str(img_path))
        elif isinstance(image_input, np.ndarray):
            img = image_input
        else:
            raise ValueError(f"Unsupported image input type: {type(image_input)}")

        if img is None or img.size == 0:
            raise ValueError("Input image is invalid, corrupted, or could not be decoded.")

        # Ensure 3-channel BGR format
        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif len(img.shape) == 3 and img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        elif len(img.shape) != 3 or img.shape[2] != 3:
            raise ValueError(f"Unexpected image dimensions or channels: shape={img.shape}")

        img_h, img_w = img.shape[:2]
        if img_h < 200 or img_w < 200:
            raise ValueError(f"Image dimensions are too small for processing ({img_w}x{img_h}px).")

        # 2. YOLO Field Detection
        best_detections = self.detector.detect_fields(
            img,
            conf_thresh=self.conf_thresh,
            imgsz=self.imgsz,
        )

        # 3. Field Cropping & OCR
        raw_ocr_texts: Dict[str, str] = {}
        crops: Dict[str, Optional[np.ndarray]] = {}

        # 3a. Enrolment crop (with deterministic geometric fallback)
        enrol_det = best_detections.get("enrolment_no")
        enrol_box = enrol_det["xyxy"] if enrol_det else None
        enrol_crop, used_enrol_fallback = get_enrolment_no_crop(
            img=img,
            enrolment_box_xyxy=enrol_box,
            padding_ratio=self.padding_ratio,
        )
        crops["enrolment_no"] = enrol_crop
        txt_enrol, _ = self.ocr_engine.ocr_crop(enrol_crop)
        raw_ocr_texts["enrolment_no"] = txt_enrol
        if used_enrol_fallback:
            logger.info("YOLO enrolment_no detection absent/invalid; used deterministic geometric fallback crop.")

        # 3b. Subject code crop
        if "subject_code" in best_detections:
            subj_crop = FieldCropper.crop_padded_box(
                img,
                best_detections["subject_code"]["xyxy"],
                padding_ratio=self.padding_ratio,
            )
            crops["subject_code"] = subj_crop
            txt_subj, _ = self.ocr_engine.ocr_crop(subj_crop)
            raw_ocr_texts["subject_code"] = txt_subj
        else:
            crops["subject_code"] = None
            raw_ocr_texts["subject_code"] = ""

        # 3c. Grand total crop (primary)
        if "grand_total" in best_detections:
            gt_crop = FieldCropper.crop_padded_box(
                img,
                best_detections["grand_total"]["xyxy"],
                padding_ratio=self.padding_ratio,
            )
            crops["grand_total"] = gt_crop
            txt_gt, _ = self.ocr_engine.ocr_crop(gt_crop)
            raw_ocr_texts["grand_total"] = txt_gt
        else:
            crops["grand_total"] = None
            raw_ocr_texts["grand_total"] = ""

        # 4. Companion Cropping (Tightened grand_total & marks_in_words)
        gt_det = best_detections.get("grand_total")
        gt_xyxy = gt_det["xyxy"] if gt_det is not None else None
        existing_gt_crop = crops.get("grand_total")

        companion_crops = FieldCropper.get_grand_total_and_companion_crops(
            img=img,
            gt_box_xyxy=gt_xyxy,
            existing_gt_crop=existing_gt_crop,
        )

        gt_tight_crop = companion_crops.get("grand_total_tightened")
        mw_crop = companion_crops.get("marks_in_words")

        raw_gt_tight_txt, _ = self.ocr_engine.ocr_crop(gt_tight_crop)
        raw_mw_txt, _ = self.ocr_engine.ocr_crop(mw_crop)

        raw_ocr_texts["grand_total_tightened"] = raw_gt_tight_txt
        raw_ocr_texts["marks_in_words"] = raw_mw_txt

        # 5. Field Normalization & Parsing
        raw_enrolment = raw_ocr_texts.get("enrolment_no", "")
        raw_subject = raw_ocr_texts.get("subject_code", "")
        raw_gt_orig = raw_ocr_texts.get("grand_total", "")

        enrollment_no = fix_enrollment_no(raw_enrolment)
        if enrollment_no and str(enrollment_no).strip().lower() in {"", "nan", "none"}:
            enrollment_no = None

        subject_code = clean_single_subject_code(raw_subject)

        total_marks_strategy_b = fix_total_marks(raw_gt_orig)

        # 6. Dual-Source Total-Marks Fusion
        fusion_dict = combine_grand_total_and_words(
            raw_gt_orig=raw_gt_orig,
            raw_gt_tight=raw_gt_tight_txt,
            raw_words=raw_mw_txt,
        )

        total_marks_corrected = fusion_dict.get("final")
        fusion_status = fusion_dict.get("status")
        fusion_needs_review = bool(fusion_dict.get("needs_review", False))

        # 7. Lightweight Sanity Checks (without altering extracted values)
        needs_review, sanity_flags = SanityValidator.validate_fields(
            enrollment_no=enrollment_no,
            subject_code=subject_code,
            total_marks_corrected=total_marks_corrected,
            fusion_needs_review=fusion_needs_review,
        )

        # 8. Question-wise marks extraction (additive, no changes to existing fields)
        try:
            qm_result = self.question_marks_extractor.extract_question_marks(
                img_bgr=img,
                grand_total_box_xyxy=gt_xyxy,
                grand_total_value=total_marks_corrected,
            )
        except Exception as _qm_exc:  # pragma: no cover — defensive
            logger.warning(f"Question marks extraction failed (non-fatal): {_qm_exc}")
            qm_result = {
                "question_marks": [],
                "sum_extracted": None,
                "sum_matches_gt": None,
                "needs_review": False,
                "uncertain_count": 0,
                "method": "geometric_table",
                "debug_info": {"error": str(_qm_exc)},
            }

        return {
            "rollno": enrollment_no,
            "enrollment_no": enrollment_no,
            "subject_code": subject_code,
            "total_marks": total_marks_strategy_b,
            "total_marks_corrected": total_marks_corrected,
            "needs_review": needs_review,
            "fusion_status": fusion_status,
            "raw_ocr": raw_ocr_texts,
            "question_marks": qm_result.get("question_marks", []),
            "question_marks_meta": {
                "sum_extracted": qm_result.get("sum_extracted"),
                "sum_matches_gt": qm_result.get("sum_matches_gt"),
                "needs_review": qm_result.get("needs_review", False),
                "uncertain_count": qm_result.get("uncertain_count", 0),
                "method": qm_result.get("method", "geometric_table"),
            },
        }
