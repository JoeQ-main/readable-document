"""Find the PDF a browser is showing by looking in the browser's own HTTP cache.

A PDF opened from the web (often embedded in a course or portal page) exists
nowhere on disk except the browser cache. Firefox's cache2 stores each response
as a file whose content comes first, so a cached PDF starts with ``%PDF-``.
The right entry is the one whose text contains the lines transcribed from the screen.
Everything stays local; nothing is fetched.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

MIN_PDF_BYTES = 20_000
MAX_ENTRIES = 200  # newest cache files examined
KEY_WORDS = 6  # a screen line is matched by its first words, tolerating OCR noise further on
MIN_WORDS = 5  # shorter lines (menus, buttons) are not evidence
MIN_MATCHED_LINES = 3
MIN_MATCH_FRACTION = 0.3


@dataclass(frozen=True)
class CachedPdf:
    data: bytes
    mtime: float
    origin: str


def firefox_cache_dirs() -> list[Path]:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return []
    return sorted((Path(base) / "Mozilla" / "Firefox" / "Profiles").glob("*/cache2/entries"))


def cached_pdfs(cache_dirs: list[Path] | None = None, min_bytes: int = MIN_PDF_BYTES,
                limit: int = MAX_ENTRIES) -> list[CachedPdf]:
    """PDF entries in the cache directories, newest first."""
    dirs = cache_dirs if cache_dirs is not None else firefox_cache_dirs()
    files: list[tuple[float, Path]] = []
    for folder in dirs:
        if not folder.is_dir():
            continue
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    if entry.is_file():
                        stat = entry.stat()
                        if stat.st_size >= min_bytes:
                            files.append((stat.st_mtime, Path(entry.path)))
        except OSError:
            continue
    files.sort(reverse=True)
    found: list[CachedPdf] = []
    for mtime, path in files[:limit]:
        try:
            with path.open("rb") as f:
                if f.read(5) != b"%PDF-":
                    continue
            found.append(CachedPdf(path.read_bytes(), mtime, str(path)))
        except OSError:
            continue
    return found


def normalize_text(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", text.lower()).strip()


def _line_key(line: str) -> str | None:
    words = normalize_text(line).split()
    if len(words) < MIN_WORDS:
        return None
    return " ".join(words[:KEY_WORDS])


def match_score(screen_lines: list[str], text: str) -> tuple[int, int]:
    """(matched, eligible): how many substantial screen lines the text contains."""
    matched = eligible = 0
    for line in screen_lines:
        key = _line_key(line)
        if key is None:
            continue
        eligible += 1
        if key in text:
            matched += 1
    return matched, eligible


def _pdf_text(data: bytes) -> str:
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        return normalize_text(" ".join(page.get_text() for page in pdf))


def pdf_title(data: bytes) -> str:
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        return ((pdf.metadata or {}).get("title") or "").strip()


def find_matching_pdf(screen_lines: list[str], candidates: list[CachedPdf]) -> CachedPdf | None:
    best: CachedPdf | None = None
    best_matched = 0
    for candidate in candidates:
        try:
            matched, eligible = match_score(screen_lines, _pdf_text(candidate.data))
        except Exception:
            continue
        enough = matched >= MIN_MATCHED_LINES or (matched >= 2 and matched == eligible)
        if enough and matched / eligible >= MIN_MATCH_FRACTION and matched > best_matched:
            best, best_matched = candidate, matched
    return best


def cached_pdf_for_screen(lines: list[str]) -> tuple[bytes, str] | None:
    """The cached PDF whose text matches the transcribed screen, as (bytes, title)."""
    match = find_matching_pdf(lines, cached_pdfs())
    if match is None:
        return None
    return match.data, pdf_title(match.data) or "Document from browser cache"
