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


IC_BRACKETS = _make_brackets_ic()
REGIONAL_BRACKETS = _make_brackets_regional()


def calculate_cp(
    tournament_type: str, placement: int, num_competitors: int
) -> int:
    """Calculate Championship Points for a given placement.

    Args:
        tournament_type: "IC" or "REGIONAL" (Regional/SPE)
        placement: 1-based finishing place
        num_competitors: total number of competitors in the event
    """
    if placement <= 0 or num_competitors <= 0:
        return 0

    tt = tournament_type.strip().upper()
    brackets = IC_BRACKETS if tt == "IC" else REGIONAL_BRACKETS

    # Find all brackets whose placement range matches, then those with kicker <= N
    candidate: tuple[int, CPBracket] | None = None
    for b in brackets:
        if b.min_place <= placement <= b.max_place and num_competitors >= b.kicker:
            # We want the bracket with largest kicker that is still <= N
            if candidate is None or b.kicker > candidate[0]:
                candidate = (b.kicker, b)

    if candidate is None:
        logger.info(
            "No CP bracket matched: type=%s place=%s competitors=%s",
            tournament_type,
            placement,
            num_competitors,
        )
        return 0

    return candidate[1].cp




