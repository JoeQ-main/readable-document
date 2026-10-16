import pytest

from pdf_helper import viewer
from pdf_helper.viewer import Api, safe_filename


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
