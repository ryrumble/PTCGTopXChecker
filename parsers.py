import re
from dataclasses import dataclass

from logger import logger
from utils import extract_region_from_brackets, normalize_player_name


@dataclass
class ParsedEntry:
    placement: int
    raw_name: str
    region_code: str | None


LINE_A_REGEX = re.compile(
    r"^\s*(\d+)[\.\)]\s*(.+?)(?:\s+\[([A-Za-z]{2,3})\])?\s*$"
)


def parse_format_a(text: str) -> list[ParsedEntry]:
    """Parse simple '1. Name [XX]' style lines."""
    entries: list[ParsedEntry] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = LINE_A_REGEX.match(line)
        if not m:
            logger.debug("Format A: could not parse line: %r", line)
            continue
        placement = int(m.group(1))
        name = m.group(2)
        region = m.group(3) or extract_region_from_brackets(line)
        entries.append(ParsedEntry(placement=placement, raw_name=name, region_code=region))
    return entries


def detect_format(text: str) -> str:
    """Very lightweight auto-detection between format A and B."""
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return "A"
    # If first non-empty line starts with digit + '.' it's likely A
    if re.match(r"^\s*\d+[\.\)]", lines[0]):
        return "A"
    return "B"


def parse_format_b(text: str) -> list[ParsedEntry]:
    """Parse multi-line scoreboard style paste.

    We assume rows come in repeating pattern after header, roughly:
        <placement>
        <name>
        <country-code>
        <rest-of-row-with-points-etc>
    """
    lines = [l.rstrip() for l in text.splitlines()]
    # Remove obvious header lines starting with '#', 'Name', etc.
    filtered: list[str] = []
    for ln in lines:
        if not ln.strip():
            continue
        if ln.lstrip().startswith("#"):
            continue
        if "Name" in ln and "Points" in ln:
            continue
        filtered.append(ln)

    entries: list[ParsedEntry] = []
    i = 0
    while i < len(filtered):
        line = filtered[i].strip()
        if not re.match(r"^\d+$", line):
            i += 1
            continue
        placement = int(line)
        if i + 1 >= len(filtered):
            break
        name = filtered[i + 1].strip()
        region: str | None = None
        # Try to pick region from next line if it looks like a 2–3 letter code.
        if i + 2 < len(filtered):
            maybe_region = filtered[i + 2].strip()
            if re.fullmatch(r"[A-Za-z]{2,3}", maybe_region):
                region = maybe_region.upper()
                i_advance = 4  # we consumed placement, name, region, plus likely stats row
            else:
                i_advance = 3  # placement, name, then stats
        else:
            i_advance = 2

        entries.append(ParsedEntry(placement=placement, raw_name=name, region_code=region))
        i += i_advance
    return entries


def to_normalized_entries(
    parsed: list[ParsedEntry],
) -> list[tuple[int, str, str | None]]:
    """Turn ParsedEntry objects into (placement, norm_name, region_code)."""
    results: list[tuple[int, str, str | None]] = []
    for e in parsed:
        norm = normalize_player_name(e.raw_name)
        results.append((e.placement, norm, e.region_code))
    return results




