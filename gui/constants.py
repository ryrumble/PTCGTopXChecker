"""Shared GUI constants."""

from storage import list_seasons

# Every season the picker offers, newest first. The first one is selected
# when the app opens, so a new season is usable before it has any data.
SEASONS = list_seasons()
DEFAULT_SEASON = SEASONS[0]

CHART_COLORS = [
    "#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2",
    "#D55E00", "#CC79A7", "#000000", "#404040", "#FF0000",
]
