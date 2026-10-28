"""Yahoo OAuth 2.0: one-time interactive login, token storage and automatic refresh.

Yahoo removed the copy-paste "oob" flow, so login uses a redirect URI. The browser
lands on that URI (which doesn't need to load) and the user pastes the URL back here.
"""

import json
import secrets
import time
import webbrowser
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from yahoo_fantasy_mcp.config import TOKENS_PATH, ConfigError, client_credentials, ensure_config_dir

AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"

# Refresh a little before Yahoo's one-hour expiry.
EXPIRY_MARGIN_SECONDS = 120


def authorization_url(state: str) -> str:
    client_id, _, redirect_uri = client_credentials()
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "language": "en-us",
            "state": state,
        }
    )
    return f"{AUTH_URL}?{query}"


def extract_code(pasted: str, expected_state: str | None = None) -> str:
    """Accept either the full redirected URL or just the code."""
    pasted = pasted.strip()
    if "://" not in pasted and "code=" not in pasted:
        return pasted
    params = parse_qs(urlparse(pasted).query) if "://" in pasted else parse_qs(pasted)
    if "error" in params:
        raise ConfigError(f"Yahoo returned an error: {params['error'][0]}")
    if "code" not in params:
        raise ConfigError("Couldn't find a 'code=' value in what you pasted.")
    if expected_state and params.get("state", [expected_state])[0] != expected_state:
        raise ConfigError("The 'state' value doesn't match this login attempt. Start the login again.")
    return params["code"][0]


def _token_request(form: dict[str, str]) -> dict:
    client_id, client_secret, redirect_uri = client_credentials()
    response = httpx.post(
        TOKEN_URL,
        data={"redirect_uri": redirect_uri, **form},
        auth=(client_id, client_secret),
        timeout=30,
    )
    if response.status_code != 200:
        raise ConfigError(f"Yahoo token request failed ({response.status_code}): {response.text[:300]}")
    tokens = response.json()
    tokens["expires_at"] = time.time() + int(tokens.get("expires_in", 3600))
    return tokens


def save_tokens(tokens: dict) -> None:
    ensure_config_dir()
    TOKENS_PATH.write_text(json.dumps(tokens, indent=2))
    TOKENS_PATH.chmod(0o600)


def load_tokens() -> dict:
    if not TOKENS_PATH.exists():
        raise ConfigError("Not signed in to Yahoo yet. Run `uv run yahoo-fantasy-mcp login` in the project folder.")
    return json.loads(TOKENS_PATH.read_text())


def exchange_code(code: str) -> dict:
    tokens = _token_request({"grant_type": "authorization_code", "code": code})
    save_tokens(tokens)
    return tokens


def refresh(tokens: dict) -> dict:
    if not tokens.get("refresh_token"):
        raise ConfigError("Saved Yahoo tokens have no refresh token. Run `uv run yahoo-fantasy-mcp login` again.")
    fresh = _token_request({"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]})
    # Yahoo normally returns a new refresh token, but keep the old one if it doesn't.
    fresh.setdefault("refresh_token", tokens["refresh_token"])
    save_tokens(fresh)
    return fresh


def access_token(force_refresh: bool = False) -> str:
    tokens = load_tokens()
    if force_refresh or tokens.get("expires_at", 0) - EXPIRY_MARGIN_SECONDS < time.time():
        tokens = refresh(tokens)
    return tokens["access_token"]


def login_interactive() -> None:
    state = secrets.token_urlsafe(16)
    url = authorization_url(state)
    print("Opening Yahoo in your browser. If it doesn't open, visit this URL:\n")
    print(f"  {url}\n")
    webbrowser.open(url)
    print(
        "After you click 'Agree', the browser goes to a localhost page that won't load.\n"
        "That's expected. Copy the full URL from the address bar and paste it here.\n"
    )
    code = extract_code(input("Redirected URL: "), expected_state=state)
    exchange_code(code)
    print(f"\nSigned in. Tokens saved to {TOKENS_PATH} (readable only by you).")
