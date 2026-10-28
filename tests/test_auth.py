import pytest

from yahoo_fantasy_mcp import auth
from yahoo_fantasy_mcp.config import ConfigError


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("YAHOO_CLIENT_ID", "id123")
    monkeypatch.setenv("YAHOO_CLIENT_SECRET", "secret")
    monkeypatch.setenv("YAHOO_REDIRECT_URI", "https://localhost:8000/callback")


def test_authorization_url():
    url = auth.authorization_url("abc")
    assert url.startswith("https://api.login.yahoo.com/oauth2/request_auth?client_id=id123&")
    assert "redirect_uri=https%3A%2F%2Flocalhost%3A8000%2Fcallback" in url
    assert url.endswith("state=abc")


def test_extract_code():
    assert auth.extract_code("https://localhost:8000/callback?code=XYZ&state=abc", "abc") == "XYZ"
    assert auth.extract_code("  XYZ  ") == "XYZ"
    with pytest.raises(ConfigError, match="state"):
        auth.extract_code("https://localhost:8000/callback?code=XYZ&state=other", "abc")
    with pytest.raises(ConfigError, match="access_denied"):
        auth.extract_code("https://localhost:8000/callback?error=access_denied")
