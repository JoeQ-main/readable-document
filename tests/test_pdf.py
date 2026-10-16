from pdf_helper.extract import pdf
from pdf_helper.extract.pdf import body_size, extract, remove_running_lines
from tests.helpers import FIXTURES, L


def test_body_size_is_most_common_by_chars():
    lines = [L("x" * 50, 0, size=11.0), L("Title", 0, size=24.0), L("y" * 5, 0, size=11.2)]
    assert body_size(lines) == 11.0
    assert body_size([]) is None


def test_remove_running_lines_drops_repeated_footers_and_page_numbers():
    pages = [[L("Body", 100), L("Confidential", 780), L(f"Page {i}", 790)] for i in range(3)]
    out = remove_running_lines(pages, [792.0] * 3)
    assert all([l.text for l in p] == ["Body"] for p in out)


def test_extract_sample_structure():
    doc = extract(FIXTURES / "sample.pdf")
    kinds = [(b.kind, b.level, b.text) for b in doc.blocks]
    assert kinds[0] == ("heading", 1, "Sample Report")
    assert ("heading", 2, "Introduction") in kinds
    assert any(b.kind == "paragraph" and "example" in b.text for b in doc.blocks)
    assert [b.text for b in doc.blocks if b.kind == "list_item"] == ["one", "two"]
    assert not any("Confidential" in b.text or b.text.startswith("Page ") for b in doc.blocks)
    assert doc.title == "sample" and doc.via_ocr is False


def test_blank_page_does_not_crash_and_uses_ocr_stub(monkeypatch):
    monkeypatch.setattr(pdf, "ocr_lines", lambda img: [])
    doc = extract(FIXTURES / "blank_page.pdf")
    assert doc.blocks and doc.via_ocr is True


def test_scanned_page_goes_through_ocr(monkeypatch):
    monkeypatch.setattr(pdf, "ocr_lines", lambda img: [L("OCR LINE", 0)])
    doc = extract(FIXTURES / "blank_page.pdf")
    assert doc.blocks[0].text == "OCR LINE"
