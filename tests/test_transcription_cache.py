import json
import os

from pdf_helper import transcription_cache as cache
from pdf_helper.extract.model import Block

BLOCKS = [Block("heading", "Intro", 1), Block("paragraph", "Body text."), Block("list_item", "one")]


def test_key_changes_with_data_model_and_tags():
    base = cache.key(b"pdf bytes", "pdf", "claude-opus-5-5", "4")
    assert len(base) == 64 and all(c in "0123456789abcdef" for c in base)
    assert cache.key(b"pdf bytes", "pdf", "claude-opus-5-5", "4") == base
    assert cache.key(b"other bytes", "pdf", "claude-opus-5-5", "4") != base
    assert cache.key(b"pdf bytes", "pdf", "claude-sonnet-5-5", "4") != base
    assert cache.key(b"pdf bytes", "pdf", "claude-opus-5-5", "6") != base
    # tags are delimited, so shifting characters between them changes the key
    assert cache.key(b"x", "ab", "c") != cache.key(b"x", "a", "bc")


def test_put_then_get_round_trips_blocks(tmp_path):
    key = cache.key(b"doc", "pdf")
    assert cache.get(key, directory=tmp_path) is None
    cache.put(key, BLOCKS, title="Report", model="claude-opus-5-5", directory=tmp_path)
    assert cache.get(key, directory=tmp_path) == BLOCKS
    stored = json.loads((tmp_path / f"{key}.json").read_text(encoding="utf-8"))
    assert stored["model"] == "claude-opus-5-5" and stored["title"] == "Report" and stored["created"]
    assert stored["blocks"][0] == {"kind": "heading", "level": 1, "text": "Intro"}


def test_get_ignores_corrupt_or_foreign_entries(tmp_path):
    key = cache.key(b"doc", "pdf")
    (tmp_path / f"{key}.json").write_text("{not json", encoding="utf-8")
    assert cache.get(key, directory=tmp_path) is None
    (tmp_path / f"{key}.json").write_text(json.dumps({"blocks": [{"kind": "poem", "level": 0, "text": "x"}]}))
    assert cache.get(key, directory=tmp_path) is None
    assert cache.get("../../etc/passwd", directory=tmp_path) is None


def test_get_marks_entry_as_recently_used(tmp_path):
    key = cache.key(b"doc", "pdf")
    cache.put(key, BLOCKS, "t", "m", directory=tmp_path)
    path = tmp_path / f"{key}.json"
    os.utime(path, (1_000, 1_000))
    cache.get(key, directory=tmp_path)
    assert path.stat().st_mtime > 1_000


def test_put_prunes_oldest_entries_beyond_the_size_cap(tmp_path):
    big = [Block("paragraph", "x" * 1000)]
    keys = [cache.key(bytes([i]), "pdf") for i in range(5)]
    for i, k in enumerate(keys):
        cache.put(k, big, "t", "m", directory=tmp_path, max_bytes=3_500)
        os.utime(tmp_path / f"{k}.json", (1_000 + i, 1_000 + i))
    cache.put(cache.key(b"new", "pdf"), big, "t", "m", directory=tmp_path, max_bytes=3_500)
    remaining = sorted(p.name for p in tmp_path.glob("*.json"))
    # each entry is a little over 1 KB, so a 3.5 KB cap keeps the three newest
    assert len(remaining) == 3
    assert f"{keys[0]}.json" not in remaining and f"{keys[1]}.json" not in remaining
    assert f"{keys[4]}.json" in remaining and f"{cache.key(b'new', 'pdf')}.json" in remaining


def test_clear_removes_everything_and_reports_bytes_freed(tmp_path):
    cache.put(cache.key(b"a", "pdf"), BLOCKS, "t", "m", directory=tmp_path)
    cache.put(cache.key(b"b", "pdf"), BLOCKS, "t", "m", directory=tmp_path)
    (tmp_path / "stray.tmp").write_bytes(b"12345")
    expected = sum(p.stat().st_size for p in tmp_path.iterdir())
    assert cache.clear(directory=tmp_path) == expected
    assert list(tmp_path.iterdir()) == []
    assert cache.clear(directory=tmp_path) == 0
    assert cache.clear(directory=tmp_path / "missing") == 0


def test_describe_size():
    assert cache.describe_size(0) == "0 bytes"
    assert cache.describe_size(532) == "532 bytes"
    assert cache.describe_size(1536) == "1.5 KB"
    assert cache.describe_size(12 * 1024 * 1024) == "12.0 MB"


def test_default_directory_is_under_app_data(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert cache.cache_dir() == tmp_path / "PDFHelper" / "cache"
    assert cache.cache_dir().is_dir()
