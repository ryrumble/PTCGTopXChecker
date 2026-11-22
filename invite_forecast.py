"""Forward-looking Worlds invite forecast.

Combines three things the older charts kept separate:

1. the current invite race (CP, rank, cutoff) from ``worlds_race``;
2. player behaviour learned from the completed reference season (how many
   events they play, and the best placement tier they are capable of); and
3. a Monte Carlo projection of both the player's final CP and the cutoff.

The output is a per-player probability of still holding an invite at the end
of the season, a plausible final-CP range, and the extra CP needed to reach
a chosen confidence level. Probabilities are calibrated from last season, so
they are directional estimates rather than exact odds.
"""

from __future__ import annotations

import json
import tempfile
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from statistics import median

import numpy as np
from numpy.random import Generator, default_rng

from cp_calculator import calculate_cp
from logger import logger
from storage import list_seasons, load_player_mappings, load_total_cp_data
from utils import map_region_to_group, normalize_player_name
from worlds_race import (
    PlayerKey,
    _board_at_or_before,
    _build_per_player_events,
    _finalize_leaderboard_from_events,
    _get_snapshot_progression,
    _load_tournaments_by_date,
    _regional_rank_and_cutoff_cp,
    get_cutoff_rank_for_region,
    get_region_cutoff_series,
)

TIER_LABELS = (
    "T1", "T2", "T4", "T8", "T16", "T32", "T64", "T128", "T256", "T512", "T1024",
)
MAX_TIER_INDEX = len(TIER_LABELS) - 1

# A player can earn at most 260 CP outside Regional/IC events. This is the
# same cap the Total CP Analysis tab uses for its "Outstanding CP" column.
MAX_CUP_CHALLENGE_CP = 260

SCENARIO_FACTORS = {"Low": 0.6, "Baseline": 1.0, "High": 1.4}
DEFAULT_SCENARIO = "Baseline"

# The modern season has three International Championships. Capping IC
# projections here keeps a prior-season IC anchor from inventing extra events.
TOTAL_ICS_PER_SEASON = 3

_FIELD_FACTORS = (0.8, 0.9, 1.0, 1.1, 1.2)
_DEFAULT_FIELD_SIZE = 1500
# Wide enough that searches for players well outside the invite race still
# find a dot. CP lookups are cached, so the extra players are inexpensive.
_BUBBLE_DEPTH = 300

_FORECAST_CACHE: dict[tuple[object, ...], ForecastResult] = {}
_CP_LOOKUP_CACHE: dict[tuple[object, ...], dict[tuple[str, int, int], int]] = {}
_CUTOFF_SERIES_CACHE_VERSION = 1


@dataclass(frozen=True)
class AttendanceProjection:
    """Expected remaining schedule for one player, split by event type."""

    prior_regionals: int
    prior_ics: int
    current_regionals: int
    current_ics: int
    expected_regionals: int
    expected_ics: int
    remaining_regionals: int
    remaining_ics: int
    basis: str

    @property
    def total_remaining(self) -> int:
        return self.remaining_regionals + self.remaining_ics


@dataclass(frozen=True)
class ForecastConfig:
    """All tunable assumptions for one forecast run."""

    as_of: date | None = None
    reference_season: str | None = None
    include_cup_challenge: bool = False
    scenario: str = DEFAULT_SCENARIO
    ceiling_tiers_per_event: float = 1.0
    show_ceiling: bool = True
    simulations: int = 500
    seed: int = 20261121
    bubble_depth: int = _BUBBLE_DEPTH

    def cache_key(self) -> tuple[object, ...]:
        return (
            self.as_of,
            self.reference_season,
            self.include_cup_challenge,
            self.scenario,
            self.ceiling_tiers_per_event,
            self.show_ceiling,
            self.simulations,
            self.seed,
            self.bubble_depth,
        )


