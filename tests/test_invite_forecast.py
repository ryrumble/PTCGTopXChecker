"""Tests for the forward-looking invite forecast model and charts."""

from datetime import date
from types import SimpleNamespace

import matplotlib

matplotlib.use("Agg", force=True)

import numpy as np
import pytest
from matplotlib.figure import Figure

from gui.invite_forecast_chart import (
    draw_bubble_band,
    draw_player_detail,
    draw_safety_map,
    nearest_player,
)
from invite_forecast import (
    MAX_TIER_INDEX,
    TOTAL_ICS_PER_SEASON,
    AttendanceProjection,
    ForecastConfig,
    _best_tier_by_name,
    _ceiling_projection,
    _PlayerInputs,
    _simulate_player,
    analogous_date,
    build_forecast,
    placement_tier_index,
    project_attendance,
    season_bounds,
    season_progress,
    tier_label,
)


@pytest.fixture(autouse=True)
def clear_cache():
    from invite_forecast import reset_forecast_cache

    reset_forecast_cache()
    yield
    reset_forecast_cache()


def _inputs(cp: int, *, events_remaining: int = 0, pb_index: int = 5) -> _PlayerInputs:
    events = [
        SimpleNamespace(num_competitors=1200, tournament_type="REGIONAL", placement=17),
    ]
    projection = AttendanceProjection(
        prior_regionals=8,
        prior_ics=0,
        current_regionals=1,
        current_ics=0,
        expected_regionals=1 + events_remaining,
        expected_ics=0,
        remaining_regionals=events_remaining,
        remaining_ics=0,
        basis="test projection",
    )
    return _PlayerInputs(
        key=("Test Player", "US"),
        rank=1,
        current_cp=cp,
        cps_sorted=sorted([cp, 0, 0, 0, 0], reverse=True),
        region_code="US",
        events=events,
        pb_index=pb_index,
        ceiling_gain=1.0,
        projection=projection,
        cup_headroom=0,
    )


def _outcome(inputs: _PlayerInputs, cutoff_samples: np.ndarray, n_sims: int = 200):
    return _simulate_player(
        inputs,
        season="2026-2027",
        cutoff_samples=cutoff_samples,
        config=ForecastConfig(simulations=n_sims, seed=42),
        rng=np.random.default_rng(42),
    )


class TestTierMath:
    @pytest.mark.parametrize(
        ("placement", "expected"),
        [(1, 0), (2, 1), (3, 2), (4, 2), (5, 3), (8, 3), (9, 4), (16, 4), (17, 5), (32, 5), (1024, 10)],
    )
    def test_placement_tier_index(self, placement, expected):
        assert placement_tier_index(placement) == expected

    def test_out_of_range_placement_is_clamped(self):
        assert placement_tier_index(5000) == MAX_TIER_INDEX

    def test_tier_label(self):
        assert tier_label(0) == "T1"
        assert tier_label(5) == "T32"
        assert tier_label(99) == "T1024"


class TestSeasonTiming:
    def test_bounds(self):
        assert season_bounds("2026-2027") == (date(2026, 9, 1), date(2027, 6, 30))

    def test_progress_is_clamped(self):
        assert season_progress("2026-2027", date(2026, 1, 1)) == 0.0
        assert season_progress("2026-2027", date(2027, 12, 1)) == 1.0
        assert 0.0 < season_progress("2026-2027", date(2026, 11, 21)) < 1.0

    def test_analogous_date_tracks_progress(self):
        early = analogous_date("2025-2026", 0.1)
        late = analogous_date("2025-2026", 0.8)
        assert early < late
        assert early.year == 2025 and late.year == 2026


