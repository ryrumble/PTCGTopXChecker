"""Build web-optimized data files for every season with an aggregate."""

import json
from pathlib import Path

DATA_DIR = Path("data")
DOCS_DATA = Path("docs/data")
SEASONS_FILE = "seasons.json"


def discover_seasons(data_dir: Path = DATA_DIR) -> list[str]:
    """Return season names that have an aggregate, newest first."""
    return sorted(
        (path.parent.name for path in data_dir.glob("*/season_aggregate.json")),
        reverse=True,
    )


def _write_json(path: Path, payload: object) -> int:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return path.stat().st_size


def build_season(
    season: str,
    *,
    data_dir: Path = DATA_DIR,
    docs_data: Path = DOCS_DATA,
) -> dict[str, int]:
    """Write the compact leaderboard, results lookup and tournament list for one season."""
    src = data_dir / season / "season_aggregate.json"
    with src.open(encoding="utf-8") as f:
        raw = json.load(f)

    leaderboard = raw.get("leaderboard", [])
    tournaments = raw.get("tournaments", [])
    season = raw.get("season", season)

    # Build compact leaderboard (no TournamentResults, short keys)
    compact_lb = []
    player_results_lookup = {}

    for p in leaderboard:
        name = p["Name"]
        compact_lb.append({
            "r": p["Rank"],
            "n": name,
            "rc": p.get("RegionCode", ""),
            "rg": p.get("RegionGroup", ""),
            "cp": p["TotalCP"],
            "ev": p.get("NumTournaments", 0),
            "ab": p.get("HasAutobid", False),
            "bp": p.get("BestCP", 0),
            "hp": p.get("HighestPlacement"),
        })
        # Store tournament results separately, keyed by name
        results = p.get("TournamentResults", [])
        if results:
            player_results_lookup[name] = [
                {"t": r.get("tournament", ""), "p": r.get("placement", 0), "y": r.get("type", ""), "c": r.get("cp", 0)}
                for r in results
            ]

    out_dir = docs_data / season
    out_dir.mkdir(parents=True, exist_ok=True)

    sizes = {
        "leaderboard": _write_json(
            out_dir / "leaderboard.json",
            {"season": season, "players": compact_lb, "tournaments": len(tournaments)},
        ),
        "player_results": _write_json(out_dir / "player_results.json", player_results_lookup),
        "tournaments": _write_json(
            out_dir / "tournaments.json",
            [
                {
                    "n": t.get("title", ""),
                    "t": t.get("tournament_type", ""),
                    "c": t.get("num_competitors", 0),
                    "d": t.get("tournament_date", ""),
                    "u": t.get("url", ""),
                }
                for t in tournaments
            ],
        ),
    }

    print(
        f"{season}: {len(compact_lb)} players, {len(player_results_lookup)} with results, "
        f"{len(tournaments)} tournaments ({sum(sizes.values()) / 1024:.0f} KB)"
    )
    return sizes


def main(
    *,
    data_dir: Path = DATA_DIR,
    docs_data: Path = DOCS_DATA,
) -> list[str]:
    """Rebuild every season's web data and the season index used by the site."""
    seasons = discover_seasons(data_dir)
    if not seasons:
        raise SystemExit(f"No season aggregates found under {data_dir}/")

    docs_data.mkdir(parents=True, exist_ok=True)
    for season in seasons:
        build_season(season, data_dir=data_dir, docs_data=docs_data)

    _write_json(docs_data / SEASONS_FILE, seasons)
    print(f"Seasons: {', '.join(seasons)}")
    return seasons


if __name__ == "__main__":
    main()
