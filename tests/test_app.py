from pdf_helper import app
from pdf_helper.app import run_read_pass, safe_read_pass
from pdf_helper.errors import UserFacingError
from pdf_helper.window_finder import Candidate, CaptureSource, FileSource


def _raise(exc):
    raise exc


def test_run_read_pass_routes_pdf(monkeypatch, tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")
    monkeypatch.setattr(app, "resolve_source", lambda c: FileSource(f))
    monkeypatch.setattr(app, "extract_pdf", lambda p: "DOC")
    opened = []
    monkeypatch.setattr(app, "open_document", opened.append)
    run_read_pass(Candidate(1, "t", 2, "c"))
    assert opened == ["DOC"]


def test_run_read_pass_routes_capture_with_label(monkeypatch):
    monkeypatch.setattr(app, "resolve_source", lambda c: CaptureSource(7, "Some Page"))
    monkeypatch.setattr(app, "capture_window", lambda h: ("IMG", "screen"))
    monkeypatch.setattr(app, "recognize_image", lambda img: ["LINE"])
    monkeypatch.setattr(app, "cached_pdf_for_screen", lambda lines: None)
    calls = []
    monkeypatch.setattr(app, "document_from_lines", lambda lines, title, label: calls.append((lines, title, label)) or "DOC")
    monkeypatch.setattr(app, "open_document", lambda d: None)
    run_read_pass(Candidate(7, "Some Page", 2, "c"))
    assert calls == [(
        ["LINE"], "Some Page",
        "captured from window: Some Page — only what was visible on screen (screen region capture)",
    )]


def test_run_read_pass_prefers_cached_pdf_matching_the_screen(monkeypatch):
    monkeypatch.setattr(app, "resolve_source", lambda c: CaptureSource(7, "Course Page"))
    monkeypatch.setattr(app, "capture_window", lambda h: ("IMG", "window"))
    monkeypatch.setattr(app, "recognize_image", lambda img: ["LINE"])
    monkeypatch.setattr(app, "cached_pdf_for_screen", lambda lines: (b"%PDF-data", "2025 Publication 17"))
    calls = []
    monkeypatch.setattr(app, "extract_pdf_bytes", lambda data, title, label: calls.append((data, title, label)) or "DOC")
    opened = []
    monkeypatch.setattr(app, "open_document", opened.append)
    run_read_pass(Candidate(7, "Course Page", 2, "c"))
    assert opened == ["DOC"]
    assert calls == [(b"%PDF-data", "2025 Publication 17",
                      "2025 Publication 17 — full document from the browser cache, matched to the page on screen")]


def test_run_read_pass_falls_back_to_ocr_when_no_cached_pdf(monkeypatch):
    monkeypatch.setattr(app, "resolve_source", lambda c: CaptureSource(7, "Some Page"))
    monkeypatch.setattr(app, "capture_window", lambda h: ("IMG", "window"))
    monkeypatch.setattr(app, "recognize_image", lambda img: ["LINE"])
    monkeypatch.setattr(app, "cached_pdf_for_screen", lambda lines: None)
    calls = []
    monkeypatch.setattr(app, "document_from_lines", lambda lines, title, label: calls.append((lines, title, label)) or "DOC")
    monkeypatch.setattr(app, "open_document", lambda d: None)
    run_read_pass(Candidate(7, "Some Page", 2, "c"))
    assert calls == [(["LINE"], "Some Page", "captured from window: Some Page — only what was visible on screen")]


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
