from pathlib import Path

from pdf_helper.extract.layout import Line

FIXTURES = Path(__file__).parent / "fixtures"


def L(text, y, h=10, size=None, bold=False, x0=0) -> Line:
    return Line(text, x0, y, x0 + 10 * len(text), y + h, size, bold)
