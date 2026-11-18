from pathlib import Path

from aggregation import aggregate_season, filter_leaderboard_by_region
from logger import logger
from parsers import ParsedEntry, detect_format, parse_format_a, parse_format_b
from scraper import fetch_with_retries, parse_first_table
from storage import existing_tournament_key_ids, list_seasons, save_tournament
from utils import TournamentKey, normalize_player_name

DEFAULT_SEASON = list_seasons()[0]


def _prompt(text: str, default: str = "") -> str:
    val = input(f"{text} [{default}]: ").strip()
    return val or default


def _prompt_int(text: str, default: int = 0) -> int:
    while True:
        val = _prompt(text, str(default))
        try:
            return int(val)
        except ValueError:
            print("Please enter an integer.")


def _confirm(text: str, default: bool = False) -> bool:
    d = "Y/n" if default else "y/N"
    val = input(f"{text} ({d}): ").strip().lower()
    if not val:
        return default
    return val.startswith("y")


def _collect_paste() -> str:
    print("Paste tournament results below. End with a single '.' on its own line.")
    lines: list[str] = []
    while True:
        line = input()
        if line.strip() == ".":
            break
        lines.append(line)
    return "\n".join(lines)


def _ensure_regions(entries: list[ParsedEntry]) -> None:
    """Prompt user for any missing region codes."""
    for e in entries:
        if not e.region_code:
            while True:
                rc = input(f"Enter region code for '{normalize_player_name(e.raw_name)}': ").strip()
                if rc:
                    e.region_code = rc.upper()
                    break


def _to_raw_and_norm(entries: list[ParsedEntry]):
    raw = []
    norm = []

    for e in entries:
        raw.append(
            {
                "placement": e.placement,
                "raw_name": e.raw_name,
                "region_code": e.region_code,
            }
        )
        norm.append(
            {
                "placement": e.placement,
                "normalized_name": normalize_player_name(e.raw_name),
                "region_code": e.region_code,
            }
        )
    return raw, norm


def add_tournament_paste(season: str = DEFAULT_SEASON) -> None:
    title = _prompt("Tournament Title")
    url = _prompt("URL (optional)")
    t_type_in = _prompt("Tournament Type (IC/Regional)", "Regional").strip().upper()
    t_type = "IC" if t_type_in == "IC" else "REGIONAL"
    num_comp = _prompt_int("Number of competitors", 0)

    text = _collect_paste()
    fmt = detect_format(text)
    entries = parse_format_a(text) if fmt == "A" else parse_format_b(text)
    if not entries:
        print("No entries parsed. Aborting.")
        return
    _ensure_regions(entries)

    raw_entries, normalized_entries = _to_raw_and_norm(entries)

    # Duplicate detection
    key = TournamentKey(title_norm=title.strip(), url=url or "", season=season)
    existing = existing_tournament_key_ids(season)
    if key.to_id() in existing and not _confirm("Tournament already exists. Overwrite record?", False):
        print("Aborted by user.")
        return

    save_tournament(
        season=season,
        title=title,
        url=url,
        tournament_type=t_type,
        num_competitors=num_comp,
        raw_entries=raw_entries,
        normalized_entries=normalized_entries,
    )
    print("Tournament saved.")


def add_tournament_scrape(season: str = DEFAULT_SEASON) -> None:
    title = _prompt("Tournament Title")
    url = _prompt("URL")
    t_type_in = _prompt("Tournament Type (IC/Regional)", "Regional").strip().upper()
    t_type = "IC" if t_type_in == "IC" else "REGIONAL"
    num_comp = _prompt_int("Number of competitors", 0)

    html = fetch_with_retries(url)
    if not html:
        print("Failed to fetch URL after retries. See logs for details.")
        return
    try:
        entries = parse_first_table(html)
    except Exception as exc:
        logger.error("Scraper parse failed: %s", exc)
        print("Could not parse table automatically. Try Paste mode instead.")
        return
    _ensure_regions(entries)
    raw_entries, normalized_entries = _to_raw_and_norm(entries)

    key = TournamentKey(title_norm=title.strip(), url=url or "", season=season)
    existing = existing_tournament_key_ids(season)
    if key.to_id() in existing and not _confirm("Tournament already exists. Overwrite record?", False):
        print("Aborted by user.")
        return

    save_tournament(
        season=season,
        title=title,
        url=url,
        tournament_type=t_type,
        num_competitors=num_comp,
        raw_entries=raw_entries,
        normalized_entries=normalized_entries,
    )
    print("Tournament saved.")


def show_leaderboard(season: str = DEFAULT_SEASON) -> None:
    df = aggregate_season(season, force=True)
    if df.empty:
        print("No tournaments found for this season.")
        return
    region = _prompt("Filter by Region Group (ALL/NA/EU/LA/MESA/OC/OTHER)", "ALL").upper()
    df_f = filter_leaderboard_by_region(df, region)
    print(df_f[["Rank", "Name", "RegionCode", "RegionGroup", "TotalCP", "CPFinishesStr"]].to_string(index=False))


def export_leaderboard(season: str = DEFAULT_SEASON) -> None:
    df = aggregate_season(season, force=True)
    if df.empty:
        print("No data to export.")
        return
    out_dir = Path("data") / season
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "leaderboard.csv"
    xlsx_path = out_dir / "leaderboard.xlsx"
    df.to_csv(csv_path, index=False)
    df.to_excel(xlsx_path, index=False)
    print(f"Exported CSV to {csv_path}")
    print(f"Exported Excel to {xlsx_path}")


def run_cli_menu() -> None:
    season = DEFAULT_SEASON
    while True:
        print("\n=== PKMN Top X Leaderboard CLI ===")
        print(f"Season: {season}")
        print("1) Add Tournament (Paste)")
        print("2) Add Tournament (Scrape URL)")
        print("3) Show Leaderboard")
        print("4) Export Leaderboard (JSON/CSV/Excel)")
        print("5) Change Season")
        print("0) Exit")
        choice = input("Select option: ").strip()
        if choice == "1":
            add_tournament_paste(season)
        elif choice == "2":
            add_tournament_scrape(season)
        elif choice == "3":
            show_leaderboard(season)
        elif choice == "4":
            export_leaderboard(season)
        elif choice == "5":
            season = _prompt("Season", season)
        elif choice == "0":
            print("Goodbye.")
            break
        else:
            print("Invalid choice.")




