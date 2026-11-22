"""Matplotlib rendering for the Worlds invite-flow Sankey.

Each x-axis column is one Regional/IC date (all events on that day combined).
A column contains only real current states:

- kept invite: players invited at the previous date who are still invited
- entered invite list: players newly invited at this date
- autobid: players in the region holding an autobid after this date

Dropped players are not drawn as their own node: their absence from the next
column is the drop. Entering players are shown directly in the target column's
entered segment. Only new autobids get a transition-only node in the gap, so it
does not inflate either column's player total. Ribbon widths and the Y axis are
player counts. Dates that included an IC are shaded and called out on the X
axis. Drawing uses matplotlib only.
"""

import matplotlib.patheffects as path_effects
from matplotlib.patches import Patch, PathPatch, Rectangle
from matplotlib.path import Path

from worlds_race import InviteFlow, InviteFlowStage, InviteFlowTransition

KEPT_COLOR = "#0072B2"
ENTERED_COLOR = "#009E73"
AUTOBID_COLOR = "#CC79A7"
IC_MARKER_COLOR = "#6A3D9A"
NODE_EDGE = "white"

_NODE_WIDTH = 0.18
_GAP_NODE_WIDTH = 0.14
_TOTAL_HEIGHT = 3.6
_INLINE_LABEL_MIN_HEIGHT = 0.30
_OUTSIDE_LABEL_OFFSET = 0.06
_NODE_LABEL_FONTSIZE = 8.5


def _stage_has_ic(stage: InviteFlowStage) -> bool:
    """Whether an IC happened on this date.

    ``has_ic`` is populated from tournament metadata. The name fallback keeps
    older or manually constructed flows informative.
    """
    if stage.has_ic:
        return True
    tokens = {
        token
        for name in stage.event_names
        for token in str(name).upper().replace("-", " ").split()
    }
    return bool(tokens & {"IC", "INTERNATIONAL"})


def _column_values(flow: InviteFlow, index: int) -> dict[str, int]:
    """Counts displayed for column ``index``."""
    stage = flow.stages[index]
    if index == 0:
        kept = 0
        entered = stage.invited_count
        autobid_gained = stage.autobid_count
    else:
        transition = flow.transitions[index - 1]
        kept = transition.kept
        entered = transition.entered
        autobid_gained = transition.autobid_gained
    return {
        "kept": kept,
        "entered": entered,
        "autobid": stage.autobid_count,
        "autobid_gained": autobid_gained,
    }


def describe_column(flow: InviteFlow, index: int) -> str:
    """Footer/hover text for one column, including its Regional/IC names."""
    stage = flow.stages[index]
    values = _column_values(flow, index)
    events = ", ".join(stage.event_names) if stage.event_names else "no events"
    ic_marker = " (IC)" if _stage_has_ic(stage) else ""
    return (
        f"{stage.date:%Y-%m-%d}{ic_marker} [{events}]: "
        f"kept {values['kept']}, entered {values['entered']}, "
        f"autobids gained {values['autobid_gained']}, "
        f"autobids total {values['autobid']}"
    )


def _transition_values(transition: InviteFlowTransition) -> dict[str, int]:
    """Return identity-based ribbon widths, with a legacy-flow fallback."""
    identity_fields = (
        transition.kept_to_kept,
        transition.entered_to_kept,
        transition.kept_to_autobid,
        transition.entered_to_autobid,
        transition.autobid_to_autobid,
        transition.autobid_source,
    )
    if any(identity_fields):
        return {
            "kept_to_kept": transition.kept_to_kept,
            "entered_to_kept": transition.entered_to_kept,
            "kept_to_autobid": transition.kept_to_autobid,
            "entered_to_autobid": transition.entered_to_autobid,
            "autobid_to_autobid": transition.autobid_to_autobid,
            "autobid_source": transition.autobid_source,
        }

    # Older/manual transitions only provide the aggregate flows dict.
    invited_to_invited = transition.flows.get(("invited", "invited"), 0)
    autobid_from_invite = transition.flows.get(("invited", "autobid"), 0)
    return {
        "kept_to_kept": invited_to_invited,
        "entered_to_kept": 0,
        "kept_to_autobid": autobid_from_invite,
        "entered_to_autobid": 0,
        "autobid_to_autobid": transition.flows.get(("autobid", "autobid"), 0),
        "autobid_source": max(0, transition.autobid_gained - autobid_from_invite),
    }


def _ribbon(
    ax,
    x0: float,
    x1: float,
    y0_bottom: float,
    y0_top: float,
    y1_bottom: float,
    y1_top: float,
    color: str,
) -> None:
    """Draw one curved Sankey ribbon connecting two vertical slices."""
    if y0_top <= y0_bottom or y1_top <= y1_bottom:
        return
    bend = (x1 - x0) * 0.45
    verts = [
        (x0, y0_top),
        (x0 + bend, y0_top),
        (x1 - bend, y1_top),
        (x1, y1_top),
        (x1, y1_bottom),
        (x1 - bend, y1_bottom),
        (x0 + bend, y0_bottom),
        (x0, y0_bottom),
        (x0, y0_top),
    ]
    codes = [
        Path.MOVETO,
        Path.CURVE4,
        Path.CURVE4,
        Path.CURVE4,
        Path.LINETO,
        Path.CURVE4,
        Path.CURVE4,
        Path.CURVE4,
        Path.CLOSEPOLY,
    ]
    ax.add_patch(
        PathPatch(
            Path(verts, codes),
            facecolor=color,
            edgecolor="none",
            alpha=0.55,
            zorder=1,
        )
    )


