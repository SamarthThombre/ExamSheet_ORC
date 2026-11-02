"""
ocr_v2.normalise: Image decoding, EXIF orientation correction, canonical resizing,
and enrolment-comb based page deskew and translation alignment.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Union, Optional, Tuple, List, Dict, Any
import cv2
import numpy as np
from PIL import Image, ImageOps
import io


@dataclass
class TransformMatrix:
    dx: float = 0.0
    dy: float = 0.0
    rot_deg: float = 0.0
    matrix: Optional[np.ndarray] = None


@dataclass
class AlignmentResult:
    image: np.ndarray
    transform: TransformMatrix
    quality_score: float
    needs_review: bool
    review_reasons: List[str] = field(default_factory=list)
    comb_box: Optional[Tuple[Tuple[float, float], Tuple[float, float], float]] = None


class PageNormaliser:
    """Normalises input document images to a canonical coordinate frame."""

    def __init__(self, target_width: int = 1600):
        self.target_width = target_width

    def decode(self, input_data: Union[str, Path, bytes, np.ndarray]) -> np.ndarray:
        """
        Decodes input image with EXIF orientation correction.
        Uses fast reduced-size JPEG decode when input is high-resolution JPEG.
        """
        if isinstance(input_data, np.ndarray):
            img = input_data.copy()
            return self._apply_exif_orientation_array(img)

        # Handle bytes
        if isinstance(input_data, bytes):
            # Check for JPEG magic bytes
            is_jpeg = input_data.startswith(b"\xff\xd8\xff")
            if is_jpeg:
                # Fast reduced decode for large JPEG
                # Check dimensions via PIL header without full decode
                try:
                    pimg = Image.open(io.BytesIO(input_data))
                    pimg = ImageOps.exif_transpose(pimg)
                    w, h = pimg.size
                    if max(w, h) > 2800:
                        # Decode via OpenCV reduced color flag
                        arr = np.frombuffer(input_data, dtype=np.uint8)
                        decoded = cv2.imdecode(arr, cv2.IMREAD_REDUCED_COLOR_2)
                        return decoded
                    return cv2.cvtColor(np.array(pimg), cv2.COLOR_RGB2BGR)
                except Exception:
                    arr = np.frombuffer(input_data, dtype=np.uint8)
                    return cv2.imdecode(arr, cv2.IMREAD_COLOR)
            else:
                arr = np.frombuffer(input_data, dtype=np.uint8)
                return cv2.imdecode(arr, cv2.IMREAD_COLOR)

        # Handle file path
        path = Path(input_data)
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {path}")

        ext = path.suffix.lower()
        if ext in [".jpg", ".jpeg"]:
            try:
                # Open with PIL for accurate EXIF transposition
                pimg = Image.open(path)
                pimg = ImageOps.exif_transpose(pimg)
                w, h = pimg.size
                if max(w, h) > 2800:
                    # Reduced decode is much faster for large camera JPEGs
                    decoded = cv2.imread(str(path), cv2.IMREAD_REDUCED_COLOR_2)
                    if decoded is not None:
                        return decoded
                return cv2.cvtColor(np.array(pimg.convert("RGB")), cv2.COLOR_RGB2BGR)
            except Exception:
                return cv2.imread(str(path), cv2.IMREAD_COLOR)
        else:
            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError(f"Failed to read image from path: {path}")
            return img

    def _apply_exif_orientation_array(self, img: np.ndarray) -> np.ndarray:
        return img

    def check_orientation_0_180(self, img: np.ndarray, is_format_b: bool = False) -> Tuple[np.ndarray, bool]:
        """
        Detects if page is inverted (180 degrees) using enrolment comb verification.
        Returns (corrected_image, was_flipped).
        """
        h, w = img.shape[:2]

        def _comb_score(sub_img: np.ndarray) -> float:
            sub_h, sub_w = sub_img.shape[:2]
            crop = sub_img[int(sub_h * 0.20):int(sub_h * 0.45), int(sub_w * 0.45):int(sub_w * 0.99)]
            if crop.size == 0:
                return 0.0
            r = crop[:, :, 2].astype(float)
            g = crop[:, :, 1].astype(float)
            b = crop[:, :, 0].astype(float)
            m_a = (r > 100) & (r > 1.15 * g) & (r > 1.15 * b)
            m_b = (r > 110) & (g > 50) & (g < 200) & (b < 130) & ((r - b) > 30)
            return float(np.sum(m_b if is_format_b else m_a))

        score_0 = _comb_score(img)
        if score_0 > 1500:
            return img, False

        # Check if comb is in the 180 rotated orientation
        rot180 = cv2.rotate(img, cv2.ROTATE_180)
        score_180 = _comb_score(rot180)
        if score_180 > 1500 and score_180 > score_0 * 2.0:
            return rot180, True

        # Fallback for synthetic/grayscale without colored comb lines
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        top_ink = np.sum(gray[: int(h * 0.20), :] < 140)
        bot_ink = np.sum(gray[int(h * 0.80) :, :] < 140)
        if top_ink < (h * w * 0.005) and bot_ink > (h * w * 0.015):
            return cv2.rotate(img, cv2.ROTATE_180), True

        return img, False

    def resize_to_canonical_width(self, img: np.ndarray) -> Tuple[np.ndarray, float]:
        """Resizes image to target_width (1600 px), preserving aspect ratio."""
        h, w = img.shape[:2]
        scale = self.target_width / float(w)
        target_h = int(round(h * scale))
        resized = cv2.resize(img, (self.target_width, target_h), interpolation=cv2.INTER_AREA)
        return resized, scale

    def detect_comb_box(
        self,
        img_can: np.ndarray,
        is_format_b: bool = False,
    ) -> Tuple[Optional[Tuple[Tuple[float, float], Tuple[float, float], float]], float, str]:
        """
        Detects the 12-cell enrolment comb box using color mask + minAreaRect.
        Returns: (best_rect, quality_score, status_str)
        where best_rect is ((cx, cy), (bw, bh), angle) in canonical coordinates.
        """
        hc, wc = img_can.shape[:2]

        if not is_format_b:
            # Format A nominal search window
            sy1, sy2 = int(hc * 0.220), int(hc * 0.380)
            sx1, sx2 = int(wc * 0.480), int(wc * 0.995)
        else:
            # Format B nominal search window
            sy1, sy2 = int(hc * 0.210), int(hc * 0.420)
            sx1, sx2 = int(wc * 0.500), int(wc * 0.995)

        crop = img_can[sy1:sy2, sx1:sx2]
        if crop.size == 0:
            return None, 0.0, "CROP_EMPTY"

        r = crop[:, :, 2].astype(float)
        g = crop[:, :, 1].astype(float)
        b = crop[:, :, 0].astype(float)

        if is_format_b:
            # Orange / brown comb mask
            mask = (r > 110) & (g > 50) & (g < 200) & (b < 130) & ((r - b) > 30)
        else:
            # Red comb mask
            mask = (r > 100) & (r > 1.15 * g) & (r > 1.15 * b)

        mask_uint8 = mask.astype(np.uint8) * 255
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 5))
        closed = cv2.morphologyEx(mask_uint8, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best_rect = None
        best_score = -1.0
        best_aspect = 0.0
        best_area = 0.0
        best_touches = False
        best_bw = 0.0
        best_bh = 0.0

        for cnt in contours:
            bx, by, bw_b, bh_b = cv2.boundingRect(cnt)
            touches_top_bot = (by <= 2) or (by + bh_b >= crop.shape[0] - 2)
            rect = cv2.minAreaRect(cnt)
            (cx, cy), (bw, bh), angle = rect
            if bw < bh:
                bw, bh = bh, bw
                angle += 90
            aspect = bw / float(bh) if bh > 0 else 0
            area = bw * bh
            if bw > 0.30 * crop.shape[1] and 4.5 <= aspect <= 16.0:
                asp_score = max(0.0, 1.0 - abs(aspect - 8.5) / 4.0)
                h_score = 1.0 if 50 <= bh <= 95 else 0.5
                touch_penalty = 0.05 if touches_top_bot else 1.0
                score = area * asp_score * h_score * touch_penalty
                if score > best_score:
                    best_score = score
                    best_aspect = aspect
                    best_area = area
                    best_touches = touches_top_bot
                    best_bw = bw
                    best_bh = bh
                    best_rect = ((cx + sx1, cy + sy1), (bw, bh), angle)

        if best_rect is None:
            return None, 0.0, "COMB_NOT_FOUND"

        status = "OK"
        if best_aspect < 6.5 or best_bw < 420.0 or best_touches or best_score < 5000:
            status = "COMB_NOT_FULLY_DETECTED"

        # Quality scoring based on aspect ratio match to nominal (~8-10) and comb area
        aspect_score = max(0.0, 1.0 - abs(best_aspect - 8.8) / 5.0)
        area_ratio = best_area / (crop.shape[0] * crop.shape[1])
        area_score = min(1.0, area_ratio / 0.12)
        quality = 0.5 * aspect_score + 0.5 * area_score
        if status == "COMB_NOT_FULLY_DETECTED":
            quality = min(quality, 0.45)

        return best_rect, quality, status

    def align_page(
        self,
        img: np.ndarray,
        format_id: str,
        format_config: Optional[Dict[str, Any]] = None,
        align_mode: str = "comb_center",
    ) -> AlignmentResult:
        """
        Normalises and aligns page to canonical template coordinates.
        align_mode:
          - "comb_center": Rotates around detected comb center (M2b method)
          - "image_center": Rotates around image center (M2 method)
        """
        reasons = []

        is_b = (format_id == "format_v2")

        # 1. 0/180 check
        oriented_img, was_flipped = self.check_orientation_0_180(img, is_format_b=is_b)
        if was_flipped:
            reasons.append("PAGE_ROTATED_180_CORRECTED")

        # 2. Resize to canonical width
        img_can, scale = self.resize_to_canonical_width(oriented_img)
        hc, wc = img_can.shape[:2]

        # 3. Detect comb box
        rect, quality, status = self.detect_comb_box(img_can, is_format_b=is_b)

        if rect is None:
            reasons.append("RESCAN_RECOMMENDED: COMB_DETECTION_FAILED")
            reasons.append(f"COMB_DETECTION_FAILED_{status}")
            return AlignmentResult(
                image=img_can,
                transform=TransformMatrix(rot_deg=0.0),
                quality_score=0.0,
                needs_review=True,
                review_reasons=reasons,
                comb_box=None,
            )

        (cx, cy), (bw, bh), angle = rect

        # Normalize rotation angle
        rot_angle = angle if angle < 45 else angle - 180
        if rot_angle > 45:
            rot_angle -= 90
        elif rot_angle < -45:
            rot_angle += 90

        needs_review = False

        if status == "COMB_NOT_FULLY_DETECTED":
            needs_review = True
            reasons.append("RESCAN_RECOMMENDED: COMB_NOT_FULLY_DETECTED")

        # Check if comb touches canvas/page boundaries
        c_left = cx - bw / 2.0
        c_right = cx + bw / 2.0
        c_top = cy - bh / 2.0
        c_bot = cy + bh / 2.0
        if c_left < 10.0 or c_right > (wc - 10.0) or c_top < 10.0 or c_bot > (hc - 10.0):
            needs_review = True
            reasons.append("RESCAN_RECOMMENDED: COMB_TOUCHES_PAGE_EDGE")

        if abs(rot_angle) > 15.0:
            reasons.append(f"RESCAN_RECOMMENDED: EXCESSIVE_SKEW_{rot_angle:.1f}_DEG")
            return AlignmentResult(
                image=img_can,
                transform=TransformMatrix(rot_deg=rot_angle),
                quality_score=quality * 0.5,
                needs_review=True,
                review_reasons=reasons,
                comb_box=rect,
            )

        # Expected nominal comb center
        if format_config and "fields" in format_config and "enrollment_no" in format_config["fields"]:
            e_roi = format_config["fields"]["enrollment_no"]["roi"]
            cx_nom = (e_roi[0] + e_roi[2]) / 2.0 * wc
            cy_nom = (e_roi[1] + e_roi[3]) / 2.0 * hc
        else:
            cx_nom = 0.7525 * wc if not is_b else 0.770 * wc
            cy_nom = 0.3100 * hc if not is_b else 0.330 * hc

        dx = cx_nom - cx
        dy = cy_nom - cy

        # Affine correction matrix
        if align_mode == "image_center":
            center_x, center_y = wc / 2.0, hc / 2.0
            M_rot = cv2.getRotationMatrix2D((center_x, center_y), -rot_angle, 1.0)
            M_rot[0, 2] += dx
            M_rot[1, 2] += dy
        else:
            # comb_center
            M_rot = cv2.getRotationMatrix2D((cx, cy), -rot_angle, 1.0)
            M_rot[0, 2] += (cx_nom - cx)
            M_rot[1, 2] += (cy_nom - cy)

        aligned_img = cv2.warpAffine(
            img_can,
            M_rot,
            (wc, hc),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )

        if abs(rot_angle) > 3.6:
            needs_review = True
            reasons.append(f"RESCAN_RECOMMENDED: EXCESSIVE_SKEW_{rot_angle:.1f}_DEG")
        if quality < 0.50:
            needs_review = True
            reasons.append(f"RESCAN_RECOMMENDED: LOW_COMB_QUALITY_{quality:.2f}")

        aligned_comb_box = ((cx_nom, cy_nom), (bw, bh), 0.0)

        return AlignmentResult(
            image=aligned_img,
            transform=TransformMatrix(dx=dx, dy=dy, rot_deg=rot_angle, matrix=M_rot),
            quality_score=float(quality),
            needs_review=needs_review,
            review_reasons=reasons,
            comb_box=aligned_comb_box,
        )
