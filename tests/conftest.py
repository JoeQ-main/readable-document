import pytest

from pdf_helper.extract.model import Block, Document


@pytest.fixture
def sample_doc() -> Document:
    return Document(
        "Sample",
        "C:/x/sample.pdf",
        [
            Block("heading", "Intro", 1),
            Block("paragraph", "Hello <script>alert(1)</script> world. Two. Three. Four. Five."),
            Block("list_item", "one"),
            Block("list_item", "two"),
        ],
        False,
    )
