"""Tests for multi-season web data generation."""

import json

import pytest

from scripts import build_web_data


def _write_aggregate(root, season: str, players: list, tournaments: list) -> None:
    path = root / season / "season_aggregate.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"season": season, "leaderboard": players, "tournaments": tournaments}),
        encoding="utf-8",
    )


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_discover_seasons_newest_first(tmp_path):
    for season in ("2024-2025", "2026-2027", "2025-2026"):
        _write_aggregate(tmp_path, season, [], [])
    (tmp_path / "2000-2001").mkdir()  # no aggregate, not a season

    assert build_web_data.discover_seasons(tmp_path) == [
        "2026-2027", "2025-2026", "2024-2025",
    ]


def test_build_season_writes_compact_files(tmp_path):
    player = {
        "Name": "Alice", "Rank": 1, "RegionCode": "US", "RegionGroup": "NA",
        "TotalCP": 350, "NumTournaments": 1, "HasAutobid": True,
        "BestCP": 350, "HighestPlacement": 1,
        "TournamentResults": [
            {
                "tournament": "Regional", "placement": 1, "type": "REGIONAL",
                "cp": 350, "num_competitors": 80,
            },
        ],
    }
    _write_aggregate(
        tmp_path, "2025-2026", [player],
        [{
            "title": "Regional", "tournament_type": "REGIONAL",
            "num_competitors": 80, "tournament_date": "2026-01-01", "url": "u",
        }],
    )

    out = tmp_path / "docs"
    sizes = build_web_data.build_season("2025-2026", data_dir=tmp_path, docs_data=out)
    season_dir = out / "2025-2026"

    assert set(sizes) == {"leaderboard", "player_results", "tournaments"}
    assert _read_json(season_dir / "leaderboard.json") == {
        "season": "2025-2026", "tournaments": 1,
        "players": [{
            "r": 1, "n": "Alice", "rc": "US", "rg": "NA", "cp": 350,
            "ev": 1, "ab": True, "bp": 350, "hp": 1,
        }],
    }
    assert _read_json(season_dir / "player_results.json") == {
        "Alice": [{"t": "Regional", "p": 1, "y": "REGIONAL", "c": 350}],
    }
    assert _read_json(season_dir / "tournaments.json") == [{
        "n": "Regional", "t": "REGIONAL", "c": 80, "d": "2026-01-01", "u": "u",
    }]


def test_main_writes_index_for_every_season(tmp_path):
    for season in ("2025-2026", "2026-2027"):
        _write_aggregate(tmp_path, season, [], [])
    out = tmp_path / "docs"

    seasons = build_web_data.main(data_dir=tmp_path, docs_data=out)

    assert seasons == ["2026-2027", "2025-2026"]
    assert _read_json(out / "seasons.json") == seasons
    assert (out / "2026-2027" / "leaderboard.json").exists()
    assert (out / "2025-2026" / "leaderboard.json").exists()


def test_main_requires_at_least_one_aggregate(tmp_path):
    with pytest.raises(SystemExit, match="No season aggregates"):
        build_web_data.main(data_dir=tmp_path, docs_data=tmp_path / "docs")
