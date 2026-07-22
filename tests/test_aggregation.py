"""Tests for season aggregation logic with mocked storage layer."""

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from aggregation import (
    _AGG_DF_CACHE,
    PlayerStats,
    aggregate_season,
    filter_leaderboard_by_region,
    invalidate_season_caches,
)


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear caches before and after each test."""
    _AGG_DF_CACHE.clear()
    yield
    _AGG_DF_CACHE.clear()


@pytest.fixture
def mock_storage(monkeypatch):
    """Mock storage layer with controlled tournament data."""
    tournament_data = [
        {
            "metadata": {
                "title": "Regional 1",
                "tournament_type": "REGIONAL",
                "num_competitors": 100,
                "season": "2025-2026",
            },
            "normalized_entries": [
                {"placement": 1, "normalized_name": "Alice", "region_code": "US"},
                {"placement": 2, "normalized_name": "Bob", "region_code": "CA"},
                {"placement": 3, "normalized_name": "Charlie", "region_code": "US"},
            ],
        },
        {
            "metadata": {
                "title": "IC 1",
                "tournament_type": "IC",
                "num_competitors": 200,
                "season": "2025-2026",
            },
            "normalized_entries": [
                {"placement": 5, "normalized_name": "Alice", "region_code": "US"},
                {"placement": 10, "normalized_name": "Bob", "region_code": "CA"},
                {"placement": 2, "normalized_name": "Diana", "region_code": "GB"},
            ],
        },
    ]

    def mock_list_files(_season):
        return [Path(f"tournament_{i}.json") for i in range(len(tournament_data))]

    def mock_load_json(path):
        idx = int(path.stem.split("_")[1])
        return tournament_data[idx]

    def mock_load_mappings(_season):
        return {"merges": {}, "splits": []}

    monkeypatch.setattr("aggregation.list_tournament_files", mock_list_files)
    monkeypatch.setattr("aggregation.load_json", mock_load_json)
    monkeypatch.setattr("aggregation.load_player_mappings", mock_load_mappings)
    monkeypatch.setattr("aggregation.save_season_aggregate", MagicMock())
    monkeypatch.setattr("aggregation.reset_worlds_race_cache", MagicMock())
    return tournament_data


class TestPlayerStats:
    def test_add_result_accumulates(self):
        ps = PlayerStats(name="Alice", region_code="US")
        ps.add_result(350, 1, "Regional 1", "REGIONAL")
        ps.add_result(300, 5, "IC 1", "IC")
        assert ps.cp_finishes == [350, 300]
        assert ps.placements == [1, 5]
        assert len(ps.tournament_results) == 2

    def test_empty_stats(self):
        ps = PlayerStats(name="Alice", region_code="US")
        assert ps.cp_finishes == []
        assert ps.placements == []
        assert ps.tournament_results == []


class TestAggregateSeason:
    def test_basic_aggregation(self, mock_storage):
        df = aggregate_season("2025-2026", force=True)
        assert not df.empty
        assert len(df) == 4
        assert "Rank" in df.columns
        assert "Name" in df.columns
        assert "TotalCP" in df.columns

    def test_alice_has_highest_cp(self, mock_storage):
        df = aggregate_season("2025-2026", force=True)
        alice = df[df["Name"] == "Alice"].iloc[0]
        # Alice: placement 1 in Regional (100 comp) = 350 CP,
        #        placement 5 in IC (200 comp, kicker 17) = 380 CP
        assert alice["TotalCP"] == 350 + 380

    def test_ranking_by_total_cp_descending(self, mock_storage):
        df = aggregate_season("2025-2026", force=True)
        totals = df["TotalCP"].tolist()
        assert totals == sorted(totals, reverse=True)

    def test_rank_column_is_sequential(self, mock_storage):
        df = aggregate_season("2025-2026", force=True)
        assert df["Rank"].tolist() == list(range(1, len(df) + 1))

    def test_columns_present(self, mock_storage):
        df = aggregate_season("2025-2026", force=True)
        expected = {"Rank", "Name", "RegionCode", "RegionGroup", "TotalCP",
                     "CPFinishes", "CPFinishesStr", "NumTournaments",
                     "HighestPlacement", "HasAutobid", "TournamentResults",
                     "BestCP", "SecondBestCP"}
        assert expected.issubset(set(df.columns))

    def test_autobid_detected(self, mock_storage):
        df = aggregate_season("2025-2026", force=True)
        # Alice won Regional 1 (placement 1, REGIONAL) -> autobid
        alice = df[df["Name"] == "Alice"].iloc[0]
        assert bool(alice["HasAutobid"]) is True
        # Diana placed 2nd in IC -> autobid (top 4 in IC)
        diana = df[df["Name"] == "Diana"].iloc[0]
        assert bool(diana["HasAutobid"]) is True

    def test_region_group_mapped(self, mock_storage):
        df = aggregate_season("2025-2026", force=True)
        alice = df[df["Name"] == "Alice"].iloc[0]
        assert alice["RegionGroup"] == "NA"

    def test_caching(self, mock_storage):
        df1 = aggregate_season("2025-2026")
        df2 = aggregate_season("2025-2026")
        assert df1 is df2

    def test_force_invalidates_cache(self, mock_storage):
        df1 = aggregate_season("2025-2026")
        df2 = aggregate_season("2025-2026", force=True)
        assert df1 is not df2

    def test_no_tournaments(self, monkeypatch):
        monkeypatch.setattr("aggregation.list_tournament_files", lambda _: [])
        monkeypatch.setattr("aggregation.save_season_aggregate", MagicMock())
        monkeypatch.setattr("aggregation.reset_worlds_race_cache", MagicMock())
        df = aggregate_season("2025-2026", force=True)
        assert df.empty

    def test_player_with_top_5_limit(self, mock_storage, monkeypatch):
        """Player with more than 5 events should only sum top 5."""
        tournament_data = [
            {
                "metadata": {
                    "title": f"Event {i}",
                    "tournament_type": "REGIONAL",
                    "num_competitors": 100,
                    "season": "2025-2026",
                },
                "normalized_entries": [
                    {"placement": 1, "normalized_name": "Player", "region_code": "US"},
                ],
            }
            for i in range(7)
        ]

        def mock_list(_):
            return [Path(f"t{i}.json") for i in range(7)]

        def mock_load(p):
            return tournament_data[int(p.stem[1:])]

        monkeypatch.setattr("aggregation.list_tournament_files", mock_list)
        monkeypatch.setattr("aggregation.load_json", mock_load)
        monkeypatch.setattr("aggregation.save_season_aggregate", MagicMock())
        monkeypatch.setattr("aggregation.reset_worlds_race_cache", MagicMock())

        df = aggregate_season("2025-2026", force=True)
        player = df[df["Name"] == "Player"].iloc[0]
        assert player["TotalCP"] == 350 * 5
        assert player["NumTournaments"] == 7


class TestFilterLeaderboardByRegion:
    def test_all_returns_same(self):
        df = pd.DataFrame({"RegionGroup": ["NA", "EU", "NA"], "Name": ["A", "B", "C"]})
        result = filter_leaderboard_by_region(df, "ALL")
        assert len(result) == 3

    def test_filters_correctly(self):
        df = pd.DataFrame({"RegionGroup": ["NA", "EU", "NA"], "Name": ["A", "B", "C"]})
        result = filter_leaderboard_by_region(df, "NA")
        assert len(result) == 2
        assert all(result["RegionGroup"] == "NA")

    def test_region_filter_case_insensitive(self):
        df = pd.DataFrame({"RegionGroup": ["NA", "na", "Na"], "Name": ["A", "B", "C"]})
        result = filter_leaderboard_by_region(df, "NA")
        assert len(result) == 3

    def test_empty_df(self):
        df = pd.DataFrame()
        result = filter_leaderboard_by_region(df, "NA")
        assert result.empty

    def test_no_match_returns_empty(self):
        df = pd.DataFrame({"RegionGroup": ["NA"], "Name": ["A"]})
        result = filter_leaderboard_by_region(df, "EU")
        assert result.empty


class TestInvalidateSeasonCaches:
    def test_clears_specific_season(self, mock_storage):
        _AGG_DF_CACHE["2025-2026"] = MagicMock()
        _AGG_DF_CACHE["2024-2025"] = MagicMock()
        invalidate_season_caches("2025-2026")
        assert "2025-2026" not in _AGG_DF_CACHE
        assert "2024-2025" in _AGG_DF_CACHE

    def test_no_error_for_missing_season(self):
        invalidate_season_caches("nonexistent")
