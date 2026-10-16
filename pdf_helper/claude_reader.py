"""Read a document with the Claude API: PDFs go in as documents, screens and
image files as images, and Claude returns the headings, paragraphs and list
items as structured JSON that the reading window renders."""

import base64
import io
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Literal

import anthropic
from PIL import Image
from pydantic import BaseModel

from .errors import UserFacingError
from .extract.model import Block, Document

MODEL = "claude-opus-5-5"
EFFORT = "medium"
MAX_OUTPUT_TOKENS = 64_000
REQUEST_TIMEOUT_SECONDS = 1800.0  # long documents take minutes; the SDK guard needs an explicit timeout
MAX_IMAGE_EDGE = 1568  # the API downsizes beyond this anyway; do it here so the upload is small
MAX_IMAGE_BYTES = 4_500_000
MAX_PDF_PAGES = 600
MAX_PDF_BYTES = 30 * 1024 * 1024
CHUNK_PAGES = 15  # pages per request: keeps each transcription well under the output limit
MAX_WORKERS = 4  # chunk requests in flight at once
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """You transcribe documents for a reading tool that restyles them for easier reading.

Return the document's content as blocks in reading order:
- "heading" with level 1 (document or chapter title), 2 (section) or 3 (sub-section).
- "paragraph" for body text. Join the lines of a paragraph into one block; do not split a paragraph at line wraps or page breaks, and join hyphenated line breaks.
- "list_item" for each bullet or numbered item, without the marker.

Rules:
- Transcribe the text exactly. Never summarize, paraphrase, reorder, translate or add text. Keep every sentence of the document body.
- Multi-column layouts read column by column, not across columns. Tables become one paragraph per row with cells separated by " | ".
- Omit things that are not document content: application toolbars, menus, tabs, address bars, navigation sidebars, buttons, cookie banners, advertisements, running page headers and footers, and bare page numbers.
- Omit captions only if they are not sentences; keep figure captions that carry information.
- If the image shows no readable document text, return an empty block list.
- "title" is the document's own title if one is visible, else a short descriptive title."""

PDF_INSTRUCTION = "Transcribe this entire PDF into blocks, from the first page to the last."
PDF_CHUNK_INSTRUCTION = (
    "This PDF holds pages {first} to {last} of {total} of a longer document. Transcribe all of "
    "these pages into blocks. If the first page starts mid-paragraph, begin with that partial "
    "paragraph as it appears; if the last page ends mid-paragraph, end with the partial paragraph."
)
IMAGE_INSTRUCTION = "Transcribe the document content visible in this image into blocks."

MISSING_KEY_MESSAGE = (
    "The Claude API rejected the credentials. Put your key in the .env file next to "
    "ReadableDocument.pyw as ANTHROPIC_API_KEY=sk-ant-... (see .env.example), or set that "
    "environment variable, then quit and relaunch Readable Document."
)


class ParsedBlock(BaseModel):
    kind: Literal["heading", "paragraph", "list_item"]
    level: int
    text: str


class ParsedDocument(BaseModel):
    title: str
    blocks: list[ParsedBlock]


def _make_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


client_factory: Callable[[], anthropic.Anthropic] = _make_client  # tests replace this


def prepare_image(image: Image.Image) -> tuple[bytes, str]:
    """PNG bytes with the long edge at most MAX_IMAGE_EDGE; JPEG if PNG is too large."""
    image = image.convert("RGB")
    longest = max(image.size)
    if longest > MAX_IMAGE_EDGE:
        scale = MAX_IMAGE_EDGE / longest
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                             Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    if buffer.tell() <= MAX_IMAGE_BYTES:
        return buffer.getvalue(), "image/png"
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue(), "image/jpeg"


def _pdf_page_count(data: bytes) -> int:
    import pymupdf

    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise UserFacingError("This PDF is password-protected.")
            return pdf.page_count
    except UserFacingError:
        raise
    except Exception as exc:
        raise UserFacingError("Could not open this file as a PDF.") from exc


