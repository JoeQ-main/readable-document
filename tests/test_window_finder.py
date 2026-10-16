import os

import pytest

from pdf_helper.errors import UserFacingError
from pdf_helper.window_finder import (
    Candidate,
    CaptureSource,
    FileSource,
    default_search_dirs,
    document_title_from_window_title,
    filename_candidates,
    filename_from_title,
    find_file_by_name,
    find_pdf_by_metadata_title,
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
        # Firefox titles a web PDF "<document title> - <filename> \u2014 Mozilla Firefox".
        ("Treasury Department Circular No. 230 (Rev. 6-2014) - pcir230.pdf \u2014 Mozilla Firefox", "pcir230.pdf"),
        ("2025 Publication 17 - p17--2025.pdf \u2014 Mozilla Firefox", "p17--2025.pdf"),
    ],
)
def test_filename_from_title(title, expected):
    assert filename_from_title(title) == expected


def test_filename_candidates_prefer_the_part_after_the_last_separator():
    # A filename may itself contain " - ", so the longer reading is kept as a second candidate.
    assert filename_candidates("Quarterly Report - Final.pdf - Google Chrome") == ["Final.pdf", "Quarterly Report - Final.pdf"]
    assert filename_candidates("report.pdf - Adobe Acrobat") == ["report.pdf"]
    assert filename_candidates("Inbox - Mail") == []


def test_resolve_source_tries_the_longer_filename_too(tmp_path):
    f = tmp_path / "Quarterly Report - Final.pdf"
    f.write_bytes(b"x")
    c = Candidate(1, "Quarterly Report - Final.pdf - Google Chrome", 42, "Chrome_WidgetWin_1")
    assert resolve_source(c, cmdline=lambda pid: ["chrome.exe"], recent_dir=tmp_path / "none",
                          search_dirs=[tmp_path]) == FileSource(f)


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
    # Title names a different file than the command line: the title is what the user sees.
    assert resolve_source(
        c, cmdline=lambda pid: ["viewer.exe", str(g)], recent_dir=tmp_path / "none", search_dirs=[tmp_path]
    ) == FileSource(f)
    # Title names no file at all: the command-line file is used.
    untitled = Candidate(1, "Document viewer", 42, "X")
    assert resolve_source(
        untitled, cmdline=lambda pid: ["viewer.exe", str(g)], recent_dir=tmp_path / "none", search_dirs=[]
    ) == FileSource(g)


def test_resolve_source_ignores_stale_browser_cmdline(tmp_path):
    # Edge keeps "msedge.exe --single-argument a.pdf" for its whole life; b.pdf is in front now.
    a = tmp_path / "a.pdf"
    a.write_bytes(b"x")
    b = tmp_path / "b.pdf"
    b.write_bytes(b"x")
    c = Candidate(1, "b.pdf - Microsoft Edge", 42, "Chrome_WidgetWin_1")
    cmd = lambda pid: ["msedge.exe", "--single-argument", str(a)]  # noqa: E731
    assert resolve_source(c, cmdline=cmd, recent_dir=tmp_path / "none", search_dirs=[tmp_path]) == FileSource(b)
    # b.pdf cannot be found anywhere: capture what is on screen rather than read a.pdf.
    assert resolve_source(c, cmdline=cmd, recent_dir=tmp_path / "none", search_dirs=[]) == CaptureSource(
        1, "b.pdf - Microsoft Edge"
    )
    # The command line names the same file the title shows: use it directly, no search needed.
    same = Candidate(1, "a.pdf - Microsoft Edge", 42, "Chrome_WidgetWin_1")
    assert resolve_source(same, cmdline=cmd, recent_dir=tmp_path / "none", search_dirs=[]) == FileSource(a)


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Income Tax Course Self-Study Content — Mozilla Firefox", "Income Tax Course Self-Study Content"),
        ("Annual Report 2025 - Google Chrome", "Annual Report 2025"),
        ("Annual Report 2025 and 3 more pages - Personal - Microsoft Edge", "Annual Report 2025"),
        ("Annual Report 2025 - Microsoft​ Edge", "Annual Report 2025"),
        ("report.pdf - SumatraPDF", "report.pdf - SumatraPDF"),
        ("", ""),
    ],
)
def test_document_title_from_window_title(title, expected):
    assert document_title_from_window_title(title) == expected


def _make_pdf(path, title):
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "body text", fontsize=11)
    doc.set_metadata({"title": title})
    doc.save(str(path))
    doc.close()


def test_find_pdf_by_metadata_title_matches_newest(tmp_path):
    docs = tmp_path / "Documents"
    (docs / "sub").mkdir(parents=True)
    old = docs / "old.pdf"
    _make_pdf(old, "Income Tax Course  Self-Study Content")  # extra space: normalised away
    new = docs / "sub" / "course.pdf"
    _make_pdf(new, "income tax course self-study content")
    other = docs / "other.pdf"
    _make_pdf(other, "Something Else")
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))
    recent = tmp_path / "recent"
    assert find_pdf_by_metadata_title("Income Tax Course Self-Study Content", recent, [docs]) == new
    assert find_pdf_by_metadata_title("Not A Title", recent, [docs]) is None
    assert find_pdf_by_metadata_title("ab", recent, [docs]) is None  # too short to trust


def test_resolve_source_uses_metadata_title_when_title_has_no_filename(tmp_path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    pdf = docs / "course.pdf"
    _make_pdf(pdf, "Income Tax Course Self-Study Content")
    c = Candidate(1, "Income Tax Course Self-Study Content — Mozilla Firefox", 42, "MozillaWindowClass")
    assert resolve_source(
        c, cmdline=lambda pid: ["firefox.exe"], recent_dir=tmp_path / "none", search_dirs=[docs]
    ) == FileSource(pdf)
    assert resolve_source(
        c, cmdline=lambda pid: ["firefox.exe"], recent_dir=tmp_path / "none", search_dirs=[]
    ) == CaptureSource(1, c.title)


def test_resolve_source_matches_metadata_title_when_titled_filename_is_not_on_disk(tmp_path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    _make_pdf(docs / "saved-copy.pdf", "Treasury Department Circular No. 230 (Rev. 6-2014)")
    c = Candidate(1, "Treasury Department Circular No. 230 (Rev. 6-2014) - pcir230.pdf — Mozilla Firefox",
                  42, "MozillaWindowClass")
    assert resolve_source(c, cmdline=lambda pid: ["firefox.exe"], recent_dir=tmp_path / "none",
                          search_dirs=[docs]) == FileSource(docs / "saved-copy.pdf")


def test_default_search_dirs_are_real_known_folders():
    dirs = default_search_dirs()
    assert len(dirs) == 3 and all(d.is_dir() for d in dirs)
    assert [d.name.lower() for d in dirs] == ["downloads", "desktop", "documents"]


def test_resolve_source_without_candidate_raises():
    with pytest.raises(UserFacingError, match="No document window"):
        resolve_source(None)
