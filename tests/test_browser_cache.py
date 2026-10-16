import os

import pymupdf

from pdf_helper.browser_cache import (
    CachedPdf,
    cached_pdfs,
    find_matching_pdf,
    match_score,
    normalize_text,
)


def make_pdf_bytes(lines, title="Doc"):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 14
    doc.set_metadata({"title": title})
    data = doc.tobytes()
    doc.close()
    return data


PUB_LINES = [
    "Your Federal Income Tax for individuals is explained in this publication.",
    "The standard deduction amount depends on your filing status.",
    "You must file a return if your gross income exceeds the threshold.",
    "Chapter three covers dependents and who qualifies as one.",
]
OTHER_LINES = [
    "This unrelated manual describes how to assemble the bookshelf.",
    "Tighten all screws before attaching the back panel.",
]


def test_normalize_text_collapses_case_punctuation_and_whitespace():
    assert normalize_text("  The Standard   Deduction, amount!\n") == "the standard deduction amount"


def test_match_score_counts_long_ocr_lines_found_in_text():
    text = normalize_text(" ".join(PUB_LINES))
    screen = [
        "Your Federal Income Tax for individuals is explained",  # found
        "The standard deduction amount depends on your filing status.",  # found
        "File Edit View",  # too short to count
        "Totally different words that are not in the document at all",  # not found
    ]
    assert match_score(screen, text) == (2, 3)  # (matched, eligible)


def test_find_matching_pdf_picks_the_document_on_screen():
    pub = CachedPdf(make_pdf_bytes(PUB_LINES, "2025 Publication 17"), mtime=2.0, origin="a")
    other = CachedPdf(make_pdf_bytes(OTHER_LINES, "Bookshelf"), mtime=3.0, origin="b")
    screen = [
        "Your Federal Income Tax for individuals is explained in this",
        "The standard deduction amount depends on your filing status.",
        "You must file a return if your gross income exceeds the",
        "Bookmarks Gmail YouTube Maps",
    ]
    assert find_matching_pdf(screen, [other, pub]) is pub
    assert find_matching_pdf(["Nothing here matches anything at all today"], [other, pub]) is None
    assert find_matching_pdf(screen, []) is None


def test_cached_pdfs_reads_newest_pdf_entries_only(tmp_path):
    entries = tmp_path / "cache2" / "entries"
    entries.mkdir(parents=True)
    pdf_a = entries / "AAAA"
    pdf_a.write_bytes(make_pdf_bytes(PUB_LINES) + b"\x00metadata-tail")  # cache2 appends metadata
    pdf_b = entries / "BBBB"
    pdf_b.write_bytes(make_pdf_bytes(OTHER_LINES))
    (entries / "CCCC").write_bytes(b"<html>not a pdf</html>" * 100)
    (entries / "DDDD").write_bytes(b"%PDF-tiny")  # below the size floor
    os.utime(pdf_a, (10, 10))
    os.utime(pdf_b, (20, 20))
    found = cached_pdfs(cache_dirs=[entries], min_bytes=1000)
    assert [c.mtime for c in found] == [20, 10]
    assert all(c.data.startswith(b"%PDF-") for c in found)
    assert cached_pdfs(cache_dirs=[tmp_path / "missing"]) == []
