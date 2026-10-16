from dataclasses import replace

from pdf_helper.extract.model import Block
from pdf_helper.readable.transform import (
    chunk_paragraph,
    mark_lead,
    mark_numbers,
    render,
    split_sentences,
)
from pdf_helper.settings import DEFAULTS


def test_split_sentences():
    assert split_sentences('One. Two! "Three?" Four 5.') == ["One.", "Two!", '"Three?"', "Four 5."]


def test_split_keeps_abbreviation_like_lowercase_continuation():
    assert split_sentences("e.g. this stays. Next one.") == ["e.g. this stays.", "Next one."]


def test_chunk_paragraph_max_four_sentences():
    text = " ".join(f"Sentence {i}." for i in range(9))
    chunks = chunk_paragraph(text)
    assert len(chunks) == 3 and chunks[0].count(".") == 4 and chunks[2] == "Sentence 8."


def test_chunk_paragraph_without_terminators_is_kept_whole():
    text = "no punctuation at all " * 30
    assert chunk_paragraph(text) == [text.strip()]


def test_mark_lead_five_words_capped_at_forty_percent():
    assert mark_lead("a b c d e f g h i j k l m") == '<b class="lead">a b c d e</b> f g h i j k l m'
    assert mark_lead("one two three four five") == '<b class="lead">one two</b> three four five'
    assert mark_lead("one") == '<b class="lead">one</b>'


def test_mark_numbers():
    assert mark_numbers("Up 12.5% to $3,400 by 4/15/2026 and March 3, 2026.") == (
        'Up <mark class="num">12.5%</mark> to <mark class="num">$3,400</mark> by '
        '<mark class="num">4/15/2026</mark> and <mark class="num">March 3, 2026</mark>.'
    )


def test_mark_numbers_ignores_tag_attributes():
    assert mark_numbers('<b class="lead">In 2020</b>') == '<b class="lead">In <mark class="num">2020</mark></b>'


def test_render_escapes_and_structures(sample_doc):
    html = render(sample_doc, DEFAULTS)
    assert "&lt;script&gt;" in html and "<script>alert" not in html
    assert '<h1 id="intro-0">Intro</h1>' in html
    assert '<a href="#intro-0">Intro</a>' in html  # outline entry
    assert "<ul><li>one</li><li>two</li></ul>" in html.replace("\n", "")
    assert "--size: 19px" in html and 'data-dark="0"' in html
    assert "OCR text" not in html


def test_render_ocr_note_and_source(sample_doc):
    doc = replace(sample_doc, via_ocr=True, source_label="captured from window: Foo")
    html = render(doc, DEFAULTS)
    assert "OCR text" in html and "captured from window: Foo" in html


def test_render_no_headings_hides_outline(sample_doc):
    doc = replace(sample_doc, blocks=[Block("paragraph", "Only text.")])
    assert 'class="outline hidden"' in render(doc, DEFAULTS)
