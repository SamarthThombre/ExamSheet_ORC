from typing import Optional, Dict, Any, Union
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(default="ok", description="Service health status")
    version: str = Field(default="2.0.0", description="Service version")
    engine_name: str = Field(default="v2", description="Active production OCR engine name")
    manifest_hash: Optional[str] = Field(default=None, description="SHA-256 manifest hash")
    ocr_loaded: bool = Field(default=True, description="Indicates whether the OCR engine is initialized and ready")
    detector_loaded: bool = Field(default=True, description="Indicates whether the detector weights are loaded and ready")
    model_path: str = Field(default="models/ppocrv6/rec_ppocr_v6.onnx", description="Active model path")


class ExtractionResult(BaseModel):
    rollno: Optional[str] = Field(
        default=None,
        description="Cleaned student enrollment/roll number (e.g. '0801CA251001')",
        examples=["0801CA251001"],
    )
    enrollment_no: Optional[str] = Field(
        default=None,
        description="Synonym for rollno matching production schema",
        examples=["0801CA251001"],
    )
    subject_code: Optional[str] = Field(
        default=None,
        description="Cleaned exam subject code (e.g. 'CT10718')",
        examples=["CT10718"],
    )
    total_marks: Optional[Union[int, str]] = Field(
        default=None,
        description="Total marks extracted from grand_total via Strategy B",
        examples=[54],
    )
    total_marks_corrected: Optional[Union[int, str]] = Field(
        default=None,
        description="Dual-source fused total marks combining grand_total and marks_in_words",
        examples=[54],
    )
    needs_review: bool = Field(
        default=False,
        description="Diagnostic flag set to True when sources disagree, fields are missing, or manual review is recommended",
        examples=[False],
    )
    fusion_status: Optional[str] = Field(
        default=None,
        description="Agreement / fusion state (e.g. 'AGREE_EXACT', 'AGREE_ORIG_AND_TIGHT_GT', 'RECOVERED_BY_TIGHT_GT')",
        examples=["AGREE_EXACT"],
    )
    raw_ocr: Optional[Dict[str, str]] = Field(
        default=None,
        description="Raw text content extracted directly from each field crop before cleaning",
    )


class ProcessingMeta(BaseModel):
    status: str = Field(default="completed", description="Inference lifecycle status")
    processing_time_ms: float = Field(description="Total server-side processing duration in milliseconds")


class PredictResponse(BaseModel):
    success: bool = Field(default=True, description="Indicates if extraction completed successfully")
    filename: str = Field(description="Original filename of the processed image")
    result: ExtractionResult = Field(description="Extracted and cleaned structured fields")
    processing: ProcessingMeta = Field(description="Processing performance and timing metadata")


class ErrorDetail(BaseModel):
    code: str = Field(description="Machine-readable error code")
    message: str = Field(description="Human-readable explanation of the error")


class ErrorResponse(BaseModel):
    success: bool = Field(default=False, description="Failure status flag")
    error: ErrorDetail = Field(description="Error code and message payload")
