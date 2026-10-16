"""One "Read document" pass: resolve the source, extract, open the reading window."""

from PIL import Image

from .browser_cache import cached_pdf_for_screen
from .capture import capture_window
from .claude_reader import MODEL, ChunkJoiner, iter_pdf_blocks, read_image
from .errors import UserFacingError, log_exception, show_error
from .extract.model import Document
from .viewer import open_document
from .window_finder import Candidate, FileSource, resolve_source


def show_pdf_progressively(data: bytes, title: str, source_label: str) -> None:
    """Open the reading window after the first chunk and fill it as later chunks arrive."""
    joiner = ChunkJoiner()
    window = None
    label = f"{source_label} — read by Claude ({MODEL})"

    def deliver(blocks):
        nonlocal window
        if not blocks:
            return
        if window is None:
            window = open_document(Document(title=title, source_label=label, blocks=blocks, via_ocr=False))
        else:
            window.append(blocks)

    for _, last, total, chunk in iter_pdf_blocks(data):
        deliver(joiner.push(chunk))
        if window is not None:
            window.set_progress(f"Read pages 1–{last} of {total}…" if last < total else "")
    deliver(joiner.flush())
    if window is None:
        raise UserFacingError("No readable text was found.")
    window.set_progress("")


def run_read_pass(candidate: Candidate | None) -> None:
    source = resolve_source(candidate)
    if isinstance(source, FileSource):
        if source.path.suffix.lower() == ".pdf":
            show_pdf_progressively(source.path.read_bytes(), source.path.stem, str(source.path))
            return
        with Image.open(source.path) as image:
            image.load()
            open_document(read_image(image, source.path.stem, str(source.path)))
        return

    image, method = capture_window(source.hwnd)
    label = f"captured from window: {source.title} — only what was visible on screen"
    if method == "screen":
        label += " (screen region capture)"
    doc = read_image(image, source.title, label)
    # A PDF shown from the web lives only in the browser cache; the transcribed screen
    # tells us which cached PDF it is, and then the whole document can be read.
    cached = cached_pdf_for_screen([block.text for block in doc.blocks])
    if cached:
        data, title = cached
        show_pdf_progressively(
            data, title, f"{title} — full document from the browser cache, matched to the page on screen"
        )
        return
    open_document(doc)


def safe_read_pass(candidate: Candidate | None) -> None:
    """Run a read pass and turn every failure into a message box; never raises."""
    try:
        run_read_pass(candidate)
    except UserFacingError as exc:
        show_error(str(exc))
    except Exception as exc:  # noqa: BLE001 - the tray must survive anything
        log_exception(exc)
        show_error(f"Something went wrong: {type(exc).__name__}: {exc}")
