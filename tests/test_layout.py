from pdf_helper.extract.layout import group_lines, merge_paragraph_runs, order_reading, strip_list_marker
from pdf_helper.extract.model import Block
from pdf_helper.extract.layout import Line
from tests.helpers import L


def col(text, x0, x1, y, h=10):
    return Line(text, x0, y, x1, y + h)


def test_order_reading_keeps_single_column_in_y_order():
    lines = [col("b", 20, 200, 12), col("a", 0, 200, 0), col("c", 0, 200, 24), col("d", 0, 200, 36)]
    assert [l.text for l in order_reading(lines)] == ["a", "b", "c", "d"]


def test_order_reading_reads_left_column_before_right_column():
    left = [col(f"L{i}", 0, 100, 12 * i) for i in range(6)]
    right = [col(f"R{i}", 150, 250, 12 * i) for i in range(6)]
    interleaved = [line for pair in zip(left, right) for line in pair]
    assert [l.text for l in order_reading(interleaved)] == [l.text for l in left + right]


def test_order_reading_keeps_full_width_lines_as_band_breaks():
    title = col("Title", 0, 250, 0)
    left = [col(f"L{i}", 0, 100, 20 + 12 * i) for i in range(5)]
    right = [col(f"R{i}", 150, 250, 20 + 12 * i) for i in range(5)]
    footer = col("Footer", 0, 250, 100)
    lower_left = [col(f"l{i}", 0, 100, 120 + 12 * i) for i in range(4)]
    lower_right = [col(f"r{i}", 150, 250, 120 + 12 * i) for i in range(4)]
    mixed = [title] + [x for p in zip(left, right) for x in p] + [footer] + [x for p in zip(lower_left, lower_right) for x in p]
    expected = [title] + left + right + [footer] + lower_left + lower_right
    assert [l.text for l in order_reading(mixed)] == [l.text for l in expected]


def test_order_reading_treats_line_reaching_well_into_next_column_as_spanning():
    # A footer whose OCR box covers the left column and only a third of the right one.
    left = [col(f"L{i}", 0, 100, 12 * i) for i in range(5)]
    right = [col(f"R{i}", 150, 250, 12 * i) for i in range(5)]
    footer = col("Footer", 0, 185, 100)
    mixed = [x for p in zip(left, right) for x in p] + [footer]
    assert [l.text for l in order_reading(mixed)] == [l.text for l in left + right + [footer]]


def test_regular_line_pitch_overrides_box_height_noise():
    # OCR boxes are taller on lines with descenders; with a steady 30px pitch that must
    # not split a paragraph. A doubled pitch still does.
    lines = [L("one two", 0, h=16), L("three four", 30, h=22), L("five six", 60, h=16),
             L("seven eight", 90, h=22), L("Nine ten", 150, h=16), L("eleven twelve", 180, h=22)]
    blocks = group_lines(lines)
    assert [b.text for b in blocks] == ["one two three four five six seven eight", "Nine ten eleven twelve"]


def test_pitch_rule_survives_pages_of_two_line_paragraphs():
    # Half the pitches are paragraph pitches here; the regular pitch must still win.
    ys = [0, 27, 76, 103, 152, 179]  # three 2-line paragraphs: pitch 27 inside, 49 between
    lines = [L("TITLE", -120, h=40)] + [L(f"line {i} words", y, h=20) for i, y in enumerate(ys)]
    lines += [L("Footer", 400, h=20), L("Page 1", 500, h=20)]  # more large pitches than regular ones
    assert [b.text for b in group_lines(lines)] == [
        "TITLE", "line 0 words line 1 words", "line 2 words line 3 words", "line 4 words line 5 words",
        "Footer", "Page 1"]


def test_uniform_loose_spacing_keeps_lines_separate():
    # Single lines three line-heights apart are separate items, not a paragraph.
    lines = [L(f"Item {i}", 30 * i, h=10) for i in range(5)]
    assert [b.text for b in group_lines(lines)] == [f"Item {i}" for i in range(5)]


def test_order_reading_separates_narrow_sidebar_from_ragged_content():
    # A web page: three full-width header lines, a 10%-wide sidebar, and a content
    # column where most lines are short, so the column's right half is thinly covered.
    headers = [col(f"Header {i}", 0, 1000, 12 * i) for i in range(3)]
    sidebar = [col(f"Side {i}", 0, 100, 50 + 12 * i) for i in range(30)]
    content = [col(f"Body {i}", 400, 600 if i % 7 else 1000, 50 + 12 * i) for i in range(70)]
    mixed = headers + [x for pair in zip(sidebar, content) for x in pair] + content[30:]
    texts = [l.text for l in order_reading(mixed)]
    assert texts[:3] == ["Header 0", "Header 1", "Header 2"]
    assert texts[3:33] == [l.text for l in sidebar]
    assert texts[33:] == [l.text for l in content]


def test_order_reading_handles_tiny_inputs():
    assert order_reading([]) == []
    one = [col("only", 0, 100, 0)]
    assert order_reading(one) == one


def test_column_jump_merges_only_a_lowercase_continuation():
    # After column reordering the next line sits higher on the page (negative gap).
    cont = group_lines([L("ends mid", 500), L("sentence here.", 0)])
    assert cont == [Block("paragraph", "ends mid sentence here.")]
    fresh = group_lines([L("Done here.", 500), L("New paragraph.", 0)])
    assert [b.text for b in fresh] == ["Done here.", "New paragraph."]


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


def test_ocr_reference_height_is_weighted_by_text_length():
    # Many short UI-chrome lines must not make ordinary body lines look like headings.
    chrome = [L(word, 10 * i, h=8) for i, word in enumerate(["File", "Edit", "View", "Help", "Tabs"])]
    body = [L("x" * 60 + ".", 100, h=12), L("y" * 60 + ".", 113, h=12)]
    blocks = group_lines(chrome + body)
    assert all(b.kind == "paragraph" for b in blocks if len(b.text) > 20)


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
