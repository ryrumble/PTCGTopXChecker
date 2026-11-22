"""Matplotlib renderers for the Invite Forecast tab.

Three views share one ``ForecastResult``:

- the Safety Map (CP vs. probability of keeping the invite),
- the Bubble Band (ranked players with a simulated CP range), and
- the Player Detail (one player's simulated final CP vs. the cutoff).
"""

from __future__ import annotations

from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from matplotlib.ticker import PercentFormatter

from invite_forecast import ForecastResult, PlayerForecast

ZONE_COLORS = {
    "Safe": "#009E73",
    "Likely in": "#56B4E9",
    "Bubble": "#E69F00",
    "At risk": "#D55E00",
    "Likely out": "#CC79A7",
}
CUTOFF_COLOR = "#D55E00"
BAND_COLOR = "#E69F00"
SELECTED_COLOR = "#000000"
CEILING_COLOR = "#7B3294"
BAND_ROWS_BEFORE_CUTOFF = 12
BAND_ROWS_AFTER_CUTOFF = 23
BAND_MAX_EXTRA_ROWS = 6


def _color(player: PlayerForecast) -> str:
    return ZONE_COLORS.get(player.zone, "#404040")


def _zone_legend_handles() -> list[Line2D]:
    return [
        Line2D(
            [],
            [],
            marker="o",
            color="w",
            markerfacecolor=color,
            markeredgecolor="white",
            markersize=7,
            label=zone,
        )
        for zone, color in ZONE_COLORS.items()
    ]


def _add_legend(
    ax: Axes,
    *,
    fontsize: int = 8,
    show_search: bool = False,
    show_ceiling: bool = False,
    loc: str = "lower right",
    ncol: int = 2,
    bbox_to_anchor: tuple[float, float] | None = None,
) -> None:
    handles, labels = ax.get_legend_handles_labels()
    handles.extend(_zone_legend_handles())
    labels.extend(ZONE_COLORS)
    if show_search:
        handles.append(
            Line2D(
                [],
                [],
                marker="o",
                color="w",
                markerfacecolor="none",
                markeredgecolor=SELECTED_COLOR,
                markeredgewidth=2,
                markersize=9,
                label="Search match",
            )
        )
        labels.append("Search match")
    if show_ceiling:
        handles.append(
            Line2D(
                [],
                [],
                marker="^",
                color="w",
                markerfacecolor="none",
                markeredgecolor=CEILING_COLOR,
                markeredgewidth=2,
                markersize=9,
                label="Ceiling case (not expected)",
            )
        )
        labels.append("Ceiling case (not expected)")
    kwargs: dict[str, object] = {"loc": loc, "fontsize": fontsize, "ncol": ncol}
    if bbox_to_anchor is not None:
        kwargs["bbox_to_anchor"] = bbox_to_anchor
    ax.legend(handles, labels, **kwargs)


def _search_matches(
    result: ForecastResult, search_keys: set[tuple[str, str]] | None
) -> list[PlayerForecast]:
    if not search_keys:
        return []
    return [player for player in result.players if player.key in search_keys]


def _ceiling_players(
    result: ForecastResult,
    selected_key: tuple[str, str] | None,
    matches: list[PlayerForecast],
) -> list[PlayerForecast]:
    """Selected and searched players get ceiling markers; all players would clutter."""
    players: list[PlayerForecast] = []
    seen: set[tuple[str, str]] = set()
    candidates = [p for p in result.players if p.key == selected_key] + matches
    for player in candidates:
        if player.key in seen:
            continue
        seen.add(player.key)
        players.append(player)
    return players


