## PKMN Online Top X Checker (2025–2026)

This is a small, production-style Python application to track Pokémon TCG Championship Points for the 2025–2026 season and build “Top X” leaderboards across online tournament results.

It can:

- **Scrape** single tournament webpages with an HTML table.
- **Parse pasted results** (simple list or scoreboard-style).
- **Compute CP** using the official-style 2025–2026 Regional/SPE and IC tables.
- **Aggregate** results into a season leaderboard (top 5 CP finishes per player).
- Provide both a **CLI** and **Tkinter GUI**.

### Folder / Module Layout

- **`main.py`**: Entry point (`--mode cli` or `--mode gui`).
- **`cli.py`**: Interactive text menu for adding tournaments, viewing leaderboard, and exporting.
- **`gui.py`**: Tkinter GUI with tabs for adding tournaments and viewing/exporting leaderboard.
- **`scraper.py`**: HTTP fetch with retries and HTML-table parser (first table only).
- **`parsers.py`**: Paste Format A and B parsers and normalized-entry helpers.
- **`cp_calculator.py`**: Championship Points lookup logic for 2025–2026 (IC and Regional/SPE).
- **`aggregation.py`**: Season aggregation and region filtering utilities.
- **`storage.py`**: JSON persistence, tournament and aggregate saving.
- **`utils.py`**: Name normalization, region grouping, slug generation, composite key definition.
- **`logger.py`**: Logging configuration (`logs/app.log`).
- **`tests_cp_parsing.py`**: Minimal test stubs for CP calculation and parsing.

Data is stored under:

- `data/<season>/tournaments/*.json`
- `data/<season>/season_aggregate.json`
- `data/<season>/leaderboard.csv`
- `data/<season>/leaderboard.xlsx`

### Installation

1. **Create / activate a virtual environment** (recommended).
2. Install dependencies:

```bash
pip install requests beautifulsoup4 pandas openpyxl
```

Tkinter is part of the standard library on most Python installations; on some platforms you may need to install a system package (e.g. `python3-tk`).

### Running the Application

- **CLI (default)**:

```bash
python main.py
```

- **GUI**:

```bash
python main.py --mode gui
```

### Championship Points Tables (2025–2026)

The CP logic lives in `cp_calculator.py`. It encodes **placement bands** and a **kicker threshold** (minimum number of competitors) per band.

For this season, the app uses **one kicker threshold per band**, matching the specification:

- **International Championships (IC)**:
  - 1st: Kicker 0 → 500 CP
  - 2nd: Kicker 4 → 480 CP
  - 3–4th: Kicker 8 → 420 CP
  - 5–8th: Kicker 17 → 380 CP
  - 9–16th: Kicker 33 → 300 CP
  - 17–32nd: Kicker 65 → 240 CP
  - 33–64th: Kicker 129 → 180 CP
  - 65–128th: Kicker 257 → 140 CP
  - 129–256th: Kicker 513 → 100 CP
  - 257–512th: Kicker 1,025 → 80 CP
  - 513–1,024th: Kicker 2,049 → 40 CP

- **Regionals / SPE**:
  - 1st: Kicker 0 → 350 CP
  - 2nd: Kicker 4 → 325 CP
  - 3–4th: Kicker 8 → 300 CP
  - 5–8th: Kicker 17 → 280 CP
  - 9–16th: Kicker 33 → 200 CP
  - 17–32nd: Kicker 65 → 160 CP
  - 33–64th: Kicker 129 → 120 CP
  - 65–128th: Kicker 257 → 80 CP
  - 129–256th: Kicker 513 → 60 CP
  - 257–512th: Kicker 1,025 → 40 CP
  - 513–1,024th: Kicker 2,049 → 20 CP

**Algorithm summary** (`calculate_cp`):

- Inputs: `tournament_type` (`"IC"` or `"REGIONAL"`), `placement` (1-based), `num_competitors`.
- Find all brackets for that type where:
  - `min_place <= placement <= max_place`
  - `kicker <= num_competitors`