@dataclass(frozen=True)
class PlayerForecast:
    """One player's current standing and simulated season end."""

    key: PlayerKey
    name: str
    region_code: str
    region_group: str
    rank: int
    current_cp: int
    cutoff_cp: int
    p_keep: float
    cp_needed_for_80: int
    final_cp_p10: int
    final_cp_p50: int
    final_cp_p90: int
    projected_cutoff_p10: int
    projected_cutoff_p50: int
    projected_cutoff_p90: int
    events_played: int
    events_remaining: int
    prior_regionals: int
    prior_ics: int
    current_regionals: int
    current_ics: int
    expected_regionals: int
    expected_ics: int
    remaining_regionals: int
    remaining_ics: int
    attendance_basis: str
    pb_tier: str
    pb_index: int
    ceiling_tier: str
    ceiling_index: int
    ceiling_final_cp: int
    ceiling_p_keep: float
    ceiling_events: int
    final_cp_samples: np.ndarray

    @property
    def buffer(self) -> int:
        return self.current_cp - self.cutoff_cp

    @property
    def p_lose(self) -> float:
        return 1.0 - self.p_keep

    @property
    def zone(self) -> str:
        if self.p_keep >= 0.85:
            return "Safe"
        if self.p_keep >= 0.60:
            return "Likely in"
        if self.p_keep >= 0.35:
            return "Bubble"
        if self.p_keep >= 0.15:
            return "At risk"
        return "Likely out"

    @property
    def display(self) -> str:
        return f"{self.name} ({self.region_group})"


@dataclass(frozen=True)
class ForecastResult:
    """Everything the GUI needs to draw the three forecast views."""

    season: str
    region: str
    as_of: date
    season_progress: float
    reference_season: str | None
    cutoff_rank: int
    cutoff_cp: int
    players: list[PlayerForecast]
    cutoff_samples: np.ndarray
    config: ForecastConfig
    warnings: tuple[str, ...] = ()

    @property
    def has_data(self) -> bool:
        return bool(self.players)

    def player_by_key(self, key: PlayerKey) -> PlayerForecast | None:
        return next((player for player in self.players if player.key == key), None)


def reset_forecast_cache(season: str | None = None) -> None:
    """Drop cached forecasts (call after tournament data changes)."""
    if season is None:
        _FORECAST_CACHE.clear()
        _CP_LOOKUP_CACHE.clear()
        return
    for key in list(_FORECAST_CACHE):
        if key[0] == season:
            _FORECAST_CACHE.pop(key, None)
    for key in list(_CP_LOOKUP_CACHE):
        if key[0] == season:
            _CP_LOOKUP_CACHE.pop(key, None)


def placement_tier_index(placement: int) -> int:
    """Map a finishing place to a bracket tier index (0 = 1st, 10 = T1024).

    Bracket boundaries are powers of two, so ``(place - 1).bit_length()``
    gives the tier without needing to know the tournament's field size.
    """
    if placement <= 1:
        return 0
    return min(MAX_TIER_INDEX, (placement - 1).bit_length())


def tier_label(index: int) -> str:
    return TIER_LABELS[max(0, min(MAX_TIER_INDEX, int(index)))]


def season_bounds(season: str) -> tuple[date, date]:
    """Approximate competitive season: September 1 through June 30."""
    try:
        start_year = int(season[:4])
    except ValueError as exc:
        raise ValueError(f"Invalid season label: {season!r}") from exc
    return date(start_year, 9, 1), date(start_year + 1, 6, 30)


def season_progress(season: str, as_of: date) -> float:
    start, end = season_bounds(season)
    total_days = (end - start).days
    if total_days <= 0:
        return 0.0
    return float(np.clip((as_of - start).days / total_days, 0.0, 1.0))


def analogous_date(reference_season: str, progress: float) -> date:
    start, end = season_bounds(reference_season)
    return start + float(np.clip(progress, 0.0, 1.0)) * (end - start)


def _sample_placement_for_tier(index: int) -> int:
    """Lowest finishing place inside a bracket (CP is flat within a bracket)."""
    if index <= 0:
        return 1
    return (1 << (index - 1)) + 1


def _is_ic(event_type: str) -> bool:
    return str(event_type).upper() == "IC"


def _round_half_up(value: float) -> int:
    return int(value + 0.5) if value >= 0 else int(value - 0.5)


def _distinct_dates_by_type(
    dated: list[tuple[date, dict]], as_of: date | None = None
) -> tuple[set[date], set[date]]:
    """Distinct regional and IC dates, optionally only up to ``as_of``."""
    regional_dates: set[date] = set()
    ic_dates: set[date] = set()
    for day, data in dated:
        if as_of is not None and day > as_of:
            continue
        event_type = str(data.get("metadata", {}).get("tournament_type", "REGIONAL"))
        if _is_ic(event_type):
            ic_dates.add(day)
        else:
            regional_dates.add(day)
    return regional_dates, ic_dates


