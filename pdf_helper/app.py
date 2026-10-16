"""One "Read document" pass: resolve the source, extract, open the reading window."""

from PIL import Image

from .browser_cache import cached_pdf_for_screen
from .capture import capture_window
from .claude_reader import read_image, read_pdf
from .errors import UserFacingError, log_exception, show_error
from .viewer import open_document
from .window_finder import Candidate, FileSource, resolve_source


def run_read_pass(candidate: Candidate | None) -> None:
    source = resolve_source(candidate)
    if isinstance(source, FileSource):
        if source.path.suffix.lower() == ".pdf":
            doc = read_pdf(source.path.read_bytes(), source.path.stem, str(source.path))
        else:
            with Image.open(source.path) as image:
                image.load()
                doc = read_image(image, source.path.stem, str(source.path))
    else:
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
            doc = read_pdf(
                data, title, f"{title} — full document from the browser cache, matched to the page on screen"
            )
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
