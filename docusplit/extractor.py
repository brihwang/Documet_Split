from __future__ import annotations

from pathlib import Path

import pdfplumber

from .models import PageText


MIN_TEXT_CHARS_FOR_OCR = 25


def extract_pdf_text(path: Path) -> list[PageText]:
    pages: list[PageText] = []
    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages):
            text = (page.extract_text() or "").strip()
            source = "embedded_text"
            if len(text) < MIN_TEXT_CHARS_FOR_OCR:
                ocr_text = try_ocr_page(path, index)
                if ocr_text:
                    text = ocr_text
                    source = "ocr"
                else:
                    source = "empty_or_ocr_unavailable"
            pages.append(PageText(page_number=index + 1, text=text, source=source))
    return pages


def try_ocr_page(path: Path, page_index: int) -> str:
    try:
        import fitz  # type: ignore
        import pytesseract  # type: ignore
        from PIL import Image
    except Exception:
        return ""

    try:
        document = fitz.open(path)
        page = document.load_page(page_index)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        return (pytesseract.image_to_string(image) or "").strip()
    except Exception:
        return ""