def project_attendance(
    *,
    current_events: list,
    prior_regionals: int,
    prior_ics: int,
    region_median_regionals: int,
    regional_dates_total: int,
    regional_dates_elapsed: int,
    ic_dates_elapsed: int,
) -> AttendanceProjection:
    """Project a player's remaining regional and IC events.

    Regionals use a 50/50 blend of current pace and prior-season count. ICs use
    the prior count as an anchor when the player attended any, but the total is
    capped at ``TOTAL_ICS_PER_SEASON`` and by the number of IC slots still open.
    """
    current_regionals = sum(1 for event in current_events if not _is_ic(event.tournament_type))
    current_ics = sum(1 for event in current_events if _is_ic(event.tournament_type))

    total_dates = max(1, int(regional_dates_total))
    elapsed_dates = min(total_dates, max(1, int(regional_dates_elapsed)))
    regional_slots_remaining = max(0, total_dates - elapsed_dates)

    prior_found = prior_regionals > 0 or prior_ics > 0
    target_regionals = prior_regionals if prior_found else region_median_regionals
    pace_regionals = current_regionals / elapsed_dates * total_dates
    expected_regionals = _round_half_up(0.5 * pace_regionals + 0.5 * target_regionals)
    expected_regionals = max(current_regionals, expected_regionals)
    remaining_regionals = min(
        max(0, expected_regionals - current_regionals), regional_slots_remaining
    )

    elapsed_ic_dates = min(TOTAL_ICS_PER_SEASON, max(1, int(ic_dates_elapsed)))
    ic_slots_remaining = TOTAL_ICS_PER_SEASON - min(TOTAL_ICS_PER_SEASON, int(ic_dates_elapsed))
    if prior_ics > 0:
        expected_ics = max(current_ics, prior_ics)
        ic_basis = "prior-IC anchor"
    else:
        expected_ics = _round_half_up(current_ics / elapsed_ic_dates * TOTAL_ICS_PER_SEASON)
        ic_basis = "IC pace"
    expected_ics = min(TOTAL_ICS_PER_SEASON, max(current_ics, expected_ics))
    remaining_ics = min(max(0, expected_ics - current_ics), ic_slots_remaining)

    regional_basis = "50/50 pace+prior" if prior_found else "50/50 pace+region median"
    if remaining_regionals < expected_regionals - current_regionals:
        regional_basis += ", capped by schedule"
    if remaining_ics < expected_ics - current_ics:
        ic_basis += ", capped by remaining IC slots"

    return AttendanceProjection(
        prior_regionals=prior_regionals,
        prior_ics=prior_ics,
        current_regionals=current_regionals,
        current_ics=current_ics,
        expected_regionals=expected_regionals,
        expected_ics=expected_ics,
        remaining_regionals=remaining_regionals,
        remaining_ics=remaining_ics,
        basis=f"{regional_basis}; {ic_basis}",
    )


def _reference_profiles(
    season: str,
) -> tuple[dict[PlayerKey, tuple[int, int, int]], dict[str, int]]:
    """Return (regionals, ICs, best tier) per player and regional medians."""
    merge_map = load_player_mappings(season).get("merges", {})
    events, region_codes = _build_per_player_events(season)
    merged: dict[PlayerKey, list] = {}
    for key, player_events in events.items():
        canonical_key = (merge_map.get(key[0], key[0]), key[1])
        merged.setdefault(canonical_key, []).extend(player_events)

    profiles: dict[PlayerKey, tuple[int, int, int]] = {}
    for key, player_events in merged.items():
        regionals = sum(1 for event in player_events if not _is_ic(event.tournament_type))
        ics = sum(1 for event in player_events if _is_ic(event.tournament_type))
        tiers = [placement_tier_index(event.placement) for event in player_events]
        best_tier = min(tiers) if tiers else MAX_TIER_INDEX
        profiles[key] = (regionals, ics, best_tier)

    regional_counts: dict[str, list[int]] = {}
    for key, (regionals, _, _) in profiles.items():
        group = map_region_to_group(region_codes.get(key, key[1]))
        regional_counts.setdefault(group, []).append(regionals)
    region_medians = {group: int(median(counts)) for group, counts in regional_counts.items()}
    return profiles, region_medians


