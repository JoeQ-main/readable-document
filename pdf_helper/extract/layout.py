"""Line-level heuristics shared by the PDF and OCR extractors.

A ``Line`` is one visual line of text with its bounding box. ``group_lines``
turns a reading-ordered list of lines into headings, paragraphs and list items.
"""

import re
from dataclasses import dataclass

from .model import Block

#  is the Symbol-font bullet that Word-generated PDFs expose.
LIST_MARKER = re.compile(r"^(?:[•\-–*o]|\d+[.)]|[a-z][.)])\s+")

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


COLUMN_BINS = 200
GUTTER_COVER_FRACTION = 0.15  # a bin crossed by fewer than this share of lines is empty space
COLUMN_MIN_FRACTION = 0.15  # a covered run narrower than this share of the width is not a column
COLUMN_HIT_FRACTION = 0.2  # a line reaching this far into a second column spans both
PITCH_TOLERANCE = 1.3  # a line pitch within this factor of the typical pitch is the same paragraph


def _detect_columns(lines: list[Line]) -> list[tuple[float, float]]:
    """Return column x-ranges (left to right), or [] when the text is single-column.

    Uses a horizontal coverage histogram: gutters are x-ranges that almost no line
    crosses, so a title spanning both columns does not hide them.
    """
    x_min = min(l.x0 for l in lines)
    x_max = max(l.x1 for l in lines)
    width = x_max - x_min
    if width <= 0:
        return []
    bins = [0] * COLUMN_BINS
    scale = (COLUMN_BINS - 1) / width
    for line in lines:
        b0 = int((line.x0 - x_min) * scale)
        b1 = int((line.x1 - x_min) * scale)
        for b in range(max(0, b0), min(COLUMN_BINS - 1, b1) + 1):
            bins[b] += 1
    threshold = GUTTER_COVER_FRACTION * len(lines)
    runs: list[tuple[int, int]] = []
    start = None
    for i, count in enumerate(bins):
        covered = count >= threshold
        if covered and start is None:
            start = i
        elif not covered and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, COLUMN_BINS - 1))
    columns = [(x_min + a / scale, x_min + (b + 1) / scale) for a, b in runs
               if (b - a + 1) >= COLUMN_MIN_FRACTION * COLUMN_BINS]
    return columns if len(columns) >= 2 else []


def _column_of(line: Line, columns: list[tuple[float, float]]) -> int | None:
    """Index of the column a line belongs to, or None when it spans several."""
    hits = []
    best, best_overlap = 0, -1.0
    for i, (c0, c1) in enumerate(columns):
        overlap = max(0.0, min(line.x1, c1) - max(line.x0, c0))
        if overlap > COLUMN_HIT_FRACTION * (c1 - c0):
            hits.append(i)
        if overlap > best_overlap:
            best, best_overlap = i, overlap
    if len(hits) >= 2:
        return None
    return hits[0] if hits else best


def order_reading(lines: list[Line]) -> list[Line]:
    """Sort lines into reading order: top-to-bottom within a column, columns left
    to right, with full-width lines (titles, footers) splitting the page into bands."""
    by_y = sorted(lines, key=lambda l: (l.y0, l.x0))
    if len(by_y) < 4:
        return by_y
    columns = _detect_columns(by_y)
    if not columns:
        return by_y

    ordered: list[Line] = []
    band: list[list[Line]] = [[] for _ in columns]

    def flush() -> None:
        for column_lines in band:
            ordered.extend(column_lines)
            column_lines.clear()

    for line in by_y:
        index = _column_of(line, columns)
        if index is None:  # spans the columns: everything above it reads first
            flush()
            ordered.append(line)
        else:
            band[index].append(line)
    flush()
    return ordered


def _typical_pitch(lines: list[Line]) -> float | None:
    """Median top-to-top distance between consecutive lines, or None with too few lines
    to tell regular spacing from paragraph breaks."""
    pitches = sorted(b.y0 - a.y0 for a, b in zip(lines, lines[1:]) if b.y0 > a.y0)
    if len(pitches) < 3:
        return None
    return pitches[len(pitches) // 2]


def _reference_height(lines: list[Line]) -> float:
    """Median line height weighted by text length, so long body lines dominate
    over many short UI-chrome lines in a window capture."""
    weighted = sorted((line.height, max(1, len(line.text.strip()))) for line in lines)
    total = sum(weight for _, weight in weighted)
    running = 0
    for height, weight in weighted:
        running += weight
        if running * 2 >= total:
            return height
    return weighted[-1][0]


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
    ref_height = _reference_height(lines)
    typical_pitch = _typical_pitch(lines)
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
        if nxt is None:
            followed_by_gap = True
        elif nxt.y0 - line.y1 < -line.height:
            # The next line sits above this one: a column or page jump. Text usually
            # flows on, so only a capitalised start is treated as a new paragraph.
            followed_by_gap = not nxt.text.strip()[:1].islower()
        else:
            followed_by_gap = (nxt.y0 - line.y1) >= PARAGRAPH_GAP * line.height
            # OCR boxes vary in height from line to line (descenders), so a gap alone
            # misfires; a pitch that matches the page's regular line pitch is not a break.
            if followed_by_gap and typical_pitch and (nxt.y0 - line.y0) <= PITCH_TOLERANCE * typical_pitch:
                followed_by_gap = False

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