def _bubble_band_rows(
    result: ForecastResult,
    selected_key: tuple[str, str] | None = None,
    search_keys: set[tuple[str, str]] | None = None,
) -> list[tuple[PlayerForecast, int]]:
    """Return the players shown in the band with evenly spaced row numbers."""
    low_rank = max(1, result.cutoff_rank - BAND_ROWS_BEFORE_CUTOFF)
    high_rank = result.cutoff_rank + BAND_ROWS_AFTER_CUTOFF
    shown = [p for p in result.players if low_rank <= p.rank <= high_rank]

    extras: list[PlayerForecast] = []
    selected = next((p for p in result.players if p.key == selected_key), None)
    if selected is not None:
        extras.append(selected)
    extras.extend(_search_matches(result, search_keys))

    seen = {p.key for p in shown}
    extra_rows: list[PlayerForecast] = []
    for player in extras:
        if player.key in seen:
            continue
        seen.add(player.key)
        extra_rows.append(player)
    shown.extend(extra_rows[:BAND_MAX_EXTRA_ROWS])

    shown.sort(key=lambda p: p.rank)
    return [(player, row) for row, player in enumerate(shown)]


def _draw_search_highlights(
    ax: Axes,
    matches: list[PlayerForecast],
    *,
    y_value,
    offset_points: tuple[int, int],
) -> None:
    """Ring and label each search match with a leader line."""
    for index, player in enumerate(matches):
        x = player.current_cp
        y = y_value(player)
        ax.scatter(
            x,
            y,
            s=300,
            facecolors="none",
            edgecolors=SELECTED_COLOR,
            linewidths=2.5,
            zorder=8,
        )
        direction = 1 if index % 2 == 0 else -1
        dy = direction * offset_points[1] * (1 + index // 2)
        ax.annotate(
            player.name,
            xy=(x, y),
            xytext=(offset_points[0], dy),
            textcoords="offset points",
            fontsize=8,
            fontweight="bold",
            color=SELECTED_COLOR,
            arrowprops=dict(arrowstyle="-", color=SELECTED_COLOR, linewidth=1),
            zorder=9,
        )


def _draw_empty(ax: Axes, message: str) -> None:
    ax.clear()
    ax.set_axis_off()
    ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes)


def _projected_band(ax: Axes, player: PlayerForecast, *, horizontal: bool) -> None:
    low = player.projected_cutoff_p10
    high = player.projected_cutoff_p90
    if horizontal:
        ax.axvspan(low, high, color=BAND_COLOR, alpha=0.15, label="Projected cutoff (p10-p90)")
    else:
        ax.axhspan(low, high, color=BAND_COLOR, alpha=0.15, label="Projected cutoff (p10-p90)")


def draw_safety_map(
    ax: Axes,
    result: ForecastResult,
    selected_key: tuple[str, str] | None = None,
    search_keys: set[tuple[str, str]] | None = None,
) -> None:
    """Plot every invite-range player: CP on X, P(keep) on Y."""
    if not result.players:
        _draw_empty(ax, "No forecast data — click 'Run forecast'.")
        return

    ax.clear()
    # One shared band: every player has the same cutoff distribution.
    _projected_band(ax, result.players[0], horizontal=True)

    for player in result.players:
        is_selected = player.key == selected_key
        ax.scatter(
            player.current_cp,
            player.p_keep * 100,
            s=230 if is_selected else 45 + min(160, player.events_remaining * 12),
            c=_color(player),
            edgecolors=SELECTED_COLOR if is_selected else "white",
            linewidths=2 if is_selected else 0.6,
            alpha=1.0 if is_selected else 0.85,
            zorder=5 if is_selected else 3,
        )

    matches = _search_matches(result, search_keys)
    if matches:
        _draw_search_highlights(
            ax, matches, y_value=lambda player: player.p_keep * 100, offset_points=(14, 9)
        )

    ceiling_players = (
        _ceiling_players(result, selected_key, matches) if result.config.show_ceiling else []
    )
    for player in ceiling_players:
        x_now, y_now = player.current_cp, player.p_keep * 100
        x_ceiling, y_ceiling = player.ceiling_final_cp, player.ceiling_p_keep * 100
        ax.plot(
            [x_now, x_ceiling],
            [y_now, y_ceiling],
            color=CEILING_COLOR,
            linestyle="--",
            linewidth=1,
            alpha=0.6,
            zorder=6,
        )
        ax.scatter(
            x_ceiling,
            y_ceiling,
            marker="^",
            s=95,
            facecolors="none",
            edgecolors=CEILING_COLOR,
            linewidths=1.8,
            zorder=7,
        )
        ax.annotate(
            "ceiling",
            (x_ceiling, y_ceiling),
            xytext=(6, 6),
            textcoords="offset points",
            fontsize=7,
            color=CEILING_COLOR,
            zorder=8,
        )

    ax.axvline(
        result.cutoff_cp,
        color=CUTOFF_COLOR,
        linestyle="--",
        linewidth=2,
        label=f"Cutoff now ({result.cutoff_cp} CP)",
    )
    ax.set_xlabel("Current invite CP (regional/IC unless headroom enabled)")
    ax.set_ylabel("Probability of keeping the invite")
    ax.set_ylim(0, 102)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=100))
    ax.set_title(
        f"Invite Safety Map — {result.region} {result.season} "
        f"(as of {result.as_of:%Y-%m-%d}, top {result.cutoff_rank})"
    )
    ax.grid(True, alpha=0.3)
    _add_legend(ax, show_search=bool(matches), show_ceiling=bool(ceiling_players))


