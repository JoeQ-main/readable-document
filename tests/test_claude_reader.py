import base64
from types import SimpleNamespace

import anthropic
import pymupdf
import pytest
from PIL import Image

from pdf_helper import claude_reader, transcription_cache
from pdf_helper.claude_reader import (
    DEFAULT_MODEL,
    ChunkJoiner,
    ParsedBlock,
    ParsedDocument,
    iter_pdf_blocks,
    prepare_image,
    read_image,
    read_pdf,
)


def test_chunk_joiner_holds_back_last_paragraph_until_next_chunk():
    joiner = ChunkJoiner()
    first = joiner.push([Block("heading", "Title", 1), Block("paragraph", "ends mid")])
    assert first == [Block("heading", "Title", 1)]  # the trailing paragraph waits
    second = joiner.push([Block("paragraph", "sentence here."), Block("paragraph", "Next para.")])
    assert second == [Block("paragraph", "ends mid sentence here.")]  # joined; "Next para." waits
    third = joiner.push([Block("heading", "Section", 2), Block("list_item", "x")])
    # Only a trailing paragraph is held back; a list item cannot continue on the next page.
    assert third == [Block("paragraph", "Next para."), Block("heading", "Section", 2), Block("list_item", "x")]
    assert joiner.flush() == []


def test_chunk_joiner_hyphen_and_capital_rules():
    joiner = ChunkJoiner()
    joiner.push([Block("paragraph", "exam-")])
    assert joiner.push([Block("paragraph", "ple text."), Block("paragraph", "Tail")]) == [
        Block("paragraph", "example text.")]
    assert joiner.push([Block("paragraph", "Capital start.")]) == [Block("paragraph", "Tail")]
    assert joiner.flush() == [Block("paragraph", "Capital start.")]


def test_iter_pdf_blocks_yields_page_ranges_in_order(monkeypatch):
    monkeypatch.setattr(claude_reader, "CHUNK_PAGES", 3)
    monkeypatch.setattr(claude_reader, "MAX_WORKERS", 2)

    class Echo(FakeMessages):
        def parse(self, **kwargs):
            self.calls.append(kwargs)
            instruction = kwargs["messages"][0]["content"][-1]["text"]
            return parsed([ParsedBlock(kind="paragraph", level=0, text=instruction[:30])])

    client = FakeClient()
    client.messages = Echo()
    client.beta = SimpleNamespace(messages=client.messages)
    monkeypatch.setattr(claude_reader, "client_factory", lambda: client)

    chunks = list(iter_pdf_blocks(small_pdf(pages=7)))
    assert [(c.first, c.last, c.total) for c in chunks] == [(1, 3, 7), (4, 6, 7), (7, 7, 7)]
    assert all(len(c.blocks) == 1 and c.from_cache is False for c in chunks)
from pdf_helper.errors import UserFacingError
from pdf_helper.extract.model import Block


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response=None, error=None):
        self.messages = FakeMessages(response, error)
        self.beta = SimpleNamespace(messages=self.messages)
        self.options = None

    def with_options(self, **options):
        self.options = options
        return self


def parsed(blocks, title="Parsed Title"):
    return SimpleNamespace(
        parsed_output=ParsedDocument(title=title, blocks=blocks),
        stop_reason="end_turn",
        stop_details=None,
    )


@pytest.fixture(autouse=True)
def cache_dir(monkeypatch, tmp_path):
    folder = tmp_path / "cache"
    folder.mkdir()
    monkeypatch.setattr(transcription_cache, "cache_dir", lambda: folder)
    return folder


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient(parsed([
        ParsedBlock(kind="heading", level=1, text="Intro"),
        ParsedBlock(kind="paragraph", level=0, text="Body text."),
        ParsedBlock(kind="list_item", level=0, text="one"),
    ]))
    monkeypatch.setattr(claude_reader, "client_factory", lambda: client)
    return client


