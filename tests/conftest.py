from pathlib import Path

import pytest
import xmltodict

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return xmltodict.parse((FIXTURES / name).read_text())["fantasy_content"]


class FakeYahoo:
    """Stands in for YahooClient: answers each path from a saved fixture and records the paths."""

    routes = [
        ("/teams", "user_teams.xml"),
        ("/leagues", "user_leagues.xml"),
        ("/settings", "league_settings.xml"),
        ("/roster", "roster.xml"),
        ("/ownership", "players_ownership.xml"),
        ("/matchups", "matchup.xml"),
        ("/stats", "players_stats.xml"),
    ]

    def __init__(self):
        self.paths = []

    def get(self, path: str) -> dict:
        self.paths.append(path)
        if path.startswith("team/") and path.split(";")[0].endswith("/stats"):
            from yahoo_fantasy_mcp.client import YahooAPIError

            raise YahooAPIError("no team totals in fixtures")
        for marker, fixture in self.routes:
            if marker in path:
                return load(fixture)
        raise AssertionError(f"No fixture for {path}")


@pytest.fixture
def fake_yahoo(monkeypatch, tmp_path):
    from yahoo_fantasy_mcp import prefs, server

    fake = FakeYahoo()
    monkeypatch.setattr(server, "_client", fake)
    monkeypatch.setattr(server, "_settings_cache", {})
    monkeypatch.setattr(prefs, "PREFS_PATH", tmp_path / "prefs.json")
    monkeypatch.setattr("yahoo_fantasy_mcp.config.CONFIG_DIR", tmp_path)
    return fake
