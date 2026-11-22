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
_SEASON_INVITE_FLOW_CACHE: dict[tuple[str, str], "InviteFlow"] = {}
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

            cp = calculate_cp(t_type, placement, num_comp, season=season)
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
    season: str,
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

        cp = calculate_cp(t_type, placement, num_comp, season=season)
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
    season: str,
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
            _append_tournament_to_player_events(player_events, player_region_code, d, data, merge_map, season)
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
    dates, boards = _build_leaderboard_snapshot_progression(dated, merge_map, season)
    _SEASON_SNAPSHOT_PROG_CACHE[season] = (dict(merge_map), dates, boards)
    return dates, boards


def _regional_rank_and_cutoff_cp(
    leaderboard: dict[PlayerKey, tuple[int, list[int], int, str, bool]],
    region_group: str,
    cutoff_rank: int,
    require_positive_cp: bool = False,
) -> tuple[dict[PlayerKey, int], int | None]:
    """
    Filter by region_group, ignoring autobid players, sort by
    (TotalCP, BestCP, SecondBestCP, NumEvents), assign rank.
    Returns (player_key -> regional_rank, cutoff_cp) where cutoff_cp is the
    CP of the last invite slot (e.g. rank 135 in NA).

    ``require_positive_cp`` excludes players who have appeared in results but
    earned no CP yet. Worlds Race and Invite Flow both use it so a region is
    not shown as having invitations before its events actually award CP.
    """
    region_players: list[tuple[PlayerKey, int, int, int, int]] = []
    for key, (total, cps_sorted, num_events, region_code, has_autobid) in leaderboard.items():
        rg = map_region_to_group(region_code)
        if rg != region_group:
            continue
        # Exclude autobid players from the invite race – they no longer occupy a slot.
        if has_autobid:
            continue
        if require_positive_cp and total <= 0:
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


# States used by the invite-flow (Sankey) chart.
INVITE_STATES = ("invited", "no_player", "out", "autobid", "new")


@dataclass(frozen=True)
class InviteFlowStage:
    """Invite-pool counts after all Regional/IC events on one date."""

    date: date
    event_names: tuple[str, ...]
    invited_count: int
    no_player_count: int
    out_count: int
    autobid_count: int
    new_count: int
    num_ranked: int
    cutoff_cp: int | None
    has_ic: bool = False

    def count_for(self, state: str) -> int:
        """Number of players (or open invite slots) in ``state`` at this stage."""
        return {
            "invited": self.invited_count,
            "no_player": self.no_player_count,
            "out": self.out_count,
            "autobid": self.autobid_count,
            "new": self.new_count,
        }[state]


@dataclass(frozen=True)
class InviteFlowTransition:
    """Player movements between two consecutive invite-flow stages."""

    date: date
    flows: dict[tuple[str, str], int]
    new_players: int = 0

    # Identity-based transitions used by the Sankey. ``kept`` and ``entered``
    # describe the *previous* column's invite states; the target is this date.
    kept_to_kept: int = 0
    entered_to_kept: int = 0
    kept_to_autobid: int = 0
    entered_to_autobid: int = 0
    kept_to_fell: int = 0
    entered_to_fell: int = 0
    autobid_to_autobid: int = 0
    entering_to_entered: int = 0
    autobid_source: int = 0

    @property
    def kept(self) -> int:
        """Players who keep their invite into this date."""
        total = self.kept_to_kept + self.entered_to_kept
        return total if total else self.flows.get(("invited", "invited"), 0)

    @property
    def entered(self) -> int:
        """Players who join the invite list at this date."""
        if self.entering_to_entered:
            return self.entering_to_entered
        return sum(
            count
            for (source, target), count in self.flows.items()
            if target == "invited" and source != "invited"
        )

    @property
    def fell_out(self) -> int:
        """Players who leave the invite list (dropped out or took an autobid)."""
        total = self.kept_to_fell + self.entered_to_fell
        return total if total else sum(
            count
            for (source, target), count in self.flows.items()
            if source == "invited" and target != "invited"
        )

    @property
    def autobid_gained(self) -> int:
        """New autobids at this date, from any source."""
        total = self.kept_to_autobid + self.entered_to_autobid + self.autobid_source
        return total if total else sum(
            count
            for (source, target), count in self.flows.items()
            if target == "autobid" and source != "autobid"
        )


@dataclass(frozen=True)
class InviteFlow:
    """Time series of invite-pool stages and the flows between them."""

    season: str
    region_group: str
    cutoff_rank: int
    stages: list[InviteFlowStage]
    transitions: list[InviteFlowTransition]


@dataclass(frozen=True)
class _InviteSnapshot:
    """Internal per-date sets used to derive identity-based Sankey flows."""

    date: date
    invited: frozenset[PlayerKey]
    out: frozenset[PlayerKey]
    autobid: frozenset[PlayerKey]
    region_keys: frozenset[PlayerKey]
    cutoff_cp: int | None
    num_ranked: int
    new_count: int
    kept: frozenset[PlayerKey]
    entered: frozenset[PlayerKey]


def get_invite_flows(season: str, region_group: str) -> InviteFlow:
    """
    Build the data for the invite-flow Sankey.

    Each stage is one distinct Regional/IC date in the season; all events on
    that date are applied together before the snapshot is taken. Only players
    with positive CP can occupy an invite slot, matching Worlds Race, so dates
    before the region earns CP are skipped.

    Snapshots track invite state by player identity so transitions can tell
    players who kept an invite apart from players who just entered the list.
    The legacy ``flows`` dict is still populated for compatibility.
    """
    group = region_group.upper()
    cache_key = (season, group)
    cached = _SEASON_INVITE_FLOW_CACHE.get(cache_key)
    if cached is not None:
        return cached

    empty = InviteFlow(season, group, get_cutoff_rank_for_region(group), [], [])
    merge_map = load_player_mappings(season).get("merges", {})
    dated = _load_tournaments_by_date(season)
    if not dated:
        return empty

    events_by_day: dict[date, list[str]] = defaultdict(list)
    ic_dates: set[date] = set()
    for t_date, data in dated:
        t_type = str(data.get("metadata", {}).get("tournament_type", "REGIONAL")).upper()
        if t_type not in ("REGIONAL", "IC"):
            continue
        title = str(data.get("metadata", {}).get("title", "Unknown"))
        events_by_day[t_date].append(title)
        if t_type == "IC":
            ic_dates.add(t_date)
    if not events_by_day:
        return empty

    cutoff_rank = get_cutoff_rank_for_region(group)
    snap_dates, snap_boards = _get_snapshot_progression(season, dated, merge_map)

    # Snapshot state by player identity so the Sankey can tell "kept" and
    # "entered" invitees apart. Zero-CP players cannot hold an invite slot.
    snapshots: list[_InviteSnapshot] = []
    previous_keys: set[PlayerKey] = set()
    previous_invited: set[PlayerKey] = set()
    for d in sorted(events_by_day):
        leaderboard = _board_at_or_before(snap_dates, snap_boards, d)
        ranks, cutoff_cp = _regional_rank_and_cutoff_cp(
            leaderboard, group, cutoff_rank, require_positive_cp=True
        )
        if len(ranks) < cutoff_rank or cutoff_cp is None or cutoff_cp <= 0:
            # Matches Worlds Race: no invite line until the region has enough
            # positive-CP players to fill all of its invite slots.
            continue
        region_keys = {
            key
            for key, (_, _, _, region_code, _) in leaderboard.items()
            if map_region_to_group(region_code) == group
        }
        invited = {key for key, rank in ranks.items() if rank <= cutoff_rank}
        autobid = {key for key in region_keys if leaderboard[key][4]}
        out = region_keys - invited - autobid
        snapshots.append(
            _InviteSnapshot(
                date=d,
                invited=frozenset(invited),
                out=frozenset(out),
                autobid=frozenset(autobid),
                region_keys=frozenset(region_keys),
                cutoff_cp=cutoff_cp,
                num_ranked=len(ranks),
                new_count=len(region_keys - previous_keys),
                kept=frozenset(invited & previous_invited),
                entered=frozenset(invited - previous_invited),
            )
        )
        previous_keys = set(region_keys)
        previous_invited = set(invited)

    stages = [
        InviteFlowStage(
            date=snapshot.date,
            event_names=tuple(events_by_day[snapshot.date]),
            invited_count=len(snapshot.invited),
            no_player_count=max(cutoff_rank - len(snapshot.invited), 0),
            out_count=len(snapshot.out),
            autobid_count=len(snapshot.autobid),
            new_count=snapshot.new_count,
            num_ranked=snapshot.num_ranked,
            cutoff_cp=snapshot.cutoff_cp,
            has_ic=snapshot.date in ic_dates,
        )
        for snapshot in snapshots
    ]

    if not stages or all(
        stage.invited_count + stage.out_count + stage.autobid_count == 0 for stage in stages
    ):
        # This region never earns CP in the season's data.
        return empty

    real_states = ("invited", "out", "autobid")
    transitions: list[InviteFlowTransition] = []
    for i in range(len(snapshots) - 1):
        prev, curr = snapshots[i], snapshots[i + 1]
        prev_sets = {"invited": prev.invited, "out": prev.out, "autobid": prev.autobid}
        curr_sets = {"invited": curr.invited, "out": curr.out, "autobid": curr.autobid}
        flows: dict[tuple[str, str], int] = defaultdict(int)

        # Legacy aggregate flows, retained for compatibility and the footer.
        for source in real_states:
            for key in prev_sets[source]:
                target = next((s for s in real_states if key in curr_sets[s]), None)
                if target is not None:
                    flows[(source, target)] += 1

        prev_open = stages[i].no_player_count
        curr_open = stages[i + 1].no_player_count

        for source in real_states:
            departed = stages[i].count_for(source) - sum(
                flows[(source, target)] for target in real_states
            )
            if departed <= 0:
                continue
            if source == "invited" and curr_open > 0:
                to_open = min(curr_open, departed)
                flows[("invited", "no_player")] += to_open
                departed -= to_open
            flows[(source, "no_player")] += departed

        new_invited = stages[i + 1].invited_count - sum(
            flows[(source, "invited")] for source in real_states
        )
        open_in = sum(flows[(source, "no_player")] for source in real_states)
        from_open = max(0, prev_open + open_in - curr_open)
        from_open = min(from_open, max(0, new_invited))
        flows[("no_player", "invited")] += from_open
        flows[("new", "invited")] += max(0, new_invited - from_open)
        for target in ("out", "autobid"):
            new_players = stages[i + 1].count_for(target) - sum(
                flows[(source, target)] for source in real_states
            )
            if new_players > 0:
                flows[("new", target)] += new_players

        new_players = sum(flows[("new", target)] for target in real_states)
        transitions.append(
            InviteFlowTransition(
                date=curr.date,
                flows=dict(flows),
                new_players=new_players,
                kept_to_kept=len(prev.kept & curr.invited),
                entered_to_kept=len(prev.entered & curr.invited),
                kept_to_autobid=len(prev.kept & curr.autobid),
                entered_to_autobid=len(prev.entered & curr.autobid),
                kept_to_fell=len(prev.kept - curr.invited - curr.autobid),
                entered_to_fell=len(prev.entered - curr.invited - curr.autobid),
                autobid_to_autobid=len(prev.autobid & curr.autobid),
                entering_to_entered=len(curr.entered),
                autobid_source=len((curr.autobid - prev.autobid) - prev.invited),
            )
        )

    result = InviteFlow(season, group, cutoff_rank, stages, transitions)
    _SEASON_INVITE_FLOW_CACHE[cache_key] = result
    return result


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
        _SEASON_INVITE_FLOW_CACHE.clear()
        _SEASON_SNAPSHOT_PROG_CACHE.clear()
        return

    _SEASON_TOURNAMENT_CACHE.pop(season, None)
    _SEASON_PLAYER_EVENTS_CACHE.pop(season, None)
    _SEASON_SNAPSHOT_PROG_CACHE.pop(season, None)
    for key in list(_SEASON_REGION_CUTOFF_CACHE.keys()):
        if key[0] == season:
            _SEASON_REGION_CUTOFF_CACHE.pop(key, None)
    for key in list(_SEASON_INVITE_FLOW_CACHE.keys()):
        if key[0] == season:
            _SEASON_INVITE_FLOW_CACHE.pop(key, None)
