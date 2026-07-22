"""Worlds Race: point-in-time regional leaderboards and time series for invite tracking."""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from cp_calculator import calculate_cp
from logger import logger
from storage import list_tournament_files, load_json, load_player_mappings
from utils import (
    WORLDS_CUTOFF_BY_REGION,
    map_region_to_group,
)

# Player key: (canonical_name, region_code_uppercase)
PlayerKey = tuple[str, str]


@dataclass
class EventRecord:
    """A single tournament result for a player (with date)."""
    tournament_date: date
    tournament_title: str
    tournament_type: str
    placement: int
    num_competitors: int
    cp: int


@dataclass
class WorldsRacePoint:
    """One point in the Worlds Race time series (after an event)."""
    date: date
    cumulative_cp: int
    regional_rank: int
    cutoff_cp: int
    points_earned_at_event: int
    placement: int
    event_name: str
    gap_to_cutoff: int


# Simple in-memory caches so repeated lookups on the Worlds Race tab
# are fast within a single application run.
_SEASON_TOURNAMENT_CACHE: dict[str, list[tuple[date, dict]]] = {}
_SEASON_PLAYER_EVENTS_CACHE: dict[
    str, tuple[dict[PlayerKey, list[EventRecord]], dict[PlayerKey, str]]
] = {}
_SEASON_REGION_CUTOFF_CACHE: dict[tuple[str, str], tuple[list[date], list[int]]] = {}
# Per-season: (merge_map snapshot, sorted snapshot dates, leaderboard after each date)
_SEASON_SNAPSHOT_PROG_CACHE: dict[
    str,
    tuple[dict[str, str], list[date], list[dict[PlayerKey, tuple[int, list[int], int, str, bool]]]],
] = {}


def _parse_tournament_date(s: str | None) -> date | None:
    if not s or not s.strip():
        return None
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _load_tournaments_by_date(season: str) -> list[tuple[date, dict]]:
    """Load all tournament data for the season, sorted by tournament_date."""
    if season in _SEASON_TOURNAMENT_CACHE:
        return _SEASON_TOURNAMENT_CACHE[season]
    files = list_tournament_files(season)
    out: list[tuple[date, dict]] = []
    for path in files:
        try:
            data = load_json(path)
            meta = data.get("metadata", {})
            t_date = _parse_tournament_date(meta.get("tournament_date", ""))
            if t_date is None:
                continue
            out.append((t_date, data))
        except Exception as exc:
            logger.warning("Failed to load tournament %s: %s", path, exc)
            continue
    out.sort(key=lambda x: x[0])
    _SEASON_TOURNAMENT_CACHE[season] = out
    return out


def _build_per_player_events(
    season: str,
) -> tuple[dict[PlayerKey, list[EventRecord]], dict[PlayerKey, str]]:
    """
    Build per-player event lists (with dates) and region_code for each key.
    Returns (player_events, player_region_code) where player_region_code[key] is the
    original region_code string for that player.
    """
    if season in _SEASON_PLAYER_EVENTS_CACHE:
        return _SEASON_PLAYER_EVENTS_CACHE[season]
    merge_map = load_player_mappings(season).get("merges", {})
    dated = _load_tournaments_by_date(season)
    player_events: dict[PlayerKey, list[EventRecord]] = defaultdict(list)
    player_region_code: dict[PlayerKey, str] = {}

    for t_date, data in dated:
        meta = data.get("metadata", {})
        t_type = meta.get("tournament_type", "REGIONAL")
        num_comp = int(meta.get("num_competitors", 0) or 0)
        title = meta.get("title", "Unknown")

        for entry in data.get("normalized_entries", []):
            placement = int(entry["placement"])
            name = entry["normalized_name"]
            canonical = merge_map.get(name, name)
            region_code = (entry.get("region_code") or "").strip()
            region_key = region_code.upper() if region_code else ""
            key: PlayerKey = (canonical, region_key)

            if key not in player_region_code:
                player_region_code[key] = region_code or ""

            cp = calculate_cp(t_type, placement, num_comp)
            player_events[key].append(
                EventRecord(
                    tournament_date=t_date,
                    tournament_title=title,
                    tournament_type=t_type,
                    placement=placement,
                    num_competitors=num_comp,
                    cp=cp,
                )
            )

    result = (dict(player_events), player_region_code)
    _SEASON_PLAYER_EVENTS_CACHE[season] = result
    return result