def small_pdf(pages=1):
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"page {i + 1}", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def test_read_pdf_sends_document_and_maps_blocks(fake):
    data = small_pdf()
    doc = read_pdf(data, title="report", source_label="C:/x/report.pdf")
    assert doc.blocks == [Block("heading", "Intro", 1), Block("paragraph", "Body text."), Block("list_item", "one")]
    assert doc.title == "report" and doc.source_label.startswith("C:/x/report.pdf") and doc.via_ocr is False
    call = fake.messages.calls[0]
    assert call["model"] == DEFAULT_MODEL and call["output_format"] is ParsedDocument
    content = call["messages"][0]["content"]
    assert content[0]["type"] == "document" and content[0]["source"]["media_type"] == "application/pdf"
    assert base64.standard_b64decode(content[0]["source"]["data"]) == data
    assert content[-1]["type"] == "text"
    assert fake.options["timeout"] >= 600


def test_model_override_from_environment(fake, monkeypatch):
    monkeypatch.setenv("READABLE_MODEL", "claude-sonnet-5-5")
    doc = read_image(Image.new("RGB", (300, 300), "white"), "t", "s")
    assert fake.messages.calls[0]["model"] == "claude-sonnet-5-5"
    assert "claude-sonnet-5-5" in doc.source_label


def test_read_image_sends_png_and_marks_transcribed(fake):
    doc = read_image(Image.new("RGB", (400, 300), "white"), title="shot", source_label="captured")
    assert doc.via_ocr is True and doc.blocks[0] == Block("heading", "Intro", 1)
    content = fake.messages.calls[0]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/png"


def test_prepare_image_downscales_long_edge():
    data, media_type = prepare_image(Image.new("RGB", (4000, 1000), "white"))
    with Image.open(__import__("io").BytesIO(data)) as img:
        assert max(img.size) == 1568 and media_type == "image/png"


def test_empty_result_is_user_facing(monkeypatch):
    monkeypatch.setattr(claude_reader, "client_factory", lambda: FakeClient(parsed([])))
    with pytest.raises(UserFacingError, match="No readable text"):
        read_image(Image.new("RGB", (300, 300)), "t", "s")


def test_refusal_is_user_facing(monkeypatch):
    response = SimpleNamespace(parsed_output=None, stop_reason="refusal",
                               stop_details=SimpleNamespace(category="x", explanation="nope"))
    monkeypatch.setattr(claude_reader, "client_factory", lambda: FakeClient(response))
    with pytest.raises(UserFacingError, match="declined"):
        read_image(Image.new("RGB", (300, 300)), "t", "s")


def _api_error(cls, status):
    request = __import__("httpx2").Request("POST", "https://api.anthropic.com/v1/messages")
    response = __import__("httpx2").Response(status, request=request)
    return cls("boom", response=response, body=None)


@pytest.mark.parametrize("error,fragment", [
    (_api_error(anthropic.AuthenticationError, 401), "ANTHROPIC_API_KEY"),
    (_api_error(anthropic.RateLimitError, 429), "rate limit"),
    (_api_error(anthropic.BadRequestError, 400), "boom"),
    (anthropic.APIConnectionError(request=__import__("httpx2").Request("POST", "https://api.anthropic.com")), "reach"),
])
def test_api_errors_are_user_facing(monkeypatch, error, fragment):
    monkeypatch.setattr(claude_reader, "client_factory", lambda: FakeClient(error=error))
    with pytest.raises(UserFacingError, match=fragment):
        read_image(Image.new("RGB", (300, 300)), "t", "s")


