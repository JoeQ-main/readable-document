"""Persisted reading preferences (toolbar toggles)."""

import json
from pathlib import Path

from .errors import app_data_dir

DEFAULTS: dict = {
    "size": 19,
    "leading": 1.75,
    "measure": 62,
    "dark": False,
    "numbers": True,
    "bionic": False,
}


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def _accepts(key: str, value) -> bool:
    default = DEFAULTS[key]
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if isinstance(default, float):
        return isinstance(value, (int, float))
    return isinstance(value, type(default))


def _sanitize(raw: dict) -> dict:
    prefs = dict(DEFAULTS)
    for key, value in raw.items():
        if key in DEFAULTS and _accepts(key, value):
            prefs[key] = value
    return prefs


def load_prefs(path: Path | None = None) -> dict:
    path = path or settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULTS)
    if not isinstance(raw, dict):
        return dict(DEFAULTS)
    return _sanitize(raw)


def save_prefs(prefs: dict, path: Path | None = None) -> dict:
    path = path or settings_path()
    merged = load_prefs(path)
    merged.update(_sanitize({**merged, **prefs}))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged
