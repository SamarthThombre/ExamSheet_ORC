# Vendored Models Metadata

This directory vendors pre-trained and exported model artifacts used by the v2 production pipeline.

## 1. PP-OCRv6 Medium Recognition (ONNX)
- **Path**: `models/PP-OCRv6_medium_rec_onnx/inference.onnx`
- **Format**: ONNX (Open Neural Network Exchange)
- **Version**: PP-OCRv6 Medium
- **Source**: PaddleOCR / PaddleX Official Release
- **SHA-256**: `9c09abf0957f7968c7586464b7397b84ad2387a0497a351af40e9acc71b673ba`
- **File Size**: 76,554,979 bytes
- **Character Dictionary**: `ocr_v2/assets/character_dict.json` (SHA-256: `bf37aa18b879fe7d9b7a70112c59bf6e3e994eab8ff7b22882e3d76e485c9df1`)
- **Licence**: Apache License 2.0
- **Usage**: Cell text recognition for student enrolments, question marks cells, subject codes, and grand totals.

## 2. Integrity Verification
Model integrity is automatically verified during application startup via the `/ready` endpoint, referencing cryptographic checksums stored in `models/checksums.json` and `models/manifest.json`.
