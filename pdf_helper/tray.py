"""Tray icon and the foreground-window tracker that remembers the last document window."""

import os
import threading
import time
from typing import Callable

from PIL import Image, ImageDraw

from .window_finder import Candidate

SHELL_CLASSES = frozenset({
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "Progman",
    "WorkerW",
    "Windows.UI.Core.CoreWindow",
    "NotifyIconOverflowWindow",
    # Windows 11 shell flyouts: the tray overflow (opened to reach this very icon),
    # Start/search hosts, and XAML popups. All titled, visible and not ours.
    "TopLevelWindowForOverflowXamlIsland",
    "XamlExplorerHostIslandWindow",
    "Xaml_WindowedPopupClass",
    "#32768",  # popup menus
    "tooltips_class32",
})
ICON_SIZE = 64
POLL_SECONDS = 0.5
MIN_CANDIDATE_SIDE = 200  # same floor as capture.MIN_SIDE: smaller windows cannot be read anyway

WindowEntry = tuple[int, str, str, int, bool, int, int]  # hwnd, title, class, pid, visible, width, height


def accept_window(title: str, cls: str, pid: int, own_pid: int, visible: bool,
                  width: int | None = None, height: int | None = None) -> bool:
    if not title or not visible or cls in SHELL_CLASSES or pid == own_pid:
        return False
    if width is not None and height is not None:
        if width < MIN_CANDIDATE_SIDE or height < MIN_CANDIDATE_SIDE:
            return False
    return True


def pick_topmost(entries: list[WindowEntry], own_pid: int) -> Candidate | None:
    """First acceptable window in a top-to-bottom Z-order listing."""
    for hwnd, title, cls, pid, visible, width, height in entries:
        if accept_window(title, cls, pid, own_pid, visible, width, height):
            return Candidate(hwnd, title, pid, cls)
    return None


class ReadGate:
    """Lets one read pass run at a time and swallows the second click of a double-click.

    pystray fires the default menu item on every left-button-up, and a double-click
    delivers two of those, so without this gate one click opened two windows.
    """

    def __init__(self, debounce_seconds: float = 1.0):
        self._debounce = debounce_seconds
        self._lock = threading.Lock()
        self._busy = False
        self._last_start = float("-inf")

    def try_acquire(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._busy or now - self._last_start < self._debounce:
                return False
            self._busy = True
            self._last_start = now
            return True

    def release(self) -> None:
        with self._lock:
            self._busy = False


def _window_size(hwnd: int) -> tuple[int, int]:
    import win32gui

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return right - left, bottom - top


def _is_cloaked(hwnd: int) -> bool:
    """UWP windows that are suspended or on another virtual desktop report visible but are cloaked."""
    import ctypes

    cloaked = ctypes.c_int(0)
    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        ctypes.c_void_p(hwnd), ctypes.c_uint(14), ctypes.byref(cloaked), ctypes.sizeof(cloaked)
    )
    return result == 0 and cloaked.value != 0


def find_topmost_window() -> Candidate | None:
    """The most prominent window on screen: top of the Z-order that is not shell, hidden or ours."""
    import win32gui
    import win32process

    entries: list[WindowEntry] = []

    def visit(hwnd: int, _) -> None:
        try:
            visible = bool(win32gui.IsWindowVisible(hwnd)) and not _is_cloaked(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            width, height = _window_size(hwnd)
            entries.append((hwnd, win32gui.GetWindowText(hwnd), win32gui.GetClassName(hwnd),
                            pid, visible, width, height))
        except Exception:
            pass

    win32gui.EnumWindows(visit, None)  # EnumWindows yields top-level windows in Z-order
    return pick_topmost(entries, os.getpid())


class ForegroundTracker:
    """Polls the foreground window and keeps the last one that looks like a document window."""

    def __init__(self, poll_seconds: float = POLL_SECONDS):
        self._poll_seconds = poll_seconds
        self._lock = threading.Lock()
        self._candidate: Candidate | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="foreground-tracker", daemon=True)

    @property
    def candidate(self) -> Candidate | None:
        with self._lock:
            return self._candidate

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        import win32gui
        import win32process

        own_pid = os.getpid()
        while not self._stop.wait(self._poll_seconds):
            try:
                hwnd = win32gui.GetForegroundWindow()
                if not hwnd:
                    continue
                title = win32gui.GetWindowText(hwnd)
                cls = win32gui.GetClassName(hwnd)
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                visible = bool(win32gui.IsWindowVisible(hwnd))
                width, height = _window_size(hwnd)
            except Exception:
                continue
            if accept_window(title, cls, pid, own_pid, visible, width, height):
                with self._lock:
                    self._candidate = Candidate(hwnd, title, pid, cls)


def make_icon_image() -> Image.Image:
    """A page with three text lines, drawn at 64x64."""
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((12, 6, 52, 58), radius=6, fill="#FAF7F0", outline="#2F6F9F", width=3)
    for y in (20, 30, 40):
        draw.rounded_rectangle((20, y, 44, y + 4), radius=2, fill="#2F6F9F")
    draw.rounded_rectangle((20, 48, 34, 52), radius=2, fill="#2F6F9F")
    return img


def build_icon(on_read: Callable[[], None], on_quit: Callable[[], None]):
    import pystray

    menu = pystray.Menu(
        pystray.MenuItem("Read document", lambda icon, item: on_read(), default=True),
        pystray.MenuItem("Quit", lambda icon, item: on_quit()),
    )
    return pystray.Icon("readable-document", make_icon_image(), "Readable Document", menu=menu)
