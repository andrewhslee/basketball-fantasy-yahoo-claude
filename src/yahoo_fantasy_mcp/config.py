"""Paths and credentials shared by the login command and the MCP server."""

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

CONFIG_DIR = Path(os.environ.get("YAHOO_FANTASY_MCP_HOME", Path.home() / ".config" / "yahoo-fantasy-mcp"))
TOKENS_PATH = CONFIG_DIR / "tokens.json"
PREFS_PATH = CONFIG_DIR / "prefs.json"

DEFAULT_REDIRECT_URI = "https://localhost:8000/callback"

# Credentials can live in the project's .env or in ~/.config/yahoo-fantasy-mcp/.env.
load_dotenv(CONFIG_DIR / ".env")
load_dotenv(find_dotenv(usecwd=True))
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class ConfigError(RuntimeError):
    """Something the user has to set up before the server can talk to Yahoo."""


def client_credentials() -> tuple[str, str, str]:
    client_id = os.environ.get("YAHOO_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YAHOO_CLIENT_SECRET", "").strip()
    redirect_uri = os.environ.get("YAHOO_REDIRECT_URI", "").strip() or DEFAULT_REDIRECT_URI
    if not client_id or not client_secret:
        raise ConfigError(
            "YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET are not set. Copy .env.example to .env "
            "in the project folder and fill in the values from your Yahoo developer app."
        )
    return client_id, client_secret, redirect_uri


def ensure_config_dir() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.chmod(0o700)
    return CONFIG_DIR