def _best_tier_by_name(season: str, as_of: date) -> dict[str, int]:
    """Best placement tier achieved by each player in any available season.

    Merges are applied using the forecast season's mapping so a player renamed
    in an older season still contributes their historical personal best.
    """
    merges = load_player_mappings(season).get("merges", {})
    best: dict[str, int] = {}
    for candidate in (value for value in list_seasons() if value <= season):
        events, _ = _build_per_player_events(candidate)
        for (name, _region), player_events in events.items():
            canonical = merges.get(name, name)
            for event in player_events:
                if candidate == season and event.tournament_date > as_of:
                    continue
                if event.placement <= 0:
                    continue
                tier = placement_tier_index(event.placement)
                if tier < best.get(canonical, MAX_TIER_INDEX):
                    best[canonical] = tier
    return best


def _cup_challenge_headroom(entries: list[dict], key: PlayerKey, current_cp: int) -> tuple[int, bool]:
    """Remaining non-regional CP from the (deprecated) pokedata export."""
    name = normalize_player_name(key[0])
    for entry in entries:
        if normalize_player_name(str(entry.get("raw_name", ""))) != name:
            continue
        total_cp = int(entry.get("current_points", 0) or 0)
        non_regional = max(0, total_cp - current_cp)
        return max(0, MAX_CUP_CHALLENGE_CP - non_regional), True
    return 0, False


def _cutoff_series_signature(season: str, dated: list[tuple[date, dict]]) -> str:
    """Cheap fingerprint for invalidating the on-disk cutoff-series cache."""
    merge_map = load_player_mappings(season).get("merges", {})
    tournaments = []
    for day, data in dated:
        meta = data.get("metadata") or {}
        tournaments.append(
            [day.isoformat(), str(meta.get("id", "")), str(meta.get("added_at", ""))]
        )
    payload = {
        "version": _CUTOFF_SERIES_CACHE_VERSION,
        "merges": merge_map,
        "tournaments": tournaments,
    }
    digest = sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8"))
    return digest.hexdigest()[:16]


def _cached_cutoff_series(
    season: str, region: str, dated: list[tuple[date, dict]]
) -> tuple[list[date], list[int]]:
    """Load a prior season's cutoff series without rebuilding every snapshot.

    ``get_region_cutoff_series`` replays the whole season. That is expensive and
    dominates a cold forecast run, so cache the small result in the user's temp
    directory, keyed by tournament IDs, player merges, and a cache version.
    """
    region = region.upper()
    signature = _cutoff_series_signature(season, dated)
    cache_path = (
        Path(tempfile.gettempdir())
        / "pkmn-topx-invite-cache"
        / f"cutoff_{season}_{region}_{signature}.json"
    )
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        dates = [date.fromisoformat(value) for value in payload["dates"]]
        values = [int(value) for value in payload["values"]]
        return dates, values
    except (OSError, KeyError, TypeError, ValueError):
        pass

    dates, values = get_region_cutoff_series(season, region)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "dates": [day.isoformat() for day in dates],
                    "values": values,
                }
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Could not cache cutoff series for %s/%s: %s", season, region, exc)
    return dates, values


def _cutoff_increments_from_series(
    dates: list[date], values: list[int], season: str, progress: float
) -> list[int]:
    """Observed cutoff jumps from the reference season's analogous point onward."""
    if len(values) < 2:
        return [0]
    anchor = analogous_date(season, progress)
    index = max(0, bisect_right(dates, anchor) - 1)
    tail = values[index:]
    increments = [max(0, int(tail[i + 1]) - int(tail[i])) for i in range(len(tail) - 1)]
    if not increments:
        increments = [
            max(0, int(values[i + 1]) - int(values[i])) for i in range(len(values) - 1)
        ]
    return increments or [0]


def _cutoff_increments(season: str, region: str, progress: float) -> list[int]:
    """Observed cutoff jumps from the reference season's analogous point onward."""
    dates, values = get_region_cutoff_series(season, region)
    return _cutoff_increments_from_series(dates, values, season, progress)


def _remaining_cutoff_dates(dates: list[date], season: str, progress: float) -> int:
    if not dates:
        return 1
    anchor = analogous_date(season, progress)
    return max(1, sum(1 for day in dates if day > anchor))


def _remaining_reference_dates(season: str, region: str, progress: float) -> int:
    dates, _ = get_region_cutoff_series(season, region)
    return _remaining_cutoff_dates(dates, season, progress)


def _percentile(values: np.ndarray, percent: float) -> int:
    return int(round(float(np.percentile(values, percent))))


