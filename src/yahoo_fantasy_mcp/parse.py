"""Turn Yahoo's XML (already converted to dicts by xmltodict) into small, clean dicts.

xmltodict gives a dict for a single child element and a list for repeated ones, and
attributes such as count="3" show up as "@count". The helpers below hide that.
"""

import re
import unicodedata
from typing import Any


def as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def dig(node: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def text(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("#text")
    return value


def flag(value: Any) -> bool:
    return text(value) in ("1", "true", 1, True)


def number(value: Any) -> Any:
    """Yahoo sends every value as text; turn '12' into 12, '.512' into 0.512 and '-' into None."""
    value = text(value)
    if value is None or value in ("-", ""):
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return value  # e.g. '47/98' for FGM/A
    return int(as_float) if as_float.is_integer() and "." not in value else as_float


def league_key_of(team_key: str) -> str:
    return team_key.split(".t.")[0]


# ---------------------------------------------------------------- user / league


def parse_user_teams(fc: dict) -> list[dict]:
    teams = []
    for game in as_list(dig(fc, "users", "user", "games", "game")):
        for team in as_list(dig(game, "teams", "team")):
            teams.append(
                {
                    "team_key": team.get("team_key"),
                    "name": team.get("name"),
                    "url": team.get("url"),
                    "league_key": league_key_of(team.get("team_key", "")),
                    "season": game.get("season"),
                }
            )
    return teams


def parse_user_leagues(fc: dict) -> dict[str, dict]:
    leagues = {}
    for game in as_list(dig(fc, "users", "user", "games", "game")):
        for league in as_list(dig(game, "leagues", "league")):
            leagues[league.get("league_key")] = {
                "league_key": league.get("league_key"),
                "name": league.get("name"),
                "url": league.get("url"),
                "num_teams": number(league.get("num_teams")),
                "scoring_type": league.get("scoring_type"),
                "current_week": number(league.get("current_week")),
            }
    return leagues


def parse_stat_categories(settings: dict) -> list[dict]:
    categories = []
    for stat in as_list(dig(settings, "stat_categories", "stats", "stat")):
        if stat.get("enabled", "1") != "1":
            continue
        categories.append(
            {
                "stat_id": str(stat.get("stat_id")),
                "name": stat.get("name"),
                "abbr": stat.get("abbr") or stat.get("display_name"),
                "display_only": flag(stat.get("is_only_display_stat")),
                "sort_order": stat.get("sort_order"),
            }
        )
    return categories


def parse_league_settings(fc: dict) -> dict:
    league = fc.get("league", {})
    settings = league.get("settings", {})
    modifiers = {
        str(stat.get("stat_id")): number(stat.get("value"))
        for stat in as_list(dig(settings, "stat_modifiers", "stats", "stat"))
    }
    return {
        "league_key": league.get("league_key"),
        "name": league.get("name"),
        "url": league.get("url"),
        "num_teams": number(league.get("num_teams")),
        "scoring_type": league.get("scoring_type"),
        "current_week": number(league.get("current_week")),
        "start_date": league.get("start_date"),
        "end_date": league.get("end_date"),
        "uses_faab": flag(settings.get("uses_faab")),
        "waiver_type": settings.get("waiver_type"),
        "waiver_time_days": number(settings.get("waiver_time")),
        "max_weekly_adds": number(settings.get("max_weekly_adds")),
        "trade_end_date": settings.get("trade_end_date"),
        "roster_positions": [
            {
                "position": pos.get("position"),
                "count": number(pos.get("count")) or 0,
                "is_starting": flag(pos.get("is_starting_position"))
                if "is_starting_position" in pos
                else pos.get("position") not in BENCH_LIKE,
            }
            for pos in as_list(dig(settings, "roster_positions", "roster_position"))
        ],
        "stat_categories": parse_stat_categories(settings),
        "stat_modifiers": modifiers or None,
    }


BENCH_LIKE = {"BN", "IL", "IL+", "NA"}


# ---------------------------------------------------------------- players


def parse_stats(stats_node: Any) -> dict[str, Any]:
    return {str(s.get("stat_id")): number(s.get("value")) for s in as_list(dig(stats_node, "stats", "stat"))}


def parse_player(player: dict) -> dict:
    name = player.get("name") or {}
    parsed = {
        "player_key": player.get("player_key"),
        "player_id": player.get("player_id"),
        "name": name.get("full") if isinstance(name, dict) else name,
        "nba_team": player.get("editorial_team_abbr"),
        "positions": player.get("display_position"),
        "eligible_positions": [text(p) for p in as_list(dig(player, "eligible_positions", "position"))],
        "status": player.get("status"),
        "injury_note": player.get("injury_note"),
        "is_editable": flag(player.get("is_editable")) if "is_editable" in player else None,
    }
    selected = dig(player, "selected_position", "position")
    if selected is not None:
        parsed["selected_position"] = text(selected)
    starting = dig(player, "starting_status", "is_starting")
    if starting is not None:
        parsed["is_starting_nba"] = flag(starting)
    if "player_stats" in player:
        parsed["stats"] = parse_stats(player["player_stats"])
        parsed["stats_period"] = dig(player, "player_stats", "coverage_type")
    points = dig(player, "player_points", "total")
    if points is not None:
        parsed["fantasy_points"] = number(points)
    ownership = player.get("ownership")
    if isinstance(ownership, dict):
        parsed["ownership"] = {
            "type": ownership.get("ownership_type"),  # team, freeagents or waivers
            "owner_team_key": ownership.get("owner_team_key"),
            "owner_team_name": ownership.get("owner_team_name"),
            "waiver_date": ownership.get("waiver_date"),
        }
    owned = dig(player, "percent_owned", "value")
    if owned is not None:
        parsed["percent_owned"] = number(owned)
    return {k: v for k, v in parsed.items() if v not in (None, [], "")}


def parse_roster(fc: dict) -> dict:
    team = fc.get("team", {})
    roster = team.get("roster", {})
    return {
        "team_key": team.get("team_key"),
        "team_name": team.get("name"),
        "team_url": team.get("url"),
        "date": roster.get("date"),
        "week": roster.get("week"),
        "is_editable": flag(roster.get("is_editable")) if "is_editable" in roster else None,
        "players": [parse_player(p) for p in as_list(dig(roster, "players", "player"))],
    }


def parse_team_players(fc: dict) -> list[dict]:
    """team/{key}/roster/players/stats returns players under team.roster.players or team.players."""
    team = fc.get("team", {})
    players = dig(team, "roster", "players", "player") or dig(team, "players", "player")
    return [parse_player(p) for p in as_list(players)]


def parse_league_players(fc: dict) -> list[dict]:
    return [parse_player(p) for p in as_list(dig(fc, "league", "players", "player"))]


# ---------------------------------------------------------------- team-level


def parse_team_stats(fc: dict) -> dict:
    team = fc.get("team", {})
    return {
        "team_key": team.get("team_key"),
        "name": team.get("name"),
        "period": dig(team, "team_stats", "coverage_type"),
        "stats": parse_stats(team.get("team_stats")),
        "fantasy_points": number(dig(team, "team_points", "total")),
    }


def _matchup_team(team: dict) -> dict:
    remaining = dig(team, "team_remaining_games", "total") or {}
    return {
        "team_key": team.get("team_key"),
        "name": team.get("name"),
        "stats": parse_stats(team.get("team_stats")),
        "fantasy_points": number(dig(team, "team_points", "total")),
        "projected_points": number(dig(team, "team_projected_points", "total")),
        "games": {
            "remaining": number(remaining.get("remaining_games")),
            "live": number(remaining.get("live_games")),
            "completed": number(remaining.get("completed_games")),
        }
        if remaining
        else None,
    }


def parse_matchups(fc: dict) -> list[dict]:
    matchups = []
    for matchup in as_list(dig(fc, "team", "matchups", "matchup")):
        winners = {}
        for winner in as_list(dig(matchup, "stat_winners", "stat_winner")):
            stat_id = str(winner.get("stat_id"))
            winners[stat_id] = "tie" if flag(winner.get("is_tied")) else winner.get("winner_team_key")
        matchups.append(
            {
                "week": number(matchup.get("week")),
                "week_start": matchup.get("week_start"),
                "week_end": matchup.get("week_end"),
                "status": matchup.get("status"),
                "is_playoffs": flag(matchup.get("is_playoffs")),
                "teams": [_matchup_team(t) for t in as_list(dig(matchup, "teams", "team"))],
                "stat_winners": winners,
            }
        )
    return matchups


def parse_standings(fc: dict) -> list[dict]:
    standings = []
    for team in as_list(dig(fc, "league", "standings", "teams", "team")):
        totals = dig(team, "team_standings", "outcome_totals") or {}
        standings.append(
            {
                "rank": number(dig(team, "team_standings", "rank")),
                "team_key": team.get("team_key"),
                "name": team.get("name"),
                "manager": dig(team, "managers", "manager", "nickname")
                if not isinstance(dig(team, "managers", "manager"), list)
                else None,
                "wins": number(totals.get("wins")),
                "losses": number(totals.get("losses")),
                "ties": number(totals.get("ties")),
                "points_for": number(dig(team, "team_standings", "points_for")),
            }
        )
    return sorted(standings, key=lambda t: t["rank"] if t["rank"] is not None else 999)


# ---------------------------------------------------------------- stat names

STAT_ALIASES = {
    "points": "pts",
    "rebounds": "reb",
    "rebs": "reb",
    "assists": "ast",
    "asts": "ast",
    "steals": "st",
    "stl": "st",
    "stls": "st",
    "blocks": "blk",
    "blks": "blk",
    "turnovers": "to",
    "tov": "to",
    "threes": "3ptm",
    "3s": "3ptm",
    "3pm": "3ptm",
    "3pt": "3ptm",
    "fg": "fg%",
    "fgpct": "fg%",
    "ft": "ft%",
    "ftpct": "ft%",
    "doubledoubles": "dd",
    "tripledoubles": "td",
}


def _norm_stat(name: str) -> str:
    return re.sub(r"[^a-z0-9%]", "", name.lower())


def match_stats(requested: list[str], categories: list[dict]) -> tuple[list[str], list[str]]:
    """Map names like 'PTS', 'threes' or 'Field Goal Percentage' to stat ids. Returns (ids, unknown names)."""
    lookup: dict[str, str] = {}
    for cat in categories:
        for label in (cat.get("abbr"), cat.get("name")):
            if label:
                lookup.setdefault(_norm_stat(label), cat["stat_id"])
    ids, unknown = [], []
    for name in requested:
        key = _norm_stat(name)
        stat_id = lookup.get(key) or lookup.get(STAT_ALIASES.get(key, ""))
        if stat_id is None and key.isdigit():
            stat_id = key if any(c["stat_id"] == key for c in categories) else None
        if stat_id is None:
            unknown.append(name)
        elif stat_id not in ids:
            ids.append(stat_id)
    return ids, unknown


def label_stats(stats: dict[str, Any], categories: list[dict], only_ids: list[str] | None = None) -> dict[str, Any]:
    """Swap stat ids for abbreviations, in the league's category order."""
    labeled = {}
    for cat in categories:
        if only_ids is not None and cat["stat_id"] not in only_ids:
            continue
        if cat["stat_id"] in stats:
            labeled[cat["abbr"]] = stats[cat["stat_id"]]
    if only_ids is not None:  # keep the order the user asked for
        order = {sid: i for i, sid in enumerate(only_ids)}
        abbr_to_id = {c["abbr"]: c["stat_id"] for c in categories}
        labeled = dict(sorted(labeled.items(), key=lambda kv: order.get(abbr_to_id.get(kv[0]), 0)))
    return labeled


# ---------------------------------------------------------------- player names


def normalize_name(name: str, keep_suffix: bool = False) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-z ]", "", name.lower())
    return " ".join(w for w in name.split() if keep_suffix or w not in {"jr", "sr", "ii", "iii", "iv"})
