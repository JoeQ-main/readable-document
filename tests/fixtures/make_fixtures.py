"""Generate the PDF/PNG fixtures used by the tests. Run: python tests/fixtures/make_fixtures.py"""

from pathlib import Path

import pymupdf

HERE = Path(__file__).parent
BODY = 11
H1 = 24
H2 = 16
LEFT = 72
WIDTH, HEIGHT = 612, 792  # Letter


class Writer:
    def __init__(self, page: pymupdf.Page):
        self.page = page
        self.y = 90.0

    def line(self, text: str, size: float = BODY, fontname: str = "helv") -> None:
        kwargs = {"fontname": fontname}
        if fontname == "arial":  # base-14 Helvetica cannot encode the bullet glyph
            kwargs["fontfile"] = r"C:\Windows\Fonts\arial.ttf"
        self.page.insert_text((LEFT, self.y), text, fontsize=size, **kwargs)
        self.y += size * 1.25

    def heading(self, text: str, size: float) -> None:
        self.y += size * 0.8
        self.line(text, size)
        self.y += size * 0.5

    def paragraph(self, *lines: str) -> None:
        for text in lines:
            self.line(text)
        self.y += BODY * 1.0

    def footer(self, page_number: int) -> None:
        self.page.insert_text((LEFT, 770), "Sample Corp Confidential", fontsize=9)
        self.page.insert_text((WIDTH - 120, 782), f"Page {page_number}", fontsize=9)


def make_sample() -> None:
    doc = pymupdf.open()
    w = Writer(doc.new_page(width=WIDTH, height=HEIGHT))
    w.heading("Sample Report", H1)
    w.heading("Introduction", H2)
    w.paragraph(
        "This report describes a small experiment in readability.",
        "It exists only so the tests have a predictable document.",
    )
    w.paragraph(
        "This paragraph has an exam-",
        "ple of a hyphenated line break that should be joined.",
    )
    w.paragraph("Key points follow as a list.")
    w.line("• one", fontname="arial")
    w.line("• two", fontname="arial")
    w.footer(1)

    w = Writer(doc.new_page(width=WIDTH, height=HEIGHT))
    w.heading("Methods", H2)
    w.paragraph(
        "We measured reading speed with and without restyling.",
        "Participants read the same text in both forms.",
    )
    w.footer(2)

    w = Writer(doc.new_page(width=WIDTH, height=HEIGHT))
    w.heading("Results", H2)
    w.paragraph(
        "Restyled text was read 12% faster on average.",
        "Comprehension scores did not change.",
    )
    w.footer(3)

    doc.save(HERE / "sample.pdf")
    pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(2, 2))
    pix.save(HERE / "sample.png")
    doc.close()


def make_blank_page() -> None:
    doc = pymupdf.open()
    doc.new_page(width=WIDTH, height=HEIGHT)
    w = Writer(doc.new_page(width=WIDTH, height=HEIGHT))
    w.paragraph(
        "The second page has a text layer with enough characters.",
        "The first page is intentionally blank.",
    )
    doc.save(HERE / "blank_page.pdf")
    doc.close()


if __name__ == "__main__":
    make_sample()
    make_blank_page()
    print("fixtures written to", HERE)
