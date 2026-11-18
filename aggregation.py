from dataclasses import dataclass, field

import pandas as pd

from cp_calculator import calculate_cp
from logger import logger
from storage import list_tournament_files, load_json, load_player_mappings, save_season_aggregate
from utils import map_region_to_group
from worlds_race import reset_worlds_race_cache

# Composite key for same-name players in different regions: (canonical_name, region_code)
PlayerKey = tuple[str, str]

_AGG_DF_CACHE: dict[str, pd.DataFrame] = {}


def invalidate_season_caches(season: str) -> None:
    """Drop caches for this season (call after saves/deletes)."""
    _AGG_DF_CACHE.pop(season, None)
    reset_worlds_race_cache(season)


@dataclass
class PlayerStats:
    name: str
    region_code: str | None
    cp_finishes: list[int] = field(default_factory=list)
    placements: list[int] = field(default_factory=list)
    tournament_results: list[dict] = field(default_factory=list)

    def add_result(
        self,
        cp: int,
        placement: int,
        tournament_title: str,
        tournament_type: str,
        num_competitors: int = 0,
        tournament_id: str = "",
    ) -> None:
        self.cp_finishes.append(cp)
        self.placements.append(placement)
        self.tournament_results.append({
            "tournament": tournament_title,
            "placement": placement,
            "type": tournament_type,
            "cp": cp,
            "num_competitors": num_competitors,
            "tournament_id": tournament_id,
        })


def aggregate_season(season: str, *, force: bool = False) -> pd.DataFrame:
    """Aggregate all tournaments for a season into a leaderboard DataFrame.

    Results are cached per season until ``force=True`` or :func:`invalidate_season_caches`.
    """
    if force:
        invalidate_season_caches(season)
    elif season in _AGG_DF_CACHE:
        return _AGG_DF_CACHE[season]

    logger.debug("Aggregating season %s", season)
    files = list_tournament_files(season)
    players: dict[PlayerKey, PlayerStats] = {}
    tournaments_meta: list[dict] = []

    # Load player mappings
    mappings = load_player_mappings(season)
    merge_map = mappings.get("merges", {})

    for path in files:
        data = load_json(path)
        meta = data.get("metadata", {})
        t_type = meta.get("tournament_type", "REGIONAL")
        num_comp = int(meta.get("num_competitors", 0) or 0)
        tournaments_meta.append(meta)

        for entry in data.get("normalized_entries", []):
            placement = int(entry["placement"])
            name = entry["normalized_name"]
            # Apply merge mapping if exists (same person, different spellings)
            canonical_name = merge_map.get(name, name)
            region_code = entry.get("region_code")
            # Key by (name, region) so same name in different regions = different players
            region_key = (region_code or "").strip().upper() if region_code else ""
            key: PlayerKey = (canonical_name, region_key)
            cp = calculate_cp(t_type, placement, num_comp)
            if key not in players:
                players[key] = PlayerStats(name=canonical_name, region_code=region_code)
            players[key].add_result(
                cp,
                placement,
                meta.get("title", "Unknown"),
                t_type,
                num_comp,
                meta.get("id", ""),
            )

    rows: list[dict] = []
    for p in players.values():
        cps_sorted = sorted(p.cp_finishes, reverse=True)
        top5 = cps_sorted[:5]
        total_cp = sum(top5)
        num_events = len(p.cp_finishes)
        highest_placement = min(p.placements) if p.placements else None

        # Check for autobid: won regional (placement 1 in REGIONAL) or top 4 in IC
        has_autobid = False
        for result in p.tournament_results:
            if (result["type"] == "REGIONAL" and result["placement"] == 1) or (result["type"] == "IC" and result["placement"] <= 4):
                has_autobid = True
                break

        rows.append(
            {
                "Name": p.name,
                "RegionCode": p.region_code or "",
                "RegionGroup": map_region_to_group(p.region_code),
                "TotalCP": total_cp,
                "CPFinishes": cps_sorted,
                "CPFinishesStr": ", ".join(str(x) for x in cps_sorted),
                "NumTournaments": num_events,
                "HighestPlacement": highest_placement,
                "HasAutobid": has_autobid,
                "TournamentResults": p.tournament_results,  # Store for double-click display
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Ranking with tie-breakers:
    # 1) TotalCP desc
    # 2) Highest single CP (max of finishes)
    # 3) Second-highest, etc. (handled implicitly by CPFinishes list)
    # 4) Most tournaments
    df["BestCP"] = df["CPFinishes"].apply(lambda lst: lst[0] if lst else 0)
    df["SecondBestCP"] = df["CPFinishes"].apply(lambda lst: lst[1] if len(lst) > 1 else 0)

    df = df.sort_values(
        by=["TotalCP", "BestCP", "SecondBestCP", "NumTournaments"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    df.insert(0, "Rank", df.index + 1)

    # Write season aggregate JSON
    aggregate_payload = {
        "season": season,
        "leaderboard": df.to_dict(orient="records"),
        "tournaments": tournaments_meta,
    }
    save_season_aggregate(season, aggregate_payload)

    logger.debug("Season %s aggregation complete: %s players", season, len(df))
    _AGG_DF_CACHE[season] = df
    return df


def filter_leaderboard_by_region(df, region_group: str):
    """Return subset of leaderboard for given region group code (e.g., NA, EU)."""
    if df is None or df.empty:
        return df
    rg = region_group.upper()
    if rg == "ALL":
        return df
    return df[df["RegionGroup"].str.upper() == rg]