def draw_bubble_band(
    ax: Axes,
    result: ForecastResult,
    selected_key: tuple[str, str] | None = None,
    search_keys: set[tuple[str, str]] | None = None,
) -> None:
    """Ranked strip around the cutoff with evenly spaced, readable rows."""
    if not result.players:
        _draw_empty(ax, "No forecast data — click 'Run forecast'.")
        return

    ax.clear()
    rows = _bubble_band_rows(result, selected_key, search_keys)
    if not rows:
        _draw_empty(ax, "No players near the cutoff.")
        return

    shown = [player for player, _ in rows]
    row_by_key = {player.key: row for player, row in rows}
    matches = _search_matches(result, search_keys)
    shown_matches = [player for player in matches if player.key in row_by_key]

    for index, (_, row) in enumerate(rows):
        if index % 2 == 1:
            ax.axhspan(row - 0.5, row + 0.5, color="#F2F2F2", zorder=0)

    _projected_band(ax, shown[0], horizontal=True)

    for player, row in rows:
        color = _color(player)
        ax.hlines(row, player.final_cp_p10, player.final_cp_p90, color=color, alpha=0.8, linewidth=2)
        ax.plot(
            [player.final_cp_p50],
            [row],
            marker="|",
            markersize=11,
            markeredgewidth=2,
            color=color,
        )
        ax.scatter(
            player.current_cp,
            row,
            s=78 if player.key == selected_key else 38,
            c=color,
            edgecolors=SELECTED_COLOR if player.key == selected_key else "white",
            linewidths=1.6 if player.key == selected_key else 0.5,
            zorder=4,
        )
        ax.text(
            player.final_cp_p90 + 6, row, f"{player.p_keep:.0%}", va="center", fontsize=8, zorder=5
        )

    if shown_matches:
        _draw_search_highlights(
            ax,
            shown_matches,
            y_value=lambda player: float(row_by_key[player.key]),
            offset_points=(16, 0),
        )

    ceiling_players = (
        _ceiling_players(result, selected_key, shown_matches)
        if result.config.show_ceiling
        else []
    )
    for player in ceiling_players:
        row = row_by_key[player.key]
        ax.hlines(
            row,
            player.final_cp_p90,
            player.ceiling_final_cp,
            color=CEILING_COLOR,
            linestyle="--",
            linewidth=1.2,
            alpha=0.7,
            zorder=6,
        )
        ax.scatter(
            player.ceiling_final_cp,
            row,
            marker="^",
            s=75,
            facecolors="none",
            edgecolors=CEILING_COLOR,
            linewidths=1.6,
            zorder=7,
        )

    ax.axvline(
        result.cutoff_cp,
        color=CUTOFF_COLOR,
        linestyle="--",
        linewidth=2,
        label=f"Cutoff now ({result.cutoff_cp} CP)",
    )

    x_values = (
        [p.current_cp for p in shown]
        + [p.final_cp_p10 for p in shown]
        + [p.final_cp_p90 for p in shown]
        + [p.ceiling_final_cp for p in ceiling_players]
        + [result.cutoff_cp]
    )
    ax.set_xlim(min(x_values) - 10, max(x_values) + 28)

    ax.set_yticks([row for _, row in rows])
    ax.set_yticklabels([f"#{p.rank} {p.name[:18]}" for p in shown], fontsize=8)
    ax.set_ylim(len(rows) - 0.5, -0.5)
    ax.set_xlabel(
        "CP: dot = now, bar = simulated p10-p90, | = median, % = P(keep)\n"
        "Orange band = projected cutoff; red dashed = today; purple ^ = ceiling (not expected)"
    )
    ax.set_title(
        f"Bubble Band — {result.region} {result.season}, cutoff rank {result.cutoff_rank}\n"
        f"{len(rows)} evenly spaced rows (rank shown at left)"
    )
    ax.grid(True, alpha=0.25, axis="x")
    ax.figure.subplots_adjust(left=0.19, right=0.97, top=0.91, bottom=0.18)
    _add_legend(
        ax,
        fontsize=7,
        show_search=bool(shown_matches),
        show_ceiling=bool(ceiling_players),
        loc="upper center",
        ncol=4,
        bbox_to_anchor=(0.5, -0.09),
    )


