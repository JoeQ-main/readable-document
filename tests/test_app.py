import pytest

from pdf_helper import app
from pdf_helper.app import run_read_pass, safe_read_pass
from pdf_helper.errors import UserFacingError
from pdf_helper.window_finder import Candidate, CaptureSource, FileSource


def _raise(exc):
    raise exc


from pdf_helper.extract.model import Block, Document


def _doc(*texts):
    return Document("t", "s", [Block("paragraph", t) for t in texts], True)


class FakeWindow:
    def __init__(self):
        self.appended = []
        self.progress = []

    def append(self, blocks):
        self.appended.append(blocks)

    def set_progress(self, text):
        self.progress.append(text)


def test_run_read_pass_streams_pdf_chunks_into_one_window(monkeypatch, tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-x")
    monkeypatch.setattr(app, "resolve_source", lambda c: FileSource(f))
    seen = []

    def chunks(data):
        seen.append(data)
        yield 1, 15, 32, [Block("heading", "Title", 1), Block("paragraph", "ends mid")]
        yield 16, 30, 32, [Block("paragraph", "sentence here."), Block("paragraph", "Second.")]
        yield 31, 32, 32, [Block("paragraph", "Last.")]

    monkeypatch.setattr(app, "iter_pdf_blocks", chunks)
    window = FakeWindow()
    opened = []
    monkeypatch.setattr(app, "open_document", lambda doc: opened.append(doc) or window)
    run_read_pass(Candidate(1, "t", 2, "c"))
    assert seen == [b"%PDF-x"]
    assert opened[0].title == "a" and opened[0].blocks == [Block("heading", "Title", 1)]
    assert window.appended == [
        [Block("paragraph", "ends mid sentence here.")],
        [Block("paragraph", "Second.")],
        [Block("paragraph", "Last.")],
    ]
    assert window.progress[0] == "Read pages 1–15 of 32…" and window.progress[-1] == ""


def test_run_read_pass_pdf_with_no_text_is_user_facing(monkeypatch, tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-x")
    monkeypatch.setattr(app, "resolve_source", lambda c: FileSource(f))
    monkeypatch.setattr(app, "iter_pdf_blocks", lambda data: iter([(1, 1, 1, [])]))
    monkeypatch.setattr(app, "open_document", lambda doc: FakeWindow())
    with pytest.raises(UserFacingError, match="No readable text"):
        run_read_pass(Candidate(1, "t", 2, "c"))


def test_run_read_pass_routes_capture_with_label(monkeypatch):
    monkeypatch.setattr(app, "resolve_source", lambda c: CaptureSource(7, "Some Page"))
    monkeypatch.setattr(app, "capture_window", lambda h: ("IMG", "screen"))
    monkeypatch.setattr(app, "cached_pdf_for_screen", lambda lines: None)
    calls = []
    screen = _doc("LINE")
    monkeypatch.setattr(app, "read_image", lambda img, title, label: calls.append((img, title, label)) or screen)
    opened = []
    monkeypatch.setattr(app, "open_document", opened.append)
    run_read_pass(Candidate(7, "Some Page", 2, "c"))
    assert calls == [(
        "IMG", "Some Page",
        "captured from window: Some Page — only what was visible on screen (screen region capture)",
    )]
    assert opened == [screen]


def test_run_read_pass_prefers_cached_pdf_matching_the_screen(monkeypatch):
    monkeypatch.setattr(app, "resolve_source", lambda c: CaptureSource(7, "Course Page"))
    monkeypatch.setattr(app, "capture_window", lambda h: ("IMG", "window"))
    monkeypatch.setattr(app, "read_image", lambda img, title, label: _doc("LINE"))
    seen = []
    monkeypatch.setattr(app, "cached_pdf_for_screen", lambda lines: seen.append(lines) or (b"%PDF-data", "2025 Publication 17"))
    monkeypatch.setattr(app, "iter_pdf_blocks", lambda data: iter([(1, 1, 1, [Block("paragraph", "Full.")])]))
    opened = []
    monkeypatch.setattr(app, "open_document", lambda doc: opened.append(doc) or FakeWindow())
    run_read_pass(Candidate(7, "Course Page", 2, "c"))
    assert seen == [["LINE"]] and len(opened) == 1
    assert opened[0].title == "2025 Publication 17" and opened[0].blocks == [Block("paragraph", "Full.")]
    assert opened[0].source_label.startswith(
        "2025 Publication 17 — full document from the browser cache, matched to the page on screen")


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
