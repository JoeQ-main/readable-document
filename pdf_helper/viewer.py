"""The reading window: a pywebview window plus the JS bridge for Save and prefs."""

import re
from pathlib import Path
from typing import Callable

from .extract.model import Document
from .readable.transform import render
from .settings import load_prefs, save_prefs, settings_path

WINDOW_WIDTH = 960
WINDOW_HEIGHT = 1000
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

Dialog = Callable[[Path, str], Path | None]


def documents_dir() -> Path:
    return Path.home() / "Documents"


def safe_filename(title: str) -> str:
    name = INVALID_FILENAME_CHARS.sub("_", title).strip()
    return f"{name or 'document'}-readable.html"


class Api:
    """Methods callable from the page as window.pywebview.api.<name>."""

    def __init__(self, doc: Document, dialog: Dialog | None = None):
        self._doc = doc
        self._dialog = dialog or self._native_dialog
        # Private on purpose: pywebview serializes every public attribute of js_api
        # into the page, and a native window object recurses forever.
        self._window = None  # set by open_document

    def attach(self, window) -> None:
        self._window = window

    def _native_dialog(self, directory: Path, filename: str) -> Path | None:
        import webview

        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG, directory=str(directory), save_filename=filename
        )
        if not result:
            return None
        if isinstance(result, (tuple, list)):
            result = result[0]
        return Path(result)

    def save(self, html: str) -> str | None:
        target = self._dialog(documents_dir(), safe_filename(self._doc.title))
        if target is None:
            return None
        target.write_text(html, encoding="utf-8")
        return str(target)

    def get_prefs(self) -> dict:
        return load_prefs(settings_path())

    def set_prefs(self, prefs: dict) -> dict:
        return save_prefs(prefs, settings_path())


def open_document(doc: Document):
    import webview

    api = Api(doc)
    html = render(doc, load_prefs(settings_path()))
    window = webview.create_window(
        title=f"Readable: {doc.title}",
        html=html,
        js_api=api,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
    )
    api.attach(window)
    return window