def test_long_pdf_is_read_in_page_chunks_and_joined(monkeypatch):
    # 7 pages with a chunk size of 3 -> pages 1-3, 4-6, 7; blocks come back in page order
    # and a paragraph split across a chunk boundary is joined when it continues lowercase.
    monkeypatch.setattr(claude_reader, "CHUNK_PAGES", 3)
    monkeypatch.setattr(claude_reader, "MAX_WORKERS", 2)

    class ChunkedMessages(FakeMessages):
        def parse(self, **kwargs):
            self.calls.append(kwargs)
            data = base64.standard_b64decode(kwargs["messages"][0]["content"][0]["source"]["data"])
            with pymupdf.open(stream=data, filetype="pdf") as pdf:
                first = pdf[0].get_text().strip()
                n = pdf.page_count
            if first == "page 1":
                blocks = [ParsedBlock(kind="heading", level=1, text="Title"),
                          ParsedBlock(kind="paragraph", level=0, text="ends mid")]
            elif first == "page 4":
                blocks = [ParsedBlock(kind="paragraph", level=0, text="sentence here."),
                          ParsedBlock(kind="paragraph", level=0, text=f"chunk of {n} pages")]
            else:
                blocks = [ParsedBlock(kind="paragraph", level=0, text=f"Last chunk of {n} page")]
            return parsed(blocks, title="Title")

    client = FakeClient()
    client.messages = ChunkedMessages()
    client.beta = SimpleNamespace(messages=client.messages)
    monkeypatch.setattr(claude_reader, "client_factory", lambda: client)

    doc = read_pdf(small_pdf(pages=7), "long", "src")
    assert [b.text for b in doc.blocks] == [
        "Title", "ends mid sentence here.", "chunk of 3 pages", "Last chunk of 1 page"]
    assert len(client.messages.calls) == 3
    instructions = [c["messages"][0]["content"][-1]["text"] for c in client.messages.calls]
    assert any("pages 1 to 3 of 7" in t for t in instructions)
    assert any("pages 7 to 7 of 7" in t for t in instructions)


def test_pdf_too_long_is_rejected_before_sending(fake, monkeypatch):
    monkeypatch.setattr(claude_reader, "MAX_PDF_PAGES", 2)
    with pytest.raises(UserFacingError, match="pages"):
        read_pdf(small_pdf(pages=3), "t", "s")
    assert fake.messages.calls == []


SAMPLE_PDF = __import__("pathlib").Path(__file__).parent / "fixtures" / "sample.pdf"


def test_second_read_of_the_same_pdf_makes_no_api_call(fake, cache_dir):
    data = SAMPLE_PDF.read_bytes()
    first = read_pdf(data, "sample", "C:/x/sample.pdf")
    assert len(fake.messages.calls) == 1 and first.source_label.endswith(f"read by Claude ({DEFAULT_MODEL})")
    assert len(list(cache_dir.glob("*.json"))) == 1

    second = read_pdf(data, "sample", "C:/x/sample.pdf")
    assert fake.messages.calls == fake.messages.calls[:1]  # zero new API calls
    assert second.blocks == first.blocks
    assert second.source_label == first.source_label + ", from cache"


def test_cache_key_depends_on_model_and_chunk_size(fake, monkeypatch):
    data = small_pdf()
    read_pdf(data, "t", "s")
    monkeypatch.setenv("READABLE_MODEL", "claude-sonnet-5-5")
    read_pdf(data, "t", "s")
    assert len(fake.messages.calls) == 2  # another model means another transcription
    monkeypatch.delenv("READABLE_MODEL")
    monkeypatch.setattr(claude_reader, "CHUNK_PAGES", 2)
    read_pdf(data, "t", "s")
    assert len(fake.messages.calls) == 3


def _chunked_client(monkeypatch, fail_first=()):
    """A fake that answers each chunk with its page range, failing the pages in fail_first once."""
    failures = set(fail_first)

    class Chunked(FakeMessages):
        def parse(self, **kwargs):
            self.calls.append(kwargs)
            instruction = kwargs["messages"][0]["content"][-1]["text"]
            first_page = int(instruction.split("pages ")[1].split(" ")[0])
            if first_page in failures:
                failures.discard(first_page)
                raise UserFacingError("The Claude API rate limit was hit.")
            return parsed([ParsedBlock(kind="list_item", level=0, text=f"from page {first_page}")])

    client = FakeClient()
    client.messages = Chunked()
    client.beta = SimpleNamespace(messages=client.messages)
    monkeypatch.setattr(claude_reader, "client_factory", lambda: client)
    return client


