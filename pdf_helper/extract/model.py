"""The intermediate document model shared by every extractor and the renderer."""

from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal["heading", "paragraph", "list_item"]


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str
    level: int = 0  # headings: 1..3; list items: nesting (0 for now)


@dataclass(frozen=True)
class Document:
    title: str  # file stem or window title
    source_label: str  # shown in the header line
    blocks: list[Block] = field(default_factory=list)
    via_ocr: bool = False
