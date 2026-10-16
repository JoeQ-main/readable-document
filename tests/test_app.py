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
    calls = []
    monkeypatch.setattr(app, "extract_ocr", lambda img, title, label: calls.append((img, title, label)) or "DOC")
    monkeypatch.setattr(app, "open_document", lambda d: None)
    run_read_pass(Candidate(7, "Some Page", 2, "c"))
    assert calls == [("IMG", "Some Page", "captured from window: Some Page (screen region capture)")]


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
