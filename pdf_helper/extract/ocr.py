"""OCR extraction using the Windows built-in OCR engine (via winocr)."""

from pathlib import Path

from PIL import Image

from ..errors import UserFacingError
from .layout import Line, group_lines
from .model import Document

MIN_TEXT_CHARS = 20
MAX_DIMENSION = 10000  # Windows OCR limit on either side
LANGUAGE = "en"

MISSING_LANGUAGE_MESSAGE = (
    "Windows OCR has no English language pack. Install it under Settings → Time & language → "
    "Language & region → English → Language options → Basic typing / OCR, or run in an admin "
    'PowerShell: Add-WindowsCapability -Online -Name "Language.OCR~~~en-US~0.0.1.0"'
)


def _winocr_recognize(image: Image.Image) -> dict:
    import winocr  # lazy: loads the winrt packages only when OCR is really needed

    return winocr.recognize_pil_sync(image, lang=LANGUAGE)


recognizer = _winocr_recognize  # tests replace this


def _prepare(image: Image.Image) -> Image.Image:
    image = image.convert("RGB")
    longest = max(image.width, image.height)
    if longest > MAX_DIMENSION:
        scale = MAX_DIMENSION / longest
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
    return image


def lines_from_result(result: dict) -> list[Line]:
    """Convert a winocr result dict into lines sorted top-to-bottom, left-to-right."""
    lines: list[Line] = []
    for raw in result.get("lines", []):
        words = raw.get("words") or []
        rects = [w["bounding_rect"] for w in words if w.get("bounding_rect")]
        text = (raw.get("text") or " ".join(w.get("text", "") for w in words)).strip()
        if not text or not rects:
            continue
        x0 = min(r["x"] for r in rects)
        y0 = min(r["y"] for r in rects)
        x1 = max(r["x"] + r["width"] for r in rects)
        y1 = max(r["y"] + r["height"] for r in rects)
        lines.append(Line(text, x0, y0, x1, y1))
    lines.sort(key=lambda l: (l.y0, l.x0))
    return lines


def recognize_image(image: Image.Image) -> list[Line]:
    try:
        result = recognizer(_prepare(image))
    except AssertionError as exc:  # winocr asserts the language pack exists
        raise UserFacingError(MISSING_LANGUAGE_MESSAGE) from exc
    return lines_from_result(result)


def extract(image: Image.Image, title: str, source_label: str) -> Document:
    lines = recognize_image(image)
    if sum(len(l.text) for l in lines) < MIN_TEXT_CHARS:
        raise UserFacingError("No readable text was found.")
    return Document(title=title, source_label=source_label, blocks=group_lines(lines), via_ocr=True)


def extract_file(path: Path) -> Document:
    with Image.open(path) as image:
        image.load()
        return extract(image, path.stem, str(path))