- Pick the bracket with the **largest kicker ≤ num_competitors** and return its `cp`.
- If no bracket matches (e.g. placement outside supported range), CP=0.

To update for a new season, adjust the lists in `_make_brackets_ic()` and `_make_brackets_regional()` in `cp_calculator.py`.

### Parsing Rules

#### Paste Format A

Lines like:

```text
1. Tord Reklev [NO]
2. Liam Halliburton [US]
3. Henry Chao [US]
4. RYUKI OKADA [JP]
```

- The parser extracts:
  - **Placement**: integer at the start before `.` or `)`.
  - **Name**: text until the trailing bracket.
  - **Region code**: `[XX]` at the end of the line (if present).

#### Paste Format B

Scoreboard-style, potentially multi-line rows:

```text
#	Name		Points	Record	OPW%	OOPW%
1
Eduardo Molina
CL
38	12 - 1 - 2	62.08%	60.63%
2
Denis Provázek
CZ
34	10 - 1 - 4	63.12%	57.47%
```

- The parser:
  - Skips obvious header lines (`#`, `Name`, `Points`).
  - Treats any line that is a bare integer as **placement**.
  - Takes the next line as **name**.
  - If the following line is a 2–3 letter token, treats it as **region code**.
  - The rest of the row (points/record/etc.) is ignored.

If a row in either format ends up **without a region code**, then:

- **CLI**: Prompts you interactively to enter a region code for that player.
- **GUI**: Shows an empty region cell; you must fill it manually in the Treeview before saving.

### Name Normalization and De-duplication

Name normalization is handled in `utils.normalize_player_name`:

- Removes trailing region markers like ` [US]`.
- Normalizes whitespace and Unicode.
- Converts to **title case** for display (e.g. `RYUKI OKADA` → `Ryuki Okada`).

Players are de-duplicated across tournaments by **exact normalized name match** (no fuzzy logic yet). There is a placeholder conceptually for a future fuzzy-merge (e.g. comparing `normalize_player_name` outputs with a similarity metric), but this version does **not** implement interactive merging.

### Region Groups and Filters

The app breaks out regions into groups (see `utils.REGION_GROUPS`):

- **NA**: `US`, `CA`
- **EU**: `EU`, `GB`, `FR`, `DE`, `ES`, `IT`, `PL`, `CZ`, `NO`, `SE`, `FI`, `DK`
- **LA**: `CL`, `BR`, `AR`, `MX`, `PE`, `CO`
- **MESA**: `AE`, `SA`, `QA`, `KW`
- **BA**: `BA`
- **OC**: `AU`, `NZ`
- All others → `OTHER`

In both CLI and GUI you can filter leaderboard by **region group** (e.g. `NA`, `EU`, `LA`), with `NA` automatically including `US` and `CA`.

### Aggregation / Top X Rules

- The aggregator scans all `data/<season>/tournaments/*.json`.
- For each **normalized player name**:
  - Collects all CP finishes across events.
  - Sorts them descending.
  - Sums the **top 5** CP values to get `TotalCP`.
- Columns in the leaderboard:
  - **Rank** (1-based, after sorting).
  - **Name**.
  - **RegionCode** (primary region, like `US`).
  - **RegionGroup** (`NA`, `EU`, `OTHER`, etc.).
  - **TotalCP** (sum of top 5).
  - **CPFinishes** (list of all CP finishes).
  - **CPFinishesStr** (comma-separated string).
  - **NumTournaments**.
  - **HighestPlacement** (best numerical placement).

Tie-breaks are resolved in this order:

1. **TotalCP** (higher is better).
2. **Best single CP finish** (`BestCP`).
3. **Second-best CP finish** (`SecondBestCP`).
4. **Most tournaments** (`NumTournaments`).

The GUI leaderboard tab allows you to filter by region group and export to CSV/Excel. The CLI shows a text table and also exposes an export option.

