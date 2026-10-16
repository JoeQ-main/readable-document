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


def filename_from_title(title: str) -> str | None:
    m = TITLE_FILENAME.search(title)
    if not m:
        return None
    return re.split(r"[\\/]", m.group(1))[-1].strip()


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
    home = Path.home()
    return [home / "Downloads", home / "Desktop", home / "Documents"]


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
    name = filename_from_title(candidate.title)
    from_args = path_from_cmdline(cmdline(candidate.pid))
    if from_args and (name is None or from_args.name.lower() == name.lower()):
        return FileSource(from_args)

    if name:
        found = find_file_by_name(
            name,
            recent_dir if recent_dir is not None else recent_items_dir(),
            search_dirs if search_dirs is not None else default_search_dirs(),
        )
        if found:
            return FileSource(found)

    return CaptureSource(candidate.hwnd, candidate.title)