def _find_reference_season(season: str, requested: str | None) -> str | None:
    if requested:
        return requested if requested != season else None
    available = [candidate for candidate in list_seasons() if candidate < season]
    return available[0] if available else None


@dataclass
class _PlayerInputs:
    key: PlayerKey
    rank: int
    current_cp: int
    cps_sorted: list[int]
    region_code: str
    events: list
    pb_index: int
    ceiling_gain: float
    projection: AttendanceProjection
    cup_headroom: int

    @property
    def events_remaining(self) -> int:
        return self.projection.total_remaining


def _build_player_inputs(
    *,
    leaderboard: dict,
    ranks: dict[PlayerKey, int],
    events_by_player: dict[PlayerKey, list],
    reference: dict[PlayerKey, tuple[int, int, int]],
    pb_by_name: dict[str, int],
    region_median_regionals: dict[str, int],
    regional_dates_total: int,
    regional_dates_elapsed: int,
    ic_dates_elapsed: int,
    cutoff_rank: int,
    as_of: date,
    config: ForecastConfig,
    cup_by_player: dict[PlayerKey, int],
) -> list[_PlayerInputs]:
    results: list[_PlayerInputs] = []
    limit = min(cutoff_rank + config.bubble_depth, len(ranks))
    ranked_keys = sorted(ranks, key=lambda key: ranks[key])[:limit]

    for key in ranked_keys:
        total, cps_sorted, _, region_code, _ = leaderboard[key]
        events = [event for event in events_by_player.get(key, []) if event.tournament_date <= as_of]
        if not events:
            continue

        tiers = [placement_tier_index(event.placement) for event in events if event.placement > 0]
        current_pb = min(tiers) if tiers else MAX_TIER_INDEX
        ref_entry = reference.get(key)
        season_pb = min(current_pb, ref_entry[2]) if ref_entry is not None else current_pb
        pb_index = pb_by_name.get(key[0], season_pb)
        prior_regionals = ref_entry[0] if ref_entry is not None else 0
        prior_ics = ref_entry[1] if ref_entry is not None else 0
        group = map_region_to_group(region_code)
        region_median = region_median_regionals.get(group, 0)

        projection = project_attendance(
            current_events=events,
            prior_regionals=prior_regionals,
            prior_ics=prior_ics,
            region_median_regionals=region_median,
            regional_dates_total=regional_dates_total,
            regional_dates_elapsed=regional_dates_elapsed,
            ic_dates_elapsed=ic_dates_elapsed,
        )

        results.append(
            _PlayerInputs(
                key=key,
                rank=ranks[key],
                current_cp=int(total),
                cps_sorted=list(cps_sorted),
                region_code=region_code,
                events=events,
                pb_index=min(pb_index, MAX_TIER_INDEX),
                ceiling_gain=float(config.ceiling_tiers_per_event),
                projection=projection,
                cup_headroom=cup_by_player.get(key, 0),
            )
        )
    return results


def _cp_lookup_key(events: list, season: str) -> tuple[str, int, tuple[str, ...]]:
    """Summarise the inputs that affect a player's CP lookup table."""
    field_sizes = [event.num_competitors for event in events if event.num_competitors > 0]
    field_size = int(median(field_sizes)) if field_sizes else _DEFAULT_FIELD_SIZE
    event_types = {
        "IC" if _is_ic(str(event.tournament_type)) else "REGIONAL" for event in events
    }
    return season, field_size, tuple(sorted(event_types or {"REGIONAL"}))


def _cp_lookup(events: list, season: str) -> dict[tuple[str, int, int], int]:
    """Precompute CP for each event type / field-size factor / tier."""
    cache_key = _cp_lookup_key(events, season)
    cached = _CP_LOOKUP_CACHE.get(cache_key)
    if cached is not None:
        return cached

    _, field_size, types = cache_key
    lookup: dict[tuple[str, int, int], int] = {}
    for event_type in types:
        for factor_index, factor in enumerate(_FIELD_FACTORS):
            competitors = max(1, int(round(field_size * factor)))
            for tier in range(MAX_TIER_INDEX + 1):
                lookup[(event_type, factor_index, tier)] = calculate_cp(
                    event_type, _sample_placement_for_tier(tier), competitors, season=season
                )
    _CP_LOOKUP_CACHE[cache_key] = lookup
    return lookup


