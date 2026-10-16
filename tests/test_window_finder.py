import os

import pytest

from pdf_helper.errors import UserFacingError
from pdf_helper.window_finder import (
    Candidate,
    CaptureSource,
    FileSource,
    filename_from_title,
    find_file_by_name,
    path_from_cmdline,
    resolve_source,
)


@pytest.mark.parametrize(
    "title,expected",
    [
        ("report.pdf - Adobe Acrobat", "report.pdf"),
        ("my.report.v2.pdf - Microsoft Edge", "my.report.v2.pdf"),
        ("REPORT.PDF", "REPORT.PDF"),
        (r"C:\Users\x\report.pdf - SumatraPDF", "report.pdf"),
        ("scan.jpeg \u2013 Photos", "scan.jpeg"),
        ("Inbox - Mail", None),
        ("notes.pdfx - Editor", None),
    ],
)
def test_filename_from_title(title, expected):
    assert filename_from_title(title) == expected


def test_path_from_cmdline_picks_existing_supported_file(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF")
    assert path_from_cmdline(["viewer.exe", "-flag", str(tmp_path / "missing.pdf"), str(f)]) == f
    assert path_from_cmdline(["viewer.exe", str(tmp_path)]) is None


def test_find_file_by_name_prefers_newest_and_searches_depth_two(tmp_path):
    recent = tmp_path / "recent"
    recent.mkdir()
    dl = tmp_path / "Downloads"
    (dl / "a" / "b" / "c").mkdir(parents=True)
    old = dl / "a" / "report.pdf"
    old.write_bytes(b"1")
    new = dl / "a" / "b" / "report.pdf"
    new.write_bytes(b"2")
    deep = dl / "a" / "b" / "c" / "report.pdf"
    deep.write_bytes(b"3")
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))
    os.utime(deep, (3, 3))
    assert find_file_by_name("report.pdf", recent, [dl], resolve_link=lambda p: None) == new


def test_find_file_by_name_uses_recent_links(tmp_path):
    recent = tmp_path / "recent"
    recent.mkdir()
    (recent / "report.pdf.lnk").write_bytes(b"")
    target = tmp_path / "elsewhere" / "Report.PDF"
    target.parent.mkdir()
    target.write_bytes(b"x")
    assert find_file_by_name("report.pdf", recent, [], resolve_link=lambda p: target) == target


def test_resolve_source_order(tmp_path):
    c = Candidate(1, "report.pdf - Edge", 42, "Chrome_WidgetWin_1")
    f = tmp_path / "report.pdf"
    f.write_bytes(b"x")
    assert resolve_source(
        c, cmdline=lambda pid: ["msedge.exe"], recent_dir=tmp_path / "none", search_dirs=[tmp_path]
    ) == FileSource(f)
    assert resolve_source(
        c, cmdline=lambda pid: ["msedge.exe"], recent_dir=tmp_path / "none", search_dirs=[]
    ) == CaptureSource(1, "report.pdf - Edge")
    g = tmp_path / "other.pdf"
    g.write_bytes(b"x")
    assert resolve_source(
        c, cmdline=lambda pid: ["viewer.exe", str(g)], recent_dir=tmp_path / "none", search_dirs=[tmp_path]
    ) == FileSource(g)


def test_resolve_source_without_candidate_raises():
    with pytest.raises(UserFacingError, match="No document window"):
        resolve_source(None)
