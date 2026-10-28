"""Checks for lineup changes and add/drops, done before anything is changed on Yahoo.

These functions only work on data already fetched, so they're easy to unit test.
"""

from collections import Counter

from yahoo_fantasy_mcp.parse import normalize_name

INACTIVE_SLOTS = {"IL", "IL+", "NA"}  # slots that don't count toward roster size
NOT_PLAYING_STATUSES = {"O", "INJ", "SUSP", "NA"}

POSITION_ALIASES = {"BENCH": "BN", "IR": "IL", "IR+": "IL+", "UTIL": "Util", "UTILITY": "Util"}


class LineupError(ValueError):
    pass


def find_player(name: str, players: list[dict]) -> dict:
    """Find a player by (partial) name, ignoring accents, case and Jr./III suffixes."""
    wanted = normalize_name(name)
    if not wanted:
        raise LineupError("Empty player name.")
    # Exact name first (so "Gary Payton" doesn't also match "Gary Payton II"), then ignoring suffixes.
    for same in (
        lambda p: normalize_name(p.get("name", ""), keep_suffix=True) == normalize_name(name, keep_suffix=True),
        lambda p: normalize_name(p.get("name", "")) == wanted,
    ):
        exact = [p for p in players if same(p)]
        if len(exact) == 1:
            return exact[0]
    words = wanted.split()
    partial = [p for p in players if all(w in normalize_name(p.get("name", "")).split() for w in words)]
    if not partial:
        partial = [p for p in players if wanted in normalize_name(p.get("name", ""))]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise LineupError(f"No player matching '{name}'.")
    raise LineupError(f"'{name}' matches several players: {', '.join(p['name'] for p in partial)}. Be more specific.")


def _slot_capacity(roster_positions: list[dict]) -> dict[str, int]:
    capacity = {p["position"]: p["count"] for p in roster_positions}
    capacity.setdefault("BN", 99)
    return capacity


def _canonical_position(position: str, capacity: dict[str, int]) -> str:
    alias = POSITION_ALIASES.get(position.strip().upper(), position.strip())
    for slot in capacity:
        if slot.upper() == alias.upper():
            return slot
    raise LineupError(f"'{position}' isn't a roster slot in this league. Slots: {', '.join(capacity)}.")


def _can_play(player: dict, slot: str) -> bool:
    return slot == "BN" or slot in player.get("eligible_positions", [])


def _lineup_by_slot(players: list[dict], slots: dict[str, str], capacity: dict[str, int]) -> dict[str, list[str]]:
    lineup = {slot: [] for slot in capacity}
    for p in players:
        lineup.setdefault(slots[p["player_key"]], []).append(p["name"])
    return {slot: names for slot, names in lineup.items() if names or capacity.get(slot, 0) < 99}


