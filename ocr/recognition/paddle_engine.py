"""
PaddleOCR recognition engine wrapper with Windows CPU and torch import isolation safeguards.
"""

import os
import time
import logging
import importlib.util
from typing import Tuple, Optional
import numpy as np

# Ensure environment flags are active before importing paddle
os.environ["FLAGS_enable_pir_api"] = "0"
os.environ["FLAGS_enable_pir_in_executor"] = "0"
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["FLAGS_use_onednn"] = "0"
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

logger = logging.getLogger("ocr.recognition.paddle_engine")


class PaddleOCREngine:
    """
    Manages PaddleOCR model lifecycle and single-crop text recognition.
    """

    def __init__(self, lang: str = "en"):
        self.lang = lang
        self.engine = None
        self.is_loaded = False

    def load_engine(self):
        """
        Initializes PaddleOCR with torch import isolation to circumvent
        Windows DLL loading issues (Error 127 with torch.lib.shm.dll).
        """
        if self.is_loaded:
            return

        t0 = time.perf_counter()
        logger.info(f"Initializing PaddleOCR engine (lang='{self.lang}', CPU safe mode)...")

        _orig_find_spec = importlib.util.find_spec
        importlib.util.find_spec = (
            lambda name, *a, **kw: None
            if name == "torch" or name.startswith("torch.")
            else _orig_find_spec(name, *a, **kw)
        )
        try:
            from paddleocr import PaddleOCR
            self.engine = PaddleOCR(
                enable_mkldnn=False,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                lang=self.lang,
            )
        finally:
            importlib.util.find_spec = _orig_find_spec

        self.is_loaded = True
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(f"PaddleOCR engine loaded successfully in {elapsed_ms:.1f}ms.")

    def ocr_crop(self, crop: Optional[np.ndarray]) -> Tuple[str, float]:
        """
        Runs text recognition on a cropped image array.
        Compatible with both PaddleOCR 2.x and 3.x result formats.

        Returns:
          (joined_text: str, average_confidence: float)
        """
        if crop is None or crop.size == 0 or crop.shape[0] < 5 or crop.shape[1] < 5:
            return "", 0.0

        if not self.is_loaded:
            self.load_engine()

        try:
            ocr_res = self.engine.ocr(crop)
            if not ocr_res or not ocr_res[0]:
                return "", 0.0

            texts, confs = [], []
            first_entry = ocr_res[0]

            # PaddleOCR 3.x dictionary format
            if isinstance(first_entry, dict) and "rec_texts" in first_entry:
                raw_texts = first_entry.get("rec_texts", [])
                raw_scores = first_entry.get("rec_scores", [])
                for txt, cf in zip(raw_texts, raw_scores):
                    t = str(txt).strip()
                    if t:
                        texts.append(t)
                        confs.append(float(cf))
            elif isinstance(first_entry, list):
                # PaddleOCR 2.x list of line detections format
                for line in first_entry:
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
                        texts.append(txt)
                        confs.append(cf)

            joined_text = " ".join(texts)
            avg_conf = sum(confs) / len(confs) if confs else 0.0
            return joined_text, round(avg_conf, 3)

        except Exception as e:
            logger.warning(f"PaddleOCR recognition exception on crop: {e}")
            return "", 0.0
