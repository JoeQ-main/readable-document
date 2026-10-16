"""One "Read document" pass: resolve the source, extract, open the reading window."""

from .capture import capture_window
from .errors import UserFacingError, log_exception, show_error
from .extract.ocr import extract as extract_ocr
from .extract.ocr import extract_file as extract_image
from .extract.pdf import extract as extract_pdf
from .viewer import open_document
from .window_finder import Candidate, FileSource, resolve_source


def run_read_pass(candidate: Candidate | None) -> None:
    source = resolve_source(candidate)
    if isinstance(source, FileSource):
        if source.path.suffix.lower() == ".pdf":
            doc = extract_pdf(source.path)
        else:
            doc = extract_image(source.path)
    else:
        image, method = capture_window(source.hwnd)
        label = f"captured from window: {source.title}"
        if method == "screen":
            label += " (screen region capture)"
        doc = extract_ocr(image, source.title, label)
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