def _ceiling_projection(inputs: _PlayerInputs, season: str) -> tuple[int, int]:
    """Best plausible tier/CP if every remaining event hits its ceiling.

    The ceiling improves one tier per remaining event by default, capped at
    T1. This is deliberately separate from the simulation used for P(keep).
    """
    gain = max(0.0, float(inputs.ceiling_gain))
    steps = int(np.rint(inputs.events_remaining * gain))
    ceiling_index = max(0, inputs.pb_index - steps)
    if inputs.events_remaining == 0:
        return ceiling_index, inputs.current_cp

    _, field_size, _ = _cp_lookup_key(inputs.events, season)
    types = ["REGIONAL"] * inputs.projection.remaining_regionals
    types += ["IC"] * inputs.projection.remaining_ics
    types = (types + ["REGIONAL"] * inputs.events_remaining)[: inputs.events_remaining]

    cps = list(inputs.cps_sorted[:5])
    for event_number, event_type in enumerate(types, start=1):
        tier = max(0, inputs.pb_index - int(np.rint(event_number * gain)))
        cps.append(
            calculate_cp(
                event_type, _sample_placement_for_tier(tier), field_size, season=season
            )
        )
    ceiling_cp = sum(sorted(cps, reverse=True)[:5]) + inputs.cup_headroom
    return ceiling_index, max(0, ceiling_cp)


@dataclass(frozen=True)
class _SimulationOutcome:
    """Values derived from the Monte Carlo run, before GUI-facing fields are added."""

    p_keep: float
    cp_needed_for_80: int
    final_cp_p10: int
    final_cp_p50: int
    final_cp_p90: int
    final_cp_samples: np.ndarray


def _simulate_player(
    inputs: _PlayerInputs,
    *,
    season: str,
    cutoff_samples: np.ndarray,
    config: ForecastConfig,
    rng: Generator,
) -> _SimulationOutcome:
    n_sims = max(50, int(config.simulations))
    lookup = _cp_lookup(inputs.events, season)

    type_counts: dict[str, int] = {}
    for event in inputs.events:
        event_type = "IC" if str(event.tournament_type).upper() == "IC" else "REGIONAL"
        type_counts[event_type] = type_counts.get(event_type, 0) + 1
    types = list(type_counts) or ["REGIONAL"]
    type_probabilities = np.array([type_counts[t] for t in types], dtype=float)
    type_probabilities /= type_probabilities.sum()

    n_factors = len(_FIELD_FACTORS)
    n_events = max(0, int(inputs.events_remaining))
    cp_matrix = np.array(
        [
            [lookup[(event_type, factor_index, tier)] for tier in range(MAX_TIER_INDEX + 1)]
            for event_type in types
            for factor_index in range(n_factors)
        ],
        dtype=np.int64,
    )

    base_cps = np.zeros((n_sims, 5), dtype=np.int64)
    existing = sorted(inputs.cps_sorted, reverse=True)[:5]
    base_cps[:, : len(existing)] = existing

    if n_events:
        # Expected placements stay anchored at the demonstrated PB. Ceiling
        # improvement is shown separately and never inflates P(keep).
        expected = np.full((1, n_events), inputs.pb_index)
        worst = np.full((1, n_events), min(MAX_TIER_INDEX, inputs.pb_index + 2))
        tiers = np.rint(
            rng.triangular(expected, expected, worst, size=(n_sims, n_events))
        ).astype(int)
        tiers = np.clip(tiers, 0, MAX_TIER_INDEX)
        type_slots = rng.choice(len(types), size=(n_sims, n_events), p=type_probabilities)
        factor_slots = rng.integers(0, n_factors, size=(n_sims, n_events))
        future_cps = cp_matrix[type_slots * n_factors + factor_slots, tiers]
        all_cps = np.concatenate((base_cps, future_cps), axis=1)
    else:
        all_cps = base_cps

    all_cps.sort(axis=1)
    final_cps = all_cps[:, -5:].sum(axis=1)
    if inputs.cup_headroom > 0:
        final_cps += rng.integers(0, inputs.cup_headroom + 1, size=n_sims)

    # Small symmetric jitter resolves exact ties roughly 50/50 without
    # pretending to know the rival's tiebreaker scores.
    jitter = rng.uniform(-0.5, 0.5, size=n_sims)
    margins = final_cps.astype(float) + jitter - cutoff_samples
    p_keep = float(np.mean(margins >= 0))

    low, high = 0, MAX_CUP_CHALLENGE_CP
    while float(np.mean(margins + high >= 0)) < 0.80 and high < 5000:
        high *= 2
    while low < high:
        mid = (low + high) // 2
        if float(np.mean(margins + mid >= 0)) >= 0.80:
            high = mid
        else:
            low = mid + 1

    return _SimulationOutcome(
        p_keep=p_keep,
        cp_needed_for_80=low,
        final_cp_p10=_percentile(final_cps, 10),
        final_cp_p50=_percentile(final_cps, 50),
        final_cp_p90=_percentile(final_cps, 90),
        final_cp_samples=final_cps,
    )


