"""Moneyball efficiency: the most Championship Points from the smallest fields.

An event's "size tier" is derived from the CP kicker ladder: an event with N
competitors reaches every bracket whose kicker is <= N, and no more. A finish's
efficiency is its CP divided by (event size tier + 1), so a 350-CP win at a
tier-65 event scores ~5.3 while the same win at a tier-2,049 event scores ~0.17.

Only a player's Best Finish Limit (top 5 CP-scoring finishes) counts toward the
score, matching the season leaderboard's top-5 rule. Players must have at least
``min_counting_finishes`` CP-scoring finishes to qualify.
"""

import pandas as pd

from aggregation import aggregate_season
from cp_calculator import max_kicker_for_field
from logger import logger

DEFAULT_MIN_COUNTING_FINISHES = 4
DEFAULT_TOP_X = 200

REGION_OPTIONS = ("ALL", "NA", "EU", "LA", "OC", "MEA", "BA", "OTHER")


def max_kicker_for_result(result: dict) -> int:
    """Size tier for a single tournament result, tolerating missing metadata."""
    competitors = int(result.get("num_competitors") or 0)
    return max_kicker_for_field(competitors, result.get("type", "REGIONAL"))


def finish_efficiency(cp: int, size_tier: int) -> float:
    """CP extracted per unit of field difficulty. ``+1`` avoids tier-0 divide-by-zero."""
    if cp <= 0:
        return 0.0
    return cp / (size_tier + 1)


def moneyball_leaderboard(
    season: str,
    region_group: str = "ALL",
    min_counting_finishes: int = DEFAULT_MIN_COUNTING_FINISHES,
    top_x: int = DEFAULT_TOP_X,
    include_autobid: bool = True,
) -> pd.DataFrame:
    """Rank players by efficiency of their top-5 CP finishes.

    Args:
        season: Season identifier (e.g. "2025-2026").
        region_group: Region group code to restrict to, or "ALL".
        min_counting_finishes: Minimum number of CP-scoring finishes required.
        top_x: Maximum number of rows to return after ranking.
        include_autobid: When False, drop players holding a Worlds autobid.
    """
    df = aggregate_season(season)
    columns = [
        "Rank", "Name", "RegionCode", "RegionGroup", "TotalCP", "MoneyballScore",
        "AvgEventTier", "SmallestField", "CountingFinishes", "NumTournaments",
        "Finishes", "AllResults",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    work = df
    rg = (region_group or "ALL").strip().upper()
    if rg != "ALL" and "RegionGroup" in work.columns:
        work = work[work["RegionGroup"].str.upper() == rg]
    if not include_autobid and "HasAutobid" in work.columns:
        work = work[~work["HasAutobid"]]
    if work.empty:
        return pd.DataFrame(columns=columns)

    min_finishes = max(1, int(min_counting_finishes))
    rows: list[dict] = []

    for _, player in work.iterrows():
        results = player.get("TournamentResults") or []
        detailed: list[dict] = []
        scoring = []
        for index, result in enumerate(results):
            cp = int(result.get("cp") or 0)
            tier = max_kicker_for_result(result)
            item = dict(result)
            item["tier"] = tier
            item["efficiency"] = round(finish_efficiency(cp, tier), 3) if cp > 0 else 0.0
            item["counts"] = False
            detailed.append(item)
            if cp <= 0:
                continue
            scoring.append((index, item))

        if len(scoring) < min_finishes:
            continue

        # Best Finish Limit: the five highest-CP scoring finishes decide the score.
        counting_pairs = sorted(scoring, key=lambda pair: pair[1]["cp"], reverse=True)[:5]
        for index, _ in counting_pairs:
            detailed[index]["counts"] = True
        counting = [item for _, item in counting_pairs]
        score = sum(f["efficiency"] for f in counting) / len(counting)
        tiers = [f["tier"] for f in counting]
        fields = [f["num_competitors"] for f in counting if f["num_competitors"] > 0]

        rows.append({
            "Name": player.get("Name", ""),
            "RegionCode": player.get("RegionCode", ""),
            "RegionGroup": player.get("RegionGroup", "OTHER"),
            "TotalCP": int(player.get("TotalCP") or 0),
            "MoneyballScore": round(score, 3),
            "AvgEventTier": round(sum(tiers) / len(tiers), 1),
            "SmallestField": min(fields) if fields else 0,
            "CountingFinishes": len(counting),
            "NumTournaments": int(player.get("NumTournaments") or 0),
            "Finishes": counting,
            "AllResults": detailed,
        })

    if not rows:
        return pd.DataFrame(columns=columns)

    out = pd.DataFrame(rows)
    out = out.sort_values(
        by=["MoneyballScore", "TotalCP", "CountingFinishes"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    out.insert(0, "Rank", out.index + 1)

    limit = max(1, int(top_x))
    out = out.head(limit).reset_index(drop=True)
    logger.debug("Moneyball: %s players for %s (%s, top %s)", len(out), season, rg, limit)
    return out[columns]
