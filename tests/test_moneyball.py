"""Tests for Moneyball efficiency analysis."""

import pandas as pd
import pytest

import moneyball
from cp_calculator import max_kicker_for_field
from moneyball import finish_efficiency, max_kicker_for_result, moneyball_leaderboard


class TestMaxKickerForField:
    @pytest.mark.parametrize(
        "competitors,expected",
        [
            (0, 0),
            (3, 0),
            (4, 4),
            (7, 4),
            (8, 8),
            (16, 8),
            (17, 17),
            (64, 33),
            (65, 65),
            (80, 65),
            (128, 65),
            (129, 129),
            (350, 257),
            (616, 513),
            (3_119, 2_049),
        ],
    )
    def test_kicker_boundaries(self, competitors, expected):
        assert max_kicker_for_field(competitors, "REGIONAL") == expected

    def test_ic_uses_same_ladder(self):
        for n in (0, 4, 65, 2_049, 5_000):
            assert max_kicker_for_field(n, "IC") == max_kicker_for_field(n, "REGIONAL")


class TestFinishEfficiency:
    def test_zero_cp_is_zero(self):
        assert finish_efficiency(0, 65) == 0.0

    def test_tier_zero_does_not_divide_by_zero(self):
        assert finish_efficiency(350, 0) == 350.0

    def test_smaller_field_is_more_efficient(self):
        assert finish_efficiency(350, 65) > finish_efficiency(350, 2_049)


class TestResultTierLookup:
    def test_reads_num_competitors(self):
        assert max_kicker_for_result({"type": "REGIONAL", "num_competitors": 80}) == 65

    def test_missing_metadata_defaults_to_zero(self):
        assert max_kicker_for_result({}) == 0


def _result(cp, competitors, placement=1, ttype="REGIONAL", title="Regional"):
    return {
        "tournament": title,
        "placement": placement,
        "type": ttype,
        "cp": cp,
        "num_competitors": competitors,
    }


def _player(name, results, *, region="US", group="NA", autobid=False):
    return {
        "Name": name,
        "RegionCode": region,
        "RegionGroup": group,
        "TotalCP": sum(r["cp"] for r in results),
        "HasAutobid": autobid,
        "NumTournaments": len(results),
        "TournamentResults": results,
        "BestCP": max((r["cp"] for r in results), default=0),
    }


@pytest.fixture
def aggregate(monkeypatch):
    """Four scoring finishes for most players; edge cases for filters."""
    rows = [
        _player(
            "Small Field Sam",
            [
                _result(350, 80, title="Auckland"),
                _result(350, 89, title="Cape Town"),
                _result(350, 350, title="Buenos Aires"),
                _result(350, 553, title="Buenos Aires 2"),
            ],
            autobid=True,
        ),
        _player(
            "Big Field Ben",
            [
                _result(350, 2_000, title="Regional A"),
                _result(350, 2_500, title="Regional B"),
                _result(350, 3_000, title="Regional C"),
                _result(350, 3_100, title="Regional D"),
            ],
            region="CA",
        ),
        _player(
            "Mixed Mia",
            [
                _result(350, 80, title="Auckland"),
                _result(300, 100, title="Small Regional"),
                _result(280, 200, title="Mid Regional"),
                _result(200, 1_000, title="Large Regional"),
            ],
            region="GB",
            group="EU",
        ),
        _player("Casual Carl", [_result(350, 80), _result(350, 89), _result(350, 350)]),
        _player(
            "Zero Zoe",
            [_result(0, 80), _result(0, 89), _result(0, 350), _result(0, 553)],
        ),
    ]
    df = pd.DataFrame(rows)
    monkeypatch.setattr(moneyball, "aggregate_season", lambda *_: df.copy())
    return df


