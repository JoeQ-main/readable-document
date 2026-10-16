"""Launcher without a console window. Double-click, or make a shortcut to it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdf_helper.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
