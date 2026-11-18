import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from logger import logger
from utils import TournamentKey, ensure_dir, slugify, timestamp_str

DATA_DIR = Path("data")
_MAX_JSON_SIZE_MB = 100
_VALID_TOURNAMENT_TYPES = {"REGIONAL", "IC"}

# Seasons offered by the picker even before any data has been saved for them.
# Keep this sorted; list_seasons() returns everything newest first.
KNOWN_SEASONS: tuple[str, ...] = ("2026-2027",)
_SEASON_DIR_PATTERN = re.compile(r"\d{4}-\d{4}")


def validate_tournament_data(
    title: str,
    tournament_type: str,
    num_competitors: int,
    raw_entries: list[dict[str, Any]],
    normalized_entries: list[dict[str, Any]],
) -> None:
    """Validate tournament data before saving. Raises ValueError on invalid data."""
    if not title or not title.strip():
        raise ValueError("Tournament title cannot be empty")
    tt = tournament_type.strip().upper()
    if tt not in _VALID_TOURNAMENT_TYPES:
        raise ValueError(f"Invalid tournament type: {tournament_type}. Must be one of {_VALID_TOURNAMENT_TYPES}")
    if num_competitors < 0:
        raise ValueError(f"Number of competitors cannot be negative: {num_competitors}")
    if not raw_entries:
        raise ValueError("Tournament must have at least one entry")
    if len(raw_entries) != len(normalized_entries):
        raise ValueError(
            f"Entry count mismatch: {len(raw_entries)} raw vs {len(normalized_entries)} normalized"
        )
    for i, entry in enumerate(normalized_entries):
        placement = entry.get("placement", 0)
        if not isinstance(placement, int) or placement <= 0:
            raise ValueError(f"Entry {i}: invalid placement {placement}")
        name = entry.get("normalized_name", "")
        if not name or not name.strip():
            raise ValueError(f"Entry {i}: empty player name")


def tournament_dir(season: str) -> Path:
    path = DATA_DIR / season / "tournaments"
    ensure_dir(path)
    return path


def season_dir(season: str) -> Path:
    path = DATA_DIR / season
    ensure_dir(path)
    return path


def list_tournament_files(season: str) -> list[Path]:
    tdir = tournament_dir(season)
    return sorted(tdir.glob("*.json"))


def list_seasons() -> list[str]:
    """Return all selectable seasons, newest first.

    Combines seasons with an existing ``data/<season>/`` directory with
    ``KNOWN_SEASONS`` so a new season can be chosen before it has any data.
    """
    seasons = set(KNOWN_SEASONS)
    if DATA_DIR.is_dir():
        seasons.update(
            path.name
            for path in DATA_DIR.iterdir()
            if path.is_dir() and _SEASON_DIR_PATTERN.fullmatch(path.name)
        )
    return sorted(seasons, reverse=True)


def load_json(path: Path) -> dict[str, Any]:
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > _MAX_JSON_SIZE_MB:
        raise ValueError(
            f"File too large: {path.name} is {size_mb:.1f} MB "
            f"(max {_MAX_JSON_SIZE_MB} MB)"
        )
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _env_compact_json() -> bool:
    return os.environ.get("PKMN_TOPX_COMPACT_JSON", "").strip().lower() in ("1", "true", "yes")


def save_json(path: Path, data: dict[str, Any], *, compact: bool | None = None) -> None:
    """Write JSON atomically via temp file + rename.

    Set ``compact=True`` or env ``PKMN_TOPX_COMPACT_JSON=1`` for minified output.
    """
    if compact is None:
        compact = _env_compact_json()
    ensure_dir(path.parent)

    # Atomic write: write to a temp file in the same directory, then rename
    fd, tmp_path_str = tempfile.mkstemp(
        suffix=".tmp",
        prefix=path.stem + "_",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if compact:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            else:
                json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path_str, str(path))  # noqa: PTH105
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path_str)  # noqa: PTH108
        except OSError:
            pass
        raise

    logger.debug("Saved JSON: %s", path)