def draw_player_detail(ax: Axes, result: ForecastResult, player: PlayerForecast) -> None:
    """Show one player's simulated final CP next to the projected cutoff."""
    ax.clear()
    samples = [float(value) for value in player.final_cp_samples]
    if not samples:
        _draw_empty(ax, "No simulations available for this player.")
        return

    sample_min = min(samples)
    sample_max = max(samples)
    pad = max(10.0, (sample_max - sample_min) * 0.04)
    show_ceiling = result.config.show_ceiling
    ceiling_cp = player.ceiling_final_cp if show_ceiling else sample_min
    xmin = min(sample_min, result.cutoff_cp, player.projected_cutoff_p10) - pad
    xmax = max(sample_max, result.cutoff_cp, player.projected_cutoff_p90, ceiling_cp) + pad
    ax.set_xlim(xmin, xmax)

    ax.axvspan(
        xmin,
        player.projected_cutoff_p50,
        color=ZONE_COLORS["At risk"],
        alpha=0.07,
        zorder=0,
        label="Below cutoff (miss side)",
    )
    ax.axvspan(
        player.projected_cutoff_p50,
        xmax,
        color=ZONE_COLORS["Safe"],
        alpha=0.08,
        zorder=0,
        label="Above cutoff (keep side)",
    )
    ax.hist(
        samples,
        bins=30,
        color="#56B4E9",
        alpha=0.8,
        edgecolor="white",
        label="Simulated final CP (bar height = how often)",
    )
    ax.axvline(
        result.cutoff_cp,
        color=CUTOFF_COLOR,
        linestyle="--",
        linewidth=2,
        label=f"Cutoff now ({result.cutoff_cp})",
    )
    ax.axvspan(
        player.projected_cutoff_p10,
        player.projected_cutoff_p90,
        color=BAND_COLOR,
        alpha=0.18,
        label="Cutoff p10-p90",
    )
    ax.axvline(
        player.projected_cutoff_p50,
        color=BAND_COLOR,
        linestyle="-.",
        linewidth=2,
        label=f"Projected cutoff median ({player.projected_cutoff_p50})",
    )
    ax.axvline(
        player.final_cp_p50,
        color="#333333",
        linewidth=1.8,
        label=f"Your median final CP ({player.final_cp_p50})",
    )
    if show_ceiling:
        ax.axvline(
            player.ceiling_final_cp,
            color=CEILING_COLOR,
            linestyle=":",
            linewidth=2,
            label=f"Ceiling case ({player.ceiling_tier}, {player.ceiling_final_cp} CP) — upside only",
        )

    ceiling_note = ""
    if show_ceiling:
        ceiling_note = (
            f"\nPurple dotted line = ceiling case ({player.ceiling_tier}, "
            f"{player.ceiling_final_cp} CP) if placements peak by one tier/event; "
            f"shown for upside only, not counted in P(keep)."
        )
    explanation = (
        f"Now: {player.current_cp} CP (#{player.rank}, buffer {player.buffer:+d}); "
        f"{player.events_remaining} events left "
        f"({player.expected_regionals} regional, {player.expected_ics} IC)\n"
        f"Blue bars = how often each final CP happened across simulations; "
        f"black line = your median final CP.\n"
        f"Orange line/band = projected cutoff median and p10-p90; "
        f"red dashed = today's cutoff (reference only).\n"
        f"Green side = kept invite, red side = missed invite. "
        f"Need ~{player.cp_needed_for_80} more CP for 80% confidence."
        f"{ceiling_note}"
    )
    ax.text(
        0.02,
        0.98,
        explanation,
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=8,
        bbox={"facecolor": "white", "edgecolor": "#CCCCCC", "alpha": 0.9, "pad": 4},
        zorder=10,
    )
    ax.set_xlabel("Final CP after remaining events (regional/IC CP unless headroom is enabled)")
    ax.set_ylabel("How often that final CP occurred (simulations)")
    ax.set_title(
        f"{player.display}\n"
        f"P(keep) {player.p_keep:.0%} / P(lose) {player.p_lose:.0%} — "
        f"calibrated directional estimate, not exact odds"
    )
    ax.grid(True, alpha=0.3, axis="y")
    ax.legend(fontsize=7, loc="upper right", framealpha=0.95)