class TestAttendanceProjection:
    @staticmethod
    def _events(regionals: int, ics: int) -> list:
        return [
            SimpleNamespace(tournament_type="REGIONAL") for _ in range(regionals)
        ] + [SimpleNamespace(tournament_type="IC") for _ in range(ics)]

    @staticmethod
    def _project(**overrides) -> AttendanceProjection:
        base = dict(
            current_events=[],
            prior_regionals=6,
            prior_ics=2,
            region_median_regionals=6,
            regional_dates_total=10,
            regional_dates_elapsed=5,
            ic_dates_elapsed=1,
        )
        base.update(overrides)
        return project_attendance(**base)

    def test_prior_ic_anchor_respects_two_recorded_ics(self):
        projection = self._project(ic_dates_elapsed=2)
        assert projection.prior_ics == 2
        assert projection.current_ics == 0
        assert projection.expected_ics == 2
        assert projection.remaining_ics == 1
        assert "remaining IC slots" in projection.basis

    def test_one_recorded_ic_allows_two_more(self):
        projection = self._project(ic_dates_elapsed=1)
        assert projection.remaining_ics == 2

    def test_all_ics_recorded_means_no_more(self):
        projection = self._project(ic_dates_elapsed=TOTAL_ICS_PER_SEASON)
        assert projection.remaining_ics == 0

    def test_current_ics_are_never_reduced_by_prior_anchor(self):
        projection = self._project(
            current_events=self._events(0, 3), prior_ics=2, ic_dates_elapsed=3
        )
        assert projection.expected_ics == 3
        assert projection.remaining_ics == 0

    def test_zero_prior_ics_uses_pace_not_invented_anchor(self):
        projection = self._project(
            current_events=self._events(0, 1),
            prior_ics=0,
            ic_dates_elapsed=2,
        )
        assert projection.expected_ics == 2
        assert projection.remaining_ics == 1
        assert "IC pace" in projection.basis

    def test_regional_projection_is_half_pace_and_half_prior(self):
        projection = self._project(
            current_events=self._events(2, 0),
            prior_regionals=8,
            regional_dates_total=10,
            regional_dates_elapsed=4,
        )
        # Pace = 2/4 * 10 = 5; 50/50 with 8 gives 7 total, so 5 remaining.
        assert projection.expected_regionals == 7
        assert projection.remaining_regionals == 5
        assert "50/50 pace+prior" in projection.basis

    def test_remaining_regionals_capped_by_schedule(self):
        projection = self._project(
            current_events=self._events(4, 0),
            prior_regionals=8,
            regional_dates_total=10,
            regional_dates_elapsed=9,
        )
        assert projection.remaining_regionals == 1
        assert "capped by schedule" in projection.basis

    def test_missing_prior_player_uses_region_median(self):
        projection = self._project(
            prior_regionals=0,
            prior_ics=0,
            region_median_regionals=6,
            current_events=self._events(1, 0),
        )
        assert projection.expected_regionals == 4
        assert "region median" in projection.basis


class TestSimulation:
    def test_no_remaining_events_is_deterministic(self):
        cutoff = np.full(200, 300)
        assert _outcome(_inputs(500), cutoff).p_keep == pytest.approx(1.0)
        assert _outcome(_inputs(100), cutoff).p_keep == pytest.approx(0.0)

    def test_more_cp_means_higher_probability(self):
        cutoff = np.full(200, 1000)
        low = _outcome(_inputs(200, events_remaining=6), cutoff)
        high = _outcome(_inputs(500, events_remaining=6), cutoff)
        assert low.p_keep < high.p_keep

    def test_higher_pb_ceiling_never_hurts(self):
        cutoff = np.full(200, 450)
        low_pb = _outcome(_inputs(300, events_remaining=6, pb_index=8), cutoff)
        high_pb = _outcome(_inputs(300, events_remaining=6, pb_index=2), cutoff)
        assert low_pb.p_keep <= high_pb.p_keep

    def test_ceiling_is_upside_only(self):
        inputs = _inputs(300, events_remaining=4, pb_index=5)
        outcome = _outcome(inputs, np.full(200, 300))
        ceiling_index, ceiling_cp = _ceiling_projection(inputs, "2026-2027")

        assert ceiling_index < inputs.pb_index
        assert ceiling_cp > outcome.final_cp_p50

    def test_ceiling_capped_at_t1(self):
        inputs = _inputs(300, events_remaining=6, pb_index=1)
        ceiling_index, _ = _ceiling_projection(inputs, "2026-2027")
        assert ceiling_index == 0
        assert tier_label(ceiling_index) == "T1"

    def test_pb_uses_placements_from_all_seasons(self, monkeypatch):
        import invite_forecast as model

        seasons = ["2024-2025", "2025-2026", "2026-2027"]
        placements = {"2024-2025": 3, "2025-2026": 17, "2026-2027": 65}
        monkeypatch.setattr(model, "list_seasons", lambda: seasons)
        monkeypatch.setattr(model, "load_player_mappings", lambda _season: {"merges": {}})
        monkeypatch.setattr(
            model,
            "_build_per_player_events",
            lambda season: (
                {
                    ("Sample", "US"): [
                        SimpleNamespace(
                            placement=placements[season], tournament_date=date(2026, 1, 1)
                        )
                    ]
                },
                {},
            ),
        )

        assert _best_tier_by_name("2026-2027", date(2026, 11, 20))["Sample"] == 2

    def test_sample_count_matches_config(self):
        outcome = _outcome(_inputs(300, events_remaining=4), np.full(200, 300), n_sims=200)
        assert outcome.final_cp_samples.shape == (200,)


