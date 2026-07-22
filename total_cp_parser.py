"""Parser for pokedata.ovh total CP data format.

The format is:
- rank, player, country, current points (in black), player points (in blue),
  then date-points pairs (e.g., "2025-11-24: 1330 (+180)")

Example line:
1	Abaan A	USA	1510	2025-11-24: 1330 (+180)	2025-11-19: 1050 (+280)	...
"""

import re
from dataclasses import dataclass

from logger import logger
from utils import normalize_player_name


@dataclass
class TotalCPEntry:
    """Represents a player's total CP data from pokedata.ovh."""
    rank: int
    raw_name: str
    country: str
    current_points: int
    date_points: list[tuple[str, int, int]]  # List of (date, total_points, points_gained)

    @property
    def normalized_name(self) -> str:
        """Get normalized name for matching."""
        return normalize_player_name(self.raw_name)


DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
POINTS_GAINED_PATTERN = re.compile(r"^\+(\d+)$")


def parse_pokedata_line(line: str) -> TotalCPEntry | None:
    """Parse a single line from pokedata.ovh format.
    
    Expected format (tab-separated):
    rank, player, country, current_points, date1, +points1, total1, date2, +points2, total2, ...
    
    Or the format might have dates and points in alternating columns.
    """
    line = line.strip()
    if not line:
        return None

    # Skip header lines
    if line.lower().startswith("rank") or line.lower().startswith("player"):
        return None

    # Split by tabs
    if '\t' not in line:
        logger.warning("Line doesn't contain tabs: %r", line)
        return None

    parts = [p.strip() for p in line.split('\t')]

    if len(parts) < 4:
        logger.warning("Line too short: %r", line)
        return None

    try:
        # First 4 columns: rank, player, country, current_points
        rank_str = parts[0].strip()
        if not rank_str or not rank_str.isdigit():
            return None  # Skip non-data lines

        rank = int(rank_str)
        raw_name = parts[1].strip()
        country = parts[2].strip()

        # Current points might be in column 3, but could be concatenated with other data
        # Try to extract the main number (usually 3-5 digits for CP)
        current_points_str = parts[3].strip()
        # Find all number sequences and take the longest reasonable one (3-5 digits)
        number_matches = re.findall(r'\d+', current_points_str)
        if not number_matches:
            logger.warning("Could not extract current points from: %r", current_points_str)
            return None
        # Prefer 3-5 digit numbers (typical CP range), otherwise take the longest
        best_match = None
        for match in number_matches:
            num = int(match)
            if 100 <= num <= 99999:  # Reasonable CP range
                if best_match is None or (3 <= len(match) <= 5 and len(match) > len(str(best_match))):
                    best_match = num
        if best_match is None:
            # Fallback: take the longest number
            best_match = int(max(number_matches, key=len))
        current_points = best_match

        # Parse date-points pairs from remaining columns
        # Pattern: date, +points, total_points, date, +points, total_points, ...
        date_points: list[tuple[str, int, int]] = []
        i = 4
        while i < len(parts):
            # Look for a date pattern
            if DATE_PATTERN.match(parts[i]):
                date = parts[i]
                # Next should be +points
                if i + 1 < len(parts):
                    points_gained_str = parts[i + 1].strip()
                    points_match = POINTS_GAINED_PATTERN.match(points_gained_str)
                    if points_match:
                        points_gained = int(points_match.group(1))
                        # Next should be total points
                        if i + 2 < len(parts):
                            total_points_str = parts[i + 2].strip()
                            # Extract number (might be concatenated) - prefer 3-5 digit numbers
                            number_matches = re.findall(r'\d+', total_points_str)
                            if number_matches:
                                # Prefer 3-5 digit numbers (typical CP range)
                                best_total = None
                                for match in number_matches:
                                    num = int(match)
                                    if 100 <= num <= 99999:
                                        if best_total is None or (3 <= len(match) <= 5 and len(match) > len(str(best_total))):
                                            best_total = num
                                if best_total is None:
                                    best_total = int(max(number_matches, key=len))
                                total_points = best_total
                                date_points.append((date, total_points, points_gained))
                                i += 3
                                continue
                i += 1
            else:
                i += 1

        return TotalCPEntry(
            rank=rank,
            raw_name=raw_name,
            country=country,
            current_points=current_points,
            date_points=date_points,
        )
    except (ValueError, IndexError) as exc:
        logger.warning("Failed to parse line %r: %s", line, exc)
        return None


def parse_pokedata_text(text: str) -> list[TotalCPEntry]:
    """Parse multiple lines of pokedata.ovh format text.
    
    Returns list of TotalCPEntry objects.
    Handles both single-line and multi-line formats (where fields might be on separate lines).
    """
    entries: list[TotalCPEntry] = []
    lines = text.splitlines()

    # Try to detect if data is multi-line (fields on separate lines)
    # If we see a pattern like: number, empty/name, empty/name, number, date, +number, number...
    # we might need to combine lines

    current_line_parts = []
    for line in lines:
        line = line.strip()
        if not line:
            # Empty line - if we have accumulated parts, try to parse them
            if current_line_parts:
                combined = '\t'.join(current_line_parts)
                entry = parse_pokedata_line(combined)
                if entry:
                    entries.append(entry)
                current_line_parts = []
            continue

        # Check if this looks like the start of a new entry (starts with a digit)
        if line and line[0].isdigit() and len(line) <= 3:
            # This might be a rank - if we have accumulated parts, parse them first
            if current_line_parts:
                combined = '\t'.join(current_line_parts)
                entry = parse_pokedata_line(combined)
                if entry:
                    entries.append(entry)
            current_line_parts = [line]
        else:
            # Add to current line parts
            current_line_parts.append(line)

    # Handle last entry
    if current_line_parts:
        combined = '\t'.join(current_line_parts)
        entry = parse_pokedata_line(combined)
        if entry:
            entries.append(entry)

    # If we didn't get any entries from multi-line parsing, try single-line
    if not entries:
        for line in lines:
            line = line.strip()
            if line and '\t' in line:
                entry = parse_pokedata_line(line)
                if entry:
                    entries.append(entry)

    return entries


def merge_pokedata_entries(existing: list[TotalCPEntry], new: list[TotalCPEntry]) -> list[TotalCPEntry]:
    """Merge new entries into existing, updating current_points and date_points.
    
    Matches by normalized name. When a player exists in both, the new entry
    always replaces the existing one (new file takes precedence).
    Players only in existing data are kept. Players only in new data are added.
    Final list is re-ranked by current_points.
    """
    # Create a map of normalized name -> entry
    merged_map: dict[str, TotalCPEntry] = {}

    # Add existing entries first (these will be kept if not in new file)
    for entry in existing:
        norm_name = entry.normalized_name
        merged_map[norm_name] = entry

    # Add/update with new entries (new file always takes precedence)
    for entry in new:
        norm_name = entry.normalized_name
        # Always replace with new entry when there's a match
        merged_map[norm_name] = entry

    # Convert back to list and re-rank based on current_points
    merged = list(merged_map.values())
    # Sort by current_points descending
    merged.sort(key=lambda e: -e.current_points)
    # Re-assign ranks based on current_points
    for i, entry in enumerate(merged, 1):
        entry.rank = i

    return merged

