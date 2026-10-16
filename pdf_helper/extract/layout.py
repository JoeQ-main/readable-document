"""Line-level heuristics shared by the PDF and OCR extractors.

A ``Line`` is one visual line of text with its bounding box. ``group_lines``
turns a reading-ordered list of lines into headings, paragraphs and list items.
"""

import re
from dataclasses import dataclass
from statistics import median

from .model import Block

LIST_MARKER = re.compile(r"^(?:[•\-–*o]|\d+[.)]|[a-z][.)])\s+")

PARAGRAPH_GAP = 0.6  # gap / line height at which a paragraph ends
HEADING_MAX_CHARS = 120
BOLD_HEADING_MAX_CHARS = 80
CAPS_HEADING_MAX_CHARS = 60


@dataclass(frozen=True)
class Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float | None = None
    bold: bool = False

    @property
    def height(self) -> float:
        return self.y1 - self.y0


def strip_list_marker(text: str) -> str | None:
    """Return the text without its leading list marker, or None if there is none."""
    m = LIST_MARKER.match(text)
    if not m:
        return None
    return text[m.end():]


def _level_for_ratio(ratio: float) -> int:
    if ratio >= 1.6:
        return 1
    if ratio >= 1.3:
        return 2
    return 3


def _is_all_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 3 and text.upper() == text and len(text) <= CAPS_HEADING_MAX_CHARS


def _heading_level(line: Line, text: str, body_size: float | None, ref_height: float,
                   followed_by_gap: bool) -> int:
    """0 when the line is not a heading, else its level 1..3."""
    if len(text) > HEADING_MAX_CHARS:
        return 0
    if body_size and line.size:
        ratio = line.size / body_size
        if ratio >= 1.15:
            return _level_for_ratio(ratio)
        if line.bold and len(text) <= BOLD_HEADING_MAX_CHARS and followed_by_gap:
            return 3
        return 0
    ratio = line.height / ref_height if ref_height > 0 else 1.0
    if ratio >= 1.3:
        return _level_for_ratio(ratio)
    if _is_all_caps(text):
        return 3
    return 0


def _join(previous: str, text: str) -> str:
    if previous.endswith("-") and text[:1].islower():
        return previous[:-1] + text
    return previous + " " + text


def group_lines(lines: list[Line], body_size: float | None = None) -> list[Block]:
    """Group reading-ordered lines into blocks.

    With ``body_size`` (PDF mode) headings come from font size and boldness;
    without it (OCR mode) they come from line height and all-caps text.
    """
    if not lines:
        return []
    ref_height = median(line.height for line in lines)
    blocks: list[Block] = []
    paragraph: str | None = None

    def flush() -> None:
        nonlocal paragraph
        if paragraph is not None:
            blocks.append(Block("paragraph", paragraph))
            paragraph = None

    for i, line in enumerate(lines):
        text = line.text.strip()
        if not text:
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        followed_by_gap = nxt is None or (nxt.y0 - line.y1) >= PARAGRAPH_GAP * line.height

        level = _heading_level(line, text, body_size, ref_height, followed_by_gap)
        if level:
            flush()
            blocks.append(Block("heading", text, level))
            continue

        item = strip_list_marker(text)
        if item is not None:
            flush()
            blocks.append(Block("list_item", item))
            continue

        paragraph = text if paragraph is None else _join(paragraph, text)
        if followed_by_gap:
            flush()
    flush()
    return blocks


def merge_paragraph_runs(groups: list[list[Block]]) -> list[Block]:
    """Concatenate block groups (one per page), joining a paragraph that
    continues across the boundary (next group starts with a lowercase paragraph)."""
    merged: list[Block] = []
    for group in groups:
        if not group:
            continue
        first = group[0]
        if (merged and merged[-1].kind == "paragraph" and first.kind == "paragraph"
                and first.text[:1].islower()):
            merged[-1] = Block("paragraph", _join(merged[-1].text, first.text))
            merged.extend(group[1:])
        else:
            merged.extend(group)
    return merged