def _node(
    ax,
    x: float,
    bottom: float,
    top: float,
    color: str,
    text: str,
    width: float = _NODE_WIDTH,
    label_side: str = "right",
    label_y: float | None = None,
) -> None:
    """Draw a labelled Sankey node bar.

    Tall bars get a bold inline label. Short bars (thin slivers for small
    counts) get a bold callout with an opaque background so the number stays
    readable instead of being squeezed into the bar. Callouts are
    staggered left/right (and above the stack) to avoid collisions.
    """
    if top <= bottom:
        return
    height = top - bottom
    center = (bottom + top) / 2
    ax.add_patch(
        Rectangle(
            (x - width / 2, bottom),
            width,
            height,
            facecolor=color,
            edgecolor=NODE_EDGE,
            linewidth=0.6,
            zorder=3,
        )
    )

    if height >= _INLINE_LABEL_MIN_HEIGHT:
        label = ax.text(
            x,
            center,
            text,
            ha="center",
            va="center",
            fontsize=_NODE_LABEL_FONTSIZE,
            fontweight="bold",
            color="white",
            zorder=4,
        )
        label.set_path_effects([path_effects.withStroke(linewidth=2, foreground="black")])
        return

    to_right = label_side == "right"
    edge_x = x + width / 2 if to_right else x - width / 2
    dx = _OUTSIDE_LABEL_OFFSET if to_right else -_OUTSIDE_LABEL_OFFSET
    ax.annotate(
        text,
        xy=(edge_x, center),
        xytext=(edge_x + dx, center if label_y is None else label_y),
        ha="left" if to_right else "right",
        va="center",
        fontsize=_NODE_LABEL_FONTSIZE,
        fontweight="bold",
        color="#111111",
        bbox={
            "boxstyle": "round,pad=0.18",
            "facecolor": "white",
            "edgecolor": color,
            "linewidth": 0.8,
            "alpha": 0.95,
        },
        arrowprops={"arrowstyle": "-", "color": color, "linewidth": 0.8},
        annotation_clip=False,
        zorder=5,
    )


def _take(bounds: tuple[float, float], offset: int, count: int, scale: float) -> tuple[float, float]:
    """Slice ``count`` players (scaled) starting ``offset`` players into a node."""
    bottom = bounds[0] + offset * scale
    return bottom, bottom + count * scale


