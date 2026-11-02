"""
ocr_v2.formats: Automatic cover-page format identification (Format A, Format B, or UNKNOWN).
Deterministic, multi-feature classification with strict rejection of negative samples.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
import cv2
import numpy as np

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


@dataclass
class FormatIdentificationResult:
    format_id: str                      # "format_original" | "format_v2" | "UNKNOWN"
    confidence: float                   # 0.0 to 1.0
    needs_review: bool
    reasons: List[str] = field(default_factory=list)
    features: Dict[str, Any] = field(default_factory=dict)


class FormatDetector:
    """Classifies exam cover sheets into format_original, format_v2, or UNKNOWN."""

    def __init__(
        self,
        min_confidence_threshold: float = 0.40,
        min_aspect: float = 0.55,
        max_aspect: float = 0.95,
    ):
        self.min_confidence = min_confidence_threshold
        self.min_aspect = min_aspect
        self.max_aspect = max_aspect

        p_gt_a = TEMPLATE_DIR / "tmpl_gt_a.png"
        p_gt_b = TEMPLATE_DIR / "tmpl_gt_b.png"
        p_sb_a = TEMPLATE_DIR / "tmpl_subj_a.png"
        p_sb_b = TEMPLATE_DIR / "tmpl_subj_b_left.png"
        assets_dir = Path(__file__).resolve().parent / "assets"
        p_crest = assets_dir / "tmpl_crest_a.png"
        p_hdr_b = assets_dir / "tmpl_hdr_b.png"

        self.tmpl_gt_a = cv2.imread(str(p_gt_a), 0) if p_gt_a.exists() else None
        self.tmpl_gt_b = cv2.imread(str(p_gt_b), 0) if p_gt_b.exists() else None
        self.tmpl_subj_a = cv2.imread(str(p_sb_a), 0) if p_sb_a.exists() else None
        self.tmpl_subj_b = cv2.imread(str(p_sb_b), 0) if p_sb_b.exists() else None
        self.tmpl_crest_a = cv2.imread(str(p_crest), 0) if p_crest.exists() else None
        self.tmpl_hdr_b = cv2.imread(str(p_hdr_b), 0) if p_hdr_b.exists() else None

    @staticmethod
    def _match_roi(can: np.ndarray, tmpl: Optional[np.ndarray], y1_r: float, y2_r: float, x1_r: float, x2_r: float) -> float:
        if tmpl is None:
            return 0.0
        ch, cw = can.shape
        y1, y2 = int(y1_r * ch), int(y2_r * ch)
        x1, x2 = int(x1_r * cw), int(x2_r * cw)
        roi = can[y1:y2, x1:x2]
        th, tw = tmpl.shape[:2]
        if roi.shape[0] < th or roi.shape[1] < tw:
            return 0.0
        res = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
        return float(res.max())

    def identify(self, img: np.ndarray) -> FormatIdentificationResult:
        """
        Determines format using aspect ratio, comb ink color & geometry, and layout anchor templates.
        Rejects non-covers, blank scans, rotated pages, and noise with UNKNOWN.
        """
        if img is None or img.size == 0:
            return FormatIdentificationResult(
                format_id="UNKNOWN",
                confidence=0.0,
                needs_review=True,
                reasons=["EMPTY_IMAGE"],
                features={},
            )

        h, w = img.shape[:2]

        # 1. Blank / uniform image check
        std_val = float(np.std(img))
        mean_val = float(np.mean(img))
        if std_val < 2.0 or mean_val > 252.0 or mean_val < 20.0:
            return FormatIdentificationResult(
                format_id="UNKNOWN",
                confidence=0.0,
                needs_review=True,
                reasons=["BLANK_OR_UNIFORM_IMAGE"],
                features={"mean": mean_val, "std": std_val},
            )

        # 2. Aspect ratio check (allows cropped phone/scan cover sheets while rejecting rotated pages)
        ar = w / float(h)
        if ar < self.min_aspect or ar > self.max_aspect:
            return FormatIdentificationResult(
                format_id="UNKNOWN",
                confidence=0.0,
                needs_review=True,
                reasons=[f"INVALID_ASPECT_RATIO_{ar:.3f}"],
                features={"aspect_ratio": ar},
            )

        # 3. Comb ink and geometry checks
        comb_a_score = 0.0
        comb_b_score = 0.0

        if img.ndim == 3:
            # Check A comb (red ink in Format A comb window)
            ca = img[int(h * 0.25) : int(h * 0.38), int(w * 0.50) : int(w * 0.99)]
            ra, ga, ba = ca[:, :, 2].astype(float), ca[:, :, 1].astype(float), ca[:, :, 0].astype(float)
            ink_a = (ra > 100) & ((ra - ba) > 30)
            ma = ink_a & ((ra - ga) > 0.65 * (ra - ba))
            if np.sum(ma) > 1200:
                cla = cv2.morphologyEx(
                    (ma * 255).astype(np.uint8),
                    cv2.MORPH_CLOSE,
                    cv2.getStructuringElement(cv2.MORPH_RECT, (7, 5)),
                )
                cnts_a, _ = cv2.findContours(cla, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for c in cnts_a:
                    rect = cv2.minAreaRect(c)
                    bw, bh = max(rect[1]), min(rect[1])
                    aspect = bw / float(bh) if bh > 0 else 0
                    if bw > 0.35 * ca.shape[1] and 4.0 <= aspect <= 16.0:
                        comb_a_score = 1.0
                        break

            # Check B comb (orange ink in Format B comb window)
            cb = img[int(h * 0.24) : int(h * 0.42), int(w * 0.53) : int(w * 0.99)]
            rb, gb, bb = cb[:, :, 2].astype(float), cb[:, :, 1].astype(float), cb[:, :, 0].astype(float)
            ink_b = (rb > 110) & ((rb - bb) > 25)
            mb = ink_b & (gb > 50) & (gb > bb) & ((rb - gb) < 0.62 * (rb - bb))
            if np.sum(mb) > 1200:
                clb = cv2.morphologyEx(
                    (mb * 255).astype(np.uint8),
                    cv2.MORPH_CLOSE,
                    cv2.getStructuringElement(cv2.MORPH_RECT, (7, 5)),
                )
                cnts_b, _ = cv2.findContours(clb, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for c in cnts_b:
                    rect = cv2.minAreaRect(c)
                    bw, bh = max(rect[1]), min(rect[1])
                    aspect = bw / float(bh) if bh > 0 else 0
                    if bw > 0.35 * cb.shape[1] and 4.0 <= aspect <= 16.0:
                        comb_b_score = 1.0
                        break

        # 4. Canonical scale for template anchors
        scale = 1600.0 / float(w)
        target_h = int(round(h * scale))
        can = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img, (1600, target_h))

        s_gt_a = self._match_roi(can, self.tmpl_gt_a, 0.65, 0.92, 0.35, 0.85)
        s_sb_a = self._match_roi(can, self.tmpl_subj_a, 0.18, 0.44, 0.02, 0.28)
        s_crest_a = self._match_roi(can, self.tmpl_crest_a, 0.04, 0.22, 0.05, 0.45)

        s_gt_b = self._match_roi(can, self.tmpl_gt_b, 0.55, 0.85, 0.15, 0.65)
        s_sb_b = self._match_roi(can, self.tmpl_subj_b, 0.18, 0.42, 0.01, 0.25)
        s_hdr_b = self._match_roi(can, self.tmpl_hdr_b, 0.35, 0.60, 0.20, 0.80)

        if comb_a_score > 0.5 or comb_b_score > 0.5:
            tot_a = 0.50 * comb_a_score + 0.30 * max(0.0, (s_gt_a - 0.30) / 0.45) + 0.20 * max(0.0, (s_sb_a - 0.25) / 0.40)
            tot_b = 0.50 * comb_b_score + 0.30 * max(0.0, (s_gt_b - 0.30) / 0.45) + 0.20 * max(0.0, (s_sb_b - 0.25) / 0.40)
        else:
            # Grayscale / binarized / desaturated / color-cast:
            # Rely on printed geometry anchors without requiring color
            geom_a = max(s_gt_a, 0.45 + (s_crest_a - 0.30) if s_crest_a >= 0.30 else s_gt_a)
            geom_b = max(s_gt_b, s_hdr_b)
            tot_a = geom_a
            tot_b = geom_b

        has_anchor_a = (s_gt_a >= 0.35 or s_crest_a >= 0.30 or s_sb_a >= 0.35 or comb_a_score > 0.5)
        has_anchor_b = (s_gt_b >= 0.35 or s_hdr_b >= 0.35 or s_sb_b >= 0.35 or comb_b_score > 0.5)

        features = {
            "mean_intensity": mean_val,
            "aspect_ratio": ar,
            "comb_a_detected": comb_a_score > 0.5,
            "comb_b_detected": comb_b_score > 0.5,
            "anchor_gt_a": s_gt_a,
            "anchor_subj_a": s_sb_a,
            "anchor_crest_a": s_crest_a,
            "anchor_gt_b": s_gt_b,
            "anchor_hdr_b": s_hdr_b,
            "anchor_subj_b": s_sb_b,
            "score_format_original": tot_a,
            "score_format_v2": tot_b,
        }

        diff = tot_a - tot_b
        if (comb_a_score > 0.5 and tot_a > tot_b):
            conf_a = float(max(tot_a, 0.75 * comb_a_score))
            return FormatIdentificationResult(
                format_id="format_original",
                confidence=conf_a,
                needs_review=False,
                reasons=[],
                features=features,
            )
        elif (comb_b_score > 0.5 and tot_b > tot_a):
            conf_b = float(max(tot_b, 0.75 * comb_b_score))
            return FormatIdentificationResult(
                format_id="format_v2",
                confidence=conf_b,
                needs_review=False,
                reasons=[],
                features=features,
            )
        elif diff > 0.08 and has_anchor_a and tot_a >= 0.45 and (s_crest_a >= 0.22 or s_gt_a >= 0.45):
            conf_a = float(tot_a)
            return FormatIdentificationResult(
                format_id="format_original",
                confidence=conf_a,
                needs_review=False,
                reasons=[],
                features=features,
            )
        elif diff < -0.08 and has_anchor_b and tot_b >= 0.45 and (s_hdr_b >= 0.40 or s_gt_b >= 0.60) and s_crest_a < 0.25 and (s_gt_a < 0.45) and (s_sb_a < 0.40):
            conf_b = float(tot_b)
            return FormatIdentificationResult(
                format_id="format_v2",
                confidence=conf_b,
                needs_review=False,
                reasons=[],
                features=features,
            )
        else:
            max_score = max(tot_a, tot_b)
            return FormatIdentificationResult(
                format_id="UNKNOWN",
                confidence=float(max_score),
                needs_review=True,
                reasons=[f"LOW_FORMAT_CONFIDENCE_{max_score:.2f}"],
                features=features,
            )
