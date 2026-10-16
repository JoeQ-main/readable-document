from pdf_helper.extract.layout import group_lines, merge_paragraph_runs, strip_list_marker
from pdf_helper.extract.model import Block
from tests.helpers import L


def test_empty_input():
    assert group_lines([]) == []


def test_single_line_is_paragraph():
    assert group_lines([L("Just one line.", 0)]) == [Block("paragraph", "Just one line.")]


def test_close_lines_merge_into_paragraph():
    # gap 2 < 0.6*10
    blocks = group_lines([L("First part", 0), L("second part.", 12)])
    assert blocks == [Block("paragraph", "First part second part.")]


def test_wide_gap_splits_paragraphs():
    blocks = group_lines([L("One.", 0), L("Two.", 30)])
    assert [b.text for b in blocks] == ["One.", "Two."]


def test_hyphen_join():
    blocks = group_lines([L("exam-", 0), L("ple text", 12)])
    assert blocks[0].text == "example text"


def test_pdf_heading_by_size():
    blocks = group_lines([L("Title", 0, size=20), L("Body text here.", 30, size=10)], body_size=10)
    assert blocks[0] == Block("heading", "Title", 1)  # 20 >= 1.6*10
    blocks = group_lines([L("Sub", 0, size=14), L("Body.", 30, size=10)], body_size=10)
    assert blocks[0].level == 2  # 14 >= 1.3*10
    blocks = group_lines([L("Minor", 0, size=11.5), L("Body.", 30, size=10)], body_size=10)
    assert blocks[0].level == 3  # 11.5 >= 1.15*10


def test_pdf_bold_short_line_followed_by_gap_is_heading():
    blocks = group_lines([L("Bold lead", 0, size=10, bold=True), L("Body.", 30, size=10)], body_size=10)
    assert blocks[0].kind == "heading" and blocks[0].level == 3


def test_pdf_bold_line_without_gap_is_not_heading():
    blocks = group_lines([L("Bold lead", 0, size=10, bold=True), L("continues.", 12, size=10)], body_size=10)
    assert blocks[0].kind == "paragraph"


def test_pdf_long_large_line_is_not_heading():
    blocks = group_lines([L("x" * 121, 0, size=20), L("Body.", 40, size=10)], body_size=10)
    assert blocks[0].kind == "paragraph"


def test_ocr_heading_by_height():
    blocks = group_lines([L("Big", 0, h=14), L("normal", 30), L("normal", 42), L("normal", 54)])
    assert blocks[0] == Block("heading", "Big", 2)  # 14 >= 1.3*10, < 1.6*10


def test_ocr_all_caps_short_line_is_heading():
    blocks = group_lines([L("SECTION TWO", 0), L("normal text", 30)])
    assert blocks[0] == Block("heading", "SECTION TWO", 3)


def test_list_items():
    assert strip_list_marker("• apples") == "apples"
    assert strip_list_marker("1. apples") == "apples"
    assert strip_list_marker("a) apples") == "apples"
    assert strip_list_marker("o apples") == "apples"
    assert strip_list_marker(" apples") == "apples"  # Symbol-font bullet from Word PDFs
    assert strip_list_marker("-apples") is None
    assert strip_list_marker("plain") is None
    blocks = group_lines([L("• one", 0), L("• two", 12)])
    assert blocks == [Block("list_item", "one"), Block("list_item", "two")]


def test_merge_paragraph_runs_joins_lowercase_continuation():
    g1 = [Block("paragraph", "ends mid")]
    g2 = [Block("paragraph", "sentence here."), Block("heading", "Next", 1)]
    assert merge_paragraph_runs([g1, g2]) == [
        Block("paragraph", "ends mid sentence here."),
        Block("heading", "Next", 1),
    ]


def test_merge_paragraph_runs_keeps_capitalized_start_separate():
    out = merge_paragraph_runs([[Block("paragraph", "Done.")], [Block("paragraph", "New.")]])
    assert len(out) == 2
