"""A local cache of transcriptions, so reading the same document twice does not
call the Claude API again.

Entries live in %APPDATA%/PDFHelper/cache/<key>.json, where the key is a SHA-256
of the document bytes plus whatever else shapes the output (model name, chunk
size, instruction). Each file holds the model, a timestamp, the title and the
transcribed blocks. The newest entries are kept up to MAX_BYTES; the oldest by
modification time are pruned, and a hit refreshes an entry's time."""

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

from .errors import app_data_dir
from .extract.model import Block

MAX_BYTES = 200 * 1024 * 1024
BLOCK_KINDS = frozenset({"heading", "paragraph", "list_item"})
_KEY = re.compile(r"^[0-9a-f]{64}$")


def cache_dir() -> Path:
    path = app_data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def key(data: bytes, *tags: str) -> str:
    """SHA-256 over the document bytes and the tags that change its transcription."""
    digest = hashlib.sha256(data)
    for tag in tags:
        digest.update(b"\0")
        digest.update(tag.encode("utf-8"))
    return digest.hexdigest()


def _path(key: str, directory: Path | None) -> Path | None:
    if not _KEY.match(key):
        return None
    return (directory if directory is not None else cache_dir()) / f"{key}.json"


def get(key: str, directory: Path | None = None) -> list[Block] | None:
    """The cached blocks for this key, or None. A hit counts as a recent use."""
    path = _path(key, directory)
    if path is None:
        return None
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        blocks = [Block(b["kind"], b["text"], int(b["level"])) for b in entry["blocks"]]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if any(b.kind not in BLOCK_KINDS or not isinstance(b.text, str) for b in blocks):
        return None
    try:
        os.utime(path)
    except OSError:
        pass
    return blocks


def put(key: str, blocks: list[Block], title: str, model: str,
        directory: Path | None = None, max_bytes: int = MAX_BYTES) -> None:
    path = _path(key, directory)
    if path is None:
        return
    entry = {
        "model": model,
        "created": datetime.now().isoformat(timespec="seconds"),
        "title": title,
        "blocks": [{"kind": b.kind, "level": b.level, "text": b.text} for b in blocks],
    }
    temp = path.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        temp.unlink(missing_ok=True)
        return
    prune(path.parent, max_bytes)


def prune(directory: Path, max_bytes: int = MAX_BYTES) -> None:
    """Delete the oldest entries until the newest ones fit in max_bytes."""
    entries = []
    for file in directory.glob("*.json"):
        try:
            stat = file.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, file))
    entries.sort(reverse=True)
    total = 0
    for _, size, file in entries:
        total += size
        if total > max_bytes:
            file.unlink(missing_ok=True)


def clear(directory: Path | None = None) -> int:
    """Delete everything in the cache folder; returns the number of bytes freed."""
    folder = directory if directory is not None else cache_dir()
    freed = 0
    if not folder.is_dir():
        return 0
    for file in folder.iterdir():
        try:
            if file.is_file():
                size = file.stat().st_size
                file.unlink()
                freed += size
        except OSError:
            continue
    return freed


def describe_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} bytes"
