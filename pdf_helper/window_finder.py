"""Resolve the document behind a window: a file on disk, or the window itself to capture."""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .errors import UserFacingError

SUPPORTED_EXTS = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"})

TITLE_FILENAME = re.compile(
    r'([^\\/:*?"<>|\r\n]+?\.(?:pdf|png|jpe?g|bmp|tiff?|webp|gif))(?![\w.])', re.IGNORECASE
)
SEARCH_DEPTH_PATTERNS = ("{name}", "*/{name}", "*/*/{name}")
SEARCH_DEPTH = 2

# Browsers title a PDF tab with the PDF's own metadata title plus a suffix such as
# " — Mozilla Firefox", " - Google Chrome", " and 3 more pages - Personal - Microsoft Edge".
BROWSER_SUFFIX = re.compile(
    r"(?:\s+and\s+\d+\s+more\s+pages?)?"
    r"(?:\s+[-–—]\s+[^-–—]+?)?"
    r"\s+[-–—]\s+(?:Mozilla Firefox|Google Chrome|Microsoft​? Edge|Brave|Opera|Vivaldi|Chromium)"
    r"(?:\s+\([^)]*\))?$"
)
MIN_TITLE_CHARS = 4
METADATA_SEARCH_LIMIT = 300  # newest PDFs opened for a metadata-title comparison

# Known folder ids, resolved through the shell so OneDrive redirection is honoured.
KNOWN_FOLDERS = (
    "{374DE290-123F-4565-9164-39C4925E467B}",  # Downloads
    "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",  # Desktop
    "{FDD39AD0-238F-46AF-ADB4-6D6C0B5C5A1C}",  # Documents
)

NO_CANDIDATE_MESSAGE = "No document window found. Open a PDF or image, then click Read document."


@dataclass(frozen=True)
class Candidate:
    hwnd: int
    title: str
    pid: int
    cls: str


@dataclass(frozen=True)
class FileSource:
    path: Path


@dataclass(frozen=True)
class CaptureSource:
    hwnd: int
    title: str


TITLE_SEPARATOR = re.compile(r"\s+[-–—|]\s+")


def filename_candidates(title: str) -> list[str]:
    """Possible filenames in a window title, most likely first.

    The regex match runs from the start of the title to the extension, but
    browsers put the document title first ("Circular 230 - pcir230.pdf — Mozilla
    Firefox"), so the part after the last " - " separator is tried first and the
    whole match second, in case the filename itself contains a separator.
    """
    m = TITLE_FILENAME.search(title)
    if not m:
        return []
    full = re.split(r"[\\/]", m.group(1))[-1].strip()
    short = TITLE_SEPARATOR.split(full)[-1].strip()
    return [short, full] if short and short != full else [full]


def filename_from_title(title: str) -> str | None:
    candidates = filename_candidates(title)
    return candidates[0] if candidates else None


def _is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTS and path.is_file()


def path_from_cmdline(args: list[str]) -> Path | None:
    for arg in args[1:]:
        candidate = Path(arg.strip('"'))
        if _is_supported_file(candidate):
            return candidate
    return None


def psutil_cmdline(pid: int) -> list[str]:
    import psutil

    try:
        return psutil.Process(pid).cmdline()
    except psutil.Error:
        return []


def resolve_shortcut(lnk: Path) -> Path | None:
    try:
        import pythoncom
        from win32com.shell import shell

        link = pythoncom.CoCreateInstance(
            shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink
        )
        link.QueryInterface(pythoncom.IID_IPersistFile).Load(str(lnk))
        target = link.GetPath(shell.SLGP_UNCPRIORITY)[0]
        return Path(target) if target else None
    except Exception:
        return None


def recent_items_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "Microsoft" / "Windows" / "Recent"


def default_search_dirs() -> list[Path]:
    """Downloads, Desktop, Documents as Windows actually locates them."""
    try:
        import pywintypes
        from win32com.shell import shell

        return [Path(shell.SHGetKnownFolderPath(pywintypes.IID(fid), 0, None)) for fid in KNOWN_FOLDERS]
    except Exception:
        home = Path.home()
        return [home / "Downloads", home / "Desktop", home / "Documents"]


