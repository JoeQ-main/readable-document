"""Read a document with the Claude API: PDFs go in as documents, screens and
image files as images, and Claude returns the headings, paragraphs and list
items as structured JSON that the reading window renders."""

import base64
import io
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterator, Literal

import anthropic
from PIL import Image
from pydantic import BaseModel

from .errors import UserFacingError
from .extract.model import Block, Document

DEFAULT_MODEL = "claude-opus-5-5"
MODEL_ENV_VAR = "READABLE_MODEL"  # set in .env to use another model, e.g. claude-sonnet-5-5
EFFORT = "low"  # transcription output dominates the cost; measured: effort changes neither speed nor quality
MAX_OUTPUT_TOKENS = 64_000
REQUEST_TIMEOUT_SECONDS = 1800.0  # long documents take minutes; the SDK guard needs an explicit timeout
MAX_IMAGE_EDGE = 1568  # the API downsizes beyond this anyway; do it here so the upload is small
MAX_IMAGE_BYTES = 4_500_000
MAX_PDF_PAGES = 600
MAX_PDF_BYTES = 30 * 1024 * 1024
# Measured on Opus 5.5: a dense page is ~3,200 output tokens at ~150 tokens/s, so 6 pages
# is ~2 minutes per request and stays far below the output cap; 8 in flight keeps a
# 140-page document under ten minutes with the first pages on screen after the first chunk.
CHUNK_PAGES = 6
MAX_WORKERS = 8


def model() -> str:
    return os.environ.get(MODEL_ENV_VAR, "").strip() or DEFAULT_MODEL
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
            model=model(),
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


class ChunkJoiner:
    """Joins page chunks in order, holding back each chunk's trailing paragraph until
    the next chunk shows whether it continues (a lowercase start means it does)."""

    def __init__(self) -> None:
        self._pending: Block | None = None

    def push(self, blocks: list[Block]) -> list[Block]:
        """Blocks that are final after adding this chunk."""
        ready: list[Block] = []
        blocks = list(blocks)
        if self._pending is not None:
            if blocks and blocks[0].kind == "paragraph" and blocks[0].text[:1].islower():
                previous = self._pending.text
                joiner = "" if previous.endswith("-") else " "
                blocks[0] = Block("paragraph", previous.rstrip("-") + joiner + blocks[0].text)
            else:
                ready.append(self._pending)
            self._pending = None
        if blocks and blocks[-1].kind == "paragraph":
            self._pending = blocks.pop()
        ready.extend(blocks)
        return ready

    def flush(self) -> list[Block]:
        pending, self._pending = self._pending, None
        return [pending] if pending is not None else []


def _document(blocks: list[Block], title: str, source_label: str, via_image: bool) -> Document:
    if not blocks:
        raise UserFacingError("No readable text was found.")
    return Document(title=title, source_label=f"{source_label} — read by Claude ({model()})",
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


def iter_pdf_blocks(data: bytes) -> Iterator[tuple[int, int, int, list[Block]]]:
    """Yield (first_page, last_page, total_pages, blocks) per chunk, in page order,
    each as soon as it is ready; chunks are requested MAX_WORKERS at a time."""
    if len(data) > MAX_PDF_BYTES:
        raise UserFacingError("This PDF is larger than the Claude API accepts (30 MB).")
    pages = _pdf_page_count(data)
    if pages > MAX_PDF_PAGES:
        raise UserFacingError(f"This PDF has {pages} pages; the Claude API reads at most {MAX_PDF_PAGES}.")
    chunks = _split_pdf(data, pages)
    if len(chunks) == 1:
        yield 1, pages, pages, _blocks(_ask(_pdf_content(data, PDF_INSTRUCTION)))
        return

    def read_chunk(chunk: tuple[int, int, bytes]) -> list[Block]:
        first, last, part = chunk
        instruction = PDF_CHUNK_INSTRUCTION.format(first=first, last=last, total=pages)
        return _blocks(_ask(_pdf_content(part, instruction)))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for (first, last, _), blocks in zip(chunks, pool.map(read_chunk, chunks)):
            yield first, last, pages, blocks


def read_pdf(data: bytes, title: str, source_label: str) -> Document:
    """Whole document at once; the app streams chunks via iter_pdf_blocks instead."""
    joiner = ChunkJoiner()
    blocks: list[Block] = []
    for *_, chunk in iter_pdf_blocks(data):
        blocks.extend(joiner.push(chunk))
    blocks.extend(joiner.flush())
    return _document(blocks, title, source_label, False)


def read_image(image: Image.Image, title: str, source_label: str) -> Document:
    data, media_type = prepare_image(image)
    content = [
        {"type": "image",
         "source": {"type": "base64", "media_type": media_type,
                    "data": base64.standard_b64encode(data).decode("ascii")}},
        {"type": "text", "text": IMAGE_INSTRUCTION},
    ]
    return _document(_blocks(_ask(content)), title, source_label, via_image=True)
