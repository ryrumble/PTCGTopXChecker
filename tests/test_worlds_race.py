"""Tests for the Worlds invite-flow (Sankey) data."""

from datetime import date
from pathlib import Path

import pytest

import worlds_race
from worlds_race import INVITE_STATES, InviteFlow, get_invite_flows, reset_worlds_race_cache


@pytest.fixture(autouse=True)
def clear_caches():
    reset_worlds_race_cache()
    yield
    reset_worlds_race_cache()


def _tournament(title, t_date, entries, t_type="REGIONAL", competitors=100):
    return {
        "metadata": {
            "title": title,
            "tournament_date": t_date,
            "tournament_type": t_type,
            "num_competitors": competitors,
        },
        "normalized_entries": [
            {
                "placement": placement,
                "normalized_name": name,
                "region_code": region,
            }
            for placement, name, region in entries
        ],
    }


@pytest.fixture
def season_data(monkeypatch):
    """Three dates; two regionals share the middle date. Cutoff rank is 2."""
    data = [
        _tournament(
            "Regional A",
            "2025-01-01",
            [(2, "Alice", "US"), (3, "Eve", "US")],
        ),
        _tournament(
            "Regional B1",
            "2025-01-02",
            [(2, "Bob", "US"), (1, "Carol", "CA")],
        ),
        _tournament(
            "Regional B2",
            "2025-01-02",
            [(3, "Dave", "US")],
        ),
        _tournament(
            "IC C",
            "2025-01-03",
            [
                (2, "Bob", "US"),
                (5, "Alice", "US"),
                (9, "Dave", "US"),
                (1, "Eve", "US"),
            ],
            t_type="IC",
            competitors=200,
        ),
    ]
    monkeypatch.setitem(worlds_race.WORLDS_CUTOFF_BY_REGION, "NA", 2)
    lookup = {Path(f"t{i}.json"): tournament for i, tournament in enumerate(data)}
    monkeypatch.setattr(worlds_race, "list_tournament_files", lambda _season: list(lookup))
    monkeypatch.setattr(worlds_race, "load_json", lambda path: lookup[path])
    monkeypatch.setattr(worlds_race, "load_player_mappings", lambda _season: {"merges": {}})
    return data


@pytest.mark.usefixtures("season_data")
class TestGetInviteFlows:
    def test_stages_are_one_per_distinct_date_with_combined_events(self):
        flow = get_invite_flows("2025-2026", "na")
        assert isinstance(flow, InviteFlow)
        assert flow.cutoff_rank == 2
        assert [stage.date for stage in flow.stages] == [
            date(2025, 1, 1),
            date(2025, 1, 2),
            date(2025, 1, 3),
        ]
        assert flow.stages[1].event_names == ("Regional B1", "Regional B2")
        assert [stage.has_ic for stage in flow.stages] == [False, False, True]
        assert len(flow.transitions) == 2

    def test_stages_start_once_cutoff_is_filled(self):
        flow = get_invite_flows("2025-2026", "NA")
        first, second, third = flow.stages
        assert (first.invited_count, first.no_player_count, first.out_count, first.autobid_count) == (2, 0, 0, 0)
        assert (second.invited_count, second.no_player_count, second.out_count, second.autobid_count) == (2, 0, 2, 1)
        assert (third.invited_count, third.no_player_count, third.out_count, third.autobid_count) == (2, 0, 0, 3)

    def test_new_player_replaces_a_previous_invitee(self):
        flow = get_invite_flows("2025-2026", "NA")
        first = flow.transitions[0]
        assert first.kept == 1
        assert first.entered == 1
        assert first.fell_out == 1
        assert first.flows[("new", "invited")] == 1

    def test_player_dropping_out_and_autobid_gain(self):
        flow = get_invite_flows("2025-2026", "NA")
        second = flow.transitions[1]
        assert second.flows[("out", "invited")] == 1
        assert second.flows[("invited", "autobid")] == 1
        assert second.entered == 1
        assert second.fell_out == 1
        assert second.autobid_gained == 2

    def test_transitions_track_kept_entered_and_autobid_gains(self):
        flow = get_invite_flows("2025-2026", "NA")
        first, second = flow.transitions
        assert (first.kept_to_kept, first.entered_to_kept, first.entered_to_fell) == (0, 1, 1)
        assert first.autobid_source == 1
        assert (second.kept_to_kept, second.entered_to_autobid, second.autobid_source) == (1, 1, 1)

    def test_dates_before_cutoff_is_filled_are_skipped(self, monkeypatch):
        single = _tournament("Early", "2025-01-01", [(2, "Solo", "US")])
        lookup = {Path("early.json"): single}
        monkeypatch.setattr(worlds_race, "list_tournament_files", lambda _season: list(lookup))
        monkeypatch.setattr(worlds_race, "load_json", lambda path: lookup[path])
        reset_worlds_race_cache()

        flow = get_invite_flows("2025-2026", "NA")

        assert flow.stages == []
        assert flow.transitions == []

    def test_flows_conserve_node_counts(self):
        flow = get_invite_flows("2025-2026", "NA")
        for index, transition in enumerate(flow.transitions):
            for state in INVITE_STATES:
                expected = (
                    transition.new_players
                    if state == "new"
                    else flow.stages[index].count_for(state)
                )
                assert sum(
                    count for (source, _), count in transition.flows.items() if source == state
                ) == expected

    def test_autobid_player_does_not_occupy_an_invite_slot(self):
        flow = get_invite_flows("2025-2026", "NA")
        assert flow.stages[1].autobid_count == 1
        assert flow.stages[1].invited_count == flow.cutoff_rank

    def test_other_regions_are_excluded(self):
        flow = get_invite_flows("2025-2026", "EU")
        assert flow.stages == []
        assert flow.transitions == []

    def test_result_is_cached_until_reset(self):
        first = get_invite_flows("2025-2026", "NA")
        assert get_invite_flows("2025-2026", "NA") is first
        reset_worlds_race_cache("2025-2026")
        assert get_invite_flows("2025-2026", "NA") is not first