def describe_player(player: PlayerForecast) -> str:
    """One-line status message for the selected player."""
    return (
        f"#{player.rank} {player.display}: {player.current_cp} CP now "
        f"(cutoff {player.cutoff_cp}, buffer {player.buffer:+d}); "
        f"P(keep) {player.p_keep:.0%} / P(lose) {player.p_lose:.0%}; "
        f"PB {player.pb_tier}; "
        f"regional {player.current_regionals}/{player.prior_regionals} prior "
        f"-> {player.expected_regionals} expected ({player.remaining_regionals} left), "
        f"IC {player.current_ics}/{player.prior_ics} prior "
        f"-> {player.expected_ics} expected ({player.remaining_ics} left); "
        f"final CP p10-p90 {player.final_cp_p10}-{player.final_cp_p90}; "
        f"ceiling {player.ceiling_tier} -> {player.ceiling_final_cp} CP (upside only); "
        f"~{player.cp_needed_for_80} extra CP for 80% confidence "
        f"[{player.attendance_basis}]."
    )


def nearest_player(
    ax: Axes,
    result: ForecastResult,
    x: float,
    y: float,
    *,
    view: str,
    selected_key: tuple[str, str] | None = None,
    search_keys: set[tuple[str, str]] | None = None,
) -> PlayerForecast | None:
    """Return the closest player to a mouse position, or None if far away."""
    if not result.players or x is None or y is None:
        return None
    if view == "band":
        rows = _bubble_band_rows(result, selected_key, search_keys)
        candidates = [player for player, _ in rows]
        row_by_key = {player.key: row for player, row in rows}
    else:
        candidates = list(result.players)
        row_by_key = {}
    if not candidates:
        return None

    x_span = max(1.0, abs(ax.get_xlim()[1] - ax.get_xlim()[0]))
    y_span = max(1.0, abs(ax.get_ylim()[1] - ax.get_ylim()[0]))
    if view == "band":
        y_value = lambda player: float(row_by_key[player.key])  # noqa: E731
        y_tolerance = 4.0 / y_span
    else:
        y_value = lambda player: player.p_keep * 100  # noqa: E731
        y_tolerance = 12.0 / y_span

    best: PlayerForecast | None = None
    best_distance = float("inf")
    for player in candidates:
        dx = (player.current_cp - x) / x_span
        dy = (y_value(player) - y) / y_span
        distance = dx * dx + dy * dy
        if distance < best_distance:
            best_distance = distance
            best = player
    if best is None or abs((y_value(best) - y) / y_span) > y_tolerance:
        return None
    return best