### Duplicate Tournament Protection

Each tournament is uniquely identified by a **composite key**:

- Normalized title.
- URL (if provided).
- Season.

This is represented by `utils.TournamentKey` and turned into a stable string ID.

When adding a tournament:

- The app loads all existing tournaments for that season.
- If a tournament with the same composite key exists:
  - **CLI**: Asks you to confirm overwrite (otherwise aborts).
  - **GUI**: Shows a Yes/No overwrite dialog.

### Example Paste Snippets

You can quickly test the parsers by pasting:

- **Format A**:

```text
1. Tord Reklev [NO]
2. Liam Halliburton [US]
3. Henry Chao [US]
4. RYUKI OKADA [JP]
```

- **Format B**:

```text
# Name    Points    Record    OPW%    OOPW%
1
Eduardo Molina
CL
38  12 - 1 - 2  62.08%  60.63%
2
Denis Provázek
CZ
34  10 - 1 - 4  63.12%  57.47%
3
Ricardo Vega
CL
32  10 - 2 - 2  56.68%  57.14%
```

### Re-running Season Aggregation

Aggregation is always based on the JSON files in `data/<season>/tournaments/`. To re-run aggregation (for example, after editing JSON by hand):

- Use the **CLI** and choose “Show Leaderboard” or “Export Leaderboard”; this always regenerates the season aggregate.
- Or, from Python:

```python
from aggregation import aggregate_season
df = aggregate_season("2025-2026")
print(df.head())
```

The call will also refresh `season_aggregate.json`.

### Edge Cases & Assumptions

- If a pasted or scraped row **lacks a region code**:
  - CLI: prompts you to enter one.
  - GUI: requires you to fill the region cell before saving.
- The scraper:
  - Only looks at the **first `<table>`** on the page.
  - Tries to interpret the first column as placement and the second as name; third column as region (if a 2–3 letter token).
  - If it fails to parse any rows, it raises a helpful error asking you to use Paste mode instead.
- Duplicate tournaments are never silently overwritten; you must confirm explicitly.

### Short Usage Walkthrough (Script)

**Scenario: Add a pasted Regional and generate a leaderboard via CLI**

1. Run `python main.py`.
2. At the menu, choose `1) Add Tournament (Paste)`.
3. Enter title (e.g. “Online Regional A”), URL (optional), and number of competitors.
4. Paste Format A or B data; end with a single `.` line.
5. If prompted, type missing region codes.
6. Confirm overwrite if a duplicate is detected.
7. Back at the menu, choose `3) Show Leaderboard` to see ranked players.
8. Choose `4) Export Leaderboard` to generate `leaderboard.csv` and `leaderboard.xlsx`.

**Scenario: Use the GUI**

1. Run `python main.py --mode gui`.
2. In **Add Tournament** tab:
   - Choose **Scrape URL** or **Paste Results** at the top.
   - For scrape: enter title, URL, type, and competitors; click **Preview URL** if desired, then **Parse & Preview**.
   - For paste: choose format (or AUTO), paste text, and click **Parse & Preview**.
3. Edit names/regions inside the Treeview if needed (double-click a cell).
4. Click **Save Tournament**.
5. Open the **Leaderboard** tab, click **Refresh**, adjust region filter, and click **Export** for CSV/Excel.

### Total CP Analysis Tab

The **Total CP Analysis** tab allows you to compare total Championship Points from pokedata.ovh (which includes all CP sources: Regionals, ICs, Cups, and Challenges) with your regional tournament data.

#### Features:

- **Load File**: Import HTML files from pokedata.ovh containing total CP data for all players
- **Check Duplicates**: Find and merge similar names within loaded data (e.g., "Dekari I" and "Dekari Iverson")
- **Match Names**: Match pokedata.ovh player names to regional tournament names when they differ (e.g., "Cal Connor" → "Calvin Connor")
- **Clear Data**: Remove all loaded total CP data for the current season
- **Column Sorting**: Click any column header to sort (numeric columns sort by value, name column alphabetically)
- **Comparison Metrics**:
  - **Total CP**: Total CP from pokedata.ovh (includes all sources)
  - **Regional CP**: CP from regional tournaments and ICs (from your tournament data)
  - **Non-Regional CP**: CP from Cups and Challenges (Total CP - Regional CP)
  - **Outstanding CP**: Remaining CP that could be earned from Cups/Challenges (260 - Non-Regional CP, max 260)
  - **Total Potential CP**: Maximum possible CP (Regional CP + 260)

#### Workflow:

1. **Load Data**: Click "Load File" and select a pokedata.ovh HTML file. The parser automatically separates CP from Play Points (PP).
2. **Check Duplicates**: After loading, click "Check Duplicates" to find and merge similar names within the loaded data.
3. **Match Names**: Click "Match Names" to match pokedata.ovh names to regional names. The tool:
   - Shows pokedata name with CP value and country
   - Lists regional names sorted by CP (highest first)
   - Filters out already-matched names
   - Allows country filtering to narrow the list
   - **Only affects Total CP Analysis data, not your tournament data**
4. **View Comparison**: The table shows all players with their CP breakdown. Click column headers to sort.

#### Data Storage:

- Total CP data is stored in `data/<season>/total_cp_data.json`
- Name mappings are stored in `data/<season>/pokedata_name_mappings.json`
- These files are **separate from tournament data** and do not affect the main leaderboard or tournament entries

#### Important Notes:

- The name matching tool **only creates mappings for Total CP Analysis** and does not modify your tournament data or regional leaderboard
- You can load multiple files - data is automatically merged
- The parser correctly handles HTML format and separates CP from Play Points (PP)
- All Total CP Analysis features are isolated from the main tournament tracking functionality

### Moneyball Efficiency (More Charts → Moneyball)

The **Moneyball** sub-tab shows which players extracted the most Championship Points from the smallest fields. It is a view over the normal season aggregate; it does not change the leaderboard or tournament data.

An event's **size tier** is derived from the CP kicker ladder rather than an arbitrary competitor cutoff: an event with N competitors reaches every bracket whose kicker is ≤ N (0, 4, 8, 17, 33, 65, 129, 257, 513, 1,025, 2,049). A finish's **efficiency** is `CP / (size tier + 1)`, and a player's **Moneyball score** is the average efficiency of their top 5 CP-scoring finishes (the same Best Finish Limit used for `TotalCP`). The `+1` prevents division by zero at tier 0.

For example, a 350-CP regional win scores **5.30** at a tier-65 event (65–128 players) but only **0.17** at a tier-2,049 event (2,049+ players), so two players with identical total CP can be an order of magnitude apart in efficiency.

Options in the tab:

- **Region**: `ALL` (default) or a single region group.
- **Min finishes**: minimum number of CP-scoring finishes required to qualify (default **4**).
- **Top X**: how many ranked players to show (default **200**).
- **Include autobid winners**: on by default, since winning a small regional earns an autobid and excluding those players would hide the effect.

The tab shows a scatter plot of Total CP vs. Moneyball score (top 10 labelled) and a sortable table with rank, region, total CP, score, average event tier, smallest field attended, and number of counting finishes. Click any column header to re-sort.

**Exploring a player:** double-click any row to open the same tournament-results window used by the Leaderboard tab. For Moneyball players it adds **Players**, **Kicker tier**, **Efficiency**, and **Top 5** columns, plus a summary of counting finishes and average efficiency — so you can see exactly which small-field events drove the score. The **Find player** box highlights matching rows in the table and rings the matching points in the chart (case-insensitive substring search); the highlight survives column re-sorts.

Programmatic use:

```python
from moneyball import moneyball_leaderboard

df = moneyball_leaderboard(
    "2025-2026",
    region_group="ALL",
    min_counting_finishes=4,
    top_x=200,
    include_autobid=True,
)
print(df.head(10))
```