def test_chunks_that_succeeded_before_a_failure_are_not_requested_again(monkeypatch, cache_dir):
    monkeypatch.setattr(claude_reader, "CHUNK_PAGES", 2)
    monkeypatch.setattr(claude_reader, "MAX_WORKERS", 1)
    client = _chunked_client(monkeypatch, fail_first=(5,))
    data = small_pdf(pages=6)
    with pytest.raises(UserFacingError, match="rate limit"):
        list(iter_pdf_blocks(data))
    assert len(client.messages.calls) == 3  # pages 1-2 and 3-4 succeeded and were cached
    assert len(list(cache_dir.glob("*.json"))) == 2

    chunks = list(iter_pdf_blocks(data))
    assert len(client.messages.calls) == 4  # only pages 5-6 were requested again
    assert [c.blocks[0].text for c in chunks] == ["from page 1", "from page 3", "from page 5"]
    assert all(c.from_cache is False for c in chunks)  # an API call was made for this read
    assert len(list(cache_dir.glob("*.json"))) == 4  # three chunks and the whole document

    again = list(iter_pdf_blocks(data))
    assert len(client.messages.calls) == 4
    assert [b.text for b in again[0].blocks] == ["from page 1", "from page 3", "from page 5"]
    assert [(c.first, c.last, c.from_cache) for c in again] == [(1, 6, True)]  # whole-document hit


def test_whole_document_hit_skips_the_executor(monkeypatch, cache_dir):
    monkeypatch.setattr(claude_reader, "CHUNK_PAGES", 2)
    _chunked_client(monkeypatch)
    data = small_pdf(pages=5)
    list(iter_pdf_blocks(data))

    def no_pool(*args, **kwargs):
        raise AssertionError("the executor must not be used for a cached document")

    monkeypatch.setattr(claude_reader, "ThreadPoolExecutor", no_pool)
    monkeypatch.setattr(claude_reader, "_split_pdf", no_pool)
    chunks = list(iter_pdf_blocks(data))
    # the whole-document entry is the joined document, served as one chunk
    assert [(c.first, c.last, c.total, c.from_cache) for c in chunks] == [(1, 5, 5, True)]
    assert [b.text for b in chunks[0].blocks] == ["from page 1", "from page 3", "from page 5"]


def test_all_chunks_cached_without_a_whole_document_entry_still_makes_no_call(monkeypatch, cache_dir):
    monkeypatch.setattr(claude_reader, "CHUNK_PAGES", 2)
    client = _chunked_client(monkeypatch)
    data = small_pdf(pages=4)
    list(iter_pdf_blocks(data))
    whole = cache_dir / f"{claude_reader.pdf_cache_key(data)}.json"
    assert whole.exists()
    whole.unlink()
    monkeypatch.setattr(claude_reader, "ThreadPoolExecutor", lambda *a, **k: 1 / 0)
    chunks = list(iter_pdf_blocks(data))
    assert len(client.messages.calls) == 2 and all(c.from_cache for c in chunks)


def test_second_read_of_the_same_image_makes_no_api_call(fake):
    image = Image.new("RGB", (400, 300), "white")
    first = read_image(image, "shot", "captured")
    second = read_image(image.copy(), "shot", "captured")
    assert len(fake.messages.calls) == 1
    assert second.blocks == first.blocks and second.via_ocr is True
    assert second.source_label == first.source_label + ", from cache"
    read_image(Image.new("RGB", (400, 300), "black"), "shot", "captured")
    assert len(fake.messages.calls) == 2


def test_empty_transcriptions_are_not_cached(monkeypatch, cache_dir):
    monkeypatch.setattr(claude_reader, "client_factory", lambda: FakeClient(parsed([])))
    with pytest.raises(UserFacingError):
        read_image(Image.new("RGB", (300, 300)), "t", "s")
    assert list(cache_dir.glob("*.json")) == []