def _cumulative_cp_and_tiebreakers(events: list[EventRecord]) -> tuple[int, list[int], int]:
    """Best 5 CP sum, sorted CP list (for tie-breakers), and num events."""
    cps = [e.cp for e in events]
    cps_sorted = sorted(cps, reverse=True)
    top5 = cps_sorted[:5]
    total = sum(top5)
    return total, cps_sorted, len(events)


def _append_tournament_to_player_events(
    player_events: dict[PlayerKey, list[EventRecord]],
    player_region_code: dict[PlayerKey, str],
    t_date: date,
    data: dict,
    merge_map: dict[str, str],
) -> None:
    """Mutate accumulators with one tournament's entries (same rules as leaderboard-as-of)."""
    meta = data.get("metadata", {})
    t_type = meta.get("tournament_type", "REGIONAL")
    num_comp = int(meta.get("num_competitors", 0) or 0)
    title = meta.get("title", "Unknown")

    for entry in data.get("normalized_entries", []):
        placement = int(entry["placement"])
        name = entry["normalized_name"]
        canonical = merge_map.get(name, name)
        region_code = (entry.get("region_code") or "").strip()
        region_key = region_code.upper() if region_code else ""
        key: PlayerKey = (canonical, region_key)

        if key not in player_region_code:
            player_region_code[key] = region_code or ""

        cp = calculate_cp(t_type, placement, num_comp)
        player_events[key].append(
            EventRecord(
                tournament_date=t_date,
                tournament_title=title,
                tournament_type=t_type,
                placement=placement,
                num_competitors=num_comp,
                cp=cp,
            )
        )


def _finalize_leaderboard_from_events(
    player_events: dict[PlayerKey, list[EventRecord]],
    player_region_code: dict[PlayerKey, str],
) -> dict[PlayerKey, tuple[int, list[int], int, str, bool]]:
    """Turn accumulated per-player event lists into the compact leaderboard row dict."""
    result: dict[PlayerKey, tuple[int, list[int], int, str, bool]] = {}
    for key, events in player_events.items():
        total, cps_sorted, num_events = _cumulative_cp_and_tiebreakers(events)
        has_autobid = False
        for ev in events:
            if ev.tournament_type == "REGIONAL" and ev.placement == 1:
                has_autobid = True
                break
            if ev.tournament_type == "IC" and ev.placement <= 4:
                has_autobid = True
                break
        result[key] = (total, cps_sorted, num_events, player_region_code[key], has_autobid)
    return result


def _build_leaderboard_snapshot_progression(
    dated: list[tuple[date, dict]],
    merge_map: dict[str, str],
) -> tuple[list[date], list[dict[PlayerKey, tuple[int, list[int], int, str, bool]]]]:
    """Single forward pass: one full leaderboard snapshot after each distinct tournament date."""
    by_day: dict[date, list[dict]] = defaultdict(list)
    for t_date, data in dated:
        by_day[t_date].append(data)

    player_events: dict[PlayerKey, list[EventRecord]] = defaultdict(list)
    player_region_code: dict[PlayerKey, str] = {}

    snapshot_dates: list[date] = []
    snapshot_boards: list[dict[PlayerKey, tuple[int, list[int], int, str, bool]]] = []

    for d in sorted(by_day.keys()):
        for data in by_day[d]:
            _append_tournament_to_player_events(player_events, player_region_code, d, data, merge_map)
        snapshot_dates.append(d)
        snapshot_boards.append(
            _finalize_leaderboard_from_events(player_events, player_region_code)
        )

    return snapshot_dates, snapshot_boards


def _board_at_or_before(
    snapshot_dates: list[date],
    snapshot_boards: list[dict[PlayerKey, tuple[int, list[int], int, str, bool]]],
    through_date: date,
) -> dict[PlayerKey, tuple[int, list[int], int, str, bool]]:
    """Leaderboard including all tournaments on or before ``through_date``."""
    if not snapshot_dates:
        return {}
    i = bisect_right(snapshot_dates, through_date) - 1
    if i < 0:
        return {}
    return snapshot_boards[i]


def _get_snapshot_progression(
    season: str,
    dated: list[tuple[date, dict]],
    merge_map: dict[str, str],
) -> tuple[list[date], list[dict[PlayerKey, tuple[int, list[int], int, str, bool]]]]:
    """Cached snapshot progression for a season (invalidated with reset_worlds_race_cache)."""
    ent = _SEASON_SNAPSHOT_PROG_CACHE.get(season)
    if ent is not None and ent[0] == merge_map:
        return ent[1], ent[2]
    dates, boards = _build_leaderboard_snapshot_progression(dated, merge_map)
    _SEASON_SNAPSHOT_PROG_CACHE[season] = (dict(merge_map), dates, boards)
    return dates, boards