def _nice_x_tick_step(count: int) -> int:
    """Show at most about 12 date labels."""
    return max(1, (count + 11) // 12)


def draw_invite_flow_sankey(ax, flow: InviteFlow) -> None:
    """Clear ``ax`` and draw the invite-flow Sankey for ``flow``."""
    ax.clear()
    if not flow.stages:
        ax.text(0.5, 0.5, "No Regional/IC data for this season and region.", ha="center", va="center")
        ax.set_axis_off()
        return

    # Shade columns that included an IC so the axis and the ribbons agree.
    for i, stage in enumerate(flow.stages):
        if _stage_has_ic(stage):
            ax.axvspan(
                i - 0.30,
                i + 0.30,
                facecolor=IC_MARKER_COLOR,
                edgecolor="none",
                alpha=0.12,
                zorder=1,
            )

    columns = [_column_values(flow, i) for i in range(len(flow.stages))]
    transitions = [_transition_values(transition) for transition in flow.transitions]
    column_heights = [
        column["kept"] + column["entered"] + column["autobid"] for column in columns
    ]
    gap_heights = [values["autobid_source"] for values in transitions]
    tallest = max(column_heights + gap_heights) if column_heights else 0
    scale = _TOTAL_HEIGHT / tallest if tallest else 1.0

    column_layouts: list[dict[str, tuple[float, float]]] = []
    for column in columns:
        y = 0.0
        bounds: dict[str, tuple[float, float]] = {}
        for key in ("kept", "entered", "autobid"):
            height = column[key] * scale
            bounds[key] = (y, y + height)
            y += height
        column_layouts.append(bounds)

    gap_layouts: list[dict[str, tuple[float, float]]] = []
    for values in transitions:
        scaled = values["autobid_source"] * scale
        gap_layouts.append({"autobid_source": (0.0, scaled)})

    # Ribbons first so the node bars sit cleanly on their endpoints.
    for i, values in enumerate(transitions):
        source = column_layouts[i]
        target = column_layouts[i + 1]
        gap = gap_layouts[i]
        gap_x = i + 0.5

        kept_to_kept = _take(source["kept"], 0, values["kept_to_kept"], scale)
        kept_to_autobid = _take(
            source["kept"], values["kept_to_kept"], values["kept_to_autobid"], scale
        )
        entered_to_kept = _take(source["entered"], 0, values["entered_to_kept"], scale)
        entered_to_autobid = _take(
            source["entered"], values["entered_to_kept"], values["entered_to_autobid"], scale
        )
        autobid_source_node = _take(source["autobid"], 0, values["autobid_to_autobid"], scale)

        kept_target = _take(target["kept"], 0, values["kept_to_kept"], scale)
        kept_target_entered = _take(
            target["kept"], values["kept_to_kept"], values["entered_to_kept"], scale
        )
        autobid_existing = _take(target["autobid"], 0, values["autobid_to_autobid"], scale)
        autobid_from_kept = _take(
            target["autobid"], values["autobid_to_autobid"], values["kept_to_autobid"], scale
        )
        autobid_from_entered = _take(
            target["autobid"],
            values["autobid_to_autobid"] + values["kept_to_autobid"],
            values["entered_to_autobid"],
            scale,
        )
        autobid_new = _take(
            target["autobid"],
            values["autobid_to_autobid"]
            + values["kept_to_autobid"]
            + values["entered_to_autobid"],
            values["autobid_source"],
            scale,
        )

        # Kept invite pivots: keep or take an autobid. Players who drop out
        # simply stop appearing in the next column; no drop node is drawn.
        _ribbon(ax, i, i + 1, *kept_to_kept, *kept_target, KEPT_COLOR)
        _ribbon(ax, i, gap_x, *kept_to_autobid, *autobid_from_kept, AUTOBID_COLOR)

        # Players who had just entered pivot to kept or autobid. New entrants
        # are labelled directly on the target column's entered segment.
        _ribbon(ax, i, i + 1, *entered_to_kept, *kept_target_entered, KEPT_COLOR)
        _ribbon(ax, i, gap_x, *entered_to_autobid, *autobid_from_entered, AUTOBID_COLOR)

        # Existing autobids persist; new autobids arrive from the gap.
        _ribbon(ax, i, i + 1, *autobid_source_node, *autobid_existing, AUTOBID_COLOR)
        _ribbon(
            ax,
            gap_x,
            i + 1,
            *gap["autobid_source"],
            *autobid_new,
            AUTOBID_COLOR,
        )

    # Column nodes: only players who currently hold an invite or autobid.
    for i, column in enumerate(columns):
        bounds = column_layouts[i]
        stack_top = bounds["autobid"][1]
        _node(ax, i, *bounds["kept"], KEPT_COLOR, str(column["kept"]), label_side="left")
        _node(ax, i, *bounds["entered"], ENTERED_COLOR, str(column["entered"]))
        _node(
            ax,
            i,
            *bounds["autobid"],
            AUTOBID_COLOR,
            str(column["autobid"]),
            label_y=stack_top + 0.12,
        )

    # New autobids are the only transition node; entrants and drops stay
    # represented by the columns themselves.
    for i, values in enumerate(transitions):
        gap = gap_layouts[i]
        gap_x = i + 0.5
        gap_top = gap["autobid_source"][1]
        _node(
            ax,
            gap_x,
            *gap["autobid_source"],
            AUTOBID_COLOR,
            f"auto+\n{values['autobid_source']}",
            _GAP_NODE_WIDTH,
            label_y=gap_top + 0.12,
        )

    step = _nice_x_tick_step(len(flow.stages))
    indices = list(range(0, len(flow.stages), step))
    tick_labels = []
    for i in indices:
        label = flow.stages[i].date.strftime("%Y-%m-%d")
        if _stage_has_ic(flow.stages[i]):
            label += " (IC)"
        tick_labels.append(label)
    ax.set_xticks(indices)
    ax.set_xticklabels(tick_labels, rotation=45, ha="right", fontsize=8)
    for i, label in zip(indices, ax.get_xticklabels(), strict=True):
        if _stage_has_ic(flow.stages[i]):
            label.set_color(IC_MARKER_COLOR)
            label.set_fontweight("bold")
    ax.set_xlim(-0.6, len(flow.stages) - 0.4)

    ticks = [0, 25, 50, 100, 150, 200, 300]
    tick_values = [value for value in ticks if value <= tallest]
    if not tick_values:
        tick_values = [0, tallest]
    ax.set_yticks([value * scale for value in tick_values])
    ax.set_yticklabels([str(value) for value in tick_values])
    ax.set_ylim(-0.2, _TOTAL_HEIGHT + 0.3)
    ax.set_ylabel("# of Players")
    ax.set_xlabel("Regional / IC date (IC dates in purple; events on the same date are combined)")
    ax.set_title(
        f"Worlds invite Sankey — {flow.region_group} (top {flow.cutoff_rank}), {flow.season}"
    )
    ax.grid(True, axis="y", alpha=0.2)
    ax.legend(
        handles=[
            Patch(facecolor=KEPT_COLOR, label="Kept invite"),
            Patch(facecolor=ENTERED_COLOR, label="Entered invite list"),
            Patch(facecolor=AUTOBID_COLOR, label="Autobid"),
            Patch(facecolor=IC_MARKER_COLOR, alpha=0.25, label="IC date"),
        ],
        loc="upper left",
        fontsize=8,
        ncol=5,
    )
