from pdf_helper.settings import DEFAULTS, load_prefs, save_prefs


def test_missing_file_returns_defaults(tmp_path):
    assert load_prefs(tmp_path / "none.json") == DEFAULTS


def test_corrupt_json_returns_defaults(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json")
    assert load_prefs(p) == DEFAULTS


def test_wrong_types_fall_back_per_key(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"size": "big", "dark": true, "bogus": 1}')
    prefs = load_prefs(p)
    assert prefs["size"] == 19 and prefs["dark"] is True and "bogus" not in prefs


def test_round_trip(tmp_path):
    p = tmp_path / "s.json"
    save_prefs({"size": 22, "bionic": True}, p)
    prefs = load_prefs(p)
    assert prefs["size"] == 22 and prefs["bionic"] is True and prefs["leading"] == 1.75