def _regional_rank_and_cutoff_cp(
    leaderboard: dict[PlayerKey, tuple[int, list[int], int, str, bool]],
    region_group: str,
    cutoff_rank: int,
) -> tuple[dict[PlayerKey, int], int | None]:
    """
    Filter by region_group, ignoring autobid players, sort by
    (TotalCP, BestCP, SecondBestCP, NumEvents), assign rank.
    Returns (player_key -> regional_rank, cutoff_cp) where cutoff_cp is the
    CP of the last invite slot (e.g. rank 135 in NA).
    """
    region_players: list[tuple[PlayerKey, int, int, int, int]] = []
    for key, (total, cps_sorted, num_events, region_code, has_autobid) in leaderboard.items():
        rg = map_region_to_group(region_code)
        if rg != region_group:
            continue
        # Exclude autobid players from the invite race – they no longer occupy a slot.
        if has_autobid:
            continue
        best = cps_sorted[0] if cps_sorted else 0
        second = cps_sorted[1] if len(cps_sorted) > 1 else 0
        region_players.append((key, total, best, second, num_events))

    region_players.sort(
        key=lambda x: (x[1], x[2], x[3], x[4]),
        reverse=True,
    )
    key_to_rank: dict[PlayerKey, int] = {}
    cutoff_cp: int | None = None
    for rank, (key, total, *_) in enumerate(region_players, start=1):
        key_to_rank[key] = rank
        if rank == cutoff_rank:
            cutoff_cp = total
    if cutoff_cp is None and region_players:
        cutoff_cp = region_players[-1][1]
    return key_to_rank, cutoff_cp


def get_all_players_for_season(
    season: str,
) -> list[tuple[str, str, str]]:
    """
    Return list of (display_name, canonical_name, region_code) for the dropdown.
    display_name = "Name (RegionGroup)" so same name in different regions are distinct.
    """
    player_events, player_region_code = _build_per_player_events(season)
    out: list[tuple[str, str, str]] = []
    seen: set = set()
    for (name, region_key), events in player_events.items():
        if not events:
            continue
        region_code = player_region_code.get((name, region_key), "")
        rg = map_region_to_group(region_code)
        display = f"{name} ({rg})"
        key = (name, region_key)
        if key in seen:
            continue
        seen.add(key)
        out.append((display, name, region_key))
    out.sort(key=lambda x: (x[0].lower(), x[1], x[2]))
    return out


def get_player_worlds_series(
    season: str,
    player_name: str,
    player_region_code: str,
    region_group_for_cutoff: str,
) -> list[WorldsRacePoint]:
    """
    Time series for the selected player: only dates when they had an event.
    Uses player's region for their regional rank; uses region_group_for_cutoff
    for the cutoff CP line (Chart 1). Chart 2 always uses player's region for rank.
    """
    player_region_code = (player_region_code or "").strip()
    region_key = player_region_code.upper() if player_region_code else ""
    player_key: PlayerKey = (player_name, region_key)

    merge_map = load_player_mappings(season).get("merges", {})
    dated = _load_tournaments_by_date(season)
    if not dated:
        return []

    player_events, _ = _build_per_player_events(season)
    events_list = player_events.get(player_key, [])
    if not events_list:
        return []

    cutoff_rank = WORLDS_CUTOFF_BY_REGION.get(
        region_group_for_cutoff.upper(),
        WORLDS_CUTOFF_BY_REGION.get("OTHER", 135),
    )
    player_region_group = map_region_to_group(player_region_code)

    snap_dates, snap_boards = _get_snapshot_progression(season, dated, merge_map)

    # Dates when this player played (to emit points)
    player_dates = sorted(set(e.tournament_date for e in events_list))
    event_by_date: dict[date, EventRecord] = {}
    for e in events_list:
        event_by_date[e.tournament_date] = e

    result: list[WorldsRacePoint] = []
    for d in player_dates:
        leaderboard = _board_at_or_before(snap_dates, snap_boards, d)
        if player_key not in leaderboard:
            continue

        total, cps_sorted, num_events, _, _ = leaderboard[player_key]
        rank_in_cutoff_region, cutoff_cp = _regional_rank_and_cutoff_cp(
            leaderboard, region_group_for_cutoff.upper(), cutoff_rank
        )
        rank_in_player_region, _ = _regional_rank_and_cutoff_cp(
            leaderboard, player_region_group, cutoff_rank
        )

        regional_rank = rank_in_player_region.get(player_key, 0)
        if cutoff_cp is None:
            cutoff_cp = 0
        gap = total - cutoff_cp

        ev = event_by_date.get(d)
        points_earned = ev.cp if ev else 0
        placement = ev.placement if ev else 0
        event_name = ev.tournament_title if ev else ""

        result.append(
            WorldsRacePoint(
                date=d,
                cumulative_cp=total,
                regional_rank=regional_rank,
                cutoff_cp=cutoff_cp,
                points_earned_at_event=points_earned,
                placement=placement,
                event_name=event_name,
                gap_to_cutoff=gap,
            )
        )
    return result


