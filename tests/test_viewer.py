import urllib.error
import urllib.request

import pytest

from pdf_helper import viewer
from pdf_helper.viewer import Api, PageServer, safe_filename


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
