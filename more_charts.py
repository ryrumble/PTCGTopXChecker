"""Data helpers for the More Charts tab. Uses aggregated leaderboard only."""

import pandas as pd

from aggregation import aggregate_season, filter_leaderboard_by_region
from utils import WORLDS_CUTOFF_BY_REGION


def get_region_leaderboard(
    season: str,
    region_group: str,
    exclude_autobid: bool = True,
    *,
    force_aggregate: bool = False,
) -> tuple[pd.DataFrame, int, float | None]:
    """
    Return (df, cutoff_rank, cutoff_cp) for the region.
    df is filtered by region and optionally excludes autobid; ranked by TotalCP desc.
    cutoff_cp is the TotalCP of the player at cutoff_rank (invite cutoff), or None.
    """
    df = aggregate_season(season, force=force_aggregate)
    if df is None or df.empty:
        return df, 0, None
    df = filter_leaderboard_by_region(df, region_group)
    if df.empty:
        return df, 0, None
    if exclude_autobid:
        df = df[~df["HasAutobid"]].copy()
    if df.empty:
        return df, 0, None
    df = df.sort_values(
        by=["TotalCP", "BestCP", "SecondBestCP", "NumTournaments"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    df["Rank"] = df.index + 1
    cutoff_rank = WORLDS_CUTOFF_BY_REGION.get(
        region_group.upper(),
        WORLDS_CUTOFF_BY_REGION.get("OTHER", 135),
    )
    cutoff_cp = None
    if len(df) >= cutoff_rank:
        cutoff_cp = float(df.iloc[cutoff_rank - 1]["TotalCP"])
    return df, cutoff_rank, cutoff_cp


def histogram_cp_data(
    df: pd.DataFrame,
    cutoff_cp: float | None,
    bin_width: int = 50,
    top_n: int | None = None,
) -> tuple[list[float], list[float], float | None]:
    """Bins of TotalCP for histogram. Returns (bin_centers, counts, cutoff_cp).
    If top_n is set, only players with Rank <= top_n are included.
    """
    if df is None or df.empty:
        return [], [], cutoff_cp
    work = df
    if top_n is not None and top_n > 0 and "Rank" in work.columns:
        work = work[work["Rank"] <= top_n]
    if work.empty:
        return [], [], cutoff_cp
    cp = work["TotalCP"].dropna()
    if cp.empty:
        return [], [], cutoff_cp
    low, high = int(cp.min()), int(cp.max()) + 1
    if low == high:
        high = low + bin_width
    bin_edges = list(range(low, high + bin_width, bin_width))
    if len(bin_edges) < 2:
        return [], [], cutoff_cp
    binned = pd.cut(cp, bins=bin_edges, right=False, include_lowest=True)
    counts = binned.value_counts(sort=False).tolist()
    centers = [(bin_edges[i] + bin_edges[i + 1]) / 2 for i in range(len(bin_edges) - 1)]
    return centers, counts, cutoff_cp


def box_plot_rank_buckets(
    df: pd.DataFrame,
    cutoff_rank: int,
) -> tuple[list[str], list[list[float]]]:
    """
    Group players by rank bucket; return (bucket_labels, list of TotalCP per bucket).
    Buckets: 1-50, 51-100, 101-150, 151-300, 301-800.
    """
    if df is None or df.empty:
        return [], []
    buckets = [
        (1, 50, "1-50"),
        (51, 100, "51-100"),
        (101, 150, "101-150"),
        (151, 300, "151-300"),
        (301, 800, "301-800"),
    ]
    labels = []
    data = []
    for lo, hi, label in buckets:
        sub = df[(df["Rank"] >= lo) & (df["Rank"] <= hi)]
        if not sub.empty:
            labels.append(label)
            data.append(sub["TotalCP"].tolist())
    return labels, data


def events_attended_histogram(
    df: pd.DataFrame,
    cap_at: int = 10,
) -> tuple[list[int], list[int]]:
    """Count of players with 1, 2, ..., cap_at, and cap_at+ events. Returns (counts, bin_labels)."""
    if df is None or df.empty:
        return [], []
    n = df["NumTournaments"]
    labels = [str(i) for i in range(1, cap_at + 1)] + [f"{cap_at}+"]
    counts = []
    for i in range(1, cap_at + 1):
        counts.append(int((n == i).sum()))
    counts.append(int((n > cap_at).sum()))
    return counts, labels


