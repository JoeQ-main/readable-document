import pytest

from pdf_helper import app
from pdf_helper.app import run_read_pass, safe_read_pass
from pdf_helper.claude_reader import PdfChunk
from pdf_helper.errors import UserFacingError
from pdf_helper.extract.model import Block, Document
from pdf_helper.window_finder import Candidate, CaptureSource, FileSource


def _raise(exc):
    raise exc


def _doc(*texts, source="s"):
    return Document("t", source, [Block("paragraph", t) for t in texts], True)


class FakeWindow:
    def __init__(self):
        self.appended = []
        self.progress = []
        self.sources = []
        self.closed = False

    def append(self, blocks):
        self.appended.append(blocks)

    def set_progress(self, text, fraction=None):
        self.progress.append((text, fraction))

    def set_source(self, text):
        self.sources.append(text)

    def close(self):
        self.closed = True


def test_pdf_opens_an_empty_window_first_then_streams_chunks_with_fractions(monkeypatch, tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-x")
    monkeypatch.setattr(app, "resolve_source", lambda c: FileSource(f))

    def chunks(data):
        yield PdfChunk(1, 15, 32, [Block("heading", "Title", 1), Block("paragraph", "ends mid")], False)
        yield PdfChunk(16, 30, 32, [Block("paragraph", "sentence here."), Block("paragraph", "Second.")], False)
        yield PdfChunk(31, 32, 32, [Block("paragraph", "Last.")], False)

    monkeypatch.setattr(app, "iter_pdf_blocks", chunks)
    window = FakeWindow()
    opened = []
    monkeypatch.setattr(app, "open_document", lambda doc: opened.append(doc) or window)
    run_read_pass(Candidate(1, "t", 2, "c"))
    assert opened[0].title == "a" and opened[0].blocks == [] and opened[0].via_ocr is False
    assert opened[0].source_label == f"{f} — read by Claude (claude-opus-5-5)"
    assert window.appended == [
        [Block("heading", "Title", 1)],
        [Block("paragraph", "ends mid sentence here.")],
        [Block("paragraph", "Second.")],
        [Block("paragraph", "Last.")],
    ]
    assert window.progress[0] == ("Reading with Claude…", None)
    assert window.progress[1] == ("Read pages 1–15 of 32…", 15 / 32)
    assert window.progress[2] == ("Read pages 1–30 of 32…", 30 / 32)
    assert window.progress[-1] == ("", None)
    assert window.sources == [] and not window.closed


def test_cached_pdf_updates_header_to_say_from_cache(monkeypatch, tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-x")
    monkeypatch.setattr(app, "resolve_source", lambda c: FileSource(f))
    monkeypatch.setattr(app, "iter_pdf_blocks",
                        lambda data: iter([PdfChunk(1, 40, 40, [Block("paragraph", "All of it.")], True)]))
    window = FakeWindow()
    monkeypatch.setattr(app, "open_document", lambda doc: window)
    run_read_pass(Candidate(1, "t", 2, "c"))
    assert window.sources == [f"{f} — read by Claude (claude-opus-5-5), from cache"]
    assert window.appended == [[Block("paragraph", "All of it.")]]


def test_capture_opens_window_first_then_fills_it(monkeypatch):
    monkeypatch.setattr(app, "resolve_source", lambda c: CaptureSource(7, "Some Page"))
    monkeypatch.setattr(app, "capture_window", lambda h: ("IMG", "screen"))
    monkeypatch.setattr(app, "cached_pdf_for_screen", lambda lines: None)
    calls = []
    screen = _doc("LINE", source="captured — read by Claude (x)")
    monkeypatch.setattr(app, "read_image", lambda img, title, label: calls.append((img, title, label)) or screen)
    window = FakeWindow()
    opened = []
    monkeypatch.setattr(app, "open_document", lambda doc: opened.append(doc) or window)
    run_read_pass(Candidate(7, "Some Page", 2, "c"))
    label = "captured from window: Some Page — only what was visible on screen (screen region capture)"
    assert calls == [("IMG", "Some Page", label)]
    assert opened[0].blocks == [] and opened[0].via_ocr is True and opened[0].title == "Some Page"
    assert opened[0].source_label.startswith(label)
    assert window.appended == [[Block("paragraph", "LINE")]]
    assert window.sources == ["captured — read by Claude (x)"]
    assert window.progress[0] == ("Reading with Claude…", None) and window.progress[-1] == ("", None)


def test_capture_matching_cached_pdf_swaps_to_the_full_document(monkeypatch):
    monkeypatch.setattr(app, "resolve_source", lambda c: CaptureSource(7, "Course Page"))
    monkeypatch.setattr(app, "capture_window", lambda h: ("IMG", "window"))
    monkeypatch.setattr(app, "read_image", lambda img, title, label: _doc("LINE"))
    seen = []
    monkeypatch.setattr(app, "cached_pdf_for_screen",
                        lambda lines: seen.append(lines) or (b"%PDF-data", "2025 Publication 17"))
    monkeypatch.setattr(app, "iter_pdf_blocks",
                        lambda data: iter([PdfChunk(1, 1, 1, [Block("paragraph", "Full.")], False)]))
    windows = []
    monkeypatch.setattr(app, "open_document", lambda doc: windows.append((doc, FakeWindow())) or windows[-1][1])
    run_read_pass(Candidate(7, "Course Page", 2, "c"))
    assert seen == [["LINE"]]
    capture_doc, capture_window = windows[0]
    pdf_doc, pdf_window = windows[1]
    assert capture_window.closed and capture_window.appended == []  # the screen text never shows
    assert pdf_doc.title == "2025 Publication 17" and pdf_window.appended == [[Block("paragraph", "Full.")]]
    assert pdf_doc.source_label.startswith(
        "2025 Publication 17 — full document from the browser cache, matched to the page on screen")


def test_failed_chunk_marks_open_window_and_reraises(monkeypatch, tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-x")
    monkeypatch.setattr(app, "resolve_source", lambda c: FileSource(f))

    def chunks(data):
        yield PdfChunk(1, 6, 30, [Block("heading", "Title", 1)], False)
        raise UserFacingError("The Claude API rate limit was hit.")

    monkeypatch.setattr(app, "iter_pdf_blocks", chunks)
    window = FakeWindow()
    monkeypatch.setattr(app, "open_document", lambda doc: window)
    with pytest.raises(UserFacingError, match="rate limit"):
        run_read_pass(Candidate(1, "t", 2, "c"))
    assert window.progress[-1] == ("Reading stopped after page 6 of 30: The Claude API rate limit was hit.", 6 / 30)
    assert not window.closed


def test_pdf_with_no_text_closes_the_empty_window_and_raises(monkeypatch, tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-x")
    monkeypatch.setattr(app, "resolve_source", lambda c: FileSource(f))
    monkeypatch.setattr(app, "iter_pdf_blocks", lambda data: iter([PdfChunk(1, 1, 1, [], False)]))
    window = FakeWindow()
    monkeypatch.setattr(app, "open_document", lambda doc: window)
    with pytest.raises(UserFacingError, match="No readable text"):
        run_read_pass(Candidate(1, "t", 2, "c"))
    assert window.closed


def test_failed_image_read_closes_the_empty_window_and_reraises(monkeypatch):
    monkeypatch.setattr(app, "resolve_source", lambda c: CaptureSource(7, "Some Page"))
    monkeypatch.setattr(app, "capture_window", lambda h: ("IMG", "window"))
    monkeypatch.setattr(app, "read_image", lambda img, title, label: _raise(UserFacingError("Nope")))
    window = FakeWindow()
    monkeypatch.setattr(app, "open_document", lambda doc: window)
    with pytest.raises(UserFacingError, match="Nope"):
        run_read_pass(Candidate(7, "Some Page", 2, "c"))
    assert window.closed


def test_safe_read_pass_shows_user_facing_error(monkeypatch):
    shown = []
    monkeypatch.setattr(app, "show_error", lambda m, title="": shown.append(m))
    monkeypatch.setattr(app, "run_read_pass", lambda c: _raise(UserFacingError("Nope")))
    safe_read_pass(None)
    assert shown == ["Nope"]


def test_safe_read_pass_logs_unexpected_error(monkeypatch):
    shown = []
    logged = []
    monkeypatch.setattr(app, "show_error", lambda m, title="": shown.append(m))
    monkeypatch.setattr(app, "log_exception", logged.append)
    monkeypatch.setattr(app, "run_read_pass", lambda c: 1 / 0)
    safe_read_pass(None)
    assert shown[0].startswith("Something went wrong: ZeroDivisionError") and len(logged) == 1
