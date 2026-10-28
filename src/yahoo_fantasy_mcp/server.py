"""The MCP server: tools Claude can call, and prompts that show up as slash commands.

Yahoo's API is read-only for new apps, so every tool here only reads. Changes are
planned and checked by the `plan_*` tools, then made on the Yahoo website (by you, or
by Claude through Claude in Chrome) and confirmed by reading the roster again.
"""

import functools
import logging
from urllib.parse import quote

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from yahoo_fantasy_mcp import auth, lineup, prefs
from yahoo_fantasy_mcp.client import YahooAPIError, YahooClient
from yahoo_fantasy_mcp.config import TOKENS_PATH, ConfigError, client_credentials
from yahoo_fantasy_mcp.parse import (
    label_stats,
    league_key_of,
    match_stats,
    parse_league_players,
    parse_league_settings,
    parse_matchups,
    parse_roster,
    parse_standings,
    parse_team_stats,
    parse_user_leagues,
    parse_user_teams,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")  # stderr, never stdout

INSTRUCTIONS = """\
Tools for the user's Yahoo Fantasy Basketball (NBA) team. All tools only read data:
Yahoo's API doesn't allow new apps to change rosters.

To change the lineup or add/drop players:
1. Call plan_lineup_change or plan_add_drop. Fix any errors it reports.
2. Show the user the planned moves and wait for a clear yes.
3. Make the change on the Yahoo page the plan links to, using the Claude in Chrome browser
   tools if they're available (otherwise give the user the steps).
4. Call get_roster (or search_players for adds) again to confirm Yahoo saved the change.

Player names can be partial ("Jokic", "SGA"). If the user has more than one NBA team, ask
which one and call set_default_team. Dates are YYYY-MM-DD; NBA lineups are set per day.
"""

mcp = MCPServer(name="yahoo-fantasy", instructions=INSTRUCTIONS)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
LOCAL_READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
LOCAL_ONLY = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

PERIODS = ("season", "lastweek", "lastmonth", "date")
USER_GAMES = "users;use_login=1/games;game_keys=nba"

_client: YahooClient | None = None
_settings_cache: dict[str, dict] = {}


def yahoo():
    global _client
    if _client is None:
        _client = YahooClient()
    return _client


def tool(annotations: ToolAnnotations = READ_ONLY):
    """Register a tool, passing our own errors to Claude as readable messages.

    MCPServer hides the text of unexpected exceptions from the client, so errors the
    user can act on are re-raised as ToolError.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except (YahooAPIError, ConfigError, lineup.LineupError) as exc:
                raise ToolError(str(exc)) from exc

        return mcp.tool(annotations=annotations)(wrapper)

    return decorator


# ---------------------------------------------------------------- helpers


def _my_teams() -> list[dict]:
    fc = yahoo().get(f"{USER_GAMES}/teams")
    return parse_user_teams(fc)


def _team_key(team_key: str | None) -> str:
    if team_key:
        return team_key
    saved = prefs.get("default_team_key")
    if saved:
        return saved
    teams = _my_teams()
    if len(teams) == 1:
        prefs.put("default_team_key", teams[0]["team_key"])
        return teams[0]["team_key"]
    if not teams:
        raise ConfigError("You don't have any Yahoo Fantasy NBA teams this season.")
    names = "; ".join(f"{t['name']} ({t['team_key']})" for t in teams)
    raise ConfigError(f"You have several NBA teams: {names}. Ask which one to use, then call set_default_team.")


def _settings(league_key: str) -> dict:
    if league_key not in _settings_cache:
        _settings_cache[league_key] = parse_league_settings(yahoo().get(f"league/{league_key}/settings"))
    return _settings_cache[league_key]


def _roster(team_key: str, date: str | None) -> dict:
    path = f"team/{team_key}/roster" + (f";date={date}" if date else "")
    return parse_roster(yahoo().get(path))


def _stats_param(period: str, date: str | None) -> str:
    if period not in PERIODS:
        raise ConfigError(f"period must be one of {', '.join(PERIODS)}.")
    if period == "date":
        if not date:
            raise ConfigError("period='date' needs a date (YYYY-MM-DD).")
        return f"type=date;date={date}"
    return f"type={period}"


def _player_stats(league_key: str, player_keys: list[str], stats_param: str) -> dict[str, dict]:
    """Stats for up to any number of players, 25 per request (Yahoo's limit)."""
    stats = {}
    for i in range(0, len(player_keys), 25):
        keys = ",".join(player_keys[i : i + 25])
        fc = yahoo().get(f"league/{league_key}/players;player_keys={keys}/stats;{stats_param}")
        for player in parse_league_players(fc):
            stats[player["player_key"]] = player
    return stats


def _wanted_stat_ids(stats: list[str] | None, categories: list[dict]) -> tuple[list[str] | None, list[str]]:
    names = stats or prefs.get("favorite_stats")
    if not names:
        return None, []
    return match_stats(names, categories)


def _slim(player: dict, categories: list[dict], wanted: list[str] | None) -> dict:
    """A compact player row for Claude: drop ids it doesn't need, label the stats."""
    row = {
        k: player[k]
        for k in ("name", "nba_team", "positions", "selected_position", "status", "injury_note", "fantasy_points")
        if k in player
    }
    if "stats" in player:
        row["stats"] = label_stats(player["stats"], categories, wanted)
    return row


# ---------------------------------------------------------------- setup tools


@tool()
def check_connection() -> dict:
    """Check that the server is set up: Yahoo app credentials, sign-in, and API access.

    Call this first if any other tool fails with a setup error.
    """
    client_credentials()
    if not TOKENS_PATH.exists():
        raise ConfigError("Not signed in. Run `uv run yahoo-fantasy-mcp login` in the project folder.")
    auth.access_token()
    teams = _my_teams()
    return {"ok": True, "nba_teams": len(teams), "default_team_key": prefs.get("default_team_key")}


@tool()
def list_my_teams() -> dict:
    """List the user's Yahoo Fantasy NBA teams this season, with their leagues.

    If there's exactly one team it becomes the default for every other tool.
    """
    teams = _my_teams()
    leagues = parse_user_leagues(yahoo().get(f"{USER_GAMES}/leagues"))
    for team in teams:
        league = leagues.get(team["league_key"], {})
        team["league_name"] = league.get("name")
        team["scoring_type"] = league.get("scoring_type")
    if len(teams) == 1 and not prefs.get("default_team_key"):
        prefs.put("default_team_key", teams[0]["team_key"])
    return {"teams": teams, "default_team_key": prefs.get("default_team_key")}


@tool(LOCAL_ONLY)
def set_default_team(team_key: str) -> dict:
    """Choose which team the other tools use when no team_key is given (e.g. '466.l.12345.t.3')."""
    prefs.put("default_team_key", team_key)
    return {"default_team_key": team_key}


@tool()
def get_league_settings(league_key: str | None = None) -> dict:
    """League rules: scoring type (head = H2H categories, point = points), stat categories,
    roster slots and counts, waiver type, FAAB, and weekly add limit. Defaults to the default team's league."""
    return _settings(league_key or league_key_of(_team_key(None)))


# ---------------------------------------------------------------- read tools


@tool()
def get_roster(date: str | None = None, team_key: str | None = None) -> dict:
    """A team's roster for one day: each player's lineup slot, eligible positions, injury status
    and whether they can still be moved (is_editable is false once their game starts).

    Args:
        date: YYYY-MM-DD. Defaults to today.
        team_key: Defaults to the user's team. Pass another team's key to see their roster.
    """
    roster = _roster(_team_key(team_key), date)
    settings = _settings(league_key_of(roster["team_key"]))
    order = {p["position"]: i for i, p in enumerate(settings["roster_positions"])}
    roster["players"].sort(key=lambda p: order.get(p.get("selected_position"), 99))
    for player in roster["players"]:
        player.pop("player_key", None)
        player.pop("player_id", None)
    roster["roster_slots"] = {p["position"]: p["count"] for p in settings["roster_positions"]}
    return roster


@tool()
def get_team_stats(
    stats: list[str] | None = None,
    period: str = "season",
    date: str | None = None,
    team_key: str | None = None,
) -> dict:
    """Stats for every player on a team, plus team totals when Yahoo provides them.

    Args:
        stats: Which stats to show, by name or abbreviation (e.g. ["PTS", "REB", "3PTM", "FG%"]).
            If omitted, the user's saved favorites are used, or every league category if none are saved.
        period: "season", "lastweek" (last 7 days), "lastmonth" (last 30 days) or "date".
        date: YYYY-MM-DD, required when period is "date".
        team_key: Defaults to the user's team.
    """
    team_key = _team_key(team_key)
    league_key = league_key_of(team_key)
    categories = _settings(league_key)["stat_categories"]
    wanted, unknown = _wanted_stat_ids(stats, categories)
    param = _stats_param(period, date)

    roster = _roster(team_key, date if period == "date" else None)
    player_stats = _player_stats(league_key, [p["player_key"] for p in roster["players"]], param)
    players = []
    for p in roster["players"]:
        merged = {**p, **player_stats.get(p["player_key"], {}), "selected_position": p.get("selected_position")}
        players.append(_slim(merged, categories, wanted))

    result = {"team": roster["team_name"], "period": period, "players": players}
    try:
        totals = parse_team_stats(yahoo().get(f"team/{team_key}/stats;{param}"))
        result["team_totals"] = label_stats(totals["stats"], categories, wanted)
    except YahooAPIError:
        pass  # Yahoo doesn't offer team totals for every period
    if unknown:
        result["unknown_stats"] = unknown
        result["available_stats"] = [c["abbr"] for c in categories]
    return result


@tool(LOCAL_ONLY)
def set_stat_preferences(stats: list[str]) -> dict:
    """Save the stats the user wants to see by default (e.g. ["PTS", "REB", "AST", "3PTM", "FG%"]).
    Names are checked against the league's stat categories. Pass an empty list to show everything."""
    if not stats:
        prefs.put("favorite_stats", [])
        return {"favorite_stats": [], "note": "All league categories will be shown."}
    categories = _settings(league_key_of(_team_key(None)))["stat_categories"]
    ids, unknown = match_stats(stats, categories)
    if unknown:
        raise ConfigError(
            f"Unknown stats: {', '.join(unknown)}. This league's stats: {', '.join(c['abbr'] for c in categories)}."
        )
    abbrs = [c["abbr"] for sid in ids for c in categories if c["stat_id"] == sid]
    prefs.put("favorite_stats", abbrs)
    return {"favorite_stats": abbrs}


@tool(LOCAL_READ)
def get_stat_preferences() -> dict:
    """The user's saved favorite stats (empty means all league categories)."""
    return {"favorite_stats": prefs.get("favorite_stats", [])}


@tool()
def search_players(
    query: str | None = None,
    position: str | None = None,
    status: str = "A",
    sort: str = "AR",
    period: str = "season",
    stats: list[str] | None = None,
    count: int = 25,
    start: int = 0,
) -> dict:
    """Find players in the user's league: free agents, waiver players, or anyone by name.

    Args:
        query: Part of a player's name. Leave empty to browse.
        position: PG, SG, G, SF, PF, F, C or Util.
        status: "A" all available (free agents + waivers), "FA" free agents only, "W" waivers only,
            "T" on a team, or "ALL".
        sort: "AR" (actual rank over the period), "OR" (preseason rank), "NAME", or a stat name like "3PTM".
        period: Stats period: "season", "lastweek", "lastmonth".
        stats: Which stats to show; same rules as get_team_stats.
        count: Up to 25 per call; use start to page.
    """
    league_key = league_key_of(_team_key(None))
    categories = _settings(league_key)["stat_categories"]
    wanted, unknown = _wanted_stat_ids(stats, categories)
    if sort not in ("AR", "OR", "NAME", "PTS"):
        ids, bad = match_stats([sort], categories)
        if bad:
            raise ConfigError(f"Can't sort by '{sort}'. Use AR, OR, NAME or a stat name.")
        sort = ids[0]
    if period == "date":
        raise ConfigError("search_players supports season, lastweek or lastmonth.")

    filters = [f"sort={sort}", f"sort_type={period}", f"count={min(count, 25)}", f"start={start}"]
    if status != "ALL":
        filters.append(f"status={status}")
    if position:
        filters.append(f"position={position}")
    if query:
        filters.append(f"search={quote(query)}")
    fc = yahoo().get(f"league/{league_key}/players;{';'.join(filters)}/stats;{_stats_param(period, None)}")
    players = [_slim(p, categories, wanted) for p in parse_league_players(fc)]
    result = {"players": players, "start": start, "period": period}
    if unknown:
        result["unknown_stats"] = unknown
    return result


@tool()
def get_matchup(week: int | None = None, team_key: str | None = None) -> dict:
    """This week's (or another week's) head-to-head matchup: both teams' category totals,
    who is winning each category, and games remaining.

    Args:
        week: Fantasy week number. Defaults to the current week.
        team_key: Defaults to the user's team.
    """
    team_key = _team_key(team_key)
    settings = _settings(league_key_of(team_key))
    week = week or settings.get("current_week")
    matchups = parse_matchups(yahoo().get(f"team/{team_key}/matchups;weeks={week}"))
    if not matchups:
        raise ConfigError(f"No matchup found for week {week}.")
    m = matchups[0]
    categories = settings["stat_categories"]
    scorable = {c["stat_id"]: c["abbr"] for c in categories if not c["display_only"]}
    names = {t["team_key"]: t["name"] for t in m["teams"]}

    record = {"won": 0, "lost": 0, "tied": 0}
    by_category = {}
    for stat_id, winner in m["stat_winners"].items():
        if stat_id not in scorable:
            continue
        outcome = "tied" if winner == "tie" else ("won" if winner == team_key else "lost")
        record[outcome] += 1
        by_category[scorable[stat_id]] = "tied" if winner == "tie" else names.get(winner, winner)

    return {
        "week": m["week"],
        "dates": f"{m['week_start']} to {m['week_end']}",
        "status": m["status"],
        "is_playoffs": m["is_playoffs"],
        "teams": [
            {
                "name": t["name"],
                "is_me": t["team_key"] == team_key,
                "stats": label_stats(t["stats"], categories),
                "fantasy_points": t["fantasy_points"],
                "projected_points": t["projected_points"],
                "games": t["games"],
            }
            for t in m["teams"]
        ],
        "category_leader": by_category,
        "my_category_record": record,
    }


@tool()
def get_standings(league_key: str | None = None) -> dict:
    """League standings: every team's rank, record and team_key (use the key to look at their roster or stats)."""
    league_key = league_key or league_key_of(_team_key(None))
    return {"standings": parse_standings(yahoo().get(f"league/{league_key}/standings"))}


# ---------------------------------------------------------------- change planning


class LineupChange(BaseModel):
    player: str = Field(description="Player name, full or partial")
    position: str = Field(description="Slot to put them in: PG, SG, G, SF, PF, F, C, Util, BN (bench) or IL")


@tool()
def plan_lineup_change(changes: list[LineupChange], date: str | None = None, team_key: str | None = None) -> dict:
    """Check a lineup change and work out the full lineup afterwards. Changes nothing on Yahoo.

    Players bumped from a full slot are swapped into the slot that was freed (or benched),
    like Yahoo's own editor. Returns errors (illegal moves, locked players), warnings
    (injured starters, empty slots), the before/after lineup, and the Yahoo page where
    the change can be made.

    Args:
        changes: e.g. [{"player": "Jokic", "position": "C"}, {"player": "Poole", "position": "BN"}]
        date: YYYY-MM-DD. Defaults to today.
    """
    team_key = _team_key(team_key)
    roster = _roster(team_key, date)
    settings = _settings(league_key_of(team_key))
    plan = lineup.plan_lineup(roster["players"], settings["roster_positions"], [c.model_dump() for c in changes])
    plan["date"] = roster["date"]
    if roster["team_url"]:
        plan["yahoo_page"] = f"{roster['team_url']}?date={roster['date']}"
    plan["how_to_apply"] = (
        "On the Yahoo team page for that date, move each player in 'moves' to their 'to' slot "
        "(click the player's position button, then the destination slot), then save. "
        "Afterwards call get_roster for the same date to confirm."
    )
    return plan


@tool()
def plan_add_drop(add: str | None = None, drop: str | None = None, team_key: str | None = None) -> dict:
    """Check adding a player, dropping one, or both at once. Changes nothing on Yahoo.

    Reports whether the add is an immediate free-agent pickup or a waiver claim, whether
    the roster has room, and the Yahoo page to make the move on.

    Args:
        add: Name of the player to pick up.
        drop: Name of a player on the user's roster to release.
    """
    if not add and not drop:
        raise ConfigError("Give a player to add, to drop, or both.")
    team_key = _team_key(team_key)
    league_key = league_key_of(team_key)
    settings = _settings(league_key)
    roster = _roster(team_key, None)

    add_player = None
    if add:
        fc = yahoo().get(f"league/{league_key}/players;search={quote(add)}/ownership")
        add_player = lineup.find_player(add, parse_league_players(fc))
    drop_player = lineup.find_player(drop, roster["players"]) if drop else None

    result = lineup.check_add_drop(
        roster["players"],
        settings["roster_positions"],
        add_player,
        drop_player,
        uses_faab=settings["uses_faab"],
        my_team_key=team_key,
    )
    result["add"] = _slim(add_player, [], None) if add_player else None
    result["drop"] = drop_player["name"] if drop_player else None
    league_url = settings.get("url")
    if league_url and add_player:
        result["yahoo_page"] = f"{league_url}/addplayer?apid={add_player['player_id']}"
        result["fallback_page"] = f"{league_url}/players?search={quote(add_player['name'])}"
    elif roster["team_url"]:
        result["yahoo_page"] = roster["team_url"]
    result["how_to_apply"] = (
        "Open yahoo_page. For an add, click Add (or Add/Drop and choose the player to drop); for a waiver "
        "claim also enter the FAAB bid if asked. For a drop only, use the Drop option on the team page. "
        "Afterwards call get_roster to confirm."
    )
    return result


# ---------------------------------------------------------------- prompts (slash commands)


@mcp.prompt()
def make_changes(request: str) -> str:
    """Plan a lineup change or add/drop, confirm it with you, then make it on Yahoo."""
    return f"""The user wants to make this change to their Yahoo Fantasy NBA team: {request}

1. Use plan_lineup_change (start/bench/move) or plan_add_drop (pick up/release) to check it.
   If there are errors, explain them and suggest a fix instead of continuing.
2. Show the planned moves (including any implied swaps) and warnings, and ask the user to confirm.
   Don't continue without a clear yes.
3. Make the change on the yahoo_page from the plan using the Claude in Chrome browser tools.
   If those tools aren't available, give the user short click-by-click steps instead.
4. Call get_roster again (same date) and confirm each move actually took effect. Report anything that didn't."""


@mcp.prompt()
def optimize_lineup(date: str = "today") -> str:
    """Suggest the best lineup for a day. Suggests only; nothing is changed."""
    return f"""Suggest the best lineup for my Yahoo Fantasy NBA team for {date}.

1. Call get_league_settings for the scoring type and roster slots, then get_roster for that date.
2. Call get_team_stats with period "lastmonth" (recent form) and "season" for context.
3. Start players who are playing that day and healthy; bench or IL anyone OUT/INJ.
   In category leagues, weigh the categories I'm close in this week (get_matchup).
   Respect eligible positions and slot counts. Locked players (is_editable false) can't move.
4. Show the proposed lineup as a table and list only the moves needed. Don't make any changes.
   If I want them made, I'll ask (or use /make_changes)."""


@mcp.prompt()
def waiver_targets(category: str = "") -> str:
    """Find free agents worth picking up, optionally for one stat category."""
    focus = f" who help most in {category}" if category else ""
    return f"""Find the best free-agent or waiver pickups{focus} for my Yahoo Fantasy NBA team.

1. Call get_league_settings, get_team_stats (period "lastmonth") and get_matchup to see where my team is weak.
2. Call search_players with status "A", trying sort by the weak categories and period "lastweek" and "lastmonth".
3. Recommend up to 5 pickups, each with who to drop from my roster and why (recent stats, role, injuries).
   Note waiver vs free agent and the weekly add limit. Don't make any changes."""


@mcp.prompt()
def trade_ideas() -> str:
    """Suggest fair trades that fix your team's weak categories."""
    return """Suggest trade ideas for my Yahoo Fantasy NBA team.

1. Call get_league_settings, get_team_stats (season and lastmonth) and get_standings.
2. Identify my strongest and weakest categories (or positions, in points leagues).
3. For other teams, call get_team_stats with their team_key to find teams with the opposite profile.
4. Propose 2-3 realistic trades (players out, players in, why it helps both sides).
   Yahoo's API can't send trade offers, so the user proposes them on Yahoo if they like one."""
