import pytest
from PIL import Image

from pdf_helper.errors import UserFacingError
from pdf_helper.extract import ocr
from pdf_helper.extract.model import Block
from pdf_helper.extract.ocr import extract, lines_from_result


def word(text, x, y, w=10, h=10):
    return {"text": text, "bounding_rect": {"x": x, "y": y, "width": w, "height": h}}


def test_lines_from_result_unions_word_boxes_and_sorts():
    result = {
        "lines": [
            {"text": "second line", "words": [word("second", 0, 20), word("line", 60, 20)]},
            {"text": "first line", "words": [word("first", 0, 0), word("line", 50, 0, 20, 12)]},
        ]
    }
    lines = lines_from_result(result)
    assert [l.text for l in lines] == ["first line", "second line"]
    assert (lines[0].x0, lines[0].y0, lines[0].x1, lines[0].y1) == (0, 0, 70, 12)


def test_lines_from_result_orders_two_columns_left_then_right():
    result = {"lines": []}
    for i in range(6):
        result["lines"].append({"text": f"right {i}", "words": [word("x", 300, 12 * i, 200, 10)]})
        result["lines"].append({"text": f"left {i}", "words": [word("x", 0, 12 * i, 200, 10)]})
    texts = [l.text for l in lines_from_result(result)]
    assert texts == [f"left {i}" for i in range(6)] + [f"right {i}" for i in range(6)]


def test_extract_too_little_text_raises(monkeypatch):
    monkeypatch.setattr(ocr, "recognizer", lambda img: {"lines": [{"text": "hi", "words": [word("hi", 0, 0)]}]})
    with pytest.raises(UserFacingError, match="No readable text"):
        extract(Image.new("RGB", (300, 300)), "t", "s")


def test_extract_single_line_becomes_paragraph(monkeypatch):
    monkeypatch.setattr(
        ocr,
        "recognizer",
        lambda img: {"lines": [{"text": "This is a single long line of text", "words": [word("x", 0, 0, 300, 12)]}]},
    )
    doc = extract(Image.new("RGB", (300, 300)), "t", "s")
    assert doc.blocks == [Block("paragraph", "This is a single long line of text")] and doc.via_ocr


def test_missing_language_pack_is_user_facing(monkeypatch):
    def boom(img):
        raise AssertionError('Add-WindowsCapability -Online -Name "Language.OCR~~~en-US~0.0.1.0"')

    monkeypatch.setattr(ocr, "recognizer", boom)
    with pytest.raises(UserFacingError, match="Settings"):
        extract(Image.new("RGB", (300, 300)), "t", "s")
