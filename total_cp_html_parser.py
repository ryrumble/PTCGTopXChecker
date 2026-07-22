"""Parser for pokedata.ovh HTML format.

The HTML format contains:
- <div class="cp">1510</div> for CP values
- <div class="pp">23</div> for Play Points (PP) - we ignore these
- <div class="date">2025-11-24</div> for dates
- <div class="diff">+180</div> for point differences
- Player names in onclick attributes or div text
- Country in div text
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser

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


class PokedataHTMLParser(HTMLParser):
    """Parser for pokedata.ovh HTML table format."""

    def __init__(self):
        super().__init__()
        self.entries: list[TotalCPEntry] = []
        self.current_entry: dict | None = None
        self.current_tag = None
        self.current_attrs = {}
        self.in_player_div = False
        self.in_country_div = False
        self.in_cp_div = False
        self.in_pp_div = False
        self.in_date_div = False
        self.in_diff_div = False
        self.current_rank = None
        self.current_name = None
        self.current_country = None
        self.current_cp = None
        self.current_pp = None
        self.current_date = None
        self.current_diff = None
        self.date_points_list: list[tuple[str, int, int]] = []
        self.pending_cp = None  # CP value waiting for its date/diff pair

    def handle_starttag(self, tag, attrs):
        self.current_tag = tag
        self.current_attrs = dict(attrs)

        # Check for rank in td
        if tag == 'td' and 'style' in self.current_attrs:
            style = self.current_attrs['style']
            if 'width:20px' in style:
                # This is likely the rank column
                pass

        # Check for player name in onclick
        if tag == 'div' and 'onclick' in self.current_attrs:
            onclick = self.current_attrs['onclick']
            # Extract player name from onclick="player('Abaan A', ...)"
            match = re.search(r"player\('([^']+)'", onclick)
            if match:
                self.current_name = match.group(1)
                self.in_player_div = True

        # Check for class attributes
        if tag == 'div' and 'class' in self.current_attrs:
            classes = self.current_attrs['class'].split()
            if 'player' in classes and not self.in_player_div:
                self.in_player_div = True
            elif 'country' in classes:
                self.in_country_div = True
            elif 'cp' in classes:
                self.in_cp_div = True
            elif 'pp' in classes:
                self.in_pp_div = True
            elif 'date' in classes:
                self.in_date_div = True
            elif 'diff' in classes:
                self.in_diff_div = True

    def handle_endtag(self, tag):
        if tag == 'tr':
            # End of row - finalize entry if we have one
            # Be more lenient: require name and CP, rank is optional
            if self.current_name and self.current_cp is not None:
                # Add the last CP if we have a pending one
                if self.pending_cp is not None and self.current_date and self.current_diff is not None:
                    self.date_points_list.append((
                        self.current_date,
                        self.pending_cp,
                        self.current_diff
                    ))

                # Use rank if available, otherwise use 0 (will be re-ranked later)
                rank = self.current_rank if self.current_rank is not None else 0

                entry = TotalCPEntry(
                    rank=rank,
                    raw_name=self.current_name,
                    country=self.current_country or "",
                    current_points=self.current_cp,
                    date_points=list(reversed(self.date_points_list)),  # Reverse to get chronological order
                )
                self.entries.append(entry)
            elif self.current_name or self.current_cp is not None:
                # Log incomplete entries for debugging
                logger.warning(
                    "Incomplete entry skipped: rank=%s, name=%s, cp=%s",
                    self.current_rank, self.current_name, self.current_cp
                )

            # Reset for next row
            self.current_rank = None
            self.current_name = None
            self.current_country = None
            self.current_cp = None
            self.current_pp = None
            self.current_date = None
            self.current_diff = None
            self.date_points_list = []
            self.pending_cp = None
            self.in_player_div = False
            self.in_country_div = False

        if tag == 'div':
            self.in_player_div = False
            self.in_country_div = False
            self.in_cp_div = False
            self.in_pp_div = False
            self.in_date_div = False
            self.in_diff_div = False

    def handle_data(self, data):
        data = data.strip()
        if not data:
            return

        # Rank (usually first td content that's a number)
        if self.current_tag == 'td' and data.isdigit() and self.current_rank is None:
            try:
                rank = int(data)
                if 1 <= rank <= 10000:  # Reasonable rank range
                    self.current_rank = rank
            except ValueError:
                pass

        # Player name from div content (if not already set from onclick)
        if self.in_player_div:
            # Always update name from div content (it's more reliable than onclick)
            # But only if we don't have a name yet, or if the div content is non-empty
            name_data = data.strip()
            if name_data:
                self.current_name = name_data

        # Country
        if self.in_country_div:
            self.current_country = data.strip()

        # CP value
        if self.in_cp_div:
            try:
                cp_value = int(data.strip())
                # Check if we're in a "point" td (historical) or the first one (current)
                # The first CP we encounter should be current_cp
                # Subsequent CPs in "point" class tds are historical
                if self.current_cp is None:
                    # This is the first CP - it's the current points
                    self.current_cp = cp_value
                else:
                    # This is a historical CP value - store it for pairing with date/diff
                    # We'll pair it when we get the next date/diff
                    self.pending_cp = cp_value
            except ValueError:
                pass

        # PP value (we ignore this)
        if self.in_pp_div:
            pass  # Ignore Play Points

        # Date
        if self.in_date_div:
            # Date format: YYYY-MM-DD
            date_str = data.strip()
            if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
                self.current_date = date_str
                # If we have a pending CP and diff, add them now
                if self.pending_cp is not None and self.current_diff is not None:
                    self.date_points_list.append((
                        self.current_date,
                        self.pending_cp,
                        self.current_diff
                    ))
                    # Clear pending values
                    self.pending_cp = None
                    self.current_date = None
                    self.current_diff = None

        # Point difference
        if self.in_diff_div:
            # Format: +180 or -50
            diff_str = data.strip()
            match = re.match(r'^([+-]?)(\d+)$', diff_str)
            if match:
                sign = match.group(1)
                value = int(match.group(2))
                if sign == '-':
                    value = -value
                self.current_diff = value
                # If we have a pending CP and date, add them now
                if self.pending_cp is not None and self.current_date:
                    self.date_points_list.append((
                        self.current_date,
                        self.pending_cp,
                        self.current_diff
                    ))
                    # Clear pending values
                    self.pending_cp = None
                    self.current_date = None
                    self.current_diff = None


def parse_pokedata_html(html_content: str) -> list[TotalCPEntry]:
    """Parse HTML content from pokedata.ovh file.
    
    Returns list of TotalCPEntry objects.
    """
    parser = PokedataHTMLParser()
    parser.feed(html_content)
    return parser.entries