def document_title_from_window_title(title: str) -> str:
    """The document's own title once a browser's window-title suffix is removed."""
    return BROWSER_SUFFIX.sub("", title).strip()


def _normalize_title(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _recent_targets(recent_dir: Path, resolve_link: Callable[[Path], Path | None]) -> list[Path]:
    if not recent_dir.is_dir():
        return []
    targets = []
    for lnk in recent_dir.glob("*.lnk"):
        target = resolve_link(lnk)
        if target and target.is_file():
            targets.append(target)
    return targets


def _walk_files(folder: Path, depth: int = SEARCH_DEPTH):
    try:
        entries = list(folder.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.is_file():
            yield entry
        elif depth > 0 and entry.is_dir():
            yield from _walk_files(entry, depth - 1)


def find_pdf_by_metadata_title(
    title: str,
    recent_dir: Path,
    search_dirs: list[Path],
    resolve_link: Callable[[Path], Path | None] = resolve_shortcut,
    limit: int = METADATA_SEARCH_LIMIT,
) -> Path | None:
    """The newest PDF under the search folders whose metadata title matches ``title``."""
    wanted = _normalize_title(title)
    if len(wanted) < MIN_TITLE_CHARS:
        return None
    candidates = {p for p in _recent_targets(recent_dir, resolve_link) if p.suffix.lower() == ".pdf"}
    for folder in search_dirs:
        candidates.update(p for p in _walk_files(folder) if p.suffix.lower() == ".pdf")
    newest_first = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    if not newest_first:
        return None
    import pymupdf

    for path in newest_first:
        try:
            with pymupdf.open(path) as pdf:
                meta_title = (pdf.metadata or {}).get("title") or ""
        except Exception:
            continue
        if _normalize_title(meta_title) == wanted:
            return path
    return None


def find_file_by_name(
    name: str,
    recent_dir: Path,
    search_dirs: list[Path],
    resolve_link: Callable[[Path], Path | None] = resolve_shortcut,
) -> Path | None:
    wanted = name.lower()
    matches: list[Path] = []

    if recent_dir.is_dir():
        for lnk in recent_dir.glob("*.lnk"):
            if lnk.stem.lower() != wanted:
                continue
            target = resolve_link(lnk)
            if target and target.name.lower() == wanted and target.is_file():
                matches.append(target)

    for folder in search_dirs:
        if not folder.is_dir():
            continue
        for pattern in SEARCH_DEPTH_PATTERNS:
            for hit in folder.glob(pattern.format(name=name)):
                if hit.name.lower() == wanted and hit.is_file():
                    matches.append(hit)

    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def resolve_source(
    candidate: Candidate | None,
    cmdline: Callable[[int], list[str]] = psutil_cmdline,
    recent_dir: Path | None = None,
    search_dirs: list[Path] | None = None,
) -> FileSource | CaptureSource:
    if candidate is None:
        raise UserFacingError(NO_CANDIDATE_MESSAGE)

    # Deviation from spec §5.2 (command line first): a browser keeps the file it was
    # launched with on its command line for its whole life, so when the title names a
    # different file the command line is stale and the title wins. The command line is
    # trusted on its own only when the title names no file at all.
    names = filename_candidates(candidate.title)
    from_args = path_from_cmdline(cmdline(candidate.pid))
    if from_args and (not names or from_args.name.lower() in {n.lower() for n in names}):
        return FileSource(from_args)

    recent = recent_dir if recent_dir is not None else recent_items_dir()
    dirs = search_dirs if search_dirs is not None else default_search_dirs()
    for name in names:
        found = find_file_by_name(name, recent, dirs)
        if found:
            return FileSource(found)

    # Browsers show a PDF's metadata title (sometimes followed by " - filename"); a
    # downloaded copy may carry another filename but the same metadata title.
    doc_title = document_title_from_window_title(candidate.title)
    if names:  # drop a trailing " - <filename>" so only the document title remains
        doc_title = re.sub(r"\s+[-–—|]\s+" + re.escape(names[0]) + r"$", "", doc_title)
    found = find_pdf_by_metadata_title(doc_title, recent, dirs)
    if found:
        return FileSource(found)

    return CaptureSource(candidate.hwnd, candidate.title)