def plan_lineup(players: list[dict], roster_positions: list[dict], changes: list[dict]) -> dict:
    """Work out the full lineup after `changes` ([{player, position}]) and check it's legal.

    Like Yahoo's own editor, a player who gets bumped from a full slot is swapped into
    the slot the incoming player left (or another slot they can play, or the bench).
    """
    capacity = _slot_capacity(roster_positions)
    starting = [p["position"] for p in roster_positions if p.get("is_starting")]
    before = {p["player_key"]: p.get("selected_position", "BN") for p in players}
    after = dict(before)
    by_key = {p["player_key"]: p for p in players}
    errors: list[str] = []
    warnings: list[str] = []
    moved: set[str] = set()

    for change in changes:
        try:
            player = find_player(change["player"], players)
            slot = _canonical_position(change["position"], capacity)
        except LineupError as exc:
            errors.append(str(exc))
            continue
        if player.get("is_editable") is False:
            errors.append(f"{player['name']} is locked for this date (their game has probably started).")
            continue
        if not _can_play(player, slot):
            errors.append(f"{player['name']} can't play {slot}. Eligible: {', '.join(player.get('eligible_positions', []))}.")
            continue
        after[player["player_key"]] = slot
        moved.add(player["player_key"])

    implied: list[str] = []
    for _ in range(len(players)):
        counts = Counter(after.values())
        overfull = next((s for s, n in counts.items() if n > capacity.get(s, 0)), None)
        if overfull is None:
            break
        bumpable = [
            k for k, s in after.items() if s == overfull and k not in moved and by_key[k].get("is_editable") is not False
        ]
        if not bumpable:
            errors.append(f"Too many players in {overfull} (room for {capacity.get(overfull, 0)}).")
            break
        key = bumpable[0]
        bumped = by_key[key]
        vacated = [before[k] for k in moved if before[k] != after[k]]
        options = vacated + starting + ["BN"]
        target = next(
            (s for s in options if s != overfull and _can_play(bumped, s) and counts.get(s, 0) < capacity.get(s, 0)),
            None,
        )
        if target is None:
            errors.append(f"Moving players into {overfull} leaves nowhere to put {bumped['name']}.")
            break
        after[key] = target
        moved.add(key)
        implied.append(key)

    moves = [
        {"player": by_key[k]["name"], "from": before[k], "to": after[k], "implied": k in implied}
        for k in by_key
        if before[k] != after[k]
    ]
    for k, slot in after.items():
        player = by_key[k]
        if slot in starting and player.get("status") in NOT_PLAYING_STATUSES:
            warnings.append(f"{player['name']} is starting at {slot} but is listed as {player['status']}.")
    open_slots = {s: capacity[s] - Counter(after.values()).get(s, 0) for s in starting}
    for slot, free in open_slots.items():
        if free > 0:
            warnings.append(f"{slot} has {free} empty spot(s).")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "moves": moves,
        "lineup_before": _lineup_by_slot(players, before, capacity),
        "lineup_after": _lineup_by_slot(players, after, capacity),
    }


def check_add_drop(
    roster_players: list[dict],
    roster_positions: list[dict],
    add: dict | None,
    drop: dict | None,
    uses_faab: bool = False,
    my_team_key: str | None = None,
) -> dict:
    """Check an add, a drop or both. `add` must include Yahoo ownership info."""
    errors: list[str] = []
    warnings: list[str] = []
    kind = None

    if add:
        ownership = add.get("ownership") or {}
        owner = ownership.get("type")
        if owner == "team":
            if ownership.get("owner_team_key") == my_team_key:
                errors.append(f"{add['name']} is already on your team.")
            else:
                errors.append(
                    f"{add['name']} is on {ownership.get('owner_team_name') or 'another team'}. Getting them needs a trade."
                )
        elif owner == "waivers":
            kind = "waiver_claim"
            note = f"{add['name']} is on waivers"
            if ownership.get("waiver_date"):
                note += f" until {ownership['waiver_date']}"
            warnings.append(note + ". This will be a waiver claim, not an immediate add.")
            if uses_faab:
                warnings.append("Your league uses FAAB, so the claim needs a bid amount.")
        else:
            kind = "free_agent_add"

    if drop:
        if drop.get("player_key") not in {p["player_key"] for p in roster_players}:
            errors.append(f"{drop['name']} isn't on your roster.")
        elif drop.get("is_editable") is False:
            warnings.append(f"{drop['name']}'s game has started; Yahoo may not process the drop until it ends.")

    active_capacity = sum(p["count"] for p in roster_positions if p["position"] not in INACTIVE_SLOTS)
    active_count = sum(1 for p in roster_players if p.get("selected_position") not in INACTIVE_SLOTS)
    if add and not drop and active_count >= active_capacity:
        errors.append(f"Your roster is full ({active_count}/{active_capacity}). Pick a player to drop.")

    if add and drop:
        kind = "add_drop" if kind == "free_agent_add" else "waiver_claim_with_drop"
    elif drop and not add:
        kind = "drop"

    return {
        "ok": not errors,
        "type": kind,
        "errors": errors,
        "warnings": warnings,
        "roster_spots_used": f"{active_count}/{active_capacity}",
    }
