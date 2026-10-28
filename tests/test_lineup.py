import pytest
from conftest import load

from yahoo_fantasy_mcp.lineup import LineupError, check_add_drop, find_player, plan_lineup
from yahoo_fantasy_mcp.parse import parse_league_players, parse_league_settings, parse_roster


@pytest.fixture
def roster():
    return parse_roster(load("roster.xml"))["players"]


@pytest.fixture
def slots():
    return parse_league_settings(load("league_settings.xml"))["roster_positions"]


def test_find_player_ignores_accents_and_suffixes(roster):
    assert find_player("jokic", roster)["player_id"] == "6004"
    assert find_player("Jaren Jackson", roster)["player_id"] == "6005"
    with pytest.raises(LineupError, match="several"):
        find_player("J", [{"name": "Jalen Brunson"}, {"name": "Jalen Green"}])
    with pytest.raises(LineupError, match="No player"):
        find_player("LeBron", roster)


def test_start_bench_player_swaps_into_freed_slot(roster, slots):
    plan = plan_lineup(roster, slots, [{"player": "Brunson", "position": "G"}])
    assert plan["ok"], plan["errors"]
    moves = {m["player"]: (m["from"], m["to"], m["implied"]) for m in plan["moves"]}
    assert moves["Jalen Brunson"] == ("BN", "G", False)
    assert moves["Jordan Poole"] == ("G", "BN", True)
    assert plan["lineup_after"]["G"] == ["Jalen Brunson"]


def test_swap_between_two_starting_slots(roster, slots):
    plan = plan_lineup(roster, slots, [{"player": "Booker", "position": "G"}])
    assert plan["ok"], plan["errors"]
    moves = {m["player"]: m["to"] for m in plan["moves"]}
    # Poole is bumped from G into the SG slot Booker left.
    assert moves == {"Devin Booker": "G", "Jordan Poole": "SG"}
    assert plan["warnings"] == []


def test_bumped_player_with_nowhere_to_go(roster, slots):
    # Haliburton can't play SG (the slot Booker frees) and the bench is full.
    plan = plan_lineup(roster, slots, [{"player": "Booker", "position": "PG"}])
    assert not plan["ok"]
    assert plan["errors"] == ["Moving players into PG leaves nowhere to put Tyrese Haliburton."]
    fixed = plan_lineup(
        roster, slots, [{"player": "Booker", "position": "PG"}, {"player": "Haliburton", "position": "G"}]
    )
    assert fixed["ok"], fixed["errors"]
    assert {m["player"]: m["to"] for m in fixed["moves"]}["Jordan Poole"] == "SG"


def test_locked_and_ineligible_players_are_errors(roster, slots):
    plan = plan_lineup(
        roster,
        slots,
        [{"player": "Jokic", "position": "BN"}, {"player": "Myles Turner", "position": "PG"}, {"player": "Brunson", "position": "XX"}],
    )
    assert not plan["ok"]
    assert any("locked" in e for e in plan["errors"])
    assert any("can't play PG" in e for e in plan["errors"])
    assert any("isn't a roster slot" in e for e in plan["errors"])


def test_bench_alias_and_full_bench(roster, slots):
    plan = plan_lineup(roster, slots, [{"player": "Haliburton", "position": "bench"}])
    # Bench holds 2 and is already full, so someone on it must come off the bench.
    assert plan["ok"], plan["errors"]
    moves = {m["player"]: m["to"] for m in plan["moves"]}
    assert moves["Tyrese Haliburton"] == "BN"
    assert moves["Jalen Brunson"] == "PG"


def test_injured_starter_warning(roster, slots):
    find_player("Booker", roster)["status"] = "O"
    plan = plan_lineup(roster, slots, [])
    assert plan["ok"]
    assert plan["warnings"] == ["Devin Booker is starting at SG but is listed as O."]


def test_add_drop_checks(roster, slots):
    found = parse_league_players(load("players_ownership.xml"))
    waiver, owned = found[0], found[1]
    me = "466.l.12345.t.3"

    full = check_add_drop(roster, slots, waiver, None, uses_faab=True, my_team_key=me)
    assert not full["ok"]
    assert "roster is full" in full["errors"][0]

    claim = check_add_drop(roster, slots, waiver, find_player("Poole", roster), uses_faab=True, my_team_key=me)
    assert claim["ok"]
    assert claim["type"] == "waiver_claim_with_drop"
    assert any("FAAB" in w for w in claim["warnings"])

    trade = check_add_drop(roster, slots, owned, find_player("Poole", roster), my_team_key=me)
    assert not trade["ok"]
    assert "Rivals" in trade["errors"][0]
