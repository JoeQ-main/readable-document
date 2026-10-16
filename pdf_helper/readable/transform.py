"""Turn a Document into one self-contained, skim-friendly HTML page."""

import html
import json
import re
from pathlib import Path

from ..extract.model import Block, Document

TEMPLATE_PATH = Path(__file__).parent / "template.html"

# Python's re needs fixed-width lookbehinds, hence the two alternatives.
SENTENCE_SPLIT = re.compile(r"""(?:(?<=[.!?])|(?<=[.!?]["')\]]))\s+(?=["(\[]?[A-Z0-9])""")

NUMBER_PATTERN = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}(?:, \d{4})?\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\$\d[\d,]*(?:\.\d+)?"
    r"|\b\d[\d,]*(?:\.\d+)?%?"
)
TAG_SPLIT = re.compile(r"(<[^>]+>)")

LEAD_MAX_WORDS = 5
LEAD_MAX_FRACTION = 0.4
OCR_NOTE_HTML = '<span class="ocr-note">Read from an image — may contain errors</span>'


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return [part.strip() for part in SENTENCE_SPLIT.split(text) if part.strip()]


def chunk_paragraph(text: str, max_sentences: int = 4) -> list[str]:
    sentences = split_sentences(text)
    return [" ".join(sentences[i:i + max_sentences]) for i in range(0, len(sentences), max_sentences)]


def mark_lead(escaped_text: str) -> str:
    words = escaped_text.split()
    if not words:
        return escaped_text
    n = min(LEAD_MAX_WORDS, max(1, int(LEAD_MAX_FRACTION * len(words))))
    lead = '<b class="lead">' + " ".join(words[:n]) + "</b>"
    rest = words[n:]
    return lead + (" " + " ".join(rest) if rest else "")


def _wrap_number(m: re.Match) -> str:
    return f'<mark class="num">{m.group(0)}</mark>'


def mark_numbers(html_text: str) -> str:
    parts = TAG_SPLIT.split(html_text)
    # Even indexes are text, odd indexes are tags.
    return "".join(NUMBER_PATTERN.sub(_wrap_number, part) if i % 2 == 0 else part
                   for i, part in enumerate(parts))


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def render_fragment(blocks: list[Block], heading_start: int = 0) -> tuple[str, str]:
    """Return (body_html, outline_html) for blocks appended to an open page;
    heading ids continue from heading_start so anchors stay unique."""
    body: list[str] = []
    outline: list[str] = []
    heading_index = heading_start
    pending_items: list[str] = []

    def flush_list() -> None:
        if pending_items:
            body.append("<ul>" + "".join(pending_items) + "</ul>")
            pending_items.clear()

    for block in blocks:
        if block.kind == "list_item":
            pending_items.append(f"<li>{mark_numbers(_escape(block.text))}</li>")
            continue
        flush_list()
        if block.kind == "heading":
            level = max(1, min(3, block.level or 2))
            hid = f"{slugify(block.text)[:40] or 'h'}-{heading_index}"
            heading_index += 1
            text = _escape(block.text)
            body.append(f'<h{level} id="{hid}">{text}</h{level}>')
            outline.append(f'<li class="l{level}"><a href="#{hid}">{text}</a></li>')
        else:
            for chunk in chunk_paragraph(block.text):
                body.append("<p>" + mark_numbers(mark_lead(_escape(chunk))) + "</p>")
    flush_list()
    return "\n".join(body), "\n".join(outline)


def root_style(prefs: dict) -> str:
    return f"--size: {prefs['size']}px; --leading: {prefs['leading']}; --measure: {prefs['measure']}ch;"


def data_attrs(prefs: dict) -> str:
    flag = lambda key: "1" if prefs.get(key) else "0"  # noqa: E731
    return f'data-dark="{flag("dark")}" data-numbers="{flag("numbers")}" data-bionic="{flag("bionic")}"'


def render(doc: Document, prefs: dict) -> str:
    body, outline = render_fragment(doc.blocks)
    replacements = {
        "{{TITLE}}": html.escape(doc.title),
        "{{SOURCE}}": html.escape(doc.source_label),
        "{{OCR_NOTE}}": OCR_NOTE_HTML if doc.via_ocr else "",
        "{{OUTLINE}}": outline,
        "{{OUTLINE_CLASS}}": "" if outline else " hidden",
        "{{BODY}}": body,
        "{{ROOT_STYLE}}": root_style(prefs),
        "{{DATA_ATTRS}}": data_attrs(prefs),
        "{{PREFS_JSON}}": json.dumps(prefs),
    }
    page = TEMPLATE_PATH.read_text(encoding="utf-8")
    for key, value in replacements.items():
        page = page.replace(key, value)
    return page
