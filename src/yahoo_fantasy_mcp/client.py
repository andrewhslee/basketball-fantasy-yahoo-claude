"""Thin HTTP wrapper around the Yahoo Fantasy Sports v2 API.

Yahoo's XML is used rather than its JSON: the JSON output uses numbered object keys
instead of arrays, and writes (if Yahoo ever grants them) must be sent as XML anyway.
"""

import logging

import httpx
import xmltodict

from yahoo_fantasy_mcp import auth

BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2/"

log = logging.getLogger(__name__)


class YahooAPIError(RuntimeError):
    pass


def _error_description(text: str) -> str:
    try:
        return xmltodict.parse(text)["error"]["description"]
    except Exception:
        return text[:300]


class YahooClient:
    def __init__(self, token_provider=auth.access_token, http: httpx.Client | None = None):
        self._token = token_provider
        self._http = http or httpx.Client(base_url=BASE_URL, timeout=30)

    def get(self, path: str) -> dict:
        """GET a resource path such as 'league/466.l.123/settings' and return <fantasy_content> as a dict."""
        return self._request("GET", path)

    def _request(self, method: str, path: str, body: str | None = None) -> dict:
        headers = {"Content-Type": "application/xml"} if body else {}
        response = None
        for attempt in range(2):
            headers["Authorization"] = f"Bearer {self._token(force_refresh=attempt > 0)}"
            log.debug("%s %s", method, path)
            response = self._http.request(method, path.lstrip("/"), content=body, headers=headers)
            if response.status_code != 401:
                break
        assert response is not None
        if response.status_code == 403:
            raise YahooAPIError(
                "Yahoo says this app isn't authorized (403): "
                f"{_error_description(response.text)}. New apps may need approval at "
                "https://sports.yahoo.com/developer/access/ before the Fantasy API works."
            )
        if response.status_code == 999:
            raise YahooAPIError("Yahoo is rate-limiting requests (HTTP 999). Wait a few minutes and try again.")
        if response.status_code >= 400:
            raise YahooAPIError(f"Yahoo API error {response.status_code} on {path}: {_error_description(response.text)}")
        return xmltodict.parse(response.text)["fantasy_content"]
