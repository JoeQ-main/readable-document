"""Manual check for window capture: run, then click any window within 3 seconds.

The captured image opens in the default image viewer; the method printed is
"window" (PrintWindow, only that window's content) or "screen" (fallback).
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import win32gui  # noqa: E402

from pdf_helper.capture import capture_window  # noqa: E402

if __name__ == "__main__":
    print("Click the window to capture...")
    time.sleep(3)
    hwnd = win32gui.GetForegroundWindow()
    image, method = capture_window(hwnd)
    print("title:", win32gui.GetWindowText(hwnd))
    print("method:", method, "size:", image.size)
    image.show()