def _ask(content: list[dict]) -> ParsedDocument:
    client = client_factory().with_options(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        response = client.beta.messages.parse(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            output_format=ParsedDocument,
            output_config={"effort": EFFORT},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        raise UserFacingError(MISSING_KEY_MESSAGE) from exc
    except anthropic.RateLimitError as exc:
        raise UserFacingError("The Claude API rate limit was hit. Wait a minute and try again.") from exc
    except anthropic.APIStatusError as exc:
        raise UserFacingError(f"The Claude API returned an error ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise UserFacingError("Could not reach the Claude API. Check your internet connection.") from exc

    if response.stop_reason == "refusal":
        detail = getattr(response.stop_details, "explanation", None) or ""
        raise UserFacingError(f"Claude declined to read this document. {detail}".strip())
    if response.stop_reason == "max_tokens":
        raise UserFacingError("This document is too long to transcribe in one read.")
    if response.parsed_output is None:
        raise UserFacingError("Claude returned no document content.")
    return response.parsed_output


def _blocks(parsed: ParsedDocument) -> list[Block]:
    return [Block(b.kind, b.text.strip(), b.level if b.kind == "heading" else 0)
            for b in parsed.blocks if b.text.strip()]


def _join_chunks(chunks: list[list[Block]]) -> list[Block]:
    """Concatenate per-chunk blocks, joining a paragraph that continues across the boundary."""
    merged: list[Block] = []
    for blocks in chunks:
        if (merged and blocks and merged[-1].kind == "paragraph" and blocks[0].kind == "paragraph"
                and blocks[0].text[:1].islower()):
            previous = merged.pop()
            joiner = "" if previous.text.endswith("-") else " "
            text = previous.text.rstrip("-") + joiner + blocks[0].text
            merged.append(Block("paragraph", text))
            merged.extend(blocks[1:])
        else:
            merged.extend(blocks)
    return merged


def _document(blocks: list[Block], title: str, source_label: str, via_image: bool) -> Document:
    if not blocks:
        raise UserFacingError("No readable text was found.")
    return Document(title=title, source_label=f"{source_label} — read by Claude ({MODEL})",
                    blocks=blocks, via_ocr=via_image)


def _split_pdf(data: bytes, pages: int) -> list[tuple[int, int, bytes]]:
    """(first_page, last_page, pdf_bytes) per chunk of at most CHUNK_PAGES pages."""
    if pages <= CHUNK_PAGES:
        return [(1, pages, data)]
    import pymupdf

    chunks = []
    with pymupdf.open(stream=data, filetype="pdf") as source:
        for start in range(0, pages, CHUNK_PAGES):
            end = min(start + CHUNK_PAGES, pages)
            part = pymupdf.open()
            part.insert_pdf(source, from_page=start, to_page=end - 1)
            chunks.append((start + 1, end, part.tobytes()))
            part.close()
    return chunks


def _pdf_content(pdf_bytes: bytes, instruction: str) -> list[dict]:
    return [
        {"type": "document",
         "source": {"type": "base64", "media_type": "application/pdf",
                    "data": base64.standard_b64encode(pdf_bytes).decode("ascii")}},
        {"type": "text", "text": instruction},
    ]


def read_pdf(data: bytes, title: str, source_label: str) -> Document:
    if len(data) > MAX_PDF_BYTES:
        raise UserFacingError("This PDF is larger than the Claude API accepts (30 MB).")
    pages = _pdf_page_count(data)
    if pages > MAX_PDF_PAGES:
        raise UserFacingError(f"This PDF has {pages} pages; the Claude API reads at most {MAX_PDF_PAGES}.")
    chunks = _split_pdf(data, pages)
    if len(chunks) == 1:
        return _document(_blocks(_ask(_pdf_content(data, PDF_INSTRUCTION))), title, source_label, False)

    def read_chunk(chunk: tuple[int, int, bytes]) -> list[Block]:
        first, last, part = chunk
        instruction = PDF_CHUNK_INSTRUCTION.format(first=first, last=last, total=pages)
        return _blocks(_ask(_pdf_content(part, instruction)))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        per_chunk = list(pool.map(read_chunk, chunks))
    return _document(_join_chunks(per_chunk), title, source_label, False)


def read_image(image: Image.Image, title: str, source_label: str) -> Document:
    data, media_type = prepare_image(image)
    content = [
        {"type": "image",
         "source": {"type": "base64", "media_type": media_type,
                    "data": base64.standard_b64encode(data).decode("ascii")}},
        {"type": "text", "text": IMAGE_INSTRUCTION},
    ]
    return _document(_blocks(_ask(content)), title, source_label, via_image=True)
