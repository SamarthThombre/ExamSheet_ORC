"""
ocr_v2: Clean, fast, template-first OCR pipeline.
Milestone 2 package.
"""

from .normalise import PageNormaliser, AlignmentResult, TransformMatrix
from .formats import FormatDetector, FormatIdentificationResult
from .fields import FieldCropper, FieldCropResult, extract_total_crop_tmpl
from .reader import BatchedONNXReader, PageRecognitionResult, FieldRecognitionResult, parse_total_marks
from .batch import BatchSubjectCodeConsensus, BatchVoteResult
from .review import BatchReviewManager, BatchReviewResult, classify_flags
from .table import DualAnchorTableDetector
from .cell_reader import SharedCellReader, parse_question_cell, compute_sum_status, get_ort_session

__all__ = [
    "PageNormaliser",
    "AlignmentResult",
    "TransformMatrix",
    "FormatDetector",
    "FormatIdentificationResult",
    "FieldCropper",
    "FieldCropResult",
    "extract_total_crop_tmpl",
    "BatchedONNXReader",
    "PageRecognitionResult",
    "FieldRecognitionResult",
    "parse_total_marks",
    "BatchSubjectCodeConsensus",
    "BatchVoteResult",
    "BatchReviewManager",
    "BatchReviewResult",
    "classify_flags",
    "DualAnchorTableDetector",
    "SharedCellReader",
    "parse_question_cell",
    "compute_sum_status",
    "get_ort_session",
]

