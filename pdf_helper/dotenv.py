"""Load KEY=VALUE pairs from the project's .env file into the environment.

The API key lives in `.env` next to ReadableDocument.pyw (git-ignored). Values
already present in the environment win, so a system-wide ANTHROPIC_API_KEY
still takes precedence.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


def parse_dotenv(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and " " not in key:
            values[key] = value
    return values


def load_dotenv(path: Path = DEFAULT_ENV_FILE) -> set[str]:
    """Set variables from the file that are not already set; return the names set."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    loaded: set[str] = set()
    for key, value in parse_dotenv(text).items():
        if key not in os.environ:
            os.environ[key] = value
            loaded.add(key)
    return loaded
