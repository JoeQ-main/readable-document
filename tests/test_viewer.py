import urllib.error
import urllib.request

import json
from types import SimpleNamespace

import pytest

from pdf_helper import viewer
from pdf_helper.extract.model import Block
from pdf_helper.viewer import Api, PageServer, ReadingWindow, safe_filename


def test_reading_window_appends_rendered_blocks_with_continuing_heading_ids():
    calls = []
    fake = SimpleNamespace(evaluate_js=lambda js: calls.append(js))
    window = ReadingWindow(fake, heading_count=2)
    window.append([Block("heading", "More", 2), Block("paragraph", "Text here."), Block("list_item", "i")])
    assert len(calls) == 1 and calls[0].startswith("appendContent(")
    body, outline = json.loads("[" + calls[0][len("appendContent("):-1] + "]")
    assert '<h2 id="more-2">More</h2>' in body and "<ul><li>i</li></ul>" in body.replace("\n", "")
    assert '<a href="#more-2">More</a>' in outline
    assert window.heading_count == 3


def test_reading_window_sets_progress_text():
    calls = []
    window = ReadingWindow(SimpleNamespace(evaluate_js=lambda js: calls.append(js)))
    window.set_progress("Read pages 1–15 of 142…")
    assert calls == ['setProgress("Read pages 1\\u201315 of 142\\u2026")']
    window.set_progress("")
    assert calls[-1] == 'setProgress("")'


def test_page_server_serves_html_from_memory_by_token():
    server = PageServer()
    try:
        big = "<html><body>" + ("x" * 3_000_000) + "</body></html>"  # above WebView2's 2 MB html= limit
        url = server.publish(big)
        assert url.startswith("http://127.0.0.1:")
        with urllib.request.urlopen(url) as resp:
            assert resp.headers["Content-Type"].startswith("text/html")
            assert resp.read().decode("utf-8") == big
        server.release(url)
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(url)
        assert err.value.code == 404
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(url.rsplit("/", 1)[0] + "/not-a-token")
    finally:
        server.close()


@pytest.mark.parametrize(
    "title,expected",
    [
        ("report", "report-readable.html"),
        ('Q3: plan? <draft> "final"/v2|x*', "Q3_ plan_ _draft_ _final__v2_x_-readable.html"),
        ("   ", "document-readable.html"),
    ],
)
def test_safe_filename(title, expected):
    assert safe_filename(title) == expected


def test_api_exposes_only_methods_to_the_js_bridge(sample_doc):
    # pywebview serializes every public attribute of js_api; a native window there recurses forever.
    api = Api(sample_doc, dialog=lambda d, n: None)
    public = [name for name in dir(api) if not name.startswith("_")]
    assert public and all(callable(getattr(api, name)) for name in public)


def test_api_save_writes_html_to_chosen_path(tmp_path, sample_doc):
    chosen = tmp_path / "out.html"
    api = Api(sample_doc, dialog=lambda d, name: chosen)
    assert api.save("<html>x</html>") == str(chosen)
    assert chosen.read_text(encoding="utf-8") == "<html>x</html>"


def test_api_save_cancelled_returns_none(tmp_path, sample_doc):
    api = Api(sample_doc, dialog=lambda d, name: None)
    assert api.save("<html>x</html>") is None


def test_api_prefs_round_trip(tmp_path, sample_doc, monkeypatch):
    monkeypatch.setattr(viewer, "settings_path", lambda: tmp_path / "s.json")
    api = Api(sample_doc, dialog=lambda d, n: None)
    assert api.set_prefs({"dark": True})["dark"] is True
    assert api.get_prefs()["dark"] is True
