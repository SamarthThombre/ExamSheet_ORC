"""
CLI entry point to process a single exam cover-sheet image using the unified OCRService.

Usage:
    python scripts/run_ocr.py <path_to_image> [--json]

Example:
    python scripts/run_ocr.py data/raw/images/page_000001.png
"""

import sys
import json
import argparse
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.ocr_service import ocr_service


def main():
    parser = argparse.ArgumentParser(description="Run OCR field extraction on an exam cover sheet.")
    parser.add_argument("image_path", help="Path to input image file (JPG, PNG, WEBP)")
    parser.add_argument("--json", action="store_true", default=True, help="Output formatted JSON (default)")
    parser.add_argument("--compact", action="store_true", help="Output compact single-line JSON")
    args = parser.parse_args()

    img_path = Path(args.image_path)
    if not img_path.is_file():
        print(f"[ERROR] Image file does not exist: {img_path}", file=sys.stderr)
        sys.exit(1)

    try:
        ocr_service.initialize()
        result = ocr_service.process_image(img_path)
        if args.compact:
            print(json.dumps(result))
        else:
            print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"[FATAL ERROR] Processing failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
