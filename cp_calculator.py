from dataclasses import dataclass

from logger import logger


@dataclass(frozen=True)
class CPBracket:
    min_place: int
    max_place: int
    kicker: int
    cp: int

    def matches(self, place: int, competitors: int) -> bool:
        return self.min_place <= place <= self.max_place and competitors >= self.kicker


def _make_brackets_ic() -> list[CPBracket]:
    # Defined per problem statement (single kicker per placement band)
    return [
        CPBracket(1, 1, 0, 500),
        CPBracket(2, 2, 4, 480),
        CPBracket(3, 4, 8, 420),
        CPBracket(5, 8, 17, 380),
        CPBracket(9, 16, 33, 300),
        CPBracket(17, 32, 65, 240),
        CPBracket(33, 64, 129, 180),
        CPBracket(65, 128, 257, 140),
        CPBracket(129, 256, 513, 100),
        CPBracket(257, 512, 1_025, 80),
        CPBracket(513, 1_024, 2_049, 40),
    ]


def _make_brackets_regional() -> list[CPBracket]:
    return [
        CPBracket(1, 1, 0, 350),
        CPBracket(2, 2, 4, 325),
        CPBracket(3, 4, 8, 300),
        CPBracket(5, 8, 17, 280),
        CPBracket(9, 16, 33, 200),
        CPBracket(17, 32, 65, 160),
        CPBracket(33, 64, 129, 120),
        CPBracket(65, 128, 257, 80),
        CPBracket(129, 256, 513, 60),
        CPBracket(257, 512, 1_025, 40),
        CPBracket(513, 1_024, 2_049, 20),
    ]


def _make_brackets_ic_2026_2027() -> list[CPBracket]:
    # 2026-2027 season: T512/T1024 CP adjusted upward.
    return [
        CPBracket(1, 1, 0, 500),
        CPBracket(2, 2, 4, 480),
        CPBracket(3, 4, 8, 420),
        CPBracket(5, 8, 17, 380),
        CPBracket(9, 16, 33, 300),
        CPBracket(17, 32, 65, 240),
        CPBracket(33, 64, 129, 180),
        CPBracket(65, 128, 257, 140),
        CPBracket(129, 256, 513, 100),
        CPBracket(257, 512, 1_025, 85),
        CPBracket(513, 1_024, 2_049, 42),
    ]


def _make_brackets_regional_2026_2027() -> list[CPBracket]:
    # 2026-2027 season: T512/T1024 CP adjusted upward.
    return [
        CPBracket(1, 1, 0, 350),
        CPBracket(2, 2, 4, 325),
        CPBracket(3, 4, 8, 300),
        CPBracket(5, 8, 17, 280),
        CPBracket(9, 16, 33, 200),
        CPBracket(17, 32, 65, 160),
        CPBracket(33, 64, 129, 120),
        CPBracket(65, 128, 257, 80),
        CPBracket(129, 256, 513, 60),
        CPBracket(257, 512, 1_025, 45),
        CPBracket(513, 1_024, 2_049, 22),
    ]


IC_BRACKETS = _make_brackets_ic()
REGIONAL_BRACKETS = _make_brackets_regional()
IC_BRACKETS_2026_2027 = _make_brackets_ic_2026_2027()
REGIONAL_BRACKETS_2026_2027 = _make_brackets_regional_2026_2027()


def _normalize_season(season: str | None) -> str | None:
    if season is None:
        return None
    s = str(season).strip()
    return s or None


def _brackets_for(tournament_type: str, season: str | None = None) -> list[CPBracket]:
    tt = tournament_type.strip().upper()
    s = _normalize_season(season)
    if s == "2026-2027":
        return IC_BRACKETS_2026_2027 if tt == "IC" else REGIONAL_BRACKETS_2026_2027
    return IC_BRACKETS if tt == "IC" else REGIONAL_BRACKETS


def kicker_ladder(tournament_type: str, season: str | None = None) -> list[int]:
    """Return the sorted CP kicker thresholds for a tournament type.

    The ladder is the same for IC and Regional/SPE events, but deriving it
    from the bracket tables keeps it in sync if a season's tables change.
    """
    brackets = _brackets_for(tournament_type, season)
    return sorted({b.kicker for b in brackets})


def max_kicker_for_field(
    num_competitors: int, tournament_type: str = "REGIONAL", season: str | None = None
) -> int:
    """Largest kicker threshold reached by a field of this size.

    An event with N competitors reaches every CP bracket whose kicker is
    <= N, and no more. That gives a CP-aware "size tier" for the event:
    0 for a tiny field, up to 2,049 for the largest regionals.
    """
    if num_competitors <= 0:
        return 0
    reached = [k for k in kicker_ladder(tournament_type, season) if k <= num_competitors]
    return reached[-1] if reached else 0


def calculate_cp(
    tournament_type: str, placement: int, num_competitors: int, season: str | None = None
) -> int:
    """Calculate Championship Points for a given placement.

    Args:
        tournament_type: "IC" or "REGIONAL" (Regional/SPE)
        placement: 1-based finishing place
        num_competitors: total number of competitors in the event
        season: Optional season identifier (e.g. "2026-2027") for season-specific tables
    """
    if placement <= 0 or num_competitors <= 0:
        return 0

    brackets = _brackets_for(tournament_type, season)

    # Find all brackets whose placement range matches, then those with kicker <= N
    candidate: tuple[int, CPBracket] | None = None
    for b in brackets:
        if b.min_place <= placement <= b.max_place and num_competitors >= b.kicker:
            # We want the bracket with largest kicker that is still <= N
            if candidate is None or b.kicker > candidate[0]:
                candidate = (b.kicker, b)

    if candidate is None:
        logger.info(
            "No CP bracket matched: type=%s place=%s competitors=%s season=%s",
            tournament_type,
            placement,
            num_competitors,
            season,
        )
        return 0

    return candidate[1].cp




