"""User-facing errors and the app's data directory."""

import os
from pathlib import Path


class UserFacingError(Exception):
    """An error whose message is shown to the user as-is."""


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / "PDFHelper"
    path.mkdir(parents=True, exist_ok=True)
    return path