def get_cutoff_rank_for_region(region_group: str) -> int:
    """Return the Worlds invite cutoff rank for the given region group."""
    return WORLDS_CUTOFF_BY_REGION.get(
        region_group.upper(),
        WORLDS_CUTOFF_BY_REGION.get("OTHER", 135),
    )


def get_region_cutoff_series(
    season: str,
    region_group: str,
) -> tuple[list[date], list[int]]:
    """
    For the given season and region, return (dates, cutoff_cp) where:
    - dates are all Regional **and IC** tournament dates in the season, sorted.
    - cutoff_cp is the CP of the last invite slot (e.g. rank 135) in that region
      after each of those events, excluding autobid players from the ranking.

    International Championships both award CP and create autobid players; the
    snapshot after each Regional or IC reflects all events up to that date.
    """
    key = (season, region_group.upper())
    if key in _SEASON_REGION_CUTOFF_CACHE:
        return _SEASON_REGION_CUTOFF_CACHE[key]

    merge_map = load_player_mappings(season).get("merges", {})
    dated = _load_tournaments_by_date(season)
    if not dated:
        return [], []

    # Distinct dates of Regional and IC events in this season.
    event_dates: list[date] = []
    seen_dates: set = set()
    for t_date, data in dated:
        meta = data.get("metadata", {})
        t_type = meta.get("tournament_type", "REGIONAL").upper()
        if t_type not in ("REGIONAL", "IC"):
            continue
        if t_date not in seen_dates:
            seen_dates.add(t_date)
            event_dates.append(t_date)
    event_dates.sort()

    if not event_dates:
        return [], []

    cutoff_rank = get_cutoff_rank_for_region(region_group)
    cutoff_dates_filtered: list[date] = []
    cutoff_values: list[int] = []

    snap_dates, snap_boards = _get_snapshot_progression(season, dated, merge_map)

    for d in event_dates:
        leaderboard = _board_at_or_before(snap_dates, snap_boards, d)
        _, cutoff_cp = _regional_rank_and_cutoff_cp(
            leaderboard, region_group.upper(), cutoff_rank
        )
        # Skip dates where there are no players in this region yet.
        if cutoff_cp is None or cutoff_cp <= 0:
            continue
        cutoff_dates_filtered.append(d)
        cutoff_values.append(cutoff_cp)

    _SEASON_REGION_CUTOFF_CACHE[key] = (cutoff_dates_filtered, cutoff_values)
    return cutoff_dates_filtered, cutoff_values


def reset_worlds_race_cache(season: str | None = None) -> None:
    """
    Clear cached Worlds Race data.

    If season is None, clear all seasons; otherwise clear only the given season.
    This is called when the user hits \"Load Players\" so new/edited tournaments
    are taken into account.
    """
    if season is None:
        _SEASON_TOURNAMENT_CACHE.clear()
        _SEASON_PLAYER_EVENTS_CACHE.clear()
        _SEASON_REGION_CUTOFF_CACHE.clear()
        _SEASON_SNAPSHOT_PROG_CACHE.clear()
        return

    _SEASON_TOURNAMENT_CACHE.pop(season, None)
    _SEASON_PLAYER_EVENTS_CACHE.pop(season, None)
    _SEASON_SNAPSHOT_PROG_CACHE.pop(season, None)
    for key in list(_SEASON_REGION_CUTOFF_CACHE.keys()):
        if key[0] == season:
            _SEASON_REGION_CUTOFF_CACHE.pop(key, None)
