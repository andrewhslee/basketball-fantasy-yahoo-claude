from conftest import load

from yahoo_fantasy_mcp.parse import (
    label_stats,
    match_stats,
    number,
    parse_league_players,
    parse_league_settings,
    parse_matchups,
    parse_roster,
    parse_user_teams,
)


def test_number():
    assert number("12") == 12
    assert number(".455") == 0.455
    assert number("-") is None
    assert number("40/88") == "40/88"


def test_user_teams():
    teams = parse_user_teams(load("user_teams.xml"))
    assert teams == [
        {
            "team_key": "466.l.12345.t.3",
            "name": "Splash Zone",
            "url": "https://basketball.fantasysports.yahoo.com/nba/12345/3",
            "league_key": "466.l.12345",
            "season": "2026",
        }
    ]


def test_league_settings():
    settings = parse_league_settings(load("league_settings.xml"))
    assert settings["uses_faab"] is True
    assert settings["max_weekly_adds"] == 4
    slots = {p["position"]: (p["count"], p["is_starting"]) for p in settings["roster_positions"]}
    assert slots["PG"] == (1, True)
    assert slots["BN"] == (2, False)
    fgma = next(c for c in settings["stat_categories"] if c["stat_id"] == "9004003")
    assert fgma["display_only"] is True


def test_roster():
    roster = parse_roster(load("roster.xml"))
    assert roster["date"] == "2026-10-29"
    jokic = next(p for p in roster["players"] if p["player_id"] == "6004")
    assert jokic["selected_position"] == "C"
    assert jokic["is_editable"] is False
    assert jokic["eligible_positions"] == ["C", "Util"]
    kawhi = next(p for p in roster["players"] if p["player_id"] == "6008")
    assert kawhi["status"] == "O"


def test_player_stats_and_labels():
    players = parse_league_players(load("players_stats.xml"))
    hali = players[0]
    assert hali["stats"]["12"] == 110
    assert hali["stats"]["19"] is None
    categories = parse_league_settings(load("league_settings.xml"))["stat_categories"]
    assert label_stats(hali["stats"], categories, ["16", "12"]) == {"AST": 48, "PTS": 110}
    assert list(label_stats(hali["stats"], categories))[:3] == ["FGM/A", "FG%", "FT%"]


def test_match_stats():
    categories = parse_league_settings(load("league_settings.xml"))["stat_categories"]
    ids, unknown = match_stats(["pts", "Threes", "fg%", "Assists", "steals", "dunks"], categories)
    assert ids == ["12", "10", "5", "16", "17"]
    assert unknown == ["dunks"]


def test_matchups():
    (m,) = parse_matchups(load("matchup.xml"))
    assert m["week"] == 1
    assert m["stat_winners"] == {"12": "466.l.12345.t.3", "15": "466.l.12345.t.5", "16": "tie"}
    assert m["teams"][0]["games"] == {"remaining": 12, "live": 0, "completed": 20}
    assert m["teams"][1]["games"] is None