class TestRealData:
    def test_current_season_forecast(self):
        result = build_forecast(
            "2026-2027", "NA", ForecastConfig(simulations=200, seed=7)
        )
        assert result.has_data
        assert result.cutoff_cp > 0
        assert result.reference_season == "2025-2026"
        assert all(0.0 <= player.p_keep <= 1.0 for player in result.players)
        assert all(player.zone in {"Safe", "Likely in", "Bubble", "At risk", "Likely out"}
                   for player in result.players)
        assert all(player.events_remaining >= 0 for player in result.players)
        assert all(player.remaining_ics <= TOTAL_ICS_PER_SEASON for player in result.players)
        assert all(
            player.events_remaining == player.remaining_regionals + player.remaining_ics
            for player in result.players
        )

    def test_player_archetypes_are_learned_from_reference_season(self):
        result = build_forecast("2026-2027", "NA", ForecastConfig(simulations=200, seed=7))
        by_name = {player.name: player for player in result.players}
        for name in (
            "Caleb Rogerson",
            "Henry Chao",
            "Ryan Rumble",
            "Maxwell Wyatt",
            "Ben Bilenko",
        ):
            assert name in by_name
        assert by_name["Ryan Rumble"].pb_tier == "T32"
        assert by_name["Caleb Rogerson"].pb_index <= 2
        assert by_name["Henry Chao"].pb_index <= 2
        assert by_name["Ryan Rumble"].events_remaining < by_name["Caleb Rogerson"].events_remaining

    def test_completed_season_uses_observed_cutoff(self):
        result = build_forecast("2025-2026", "NA", ForecastConfig(simulations=200, seed=7))
        assert result.has_data
        assert set(np.unique(result.cutoff_samples)) == {result.cutoff_cp}
        assert result.reference_season == "2025-2026"

    def test_scenario_shifts_projected_cutoff(self):
        def median_cutoff(scenario: str) -> int:
            result = build_forecast(
                "2026-2027",
                "NA",
                ForecastConfig(simulations=120, seed=7, scenario=scenario),
            )
            return result.players[0].projected_cutoff_p50

        assert median_cutoff("Low") <= median_cutoff("Baseline") <= median_cutoff("High")

    def test_cup_headroom_is_opt_in(self):
        base = build_forecast("2026-2027", "NA", ForecastConfig(simulations=120, seed=3))
        with_headroom = build_forecast(
            "2026-2027", "NA", ForecastConfig(simulations=120, seed=3, include_cup_challenge=True)
        )
        assert len(base.players) == len(with_headroom.players)
        assert all(player.final_cp_p90 >= base_player.final_cp_p90
                   for player, base_player in zip(with_headroom.players, base.players, strict=True))


