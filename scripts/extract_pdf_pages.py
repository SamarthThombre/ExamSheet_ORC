"""
Extracts pages from exam cover-sheet PDFs into consistently-named PNG images.
Preserves page numbering and prevents accidental overwrites.

Usage:
    python scripts/extract_pdf_pages.py --pdf exam_papers.pdf --out data/raw/images --dpi 300
"""

import argparse
import logging
from pathlib import Path
import pypdfium2 as pdfium

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("extract_pdf_pages")


def extract_pdf_pages(
    pdf_path: Path,
    output_dir: Path,
    dpi: int = 300,
    start_index: int = 1,
    overwrite: bool = False,
    prefix: str = "page_",
) -> int:
    """
    Renders and saves each page of a PDF file as a high-resolution PNG.
    """
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    total_pages = len(pdf)
    logger.info(f"Opened '{pdf_path.name}': {total_pages} pages found.")

    scale = dpi / 72.0  # 72 points per inch standard PDF scale
    saved_count = 0

    for i in range(total_pages):
        page_num = start_index + i
        target_name = f"{prefix}{page_num:06d}.png"
        target_file = output_dir / target_name

        if target_file.exists() and not overwrite:
            logger.warning(f"Skipping existing file '{target_name}' (use --overwrite to replace).")
            continue

        page = pdf[i]
        image = page.render(scale=scale).to_pil()
        image.save(str(target_file), format="PNG")
        saved_count += 1

        if (i + 1) % 20 == 0 or (i + 1) == total_pages:
            logger.info(f"Extracted {i + 1}/{total_pages} pages -> '{target_file.name}'")

    logger.info(f"Successfully extracted {saved_count} pages to '{output_dir}'.")
    return saved_count


def main():
    parser = argparse.ArgumentParser(description="Extract pages from PDF to PNG images.")
    parser.add_argument("--pdf", required=True, type=Path, help="Path to input PDF file")
    parser.add_argument("--out", default=Path("data/raw/images"), type=Path, help="Output directory")
    parser.add_argument("--dpi", default=300, type=int, help="Rendering resolution (DPI)")
    parser.add_argument("--start", default=1, type=int, help="Starting page index for numbering")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing image files")
    parser.add_argument("--prefix", default="page_", help="Filename prefix (default: 'page_')")
    args = parser.parse_args()

    extract_pdf_pages(
        pdf_path=args.pdf,
        output_dir=args.out,
        dpi=args.dpi,
        start_index=args.start,
        overwrite=args.overwrite,
        prefix=args.prefix,
    )


if __name__ == "__main__":
    main()
