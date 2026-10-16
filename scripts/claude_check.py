"""Live check: send the two fixtures through the real Claude API and print the blocks.

Needs ANTHROPIC_API_KEY. Run from the repo root:  python scripts/claude_check.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from pdf_helper.claude_reader import read_image, read_pdf  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def show(doc, seconds):
    print(f"  {len(doc.blocks)} blocks in {seconds:.1f}s; via image: {doc.via_ocr}")
    for block in doc.blocks:
        print(f"  [{block.kind}{block.level or ''}] {block.text[:100]}")


if __name__ == "__main__":
    t = time.time()
    print("PDF:", FIXTURES / "sample.pdf")
    show(read_pdf((FIXTURES / "sample.pdf").read_bytes(), "sample", "fixture"), time.time() - t)

    t = time.time()
    print("Image:", FIXTURES / "sample.png")
    with Image.open(FIXTURES / "sample.png") as image:
        show(read_image(image, "sample", "fixture"), time.time() - t)
