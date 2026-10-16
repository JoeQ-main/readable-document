"""Capture a single window's pixels for OCR, without touching the rest of the screen."""

import ctypes
import time
from ctypes import wintypes

from PIL import Image, ImageGrab

from .errors import UserFacingError

MIN_SIDE = 200
DWMWA_EXTENDED_FRAME_BOUNDS = 9
PW_RENDERFULLCONTENT = 2
FOREGROUND_SETTLE_SECONDS = 0.3

try:  # physical pixels everywhere, so window rectangles line up with screen grabs
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:  # pragma: no cover - older Windows or already set
    pass


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), ctypes.c_uint(DWMWA_EXTENDED_FRAME_BOUNDS),
        ctypes.byref(rect), ctypes.sizeof(rect),
    )
    if result == 0:
        return rect.left, rect.top, rect.right, rect.bottom
    import win32gui

    return win32gui.GetWindowRect(hwnd)


def is_flat(image: Image.Image) -> bool:
    """True when every band is a single value, i.e. nothing was rendered."""
    extrema = image.getextrema()
    if isinstance(extrema[0], tuple):
        return all(lo == hi for lo, hi in extrema)
    return extrema[0] == extrema[1]


def _print_window(hwnd: int, width: int, height: int) -> Image.Image | None:
    import win32gui
    import win32ui

    window_dc = win32gui.GetWindowDC(hwnd)
    src_dc = win32ui.CreateDCFromHandle(window_dc)
    mem_dc = src_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    try:
        bitmap.CreateCompatibleBitmap(src_dc, width, height)
        mem_dc.SelectObject(bitmap)
        ok = ctypes.windll.user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
        if not ok:
            return None
        bits = bitmap.GetBitmapBits(True)
        return Image.frombuffer("RGB", (width, height), bits, "raw", "BGRX", 0, 1)
    finally:
        try:
            win32gui.DeleteObject(bitmap.GetHandle())
        except Exception:
            pass
        mem_dc.DeleteDC()
        src_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, window_dc)


def _grab_screen(hwnd: int, rect: tuple[int, int, int, int]) -> Image.Image:
    import win32gui

    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:  # another process holds focus; grab anyway
        pass
    time.sleep(FOREGROUND_SETTLE_SECONDS)
    return ImageGrab.grab(bbox=rect, all_screens=True)


def capture_window(hwnd: int) -> tuple[Image.Image, str]:
    """Return (image, method); method is "window" (PrintWindow) or "screen" (fallback)."""
    left, top, right, bottom = window_rect(hwnd)
    width, height = right - left, bottom - top
    if width < MIN_SIDE or height < MIN_SIDE:
        raise UserFacingError("The window is too small to read.")

    try:
        image = _print_window(hwnd, width, height)
    except Exception:
        image = None
    if image is not None and not is_flat(image):
        return image, "window"
    return _grab_screen(hwnd, (left, top, right, bottom)), "screen"