def existing_tournament_key_ids(season: str) -> dict[str, Path]:
    """Return mapping from composite key id to file path."""
    result: dict[str, Path] = {}
    for path in list_tournament_files(season):
        try:
            data = load_json(path)
            meta = data.get("metadata", {})
            key = TournamentKey(
                title_norm=meta.get("title_norm", ""),
                url=meta.get("url", "") or "",
                season=meta.get("season", ""),
            )
            result[key.to_id()] = path
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to read tournament file %s: %s", path, exc)
    return result


def save_tournament(
    season: str,
    title: str,
    url: str,
    tournament_type: str,
    num_competitors: int,
    raw_entries: list[dict[str, Any]],
    normalized_entries: list[dict[str, Any]],
    tournament_date: str = "",
) -> Path:
    """Persist a single tournament file and return its path."""
    validate_tournament_data(title, tournament_type, num_competitors, raw_entries, normalized_entries)
    key = TournamentKey(title_norm=title.strip(), url=url or "", season=season)
    t_id = key.to_id()
    filename = f"{slugify(title)}_{timestamp_str()}.json"
    path = tournament_dir(season) / filename

    data: dict[str, Any] = {
        "metadata": {
            "id": t_id,
            "title": title,
            "title_norm": title.strip(),
            "url": url,
            "season": season,
            "tournament_type": tournament_type,
            "num_competitors": num_competitors,
            "tournament_date": (tournament_date or "").strip(),
            "added_at": datetime.utcnow().isoformat() + "Z",
        },
        "raw_entries": raw_entries,
        "normalized_entries": normalized_entries,
    }
    save_json(path, data)
    return path


def save_season_aggregate(season: str, aggregate: dict[str, Any]) -> Path:
    path = season_dir(season) / "season_aggregate.json"
    save_json(path, aggregate)
    return path


def load_player_mappings(season: str) -> dict[str, Any]:
    """Load player name mappings (merges/splits) for a season."""
    path = season_dir(season) / "player_mappings.json"
    if path.exists():
        try:
            return load_json(path)
        except Exception as exc:
            logger.warning("Failed to load player mappings: %s", exc)
    return {"merges": {}, "splits": []}


def save_player_mappings(season: str, mappings: dict[str, Any]) -> None:
    """Save player name mappings for a season."""
    path = season_dir(season) / "player_mappings.json"
    save_json(path, mappings)
    logger.debug("Saved player mappings for season %s", season)


def save_total_cp_data(season: str, entries: list[dict[str, Any]]) -> Path:
    """Save total CP data from pokedata.ovh for a season."""
    path = season_dir(season) / "total_cp_data.json"
    data = {
        "season": season,
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "entries": entries,
    }
    save_json(path, data)
    logger.debug("Saved total CP data for season %s: %d entries", season, len(entries))
    return path


def load_total_cp_data(season: str) -> list[dict[str, Any]]:
    """Load total CP data from pokedata.ovh for a season."""
    path = season_dir(season) / "total_cp_data.json"
    if path.exists():
        try:
            data = load_json(path)
            return data.get("entries", [])
        except Exception as exc:
            logger.warning("Failed to load total CP data: %s", exc)
    return []


def save_pokedata_name_mappings(season: str, mappings: dict[str, str]) -> None:
    """Save name mappings from pokedata.ovh names to regional names."""
    path = season_dir(season) / "pokedata_name_mappings.json"
    save_json(path, mappings)
    logger.debug("Saved pokedata name mappings for season %s", season)


def load_pokedata_name_mappings(season: str) -> dict[str, str]:
    """Load name mappings from pokedata.ovh names to regional names."""
    path = season_dir(season) / "pokedata_name_mappings.json"
    if path.exists():
        try:
            return load_json(path)
        except Exception as exc:
            logger.warning("Failed to load pokedata name mappings: %s", exc)
    return {}