class TestCharts:
    def test_all_views_render(self):
        result = build_forecast("2026-2027", "NA", ForecastConfig(simulations=120, seed=9))
        player = result.players[0]

        map_fig = Figure()
        map_ax = map_fig.add_subplot(111)
        draw_safety_map(map_ax, result, player.key)
        assert "Invite Safety Map" in map_ax.get_title()
        assert map_ax.get_ylabel().endswith("(%)") or "Probability" in map_ax.get_ylabel()
        assert 100 in [tick for tick in map_ax.get_yticks()]
        legend_labels = [text.get_text() for text in map_ax.get_legend().get_texts()]
        assert {"Safe", "Likely in", "Bubble", "At risk", "Likely out"} <= set(legend_labels)
        assert not any(line.get_linestyle() == ":" for line in map_ax.lines)

        band_fig = Figure()
        draw_bubble_band(band_fig.add_subplot(111), result, player.key)
        assert "Bubble Band" in band_fig.axes[0].get_title()

        detail_fig = Figure()
        draw_player_detail(detail_fig.add_subplot(111), result, player)
        assert player.name in detail_fig.axes[0].get_title()

    def test_bubble_band_rows_are_evenly_spaced(self):
        result = build_forecast("2026-2027", "NA", ForecastConfig(simulations=120, seed=9))
        fig = Figure()
        ax = fig.add_subplot(111)

        draw_bubble_band(ax, result, result.players[0].key)

        ticks = list(ax.get_yticks())
        assert ticks == list(range(len(ticks)))
        assert len(ticks) <= 42
        labels = [label.get_text() for label in ax.get_yticklabels()]
        assert all(label.startswith("#") for label in labels)
        assert ax.get_ylim()[1] < ax.get_ylim()[0]

    def test_bubble_band_includes_searched_player_outside_bubble(self):
        result = build_forecast("2026-2027", "NA", ForecastConfig(simulations=120, seed=9))
        by_name = {player.name: player for player in result.players}
        searched = by_name["Maxwell Wyatt"]
        fig = Figure()
        ax = fig.add_subplot(111)

        draw_bubble_band(ax, result, search_keys={searched.key})
        fig.canvas.draw()

        labels = [label.get_text() for label in ax.get_yticklabels()]
        assert any(f"#{searched.rank} {searched.name}" in label for label in labels)
        assert any(searched.name in text.get_text() for text in ax.texts)

    def test_player_detail_explains_the_chart(self):
        result = build_forecast("2026-2027", "NA", ForecastConfig(simulations=120, seed=9))
        player = result.players[0]
        fig = Figure()
        ax = fig.add_subplot(111)

        draw_player_detail(ax, result, player)

        explanation = " ".join(text.get_text() for text in ax.texts)
        assert "Blue bars" in explanation
        assert "Green side" in explanation
        assert "Purple dotted line" in explanation
        legend_labels = [t.get_text() for t in ax.get_legend().get_texts()]
        assert any(label.startswith("Projected cutoff median") for label in legend_labels)
        assert any(label.startswith("Ceiling case") for label in legend_labels)
        assert "P(keep)" in ax.get_title()

    def test_ceiling_marker_appears_for_searched_player(self):
        result = build_forecast("2026-2027", "NA", ForecastConfig(simulations=120, seed=9))
        player = next(p for p in result.players if p.name == "Ryan Rumble")
        fig = Figure()
        ax = fig.add_subplot(111)

        draw_safety_map(ax, result, None, {player.key})
        fig.canvas.draw()

        labels = [text.get_text() for text in ax.texts]
        assert "ceiling" in labels
        legend_labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert "Ceiling case (not expected)" in legend_labels

    def test_ceiling_toggle_does_not_change_probabilities(self):
        shown = build_forecast(
            "2026-2027", "NA", ForecastConfig(simulations=120, seed=9, show_ceiling=True)
        )
        hidden = build_forecast(
            "2026-2027", "NA", ForecastConfig(simulations=120, seed=9, show_ceiling=False)
        )
        assert [p.p_keep for p in shown.players] == [p.p_keep for p in hidden.players]

        fig = Figure()
        ax = fig.add_subplot(111)
        draw_player_detail(ax, hidden, hidden.players[0])
        assert "Purple dotted line" not in " ".join(text.get_text() for text in ax.texts)

    def test_nearest_player_finds_selected_dot(self):
        result = build_forecast("2026-2027", "NA", ForecastConfig(simulations=120, seed=9))
        player = result.players[0]
        fig = Figure()
        ax = fig.add_subplot(111)
        draw_safety_map(ax, result, player.key)
        fig.canvas.draw()
        found = nearest_player(ax, result, player.current_cp, player.p_keep * 100, view="map")
        assert found is not None
        assert found.key == player.key

    def test_search_highlights_are_annotated(self):
        result = build_forecast("2026-2027", "NA", ForecastConfig(simulations=120, seed=9))
        player = result.players[0]
        fig = Figure()
        ax = fig.add_subplot(111)
        draw_safety_map(ax, result, player.key, {player.key})
        fig.canvas.draw()
        labels = [text.get_text() for text in ax.texts]
        assert player.name in labels
        legend_labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert "Search match" in legend_labels

    def test_multiple_search_highlights_are_annotated(self):
        result = build_forecast("2026-2027", "NA", ForecastConfig(simulations=120, seed=9))
        by_name = {player.name: player for player in result.players}
        names = ("Ryan Rumble", "Maxwell Wyatt", "Ben Bilenko")
        search_keys = {by_name[name].key for name in names}
        fig = Figure()
        ax = fig.add_subplot(111)
        draw_safety_map(ax, result, None, search_keys)
        fig.canvas.draw()
        labels = [text.get_text() for text in ax.texts]
        assert set(names) <= set(labels)
