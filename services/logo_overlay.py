from __future__ import annotations

from pathlib import Path
import fitz  # PyMuPDF


MM_TO_PT = 72 / 25.4


def _mm(value: float) -> float:
    return value * MM_TO_PT


def add_logo_to_pdf(input_pdf: str | Path, output_pdf: str | Path, logo_path: str | Path) -> str:
    input_pdf = Path(input_pdf)
    output_pdf = Path(output_pdf)
    logo_path = Path(logo_path)

    if not input_pdf.exists():
        raise FileNotFoundError(f'Input PDF not found: {input_pdf}')
    if not logo_path.exists():
        raise FileNotFoundError(f'Logo image not found: {logo_path}')

    doc = fitz.open(str(input_pdf))
    try:
        logo_bytes = logo_path.read_bytes()
        for page in doc:
            page_width = page.rect.width

            # Keep logo visible but modest across different page sizes.
            logo_width = min(_mm(30), page_width * 0.22)
            logo_height = logo_width

            x0 = _mm(8)
            y0 = _mm(8)
            rect = fitz.Rect(x0, y0, x0 + logo_width, y0 + logo_height)
            page.insert_image(rect, stream=logo_bytes, keep_proportion=True, overlay=True)

        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(output_pdf), garbage=4, deflate=True)
    finally:
        doc.close()

    return str(output_pdf)
