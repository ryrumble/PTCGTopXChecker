from datetime import date

import matplotlib
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch
from matplotlib.text import Annotation

from gui.invite_flow_chart import _column_values, describe_column, draw_invite_flow_sankey
from worlds_race import InviteFlow, InviteFlowStage, InviteFlowTransition


def _stage(
    day: date, events: tuple[str, ...], invited: int, autobids: int, has_ic: bool = False
) -> InviteFlowStage:
    return InviteFlowStage(
        date=day,
        event_names=events,
        invited_count=invited,
        no_player_count=0,
        out_count=0,
        autobid_count=autobids,
        new_count=0,
        num_ranked=invited,
        cutoff_cp=None,
        has_ic=has_ic,
    )


def _flow() -> InviteFlow:
    return InviteFlow(
        season="2025-2026",
        region_group="NA",
        cutoff_rank=10,
        stages=[
            _stage(date(2025, 10, 4), ("Regional A",), 10, 1),
            _stage(date(2025, 10, 11), ("IC B", "Regional C"), 12, 4, has_ic=True),
        ],
        transitions=[
            InviteFlowTransition(
                date=date(2025, 10, 11),
                flows={
                    ("invited", "invited"): 8,
                    ("invited", "out"): 2,
                    ("invited", "autobid"): 1,
                    ("out", "invited"): 3,
                    ("new", "invited"): 1,
                    ("new", "autobid"): 2,
                    ("autobid", "autobid"): 1,
                },
            )
        ],
    )


def test_describe_column_lists_events_and_counts() -> None:
    flow = _flow()

    assert describe_column(flow, 0) == (
        "2025-10-04 [Regional A]: kept 0, entered 10, "
        "autobids gained 1, autobids total 1"
    )
    assert describe_column(flow, 1) == (
        "2025-10-11 (IC) [IC B, Regional C]: kept 8, entered 4, "
        "autobids gained 3, autobids total 4"
    )


def test_draw_uses_sankey_ribbons_and_player_axis() -> None:
    matplotlib.use("Agg")
    flow = _flow()
    figure = Figure(figsize=(8, 4))
    ax = figure.add_subplot(111)

    draw_invite_flow_sankey(ax, flow)

    assert any(isinstance(patch, PathPatch) for patch in ax.patches)
    assert "Players" in ax.get_ylabel()
    assert len(ax.get_xticklabels()) == len(flow.stages)


def test_ic_dates_are_marked_on_the_x_axis() -> None:
    matplotlib.use("Agg")
    flow = _flow()
    ax = Figure(figsize=(8, 4)).add_subplot(111)

    draw_invite_flow_sankey(ax, flow)

    labels = ax.get_xticklabels()
    assert labels[0].get_text() == "2025-10-04"
    assert labels[1].get_text() == "2025-10-11 (IC)"
    assert labels[1].get_fontweight() == "bold"


def test_small_entered_count_gets_callout_without_drop_nodes() -> None:
    matplotlib.use("Agg")
    flow = InviteFlow(
        season="2026-2027",
        region_group="NA",
        cutoff_rank=100,
        stages=[
            _stage(date(2026, 10, 10), ("Regional A",), 100, 0),
            _stage(date(2026, 10, 17), ("Regional B",), 100, 0),
        ],
        transitions=[
            InviteFlowTransition(
                date=date(2026, 10, 17),
                flows={},
                kept_to_kept=99,
                kept_to_fell=1,
                entering_to_entered=1,
                autobid_source=1,
            )
        ],
    )
    ax = Figure(figsize=(8, 4)).add_subplot(111)

    draw_invite_flow_sankey(ax, flow)

    callouts = {text.get_text(): text for text in ax.texts if isinstance(text, Annotation)}
    assert callouts["1"].get_ha() == "left"
    assert callouts["auto+\n1"].get_ha() == "left"
    assert not any(
        "fell" in text.get_text().lower() or text.get_text().startswith("in\n")
        for text in ax.texts
    )


def test_entering_players_are_not_counted_in_the_previous_column() -> None:
    flow = InviteFlow(
        season="2026-2027",
        region_group="MEA",
        cutoff_rank=10,
        stages=[
            _stage(date(2026, 10, 10), ("Regional A",), 10, 0),
            _stage(date(2026, 10, 17), ("Regional B",), 10, 0),
        ],
        transitions=[
            InviteFlowTransition(
                date=date(2026, 10, 17),
                flows={},
                kept_to_kept=6,
                entered_to_kept=0,
                kept_to_fell=4,
                entering_to_entered=4,
            )
        ],
    )

    before = _column_values(flow, 0)
    after = _column_values(flow, 1)

    assert (before["kept"], before["entered"]) == (0, 10)
    assert (after["kept"], after["entered"]) == (6, 4)
    assert after["kept"] + after["entered"] == 10
