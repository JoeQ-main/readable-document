"""User-facing errors, message boxes, the error log and the app's data directory."""

import os
import traceback
from datetime import datetime
from pathlib import Path

APP_TITLE = "Readable Document"
MB_ICONWARNING = 0x30
MB_TOPMOST = 0x40000


class UserFacingError(Exception):
    """An error whose message is shown to the user as-is."""


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / "PDFHelper"
    path.mkdir(parents=True, exist_ok=True)
    return path


def show_error(message: str, title: str = APP_TITLE) -> None:
    import ctypes

    ctypes.windll.user32.MessageBoxW(None, message, title, MB_ICONWARNING | MB_TOPMOST)


def log_exception(exc: BaseException) -> None:
    with (app_data_dir() / "error.log").open("a", encoding="utf-8") as log:
        log.write(datetime.now().isoformat(timespec="seconds") + "\n")
        log.write("".join(traceback.format_exception(exc)))
        log.write("\n")
