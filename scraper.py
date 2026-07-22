import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from logger import logger
from parsers import ParsedEntry


def fetch_with_retries(url: str, retries: int = 3, delay_sec: int = 20) -> str | None:
    """Fetch URL content with simple retry logic."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        logger.error("Unsupported URL scheme: %s (only http/https allowed)", parsed.scheme)
        return None

    for attempt in range(1, retries + 1):
        try:
            logger.info("Scrape attempt %s for URL %s", attempt, url)
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            logger.info("Scrape success for URL %s", url)
            return resp.text
        except Exception as exc:
            logger.error("Scrape error on attempt %s for %s: %s", attempt, url, exc)
            if attempt < retries:
                time.sleep(delay_sec)
    return None


def parse_first_table(html: str) -> list[ParsedEntry]:
    """Attempt to parse the first HTML table as tournament standings.

    We assume columns include a placement-like column and player name, with region
    either in its own column or bracketed in the name.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        raise ValueError("No <table> found on page for automatic parsing.")

    rows = table.find_all("tr")
    entries: list[ParsedEntry] = []
    for tr in rows:
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if not cells or not cells[0].strip():
            continue
        # Skip header rows that don't start with an integer
        try:
            placement = int(cells[0].split()[0])
        except ValueError:
            continue
        if len(cells) < 2:
            continue
        name = cells[1]
        region: str | None = None
        if len(cells) >= 3:
            # Heuristic: treat a pure 2-3 letter cell as region code.
            cand = cells[2].strip()
            if cand.isalpha() and 2 <= len(cand) <= 3:
                region = cand.upper()
        entries.append(ParsedEntry(placement=placement, raw_name=name, region_code=region))
    if not entries:
        raise ValueError(
            "Could not parse any rows from first table. "
            "Try using the Paste option or extending the scraper."
        )
    return entries




