"""PDF extraction: text layer via PyMuPDF, OCR fallback for scanned pages."""

import re
from collections import Counter
from pathlib import Path

import pymupdf
from PIL import Image

from ..errors import UserFacingError
from .layout import Line, group_lines, merge_paragraph_runs
from .model import Document

BOLD_FLAG = 16
SCANNED_PAGE_MAX_CHARS = 50
RUNNING_LINE_MIN_PAGES = 3
MARGIN_FRACTION = 0.10
OCR_ZOOM = 2
PAGE_NUMBER = re.compile(r"^(page\s+)?\d+(\s+of\s+\d+)?$", re.IGNORECASE)


def ocr_lines(image: Image.Image) -> list[Line]:
    """OCR an image into lines. Imported lazily so tests never load winrt."""
    from .ocr import recognize_image

    return recognize_image(image)


def page_lines(page: pymupdf.Page) -> list[Line]:
    lines: list[Line] = []
    for block in page.get_text("dict")["blocks"]:
        for raw_line in block.get("lines", []):
            spans = [s for s in raw_line.get("spans", []) if s["text"].strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in raw_line["spans"]).strip()
            longest = max(spans, key=lambda s: len(s["text"]))
            total_chars = sum(len(s["text"]) for s in spans)
            bold_chars = sum(len(s["text"]) for s in spans if s["flags"] & BOLD_FLAG)
            x0, y0, x1, y1 = raw_line["bbox"]
            lines.append(Line(text, x0, y0, x1, y1, float(longest["size"]),
                              bold_chars >= 0.6 * total_chars))
    return lines


def body_size(lines: list[Line]) -> float | None:
    counts: Counter[float] = Counter()
    for line in lines:
        if line.size is not None:
            counts[round(line.size * 2) / 2] += len(line.text)
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def _normalize(text: str) -> str:
    return re.sub(r"\d+", "#", text.strip().lower())


def remove_running_lines(pages: list[list[Line]], page_heights: list[float]) -> list[list[Line]]:
    """Drop running headers/footers (same text in the margins on 3+ pages) and page numbers."""
    seen_on_pages: Counter[str] = Counter()
    for lines, height in zip(pages, page_heights):
        in_margin = {_normalize(l.text) for l in lines
                     if l.y0 < MARGIN_FRACTION * height or l.y1 > (1 - MARGIN_FRACTION) * height}
        seen_on_pages.update(in_margin)
    running = {text for text, n in seen_on_pages.items() if n >= RUNNING_LINE_MIN_PAGES}

    cleaned: list[list[Line]] = []
    for lines, height in zip(pages, page_heights):
        kept = []
        for line in lines:
            in_margin = line.y0 < MARGIN_FRACTION * height or line.y1 > (1 - MARGIN_FRACTION) * height
            if in_margin and (_normalize(line.text) in running or PAGE_NUMBER.match(line.text.strip())):
                continue  # running header/footer or a page number; body numbers are never touched
            kept.append(line)
        cleaned.append(kept)
    return cleaned


def _render_page(page: pymupdf.Page) -> Image.Image:
    pix = page.get_pixmap(matrix=pymupdf.Matrix(OCR_ZOOM, OCR_ZOOM))
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def extract(path: Path) -> Document:
    with pymupdf.open(path) as pdf:
        text_pages: list[list[Line] | None] = []
        page_heights: list[float] = []
        scanned: list[pymupdf.Page] = []
        for page in pdf:
            lines = page_lines(page)
            page_heights.append(page.rect.height)
            if sum(len(l.text) for l in lines) < SCANNED_PAGE_MAX_CHARS:
                text_pages.append(None)
                scanned.append(page)
            else:
                text_pages.append(lines)

        present = [lines for lines in text_pages if lines is not None]
        present_heights = [h for lines, h in zip(text_pages, page_heights) if lines is not None]
        cleaned = iter(remove_running_lines(present, present_heights))
        document_body = body_size([l for lines in present for l in lines])

        via_ocr = False
        per_page: list[list] = []
        scanned_iter = iter(scanned)
        for lines in text_pages:
            if lines is None:
                via_ocr = True
                per_page.append(group_lines(ocr_lines(_render_page(next(scanned_iter)))))
            else:
                per_page.append(group_lines(next(cleaned), body_size=document_body))

    blocks = merge_paragraph_runs(per_page)
    if not blocks:
        raise UserFacingError("No readable text was found.")
    return Document(title=path.stem, source_label=str(path), blocks=blocks, via_ocr=via_ocr)
