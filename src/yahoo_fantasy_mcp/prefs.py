"""Small JSON file for things the user picks once: default team and favorite stats."""

import json

from yahoo_fantasy_mcp.config import PREFS_PATH, ensure_config_dir


def load() -> dict:
    if PREFS_PATH.exists():
        return json.loads(PREFS_PATH.read_text())
    return {}


def save(prefs: dict) -> None:
    ensure_config_dir()
    PREFS_PATH.write_text(json.dumps(prefs, indent=2))


def get(key: str, default=None):
    return load().get(key, default)


def put(key: str, value) -> None:
    prefs = load()
    prefs[key] = value
    save(prefs)