@pytest.mark.usefixtures("aggregate")
class TestMoneyballLeaderboard:
    def test_small_field_player_ranks_first(self):
        mb = moneyball_leaderboard("2025-2026")
        assert mb.iloc[0]["Name"] == "Small Field Sam"
        assert mb.iloc[0]["MoneyballScore"] == pytest.approx(3.161, abs=0.01)

    def test_large_field_player_ranks_last(self):
        mb = moneyball_leaderboard("2025-2026")
        assert mb.iloc[-1]["Name"] == "Big Field Ben"
        assert mb.iloc[-1]["MoneyballScore"] == pytest.approx(0.214, abs=0.01)

    def test_equal_total_cp_but_huge_efficiency_gap(self):
        mb = moneyball_leaderboard("2025-2026")
        sam = mb[mb["Name"] == "Small Field Sam"].iloc[0]
        ben = mb[mb["Name"] == "Big Field Ben"].iloc[0]
        assert sam["TotalCP"] == ben["TotalCP"] == 1400
        assert sam["MoneyballScore"] > ben["MoneyballScore"] * 14

    def test_min_four_finishes_filters_by_default(self):
        mb = moneyball_leaderboard("2025-2026")
        assert "Casual Carl" not in mb["Name"].tolist()
        assert "Zero Zoe" not in mb["Name"].tolist()

    def test_min_finishes_is_configurable(self):
        mb = moneyball_leaderboard("2025-2026", min_counting_finishes=3)
        assert "Casual Carl" in mb["Name"].tolist()

    def test_region_filter(self):
        mb = moneyball_leaderboard("2025-2026", region_group="EU")
        assert mb["Name"].tolist() == ["Mixed Mia"]

    def test_all_region_default(self):
        mb = moneyball_leaderboard("2025-2026")
        assert len(mb) == 3

    def test_autobid_winners_included_by_default(self):
        mb = moneyball_leaderboard("2025-2026")
        assert "Small Field Sam" in mb["Name"].tolist()

    def test_autobid_winners_can_be_excluded(self):
        mb = moneyball_leaderboard("2025-2026", include_autobid=False)
        assert "Small Field Sam" not in mb["Name"].tolist()

    def test_top_x_caps_rows(self):
        mb = moneyball_leaderboard("2025-2026", top_x=2)
        assert len(mb) == 2
        assert mb["Rank"].tolist() == [1, 2]

    def test_metadata_columns(self):
        mb = moneyball_leaderboard("2025-2026")
        sam = mb.iloc[0]
        assert sam["AvgEventTier"] == pytest.approx(225.0, abs=0.1)
        assert sam["SmallestField"] == 80
        assert sam["CountingFinishes"] == 4
        assert len(sam["Finishes"]) == 4

    def test_all_results_carry_detail_and_top5_flags(self):
        mb = moneyball_leaderboard("2025-2026")
        sam = mb[mb["Name"] == "Small Field Sam"].iloc[0]
        results = sam["AllResults"]
        assert len(results) == 4
        assert all(r["tier"] in (65, 257, 513) for r in results)
        assert sum(bool(r["counts"]) for r in results) == 4
        assert results[0]["efficiency"] == pytest.approx(5.303, abs=0.001)

    def test_only_top_five_results_are_flagged(self, monkeypatch):
        results = [_result(100 + i, 80 + i, title=f"R{i}") for i in range(6)]
        results.append(_result(0, 80, title="Zero CP"))
        df = pd.DataFrame([_player("Six Events", results)])
        monkeypatch.setattr(moneyball, "aggregate_season", lambda *_: df)

        mb = moneyball_leaderboard("2025-2026")
        player = mb.iloc[0]
        flagged = [r for r in player["AllResults"] if r["counts"]]
        assert player["CountingFinishes"] == 5
        assert sorted(r["cp"] for r in flagged) == [101, 102, 103, 104, 105]
        assert not player["AllResults"][-1]["counts"]
        assert player["AllResults"][-1]["efficiency"] == 0.0

    def test_empty_aggregate_returns_expected_columns(self, monkeypatch):
        monkeypatch.setattr(moneyball, "aggregate_season", lambda *_: pd.DataFrame())
        mb = moneyball_leaderboard("2025-2026")
        assert mb.empty
        assert "MoneyballScore" in mb.columns