def build_forecast(season: str, region: str, config: ForecastConfig | None = None) -> ForecastResult:
    """Build the invite forecast for one season and region group."""
    config = config or ForecastConfig()
    cache_key = (season, region.upper(), *config.cache_key())
    cached = _FORECAST_CACHE.get(cache_key)
    if cached is not None:
        return cached

    group = region.upper()
    dated = _load_tournaments_by_date(season)
    latest = max((day for day, _ in dated), default=None)
    as_of = config.as_of or latest
    if as_of is None:
        return ForecastResult(
            season, group, date.today(), 0.0, None,
            get_cutoff_rank_for_region(group), 0, [], np.array([], dtype=np.int64), config,
            ("No dated tournaments found for this season.",),
        )

    warnings: list[str] = []
    reference_season = _find_reference_season(season, config.reference_season)
    if reference_season is None:
        warnings.append("No earlier season available; cutoff growth is estimated from this season.")
        reference_season = season

    progress = season_progress(season, as_of)
    events_by_player, player_regions = _build_per_player_events(season)
    if latest is not None and as_of >= latest:
        # The default as-of date is the latest event. One final board is enough;
        # replaying every intermediate snapshot is pure overhead.
        leaderboard = _finalize_leaderboard_from_events(events_by_player, player_regions)
    else:
        merge_map = load_player_mappings(season).get("merges", {})
        snap_dates, snap_boards = _get_snapshot_progression(season, dated, merge_map)
        leaderboard = _board_at_or_before(snap_dates, snap_boards, as_of)

    cutoff_rank = get_cutoff_rank_for_region(group)
    ranks, cutoff_cp = _regional_rank_and_cutoff_cp(
        leaderboard, group, cutoff_rank, require_positive_cp=True
    )
    if not ranks or cutoff_cp is None:
        return ForecastResult(
            season, group, as_of, progress, reference_season, cutoff_rank, 0, [],
            np.array([], dtype=np.int64), config,
            (*warnings, "No invite race data for this region at the selected date."),
        )

    if reference_season != season:
        reference, region_median_regionals = _reference_profiles(reference_season)
    else:
        reference, region_median_regionals = {}, {}

    # The current season's regional medians are a better fallback for players
    # who did not appear in the reference season.
    current_regional_counts: dict[str, list[int]] = {}
    for key, events in events_by_player.items():
        group_key = player_regions.get(key, key[1])
        count = sum(1 for event in events if not _is_ic(event.tournament_type))
        current_regional_counts.setdefault(map_region_to_group(group_key), []).append(count)
    for group_key, counts in current_regional_counts.items():
        region_median_regionals.setdefault(group_key, int(median(counts)))

    current_regional_dates, current_ic_dates = _distinct_dates_by_type(dated, as_of)
    reference_dated = _load_tournaments_by_date(reference_season)
    reference_regional_dates, _ = _distinct_dates_by_type(reference_dated)
    regional_dates_total = max(1, len(reference_regional_dates))
    regional_dates_elapsed = min(regional_dates_total, len(current_regional_dates))
    ic_dates_elapsed = min(TOTAL_ICS_PER_SEASON, len(current_ic_dates))

    cup_by_player: dict[PlayerKey, int] = {}
    if config.include_cup_challenge:
        try:
            cup_entries = load_total_cp_data(season)
        except Exception as exc:  # noqa: BLE001 - optional/stale data must not break the tab
            logger.warning("Total CP data unavailable for %s: %s", season, exc)
            cup_entries = []
        matches = 0
        for key in ranks:
            headroom, matched = _cup_challenge_headroom(cup_entries, key, int(leaderboard[key][0]))
            if headroom > 0:
                cup_by_player[key] = headroom
            if matched:
                matches += 1
        if matches == 0:
            warnings.append("Cup/Challenge data enabled but no players matched; headroom is 0.")

    pb_by_name = _best_tier_by_name(season, as_of)

    inputs = _build_player_inputs(
        leaderboard=leaderboard,
        ranks=ranks,
        events_by_player=events_by_player,
        reference=reference,
        pb_by_name=pb_by_name,
        region_median_regionals=region_median_regionals,
        regional_dates_total=regional_dates_total,
        regional_dates_elapsed=regional_dates_elapsed,
        ic_dates_elapsed=ic_dates_elapsed,
        cutoff_rank=cutoff_rank,
        as_of=as_of,
        config=config,
        cup_by_player=cup_by_player,
    )

    if reference_season == season:
        # No completed prior season to learn from: show the observed final
        # standings rather than inventing future cutoff growth.
        increments = [0]
        n_remaining_dates = 1
    else:
        cutoff_dates, cutoff_values = _cached_cutoff_series(reference_season, group, reference_dated)
        increments = _cutoff_increments_from_series(
            cutoff_dates, cutoff_values, reference_season, progress
        )
        n_remaining_dates = _remaining_cutoff_dates(cutoff_dates, reference_season, progress)
    n_sims = max(50, int(config.simulations))
    scenario_factor = SCENARIO_FACTORS.get(config.scenario, 1.0)
    rng = default_rng(config.seed)
    jumps = rng.choice(np.array(increments, dtype=np.int64), size=(n_sims, n_remaining_dates))
    # Each row is one independent season path. Do not accumulate across rows:
    # that would distort the simulated cutoff distribution by simulation order.
    cutoff_samples = np.rint(int(cutoff_cp) + jumps.sum(axis=1) * scenario_factor).astype(np.int64)

    players: list[PlayerForecast] = []
    for player_inputs in inputs:
        outcome = _simulate_player(
            player_inputs, season=season, cutoff_samples=cutoff_samples, config=config, rng=rng
        )
        ceiling_index, ceiling_cp = _ceiling_projection(player_inputs, season)
        ceiling_p_keep = float(np.mean(cutoff_samples <= ceiling_cp))
        players.append(
            PlayerForecast(
                key=player_inputs.key,
                name=player_inputs.key[0],
                region_code=player_inputs.region_code,
                region_group=group,
                rank=player_inputs.rank,
                current_cp=player_inputs.current_cp,
                cutoff_cp=int(cutoff_cp),
                p_keep=outcome.p_keep,
                cp_needed_for_80=outcome.cp_needed_for_80,
                final_cp_p10=outcome.final_cp_p10,
                final_cp_p50=outcome.final_cp_p50,
                final_cp_p90=outcome.final_cp_p90,
                projected_cutoff_p10=_percentile(cutoff_samples, 10),
                projected_cutoff_p50=_percentile(cutoff_samples, 50),
                projected_cutoff_p90=_percentile(cutoff_samples, 90),
                events_played=len(player_inputs.events),
                events_remaining=player_inputs.events_remaining,
                prior_regionals=player_inputs.projection.prior_regionals,
                prior_ics=player_inputs.projection.prior_ics,
                current_regionals=player_inputs.projection.current_regionals,
                current_ics=player_inputs.projection.current_ics,
                expected_regionals=player_inputs.projection.expected_regionals,
                expected_ics=player_inputs.projection.expected_ics,
                remaining_regionals=player_inputs.projection.remaining_regionals,
                remaining_ics=player_inputs.projection.remaining_ics,
                attendance_basis=player_inputs.projection.basis,
                pb_tier=tier_label(player_inputs.pb_index),
                pb_index=player_inputs.pb_index,
                ceiling_tier=tier_label(ceiling_index),
                ceiling_index=ceiling_index,
                ceiling_final_cp=ceiling_cp,
                ceiling_p_keep=ceiling_p_keep,
                ceiling_events=player_inputs.events_remaining,
                final_cp_samples=outcome.final_cp_samples,
            )
        )

    result = ForecastResult(
        season=season,
        region=group,
        as_of=as_of,
        season_progress=progress,
        reference_season=reference_season,
        cutoff_rank=cutoff_rank,
        cutoff_cp=int(cutoff_cp),
        players=players,
        cutoff_samples=cutoff_samples,
        config=config,
        warnings=tuple(warnings),
    )
    _FORECAST_CACHE[cache_key] = result
    return result
