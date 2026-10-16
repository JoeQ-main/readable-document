"""One "Read document" pass: resolve the source, extract, open the reading window."""

from PIL import Image

from .browser_cache import cached_pdf_for_screen
from .capture import capture_window
from .claude_reader import ChunkJoiner, iter_pdf_blocks, read_image, source_description
from .errors import UserFacingError, log_exception, show_error
from .extract.model import Document
from .viewer import open_document
from .window_finder import Candidate, FileSource, resolve_source


WAITING = "Reading with Claude…"


def open_empty_window(title: str, source_label: str, via_image: bool):
    """Open the reading window right away with the progress bar running, before the
    first API response, so the user sees something happening."""
    window = open_document(Document(title=title, source_label=source_description(source_label),
                                    blocks=[], via_ocr=via_image))
    window.set_progress(WAITING)
    return window


def show_pdf_progressively(data: bytes, title: str, source_label: str) -> None:
    """Open the reading window immediately and fill it as page chunks arrive."""
    window = open_empty_window(title, source_label, via_image=False)
    joiner = ChunkJoiner()
    delivered = False
    pages_done, pages_total = 0, 0

    def deliver(blocks):
        nonlocal delivered
        if blocks:
            window.append(blocks)
            delivered = True

    try:
        for chunk in iter_pdf_blocks(data):
            pages_done, pages_total = chunk.last, chunk.total
            deliver(joiner.push(chunk.blocks))
            if chunk.from_cache:
                window.set_source(source_description(source_label, from_cache=True))
            window.set_progress(f"Read pages 1–{chunk.last} of {chunk.total}…", chunk.last / chunk.total)
        deliver(joiner.flush())
    except Exception as exc:
        if delivered:  # leave the partial document readable, but say why it stopped
            fraction = pages_done / pages_total if pages_total else None
            window.set_progress(f"Reading stopped after page {pages_done} of {pages_total}: {exc}", fraction)
        else:
            window.close()
        raise
    if not delivered:
        window.close()
        raise UserFacingError("No readable text was found.")
    window.set_progress("")


def show_image(image: Image.Image, title: str, source_label: str, window=None) -> Document:
    """Transcribe one image into an already-open (or newly opened) window; returns the document."""
    window = window or open_empty_window(title, source_label, via_image=True)
    try:
        doc = read_image(image, title, source_label)
    except Exception:
        window.close()
        raise
    return doc, window


def run_read_pass(candidate: Candidate | None) -> None:
    source = resolve_source(candidate)
    if isinstance(source, FileSource):
        if source.path.suffix.lower() == ".pdf":
            show_pdf_progressively(source.path.read_bytes(), source.path.stem, str(source.path))
            return
        with Image.open(source.path) as image:
            image.load()
            doc, window = show_image(image, source.path.stem, str(source.path))
        _fill(window, doc)
        return

    image, method = capture_window(source.hwnd)
    label = f"captured from window: {source.title} — only what was visible on screen"
    if method == "screen":
        label += " (screen region capture)"
    doc, window = show_image(image, source.title, label)
    # A PDF shown from the web lives only in the browser cache; the transcribed screen
    # tells us which cached PDF it is, and then the whole document can be read instead.
    cached = cached_pdf_for_screen([block.text for block in doc.blocks])
    if cached:
        window.close()
        data, title = cached
        show_pdf_progressively(
            data, title, f"{title} — full document from the browser cache, matched to the page on screen"
        )
        return
    _fill(window, doc)


def _fill(window, doc: Document) -> None:
    window.append(doc.blocks)
    window.set_source(doc.source_label)
    window.set_progress("")


def safe_read_pass(candidate: Candidate | None) -> None:
    """Run a read pass and turn every failure into a message box; never raises."""
    try:
        run_read_pass(candidate)
    except UserFacingError as exc:
        show_error(str(exc))
    except Exception as exc:  # noqa: BLE001 - the tray must survive anything
        log_exception(exc)
        show_error(f"Something went wrong: {type(exc).__name__}: {exc}")
