"""The reading window: a pywebview window plus the JS bridge for Save and prefs."""

import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from .extract.model import Document
from .readable.transform import render
from .settings import load_prefs, save_prefs, settings_path

WINDOW_WIDTH = 960
WINDOW_HEIGHT = 1000
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

Dialog = Callable[[Path, str], Path | None]


class PageServer:
    """Serves rendered pages from memory on 127.0.0.1 under unguessable tokens.

    WebView2 refuses html strings above 2 MB (and a failed window breaks later
    ones), so the reading window loads its page over HTTP instead. Nothing is
    written to disk; a page is forgotten when its window closes.
    """

    def __init__(self) -> None:
        self._pages: dict[str, bytes] = {}
        self._lock = threading.Lock()
        pages, lock = self._pages, self._lock

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - http.server API
                with lock:
                    body = pages.get(self.path.lstrip("/"))
                if body is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:  # silence request logging
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="page-server", daemon=True)
        self._thread.start()

    @property
    def address(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def publish(self, html: str) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._pages[token] = html.encode("utf-8")
        return f"{self.address}/{token}"

    def release(self, url: str) -> None:
        with self._lock:
            self._pages.pop(url.rsplit("/", 1)[-1], None)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


_page_server: PageServer | None = None
_page_server_lock = threading.Lock()


def page_server() -> PageServer:
    global _page_server
    with _page_server_lock:
        if _page_server is None:
            _page_server = PageServer()
        return _page_server


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
    server = page_server()
    url = server.publish(render(doc, load_prefs(settings_path())))
    window = webview.create_window(
        title=f"Readable: {doc.title}",
        url=url,
        js_api=api,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
    )
    api.attach(window)
    window.events.closed += lambda: server.release(url)
    return window
