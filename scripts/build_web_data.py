"""Build web-optimized data files from season_aggregate.json for docs/."""

import json
from pathlib import Path

SEASON = "2025-2026"
SRC = Path("data") / SEASON / "season_aggregate.json"
DOCS_DATA = Path("docs") / "data"


def main():
    with open(SRC, encoding="utf-8") as f:
        raw = json.load(f)

    leaderboard = raw.get("leaderboard", [])
    tournaments = raw.get("tournaments", [])
    season = raw.get("season", SEASON)

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

    DOCS_DATA.mkdir(parents=True, exist_ok=True)

    # Write optimized leaderboard
    lb_path = DOCS_DATA / "leaderboard.json"
    with open(lb_path, "w", encoding="utf-8") as f:
        json.dump({"season": season, "players": compact_lb, "tournaments": len(tournaments)}, f, ensure_ascii=False)
    lb_kb = lb_path.stat().st_size / 1024
    print(f"Leaderboard: {len(compact_lb)} players, {lb_kb:.0f} KB")

    # Write player results lookup
    results_path = DOCS_DATA / "player_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(player_results_lookup, f, ensure_ascii=False)
    rl_kb = results_path.stat().st_size / 1024
    print(f"Player results: {len(player_results_lookup)} players, {rl_kb:.0f} KB")

    # Write tournament metadata (compact)
    compact_tourneys = []
    for t in tournaments:
        compact_tourneys.append({
            "n": t.get("title", ""),
            "t": t.get("tournament_type", ""),
            "c": t.get("num_competitors", 0),
            "d": t.get("tournament_date", ""),
            "u": t.get("url", ""),
        })
    tourneys_path = DOCS_DATA / "tournaments.json"
    with open(tourneys_path, "w", encoding="utf-8") as f:
        json.dump(compact_tourneys, f, ensure_ascii=False)
    tk_kb = tourneys_path.stat().st_size / 1024
    print(f"Tournaments: {len(compact_tourneys)} entries, {tk_kb:.0f} KB")

    total_kb = lb_kb + rl_kb + tk_kb
    print(f"\nTotal: {total_kb:.0f} KB (was {SRC.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
