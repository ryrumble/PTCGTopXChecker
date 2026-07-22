import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from logger import logger

REGION_GROUPS = {
    "NA": {"US", "CA", "PR"},
    "EU": {
        "EU", "GB", "UK", "NL", "DK", "ES", "NO", "PL", "FR", "FI", "IT", "CH", "PT",
        "DE", "BE", "AT", "CZ", "SK", "AD", "RO", "IE", "IM", "GG", "GR", "HU", "SE",
        "CY", "MT", "LU", "SI",
    },
    "LA": {"CL", "BR", "MX", "PE", "AR", "EC", "GT", "UY", "CR", "SV", "CO"},
    "MEA": {"IL", "ZA", "QA", "AE", "KW"},
    "BA": {"BA"},
    "OC": {"AU", "NZ"},
}

KNOWN_REGION_CODES = set().union(*REGION_GROUPS.values())

# Worlds Race: Masters invite cutoff rank by region group (NA, EU, LA, OC, MEA).
# OTHER uses a safe default for display; filter can hide it.
WORLDS_CUTOFF_BY_REGION = {
    "NA": 135,
    "EU": 135,
    "LA": 125,
    "OC": 20,
    "MEA": 10,
    "OTHER": 135,
}

# Display labels for region dropdown (MEA shown as MESA).
REGION_DISPLAY_NAMES = {
    "NA": "NA (USA/Canada/PR)",
    "EU": "EU",
    "LA": "LATAM",
    "OC": "OCE",
    "MEA": "MESA",
    "BA": "BA",
    "OTHER": "Other",
    "ALL_COMPARE": "All Region Compare",
}


def normalize_player_name(raw: str) -> str:
    """Normalize player name for deduplication and display.

    - Strip region markers like ' [US]'
    - Normalize unicode and whitespace
    - Title-case the result
    """
    if not raw:
        return ""
    # Remove region markers in brackets at end
    name = re.sub(r"\s*\[[A-Za-z]{2,3}\]\s*$", "", raw).strip()
    name = " ".join(name.split())  # collapse whitespace
    name = unicodedata.normalize("NFKC", name)
    return name.title()


def extract_region_from_brackets(raw: str) -> str | None:
    """Extract region code inside [XX] at end of string, if any."""
    if not raw:
        return None
    m = re.search(r"\[([A-Za-z]{2,3})\]\s*$", raw)
    if not m:
        return None
    return m.group(1).upper()


def map_region_to_group(code: str | None) -> str:
    """Map a country/region code to high-level group; fallback to OTHER."""
    if not code:
        return "OTHER"
    up = code.upper()
    for group, codes in REGION_GROUPS.items():
        if up in codes:
            return group
    return "OTHER"


def slugify(text: str) -> str:
    """Create a filesystem-safe slug from text."""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "tournament"


def timestamp_str() -> str:
    return datetime.utcnow().strftime("%Y%m%d%H%M%S")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


@dataclass
class TournamentKey:
    """Composite key used to detect duplicates."""

    title_norm: str
    url: str
    season: str

    def to_id(self) -> str:
        base = slugify(self.title_norm or "tournament")
        if self.url:
            url_part = slugify(self.url)[:32]
        else:
            url_part = "no-url"
        return f"{base}_{url_part}_{self.season}"


def find_merge_candidates(names: list[str]) -> None:
    """Placeholder for future fuzzy merge logic.

    In a future version this could:
    - compute similarity between normalized names (e.g., Levenshtein / token set ratios)
    - propose groups of likely duplicates
    - ask for interactive confirmation to merge

    For now this is a stub that only logs its invocation.
    """
    logger.info("find_merge_candidates stub called for %d names", len(names))



