import tkinter as tk
import webbrowser
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from tkinter import messagebox, ttk

import matplotlib
import pandas as pd

matplotlib.use("TkAgg")
from datetime import datetime
from tkinter import filedialog

import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from aggregation import aggregate_season, filter_leaderboard_by_region, invalidate_season_caches
from gui.constants import CHART_COLORS, DEFAULT_SEASON, SEASONS
from gui.dialogs import (
    LoadTotalCPFileDialog,
    PlayerManager,
    PlayerResultsViewer,
    PokedataNameMatcher,
    TournamentEditor,
)
from gui.invite_flow_chart import describe_column, draw_invite_flow_sankey
from gui.invite_forecast_chart import (
    describe_player,
    draw_bubble_band,
    draw_player_detail,
    draw_safety_map,
    nearest_player,
)
from invite_forecast import ForecastConfig, ForecastResult, build_forecast, reset_forecast_cache
from logger import logger
from moneyball import (
    DEFAULT_MIN_COUNTING_FINISHES,
    DEFAULT_TOP_X,
    REGION_OPTIONS,
    moneyball_leaderboard,
)
from more_charts import (
    box_plot_rank_buckets,
    events_attended_histogram,
    get_region_leaderboard,
    histogram_cp_data,
)
from parsers import ParsedEntry, detect_format, parse_format_a, parse_format_b
from storage import (
    existing_tournament_key_ids,
    list_tournament_files,
    load_json,
    load_pokedata_name_mappings,
    load_total_cp_data,
    save_tournament,
)
from utils import (
    REGION_DISPLAY_NAMES,
    TournamentKey,
    map_region_to_group,
    normalize_player_name,
)
from worlds_race import (
    WorldsRacePoint,
    get_all_players_for_season,
    get_cutoff_rank_for_region,
    get_invite_flows,
    get_player_worlds_series,
    get_region_cutoff_series,
)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PKMN Top X Checker")
        self.geometry("1000x700")

        self.season_var = tk.StringVar(value=DEFAULT_SEASON)
        self.tournament_type_var = tk.StringVar(value="REGIONAL")

        self.entries: list[ParsedEntry] = []
        self.leaderboard_df: pd.DataFrame | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True)

        self.add_frame = ttk.Frame(notebook)
        self.leaderboard_frame = ttk.Frame(notebook)
        self.tournaments_frame = ttk.Frame(notebook)
        self.total_cp_frame = ttk.Frame(notebook)
        self.worlds_race_frame = ttk.Frame(notebook)
        self.invite_forecast_frame = ttk.Frame(notebook)
        self.more_charts_frame = ttk.Frame(notebook)
        notebook.add(self.add_frame, text="Add Tournament")
        notebook.add(self.leaderboard_frame, text="Leaderboard")
        notebook.add(self.tournaments_frame, text="Tournaments")
        notebook.add(self.total_cp_frame, text="Total CP Analysis")
        notebook.add(self.worlds_race_frame, text="Worlds Race")
        notebook.add(self.invite_forecast_frame, text="Invite Forecast")
        notebook.add(self.more_charts_frame, text="More Charts")

        self._build_add_tab(self.add_frame)
        self._build_leaderboard_tab(self.leaderboard_frame)
        self._build_tournaments_tab(self.tournaments_frame)
        self._build_total_cp_tab(self.total_cp_frame)
        self._build_worlds_race_tab(self.worlds_race_frame)
        self._build_invite_forecast_tab(self.invite_forecast_frame)
        self._build_more_charts_tab(self.more_charts_frame)

    def _season_combobox(self, parent: ttk.Frame) -> ttk.Combobox:
        """Create a season picker bound to the one shared season selection."""
        return ttk.Combobox(
            parent,
            textvariable=self.season_var,
            values=SEASONS,
            width=12,
            state="readonly",
        )

    # --- Add Tournament Tab ---
    def _build_add_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(top, text="Season:").grid(row=0, column=0, sticky="w")
        self._season_combobox(top).grid(row=0, column=1, sticky="w")

        # Paste controls
        paste_frame = ttk.LabelFrame(parent, text="Paste Results")
        paste_frame.pack(fill=tk.BOTH, padx=10, pady=5, expand=True)

        # Title, URL, Date, and Type for paste mode
        paste_meta_frame = ttk.Frame(paste_frame)
        paste_meta_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(paste_meta_frame, text="Tournament Title:").pack(side=tk.LEFT)
        self.paste_title_var = tk.StringVar()
        ttk.Entry(paste_meta_frame, textvariable=self.paste_title_var, width=40).pack(side=tk.LEFT, padx=5)

        paste_url_frame = ttk.Frame(paste_frame)
        paste_url_frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(paste_url_frame, text="URL:").pack(side=tk.LEFT)
        self.paste_url_var = tk.StringVar()
        ttk.Entry(paste_url_frame, textvariable=self.paste_url_var, width=60).pack(side=tk.LEFT, padx=5)
        ttk.Button(paste_url_frame, text="Preview URL", command=self._preview_url).pack(side=tk.LEFT, padx=5)

        paste_date_type_frame = ttk.Frame(paste_frame)
        paste_date_type_frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(paste_date_type_frame, text="Date (YYYY-MM-DD):").pack(side=tk.LEFT)
        self.paste_date_var = tk.StringVar()
        ttk.Entry(paste_date_type_frame, textvariable=self.paste_date_var, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Label(paste_date_type_frame, text="Tournament Type:").pack(side=tk.LEFT, padx=(15, 0))
        ttk.Combobox(
            paste_date_type_frame,
            textvariable=self.tournament_type_var,
            values=["REGIONAL", "IC"],
            width=10,
            state="readonly",
        ).pack(side=tk.LEFT, padx=5)

        self.paste_text = tk.Text(paste_frame, height=8)
        self.paste_text.pack(fill=tk.BOTH, padx=5, pady=5, expand=True)

        controls = ttk.Frame(paste_frame)
        controls.pack(fill=tk.X, padx=5, pady=2)
        ttk.Button(controls, text="Parse & Preview", command=self._parse_and_preview).pack(
            side=tk.LEFT, padx=5
        )

        # Treeview preview with scrollbars
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, padx=10, pady=5, expand=True)
        columns = ("placement", "name", "region")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings")
        for col, text in zip(columns, ["Placement", "Name", "Region"]):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=150)

        # Add scrollbars
        v_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        h_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        # Grid layout for scrollbars
        self.tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # Allow inline edits on double-click
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        # Save button
        bottom = ttk.Frame(parent)
        bottom.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(bottom, text="Save Tournament", command=self._save_tournament).pack(
            side=tk.RIGHT
        )

    def _preview_url(self) -> None:
        url = self.paste_url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please enter a URL.")
            return
        webbrowser.open(url)

    def _parse_and_preview(self) -> None:
        self.entries = []
        self.tree.delete(*self.tree.get_children())

        text = self.paste_text.get("1.0", tk.END)
        fmt = detect_format(text)
        if fmt == "A":
            self.entries = parse_format_a(text)
        else:
            self.entries = parse_format_b(text)

        if not self.entries:
            messagebox.showinfo("No Entries", "No tournament entries were parsed.")
            return

        for e in self.entries:
            self.tree.insert(
                "",
                tk.END,
                values=(e.placement, normalize_player_name(e.raw_name), e.region_code or ""),
            )

    def _on_tree_double_click(self, event) -> None:
        item_id = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not item_id or column not in ("#2", "#3"):
            return
        col_index = int(column.replace("#", "")) - 1
        x, y, width, height = self.tree.bbox(item_id, column)
        value = self.tree.item(item_id, "values")[col_index]

        edit_var = tk.StringVar(value=value)
        entry = ttk.Entry(self.tree, textvariable=edit_var)
        entry.place(x=x, y=y, width=width, height=height)

        def on_focus_out(_event):
            new_values = list(self.tree.item(item_id, "values"))
            new_values[col_index] = edit_var.get()
            self.tree.item(item_id, values=new_values)
            if col_index == 2 and new_values[2].strip():
                self.tree.item(item_id, tags=())
            entry.destroy()

        entry.bind("<FocusOut>", on_focus_out)
        entry.focus_set()

    def _focus_first_missing_region(self) -> None:
        self.tree.tag_configure("missing_region", background="#FFE4E4")
        for item_id in self.tree.get_children():
            self.tree.item(item_id, tags=())
        for item_id in self.tree.get_children():
            vals = self.tree.item(item_id, "values")
            if len(vals) > 2 and not str(vals[2]).strip():
                self.tree.item(item_id, tags=("missing_region",))
                self.tree.selection_set(item_id)
                self.tree.focus(item_id)
                self.tree.see(item_id)
                return

    def _save_tournament(self) -> None:
        season = self.season_var.get().strip() or DEFAULT_SEASON
        t_type = self.tournament_type_var.get().strip().upper() or "REGIONAL"
        title = self.paste_title_var.get().strip()
        if not title:
            messagebox.showwarning("Missing Title", "Please enter a tournament title.")
            return
        url = self.paste_url_var.get().strip()
        tournament_date = self.paste_date_var.get().strip()
        num_comp = len(self.entries)

        if not self.entries:
            messagebox.showwarning(
                "No Entries", "Please Parse & Preview before saving the tournament."
            )
            return

        # Pull latest values from treeview for names/regions
        updated_entries: list[ParsedEntry] = []
        for item_id, entry in zip(self.tree.get_children(), self.entries):
            vals = self.tree.item(item_id, "values")
            name = vals[1]
            region = vals[2].strip() or None
            updated_entries.append(
                ParsedEntry(placement=entry.placement, raw_name=name, region_code=region)
            )

        # Ensure all regions filled
        missing_regions = [e for e in updated_entries if not e.region_code]
        if missing_regions:
            self._focus_first_missing_region()
            messagebox.showerror(
                "Missing Regions",
                "Some entries are missing region codes. Please edit them in the table.",
            )
            return

        # Duplicate detection
        key = TournamentKey(title_norm=title.strip(), url=url or "", season=season)
        existing = existing_tournament_key_ids(season)
        if key.to_id() in existing:
            if not messagebox.askyesno(
                "Overwrite?",
                "A tournament with this title/URL/season already exists. Overwrite?",
            ):
                return

        # Build raw & normalized payloads
        raw_entries = []
        normalized_entries = []
        for e in updated_entries:
            raw_entries.append(
                {
                    "placement": e.placement,
                    "raw_name": e.raw_name,
                    "region_code": e.region_code,
                }
            )
            normalized_entries.append(
                {
                    "placement": e.placement,
                    "normalized_name": normalize_player_name(e.raw_name),
                    "region_code": e.region_code,
                }
            )

        save_tournament(
            season=season,
            title=title,
            url=url,
            tournament_type=t_type,
            num_competitors=num_comp,
            raw_entries=raw_entries,
            normalized_entries=normalized_entries,
            tournament_date=tournament_date,
        )
        invalidate_season_caches(season)
        reset_forecast_cache(season)
        messagebox.showinfo("Saved", "Tournament saved successfully.")

    # --- Leaderboard Tab ---
    def _build_leaderboard_tab(self, parent: ttk.Frame) -> None:
        controls = ttk.Frame(parent)
        controls.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(controls, text="Season:").pack(side=tk.LEFT)
        self._season_combobox(controls).pack(side=tk.LEFT, padx=5)
        ttk.Button(controls, text="Refresh", command=self._refresh_leaderboard).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Label(controls, text="Region:").pack(side=tk.LEFT, padx=(20, 0))
        self.region_filter_var = tk.StringVar(value="NA")
        ttk.Combobox(
            controls,
            textvariable=self.region_filter_var,
            values=["ALL", "NA", "EU", "LA", "MEA", "OC", "OTHER"],
            width=8,
            state="readonly",
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(controls, text="Apply Filter", command=self._apply_region_filter).pack(
            side=tk.LEFT, padx=5
        )
        self.hide_autobid_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="Hide Autobid Players", variable=self.hide_autobid_var, command=self._apply_filters).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Label(controls, text="Events:").pack(side=tk.LEFT, padx=(20, 0))
        self.events_min_var = tk.StringVar()
        events_min_entry = ttk.Entry(controls, textvariable=self.events_min_var, width=5)
        events_min_entry.pack(side=tk.LEFT, padx=2)
        events_min_entry.bind("<KeyRelease>", lambda e: self._apply_filters())
        ttk.Label(controls, text="to").pack(side=tk.LEFT)
        self.events_max_var = tk.StringVar()
        events_max_entry = ttk.Entry(controls, textvariable=self.events_max_var, width=5)
        events_max_entry.pack(side=tk.LEFT, padx=2)
        events_max_entry.bind("<KeyRelease>", lambda e: self._apply_filters())
        ttk.Label(controls, text="Search:").pack(side=tk.LEFT, padx=(20, 0))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(controls, textvariable=self.search_var, width=20)
        search_entry.pack(side=tk.LEFT, padx=5)
        search_entry.bind("<KeyRelease>", lambda e: self._apply_filters())
        ttk.Button(controls, text="Export", command=self._export_leaderboard).pack(
            side=tk.RIGHT
        )

        # Table with scrollbars
        lb_frame = ttk.Frame(parent)
        lb_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.lb_tree = ttk.Treeview(
            lb_frame,
            columns=("Rank", "Name", "RegionCode", "RegionGroup", "TotalCP", "CPFinishesStr"),
            show="headings",
        )
        for col in self.lb_tree["columns"]:
            self.lb_tree.heading(col, text=col)
            self.lb_tree.column(col, width=120)
        lb_v_scrollbar = ttk.Scrollbar(lb_frame, orient=tk.VERTICAL, command=self.lb_tree.yview)
        lb_h_scrollbar = ttk.Scrollbar(lb_frame, orient=tk.HORIZONTAL, command=self.lb_tree.xview)
        self.lb_tree.configure(yscrollcommand=lb_v_scrollbar.set, xscrollcommand=lb_h_scrollbar.set)
        self.lb_tree.grid(row=0, column=0, sticky="nsew")
        lb_v_scrollbar.grid(row=0, column=1, sticky="ns")
        lb_h_scrollbar.grid(row=1, column=0, sticky="ew")
        lb_frame.grid_rowconfigure(0, weight=1)
        lb_frame.grid_columnconfigure(0, weight=1)
        # Double-click to view player details
        self.lb_tree.bind("<Double-1>", self._on_leaderboard_double_click)

    def _refresh_leaderboard(self) -> None:
        season = self.season_var.get().strip() or DEFAULT_SEASON
        df = aggregate_season(season, force=True)
        if df is None or df.empty:
            messagebox.showinfo("No Data", "No tournaments found for this season.")
            self.leaderboard_df = df
            self.lb_tree.delete(*self.lb_tree.get_children())
            return
        self.leaderboard_df = df
        # Apply filters after refresh to show default view
        self._apply_filters()

    def _apply_region_filter(self) -> None:
        self._apply_filters()

    def _apply_filters(self) -> None:
        """Apply region, autobid, events, and search filters."""
        if self.leaderboard_df is None or self.leaderboard_df.empty:
            return
        df_f = self.leaderboard_df.copy()

        # Apply region filter
        region = self.region_filter_var.get().upper()
        df_f = filter_leaderboard_by_region(df_f, region)

        # Apply autobid filter
        if self.hide_autobid_var.get():
            df_f = df_f[~df_f["HasAutobid"]]

        min_str = self.events_min_var.get().strip()
        max_str = self.events_max_var.get().strip()
        if min_str and max_str:
            try:
                if int(min_str) > int(max_str):
                    messagebox.showwarning("Invalid Filter", "Events min cannot exceed max.")
                    return
            except ValueError:
                messagebox.showwarning("Invalid Filter", "Events min and max must be whole numbers.")
                return
        if min_str:
            try:
                df_f = df_f[df_f["NumTournaments"] >= int(min_str)]
            except ValueError:
                messagebox.showwarning("Invalid Filter", "Events min must be a whole number.")
                return
        if max_str:
            try:
                df_f = df_f[df_f["NumTournaments"] <= int(max_str)]
            except ValueError:
                messagebox.showwarning("Invalid Filter", "Events max must be a whole number.")
                return

        # Re-rank based on region, autobid, and events filters (before search)
        region_filter_applied = region != "ALL"
        autobid_filter_applied = self.hide_autobid_var.get()
        events_filter_applied = bool(min_str or max_str)
        should_rerank = region_filter_applied or autobid_filter_applied or events_filter_applied

        if not df_f.empty and should_rerank:
            # Re-sort using the same criteria as the original ranking
            df_f = df_f.sort_values(
                by=["TotalCP", "BestCP", "SecondBestCP", "NumTournaments"],
                ascending=[False, False, False, False],
            ).reset_index(drop=True)
            # Update ranks to reflect the filtered order (1, 2, 3, ...)
            df_f["Rank"] = df_f.index + 1

        # Apply search filter last (doesn't re-rank, just filters the visible list)
        search_term = self.search_var.get().strip()
        if search_term:
            # Case-insensitive search in player names
            df_f = df_f[df_f["Name"].str.contains(search_term, case=False, na=False)]

        self._populate_leaderboard_tree(df_f)

    def _populate_leaderboard_tree(self, df: pd.DataFrame) -> None:
        self.lb_tree.delete(*self.lb_tree.get_children())
        self.player_results_map.clear()
        if df is None or df.empty:
            return
        for _, row in df.iterrows():
            player_name = row["Name"]
            self.lb_tree.insert(
                "",
                tk.END,
                values=(
                    row["Rank"],
                    player_name,
                    row.get("RegionCode", ""),
                    row.get("RegionGroup", ""),
                    row["TotalCP"],
                    row["CPFinishesStr"],
                ),
            )
            # Store tournament results in map for double-click
            self.player_results_map[player_name] = row.get("TournamentResults", [])

    def _on_leaderboard_double_click(self, event) -> None:
        """Show player's tournament results when double-clicked."""
        item_id = self.lb_tree.identify_row(event.y)
        if not item_id:
            return

        # Get player name
        values = self.lb_tree.item(item_id, "values")
        player_name = values[1] if len(values) > 1 else "Unknown"

        # Get tournament results from stored map
        results = self.player_results_map.get(player_name, [])
        if not results:
            # Try to get from dataframe
            if self.leaderboard_df is not None and not self.leaderboard_df.empty:
                player_row = self.leaderboard_df[self.leaderboard_df["Name"] == player_name]
                if not player_row.empty:
                    results = player_row.iloc[0].get("TournamentResults", [])

        PlayerResultsViewer(self, player_name, results)

    def _export_leaderboard(self) -> None:
        if self.leaderboard_df is None or self.leaderboard_df.empty:
            messagebox.showinfo("No Data", "Nothing to export.")
            return
        season = self.season_var.get().strip() or DEFAULT_SEASON
        out_dir = Path("data") / season
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / "leaderboard.csv"
        xlsx_path = out_dir / "leaderboard.xlsx"
        self.leaderboard_df.to_csv(csv_path, index=False)
        self.leaderboard_df.to_excel(xlsx_path, index=False)
        messagebox.showinfo(
            "Exported", f"Exported CSV and Excel to:\n{csv_path}\n{xlsx_path}"
        )

    # --- Tournaments Tab ---
    def _build_tournaments_tab(self, parent: ttk.Frame) -> None:
        controls = ttk.Frame(parent)
        controls.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(controls, text="Season:").pack(side=tk.LEFT)
        self._season_combobox(controls).pack(side=tk.LEFT, padx=5)
        ttk.Button(controls, text="Refresh", command=self._refresh_tournaments_list).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(controls, text="Delete Selected", command=self._delete_selected_tournament).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(controls, text="Manage Players", command=self._open_player_manager).pack(
            side=tk.LEFT, padx=5
        )

        # Tournaments list table
        list_frame = ttk.Frame(parent)
        list_frame.pack(fill=tk.BOTH, padx=10, pady=5, expand=True)
        columns = ("name", "players", "season", "date", "winner")
        self.tournaments_tree = ttk.Treeview(list_frame, columns=columns, show="headings")
        for col, text in zip(columns, ["Tournament Name", "# Players", "Season", "Date", "Winner"]):
            self.tournaments_tree.heading(col, text=text)
            self.tournaments_tree.column(col, width=200)

        # Scrollbars for tournaments list
        t_v_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tournaments_tree.yview)
        t_h_scrollbar = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.tournaments_tree.xview)
        self.tournaments_tree.configure(yscrollcommand=t_v_scrollbar.set, xscrollcommand=t_h_scrollbar.set)

        self.tournaments_tree.grid(row=0, column=0, sticky="nsew")
        t_v_scrollbar.grid(row=0, column=1, sticky="ns")
        t_h_scrollbar.grid(row=1, column=0, sticky="ew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        # Double-click to edit
        self.tournaments_tree.bind("<Double-1>", self._on_tournament_double_click)

        # Store tournament file paths
        self.tournament_paths: dict[str, Path] = {}
        # Store player results for leaderboard double-click
        self.player_results_map: dict[str, list[dict]] = {}

        # Initial load
        self._refresh_tournaments_list()

    def _open_player_manager(self) -> None:
        """Open the player merge/split management window."""
        season = self.season_var.get().strip() or DEFAULT_SEASON
        PlayerManager(self, season)

    def _refresh_tournaments_list(self) -> None:
        season = self.season_var.get().strip() or DEFAULT_SEASON
        self.tournaments_tree.delete(*self.tournaments_tree.get_children())
        self.tournament_paths.clear()

        try:
            files = list_tournament_files(season)
            tournaments_data = []

            for path in files:
                try:
                    data = load_json(path)
                    meta = data.get("metadata", {})
                    title = meta.get("title", "Unknown")
                    num_players = len(data.get("normalized_entries", []))
                    t_season = meta.get("season", season)

                    # Get date for sorting (prefer tournament_date, then added_at, then file mtime)
                    # Use naive datetimes only so we never mix offset-naive and offset-aware
                    date_obj = None
                    tourney_date = meta.get("tournament_date", "").strip()
                    if tourney_date:
                        try:
                            date_obj = datetime.strptime(tourney_date, "%Y-%m-%d")
                        except ValueError:
                            pass
                    if date_obj is None:
                        added_at = meta.get("added_at", "")
                        if added_at:
                            try:
                                date_str = added_at.replace("Z", "+00:00")
                                date_obj = datetime.fromisoformat(date_str)
                                if date_obj.tzinfo:
                                    date_obj = date_obj.replace(tzinfo=None)
                            except Exception:
                                date_obj = datetime.fromtimestamp(path.stat().st_mtime)
                        else:
                            date_obj = datetime.fromtimestamp(path.stat().st_mtime)

                    # Find winner (placement 1)
                    winner = "N/A"
                    for entry in data.get("normalized_entries", []):
                        if int(entry.get("placement", 999)) == 1:
                            winner = entry.get("normalized_name", "N/A")
                            break

                    date_display = tourney_date if tourney_date else date_obj.strftime("%Y-%m-%d") if date_obj else ""
                    tournaments_data.append({
                        "path": path,
                        "title": title,
                        "num_players": num_players,
                        "season": t_season,
                        "winner": winner,
                        "date": date_obj,
                        "date_display": date_display,
                    })
                except Exception as exc:
                    logger.error("Failed to load tournament %s: %s", path, exc)

            # Sort by date (chronologically)
            tournaments_data.sort(key=lambda x: x["date"])

            # Insert into treeview
            for t_data in tournaments_data:
                item_id = self.tournaments_tree.insert(
                    "",
                    tk.END,
                    values=(
                        t_data["title"],
                        t_data["num_players"],
                        t_data["season"],
                        t_data["date_display"],
                        t_data["winner"],
                    ),
                )
                self.tournament_paths[item_id] = t_data["path"]
        except Exception as exc:
            logger.error("Failed to list tournaments: %s", exc)
            messagebox.showerror("Error", f"Failed to load tournaments: {exc}")

    def _on_tournament_double_click(self, event) -> None:
        item_id = self.tournaments_tree.identify_row(event.y)
        if not item_id or item_id not in self.tournament_paths:
            return

        path = self.tournament_paths[item_id]
        TournamentEditor(self, path)

    def _delete_selected_tournament(self) -> None:
        """Delete the selected tournament from the list."""
        selected = self.tournaments_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a tournament to delete.")
            return

        item_id = selected[0]
        if item_id not in self.tournament_paths:
            return

        path = self.tournament_paths[item_id]
        try:
            data = load_json(path)
            title = data.get("metadata", {}).get("title", "Unknown")
        except Exception:
            title = "Unknown"

        if not messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to delete '{title}'?\n\nThis action cannot be undone.",
        ):
            return

        try:
            path.unlink()
            season = self.season_var.get().strip() or DEFAULT_SEASON
            invalidate_season_caches(season)
            reset_forecast_cache(season)
            messagebox.showinfo("Deleted", f"Tournament '{title}' has been deleted.")
            self._refresh_tournaments_list()
        except Exception as exc:
            logger.error("Failed to delete tournament: %s", exc)
            messagebox.showerror("Error", f"Failed to delete tournament: {exc}")

    # --- Total CP Analysis Tab ---
    def _build_total_cp_tab(self, parent: ttk.Frame) -> None:
        """Build the Total CP Analysis tab for comparing pokedata.ovh data with regional CP."""
        controls = ttk.Frame(parent)
        controls.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(controls, text="Season:").pack(side=tk.LEFT)
        self._season_combobox(controls).pack(side=tk.LEFT, padx=5)
        ttk.Button(controls, text="Refresh", command=lambda: self._refresh_total_cp_analysis(force_regional_refresh=True)).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(controls, text="Load File", command=self._open_load_total_cp_file).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(controls, text="Match Names", command=self._match_pokedata_names).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(controls, text="Clear Data", command=self._clear_total_cp_data).pack(
            side=tk.LEFT, padx=5
        )

        # Comparison table
        table_frame = ttk.Frame(parent)
        table_frame.pack(fill=tk.BOTH, padx=10, pady=5, expand=True)

        columns = ("rank", "name", "total_cp", "regional_cp", "non_regional_cp", "outstanding_cp", "total_potential_cp")
        self.total_cp_tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
        )
        for col, text in zip(
            columns,
            ["Rank", "Name", "Total CP", "Regional CP", "Non-Regional CP", "Outstanding CP", "Total Potential CP"],
        ):
            self.total_cp_tree.heading(col, text=text, command=lambda c=col: self._sort_total_cp_tree(c))
            self.total_cp_tree.column(col, width=120)

        # Store sort state
        self.total_cp_sort_column = None
        self.total_cp_sort_reverse = False

        # Scrollbars
        tc_v_scrollbar = ttk.Scrollbar(
            table_frame, orient=tk.VERTICAL, command=self.total_cp_tree.yview
        )
        tc_h_scrollbar = ttk.Scrollbar(
            table_frame, orient=tk.HORIZONTAL, command=self.total_cp_tree.xview
        )
        self.total_cp_tree.configure(
            yscrollcommand=tc_v_scrollbar.set, xscrollcommand=tc_h_scrollbar.set
        )

        self.total_cp_tree.grid(row=0, column=0, sticky="nsew")
        tc_v_scrollbar.grid(row=0, column=1, sticky="ns")
        tc_h_scrollbar.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # Initial load
        self._refresh_total_cp_analysis()

    def _refresh_total_cp_analysis(self, *, force_regional_refresh: bool = False) -> None:
        """Refresh the Total CP Analysis table."""
        season = self.season_var.get().strip() or DEFAULT_SEASON

        # Load total CP data
        total_cp_entries = load_total_cp_data(season)
        if not total_cp_entries:
            self.total_cp_tree.delete(*self.total_cp_tree.get_children())
            return

        # Load name mappings
        name_mappings = load_pokedata_name_mappings(season)

        # Load regional leaderboard
        regional_df = aggregate_season(season, force=force_regional_refresh)
        if regional_df is None or regional_df.empty:
            messagebox.showinfo("No Regional Data", "No regional tournament data found.")
            self.total_cp_tree.delete(*self.total_cp_tree.get_children())
            return

        # Create a map of normalized regional names to TotalCP
        regional_cp_map: dict[str, int] = {}
        for _, row in regional_df.iterrows():
            name = row["Name"]
            total_cp = row["TotalCP"]
            regional_cp_map[normalize_player_name(name)] = total_cp

        # Build comparison data
        self.total_cp_tree.delete(*self.total_cp_tree.get_children())
        comparison_data = []

        for entry_dict in total_cp_entries:
            pokedata_name = entry_dict.get("raw_name", "")
            normalized_pokedata = normalize_player_name(pokedata_name)

            # Try to find matching regional name
            regional_name = name_mappings.get(normalized_pokedata)
            if not regional_name:
                # Try exact match
                if normalized_pokedata in regional_cp_map:
                    regional_name = normalized_pokedata
                else:
                    # No match found - will show in table but with 0 regional CP
                    regional_name = None

            total_cp = entry_dict.get("current_points", 0)
            regional_cp = regional_cp_map.get(regional_name, 0) if regional_name else 0
            non_regional_cp = max(0, total_cp - regional_cp)
            outstanding_cp = max(0, 260 - non_regional_cp)
            total_potential_cp = regional_cp + 260  # Regional CP + max from Cups/Challenges

            comparison_data.append({
                "rank": entry_dict.get("rank", 0),
                "pokedata_name": pokedata_name,
                "regional_name": regional_name or pokedata_name,
                "total_cp": total_cp,
                "regional_cp": regional_cp,
                "non_regional_cp": non_regional_cp,
                "outstanding_cp": outstanding_cp,
                "total_potential_cp": total_potential_cp,
            })

        # Store comparison data for sorting
        self.total_cp_comparison_data = comparison_data

        # Sort by total CP descending (default)
        self._sort_total_cp_data("total_cp", reverse=True)
        self._populate_total_cp_tree()

    def _sort_total_cp_data(self, column: str, reverse: bool = False) -> None:
        """Sort the comparison data by the specified column."""
        if not hasattr(self, 'total_cp_comparison_data'):
            return

        # Map column names to data keys
        column_map = {
            "rank": "rank",
            "name": "regional_name",
            "total_cp": "total_cp",
            "regional_cp": "regional_cp",
            "non_regional_cp": "non_regional_cp",
            "outstanding_cp": "outstanding_cp",
            "total_potential_cp": "total_potential_cp",
        }

        key = column_map.get(column, "total_cp")

        # Sort
        if key == "regional_name":
            # String sort
            self.total_cp_comparison_data.sort(key=lambda x: x[key].lower(), reverse=reverse)
        else:
            # Numeric sort
            self.total_cp_comparison_data.sort(key=lambda x: x[key], reverse=reverse)

    def _populate_total_cp_tree(self) -> None:
        """Populate the treeview with current comparison data."""
        self.total_cp_tree.delete(*self.total_cp_tree.get_children())

        if not hasattr(self, 'total_cp_comparison_data'):
            return

        for i, data in enumerate(self.total_cp_comparison_data, 1):
            self.total_cp_tree.insert(
                "",
                tk.END,
                values=(
                    i,  # Display rank
                    data["regional_name"],
                    data["total_cp"],
                    data["regional_cp"],
                    data["non_regional_cp"],
                    data["outstanding_cp"],
                    data["total_potential_cp"],
                ),
            )

    def _sort_total_cp_tree(self, column: str) -> None:
        """Handle column header click for sorting."""
        # Toggle reverse if clicking same column
        if self.total_cp_sort_column == column:
            self.total_cp_sort_reverse = not self.total_cp_sort_reverse
        else:
            self.total_cp_sort_column = column
            self.total_cp_sort_reverse = False

        # Only sort numeric columns
        numeric_columns = ["rank", "total_cp", "regional_cp", "non_regional_cp", "outstanding_cp", "total_potential_cp"]
        if column in numeric_columns or column == "name":
            self._sort_total_cp_data(column, self.total_cp_sort_reverse)
            self._populate_total_cp_tree()

    def _open_load_total_cp_file(self) -> None:
        """Open file dialog to load pokedata.ovh HTML file."""
        file_path = filedialog.askopenfilename(
            title="Select pokedata.ovh HTML file",
            filetypes=[("HTML files", "*.html *.htm *.txt"), ("All files", "*.*")]
        )
        if file_path:
            LoadTotalCPFileDialog(self, file_path)

    def _clear_total_cp_data(self) -> None:
        """Clear all total CP data for the current season."""
        season = self.season_var.get().strip() or DEFAULT_SEASON
        if not messagebox.askyesno(
            "Confirm Clear",
            f"Are you sure you want to clear all total CP data for season {season}?\n\nThis action cannot be undone.",
        ):
            return

        try:
            # Delete the data file
            data_file = Path("data") / season / "total_cp_data.json"
            if data_file.exists():
                data_file.unlink()

            # Also clear name mappings
            mappings_file = Path("data") / season / "pokedata_name_mappings.json"
            if mappings_file.exists():
                mappings_file.unlink()

            messagebox.showinfo("Cleared", "Total CP data cleared successfully.")
            self._refresh_total_cp_analysis()
        except Exception as exc:
            logger.error("Failed to clear total CP data: %s", exc)
            messagebox.showerror("Error", f"Failed to clear data: {exc}")

    def _match_pokedata_names(self) -> None:
        """Open dialog to match pokedata names with regional names."""
        season = self.season_var.get().strip() or DEFAULT_SEASON
        PokedataNameMatcher(self, season)

    # --- Worlds Race Tab ---
    def _build_worlds_race_tab(self, parent: ttk.Frame) -> None:
        """Build the Worlds Race tab: player selection, region filter, two charts."""
        controls = ttk.Frame(parent)
        controls.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(controls, text="Season:").pack(side=tk.LEFT)
        self._season_combobox(controls).pack(side=tk.LEFT, padx=5)
        ttk.Button(controls, text="Load Players", command=self._worlds_race_load_players).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Label(controls, text="Player:").pack(side=tk.LEFT, padx=(15, 0))
        self.worlds_race_player_var = tk.StringVar()
        self.worlds_race_player_combo = ttk.Combobox(
            controls,
            textvariable=self.worlds_race_player_var,
            width=35,
        )
        self.worlds_race_player_combo.pack(side=tk.LEFT, padx=5)
        self.worlds_race_player_combo.bind("<<ComboboxSelected>>", self._worlds_race_on_player_selected)
        self.worlds_race_player_combo.bind("<KeyRelease>", self._worlds_race_filter_players)
        ttk.Label(controls, text="Region:").pack(side=tk.LEFT, padx=(15, 0))
        region_codes = ["NA", "EU", "LA", "OC", "MEA", "ALL_COMPARE"]
        self.worlds_race_region_var = tk.StringVar(value=REGION_DISPLAY_NAMES.get("NA", "NA"))
        self.worlds_race_region_combo = ttk.Combobox(
            controls,
            textvariable=self.worlds_race_region_var,
            values=[REGION_DISPLAY_NAMES.get(r, r) for r in region_codes],
            width=18,
            state="readonly",
        )
        self.worlds_race_region_combo.pack(side=tk.LEFT, padx=5)
        self.worlds_race_region_combo.bind("<<ComboboxSelected>>", lambda e: self._worlds_race_refresh_charts())
        ttk.Button(controls, text="Update Charts", command=self._worlds_race_update_main_player).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(controls, text="Add Player", command=self._worlds_race_add_player).pack(
            side=tk.LEFT, padx=5
        )

        self.worlds_race_player_list: list[tuple[str, str, str]] = []
        self.worlds_race_selected_name: str | None = None
        self.worlds_race_selected_region_key: str | None = None

        self.worlds_race_status_var = tk.StringVar(value="Select a player and click Update Charts.")
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X, padx=10, pady=2)
        self.worlds_race_status_label = ttk.Label(
            status_frame,
            textvariable=self.worlds_race_status_var,
            wraplength=900,
        )
        self.worlds_race_status_label.pack(anchor="w")

        chart1_frame = ttk.LabelFrame(parent, text="Cumulative CP vs Cutoff CP")
        chart1_frame.pack(fill=tk.BOTH, padx=10, pady=5, expand=True)
        self.worlds_race_fig1 = Figure(figsize=(10, 3.5), dpi=100)
        self.worlds_race_ax1 = self.worlds_race_fig1.add_subplot(111)
        self.worlds_race_canvas1 = FigureCanvasTkAgg(self.worlds_race_fig1, master=chart1_frame)
        self.worlds_race_canvas1.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.worlds_race_toolbar1 = NavigationToolbar2Tk(self.worlds_race_canvas1, chart1_frame)
        self.worlds_race_toolbar1.update()
        # Data containers for chart rendering and hover.
        self.worlds_race_series: list[WorldsRacePoint] = []
        self.worlds_race_player_series_by_name: dict[str, list[WorldsRacePoint]] = {}
        self.worlds_race_cutoff_dates: list = []
        self.worlds_race_cutoff_values: list[int] = []
        self.worlds_race_all_cutoff_series: dict[str, tuple[list, list[int]]] = {}
        self.worlds_race_hover_points: list[dict] = []
        self.worlds_race_region_group_current: str | None = None
        self._worlds_race_load_players()

    def _worlds_race_load_players(self) -> None:
        """Load player list for the season and populate the dropdown."""
        season = self.season_var.get().strip() or DEFAULT_SEASON
        try:
            self.worlds_race_all_cutoff_series.clear()
            self.worlds_race_player_series_by_name.clear()
            self.worlds_race_cutoff_dates = []
            self.worlds_race_cutoff_values = []
            self.worlds_race_hover_points = []
            self.worlds_race_region_group_current = None

            self.worlds_race_player_list = get_all_players_for_season(season)
            displays = [t[0] for t in self.worlds_race_player_list]
            self.worlds_race_player_combo["values"] = displays
            if not displays:
                self.worlds_race_status_var.set("No players found for this season. Add tournaments first.")
        except Exception as exc:
            logger.error("Worlds Race load players: %s", exc)
            self.worlds_race_player_list = []
            self.worlds_race_player_combo["values"] = []
            self.worlds_race_status_var.set(f"Error loading players: {exc}")

    def _worlds_race_filter_players(self, event=None) -> None:
        """Filter dropdown list by typed substring (type-to-search)."""
        typed = self.worlds_race_player_var.get().strip().lower()
        if not typed:
            self.worlds_race_player_combo["values"] = [t[0] for t in self.worlds_race_player_list]
            return
        filtered = [t[0] for t in self.worlds_race_player_list if typed in t[0].lower()]
        self.worlds_race_player_combo["values"] = filtered

    def _worlds_race_on_player_selected(self, event=None) -> None:
        """When user selects a player, set region default and optionally refresh charts."""
        display = self.worlds_race_player_var.get()
        for d, name, region_key in self.worlds_race_player_list:
            if d == display:
                self.worlds_race_selected_name = name
                self.worlds_race_selected_region_key = region_key
                rg = map_region_to_group(region_key)
                display_name = REGION_DISPLAY_NAMES.get(rg, rg)
                self.worlds_race_region_var.set(display_name)
                self.worlds_race_region_combo.set(display_name)
                break
        else:
            self.worlds_race_selected_name = None
            self.worlds_race_selected_region_key = None

    def _worlds_race_update_main_player(self) -> None:
        """Update chart with only the currently selected player."""
        self._worlds_race_refresh_charts(reset_players=True)

    def _worlds_race_add_player(self) -> None:
        """Add the currently selected player as an additional line."""
        self._worlds_race_refresh_charts(reset_players=False)

    def _worlds_race_refresh_charts(self, reset_players: bool = True) -> None:
        """Fetch series for selected player/region and redraw chart."""
        season = self.season_var.get().strip() or DEFAULT_SEASON
        display = self.worlds_race_player_var.get().strip()
        name = self.worlds_race_selected_name
        region_key = self.worlds_race_selected_region_key
        region_display = self.worlds_race_region_var.get().strip()
        region_group = region_display
        for code, label in REGION_DISPLAY_NAMES.items():
            if label == region_display:
                region_group = code
                break
        if region_group not in ("NA", "EU", "LA", "OC", "MEA", "OTHER", "ALL_COMPARE"):
            region_group = "NA"
        # Special mode: compare all regions' cutoffs, no player lines.
        if region_group == "ALL_COMPARE":
            try:
                self.worlds_race_all_cutoff_series.clear()
                for code in ("NA", "EU", "LA", "OC", "MEA"):
                    dates, values = get_region_cutoff_series(season, code)
                    if dates:
                        self.worlds_race_all_cutoff_series[code] = (dates, values)
            except Exception as exc:
                logger.error("Worlds Race all-region series: %s", exc)
                self.worlds_race_status_var.set(f"Error: {exc}")
                self._worlds_race_clear_charts()
                return
            if not self.worlds_race_all_cutoff_series:
                self.worlds_race_status_var.set("No Regional/IC data found for this season.")
                self._worlds_race_clear_charts()
                return
            self.worlds_race_player_series_by_name.clear()
            self.worlds_race_region_group_current = "ALL_COMPARE"
            self._worlds_race_draw_charts(region_group)
            self.worlds_race_status_var.set(
                "Hover a line to see each region's cutoff CP over time."
            )
            return

        # Normal mode: one region, one or more players.
        if not display and reset_players:
            self.worlds_race_status_var.set("Select a player first.")
            self._worlds_race_clear_charts()
            return

        # Resolve player name / region key from current selection if needed.
        if name is None or region_key is None:
            for d, n, rk in self.worlds_race_player_list:
                if d == display:
                    name, region_key = n, rk
                    break

        if name is None or region_key is None:
            self.worlds_race_status_var.set("Select a player from the list first.")
            self._worlds_race_clear_charts()
            return

        # All player lines on the chart must use the same region filter.
        if (
            self.worlds_race_player_series_by_name
            and self.worlds_race_region_group_current
            and region_group != self.worlds_race_region_group_current
        ):
            self.worlds_race_status_var.set(
                "All players on the chart must use the same region. "
                "Click Update Charts to reset to this region."
            )
            return

        try:
            # Region-wide cutoff series: all Regional/IC dates in the season.
            self.worlds_race_cutoff_dates, self.worlds_race_cutoff_values = get_region_cutoff_series(
                season, region_group
            )
            series = get_player_worlds_series(
                season, name, region_key, region_group
            )
        except Exception as exc:
            logger.error("Worlds Race series: %s", exc)
            self.worlds_race_status_var.set(f"Error: {exc}")
            self._worlds_race_clear_charts()
            return

        if not self.worlds_race_cutoff_dates:
            self.worlds_race_status_var.set("No Regional/IC data found for this season.")
            self._worlds_race_clear_charts()
            return

        if reset_players:
            self.worlds_race_player_series_by_name.clear()

        if series:
            self.worlds_race_player_series_by_name[display] = series
        elif not self.worlds_race_player_series_by_name:
            # No data yet for this player or any others.
            self._worlds_race_draw_charts(region_group)
            self.worlds_race_status_var.set(
                "No event data for this player in this season; showing cutoff only."
            )
            return

        self.worlds_race_region_group_current = region_group
        self._worlds_race_draw_charts(region_group)

        # Set status from the most recently updated player's latest point, if any.
        last_series = self.worlds_race_player_series_by_name.get(display)
        if last_series:
            last = last_series[-1]
            self.worlds_race_status_var.set(
                f"Player: {display} | Event: {last.event_name} | Placement: {last.placement} | "
                f"+{last.points_earned_at_event} CP | Rank: {last.regional_rank} | "
                f"Gap to cutoff: {last.gap_to_cutoff:+d}"
            )

    def _worlds_race_clear_charts(self) -> None:
        """Clear chart axis and redraw."""
        self.worlds_race_ax1.clear()
        self.worlds_race_canvas1.draw_idle()

    def _worlds_race_draw_charts(self, region_group: str) -> None:
        """Draw CP vs cutoff chart from region-wide and player series."""
        self.worlds_race_hover_points = []
        self.worlds_race_ax1.clear()

        if region_group == "ALL_COMPARE":
            # Multiple region cutoff lines, no player series.
            for idx, (code, (dates, values)) in enumerate(self.worlds_race_all_cutoff_series.items()):
                if not dates:
                    continue
                label = f"{code} Cutoff"
                self.worlds_race_ax1.plot(
                    dates,
                    values,
                    "--",
                    label=label,
                    color=CHART_COLORS[idx % len(CHART_COLORS)],
                )
                cutoff_rank = get_cutoff_rank_for_region(code)
                for d, cp in zip(dates, values):
                    self.worlds_race_hover_points.append(
                        {
                            "kind": "cutoff",
                            "region_group": code,
                            "cutoff_rank": cutoff_rank,
                            "date": d,
                            "cp": cp,
                            "x": mdates.date2num(d),
                            "y": cp,
                        }
                    )
        else:
            # Single-region cutoff line.
            cutoff_dates = self.worlds_race_cutoff_dates
            cutoff_values = self.worlds_race_cutoff_values
            if cutoff_dates:
                label = f"{region_group} Cutoff"
                self.worlds_race_ax1.plot(
                    cutoff_dates,
                    cutoff_values,
                    "s--",
                    label=label,
                    color=CHART_COLORS[0],
                )
                cutoff_rank = get_cutoff_rank_for_region(region_group)
                for d, cp in zip(cutoff_dates, cutoff_values):
                    self.worlds_race_hover_points.append(
                        {
                            "kind": "cutoff",
                            "region_group": region_group,
                            "cutoff_rank": cutoff_rank,
                            "date": d,
                            "cp": cp,
                            "x": mdates.date2num(d),
                            "y": cp,
                        }
                    )

            # One or more player series for this region.
            for idx, (p_display, series) in enumerate(self.worlds_race_player_series_by_name.items()):
                if not series:
                    continue
                dates = [p.date for p in series]
                cum_cp = [p.cumulative_cp for p in series]
                color = CHART_COLORS[(idx + 1) % len(CHART_COLORS)]
                self.worlds_race_ax1.plot(
                    dates,
                    cum_cp,
                    "o-",
                    label=p_display,
                    color=color,
                )
                for p in series:
                    self.worlds_race_hover_points.append(
                        {
                            "kind": "player",
                            "player_display": p_display,
                            "date": p.date,
                            "cp": p.cumulative_cp,
                            "event": p.event_name,
                            "placement": p.placement,
                            "points_earned": p.points_earned_at_event,
                            "regional_rank": p.regional_rank,
                            "gap": p.gap_to_cutoff,
                            "x": mdates.date2num(p.date),
                            "y": p.cumulative_cp,
                        }
                    )

        self.worlds_race_ax1.set_xlabel("Date")
        self.worlds_race_ax1.set_ylabel("Cumulative CP")
        self.worlds_race_ax1.set_title("Your CP vs Cutoff CP (majors only)" if region_group != "ALL_COMPARE" else "Regional Cutoff CP Comparison")
        self.worlds_race_ax1.legend()
        self.worlds_race_ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        self.worlds_race_ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
        self.worlds_race_fig1.autofmt_xdate()
        self.worlds_race_ax1.grid(True, alpha=0.3)

        self.worlds_race_canvas1.draw_idle()

        if self.worlds_race_hover_points:
            self._worlds_race_connect_hover()

    def _worlds_race_connect_hover(self) -> None:
        """Connect hover on chart 1 to update status line with nearest point."""
        def on_motion(event):
            if not event.inaxes or not self.worlds_race_hover_points:
                return
            ax = self.worlds_race_canvas1.figure.axes[0]
            if event.inaxes != ax:
                return
            try:
                x, y = event.xdata, event.ydata
                if x is None or y is None:
                    return
                # Find nearest hover point in (date, CP) space.
                def dist2(pt):
                    return abs(pt["x"] - x) + 0.001 * abs(pt["y"] - y)

                nearest = min(self.worlds_race_hover_points, key=dist2)

                if nearest["kind"] == "player":
                    self.worlds_race_status_var.set(
                        f"Player: {nearest['player_display']} | Event: {nearest['event']} | "
                        f"Placement: {nearest['placement']} | +{nearest['points_earned']} CP | "
                        f"Rank: {nearest['regional_rank']} | Gap to cutoff: {nearest['gap']:+d}"
                    )
                else:
                    region_code = nearest["region_group"]
                    region_label = REGION_DISPLAY_NAMES.get(region_code, region_code)
                    date_str = nearest["date"].strftime("%Y-%m-%d")
                    self.worlds_race_status_var.set(
                        f"Date: {date_str} | {region_label} cutoff CP (rank {nearest['cutoff_rank']}): "
                        f"{nearest['cp']}"
                    )
            except (IndexError, TypeError):
                pass
        self.worlds_race_canvas1.mpl_connect("motion_notify_event", on_motion)

    # --- Invite Forecast Tab ---
    def _build_invite_forecast_tab(self, parent: ttk.Frame) -> None:
        """Build the forward-looking invite forecast tab with three linked views."""
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(top, text="Season:").pack(side=tk.LEFT)
        self._season_combobox(top).pack(side=tk.LEFT, padx=5)
        ttk.Label(top, text="Region:").pack(side=tk.LEFT, padx=(15, 0))
        self.forecast_region_var = tk.StringVar(value="NA")
        ttk.Combobox(
            top,
            textvariable=self.forecast_region_var,
            values=["NA", "EU", "LA", "OC", "MEA"],
            width=8,
            state="readonly",
        ).pack(side=tk.LEFT, padx=5)
        self.forecast_run_button = ttk.Button(top, text="Run forecast", command=self._forecast_run)
        self.forecast_run_button.pack(side=tk.LEFT, padx=5)

        options = ttk.Frame(parent)
        options.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(options, text="As of (blank = latest):").pack(side=tk.LEFT)
        self.forecast_as_of_var = tk.StringVar(value="")
        ttk.Entry(options, textvariable=self.forecast_as_of_var, width=14).pack(side=tk.LEFT, padx=(2, 12))
        ttk.Label(options, text="Cutoff scenario:").pack(side=tk.LEFT)
        self.forecast_scenario_var = tk.StringVar(value="Baseline")
        ttk.Combobox(
            options,
            textvariable=self.forecast_scenario_var,
            values=["Low", "Baseline", "High"],
            width=10,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(2, 12))
        ttk.Label(options, text="Ceiling tiers/event:").pack(side=tk.LEFT)
        self.forecast_ceiling_gain_var = tk.StringVar(value="1.0")
        ttk.Entry(options, textvariable=self.forecast_ceiling_gain_var, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(options, text="Sims:").pack(side=tk.LEFT, padx=(12, 0))
        self.forecast_sims_var = tk.StringVar(value="500")
        ttk.Entry(options, textvariable=self.forecast_sims_var, width=7).pack(side=tk.LEFT, padx=2)
        self.forecast_show_ceiling_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options,
            text="Show ceiling upside (not expected)",
            variable=self.forecast_show_ceiling_var,
        ).pack(side=tk.LEFT, padx=(12, 0))
        self.forecast_include_cup_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options,
            text="Include Cup/Challenge +260 (deprecated, stale data)",
            variable=self.forecast_include_cup_var,
        ).pack(side=tk.LEFT, padx=(12, 0))

        selection = ttk.Frame(parent)
        selection.pack(fill=tk.X, padx=10, pady=2)
        self.forecast_selected_var = tk.StringVar(value="No player selected — click a dot or name")
        ttk.Label(selection, textvariable=self.forecast_selected_var, width=44, anchor="w").pack(
            side=tk.LEFT
        )
        ttk.Label(selection, text="Find players:").pack(side=tk.LEFT, padx=(10, 0))
        self.forecast_search_var = tk.StringVar(value="")
        search_entry = ttk.Entry(selection, textvariable=self.forecast_search_var, width=36)
        search_entry.pack(side=tk.LEFT, padx=2)
        search_entry.bind("<KeyRelease>", self._forecast_on_search_changed)
        search_entry.bind("<Return>", self._forecast_apply_search)
        ttk.Button(selection, text="Search", command=self._forecast_apply_search).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(selection, text="Clear", command=self._forecast_clear_search).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Label(selection, text="(comma-separated; Search/Enter applies now, auto after 1s)").pack(
            side=tk.LEFT, padx=(6, 0)
        )

        self.forecast_status_var = tk.StringVar(
            value="Click 'Run forecast'. Estimates are calibrated from last season — directional, not exact."
        )
        ttk.Label(parent, textvariable=self.forecast_status_var, wraplength=950).pack(
            fill=tk.X, padx=10, pady=4
        )

        self.forecast_result: ForecastResult | None = None
        self.forecast_selected_key: tuple[str, str] | None = None
        self.forecast_projection_ids: dict[str, tuple[str, str]] = {}
        self.forecast_table_result: ForecastResult | None = None
        self.forecast_table_updating = False
        self.forecast_running = False
        self.forecast_search_after_id: str | None = None
        self.forecast_queue: Queue[tuple[ForecastResult | None, Exception | None]] = Queue()

        inner = ttk.Notebook(parent)
        inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        map_frame = ttk.Frame(inner)
        inner.add(map_frame, text="Safety Map")
        self.forecast_map_fig = Figure(figsize=(10, 5), dpi=100)
        self.forecast_map_ax = self.forecast_map_fig.add_subplot(111)
        self.forecast_map_canvas = FigureCanvasTkAgg(self.forecast_map_fig, master=map_frame)
        NavigationToolbar2Tk(self.forecast_map_canvas, map_frame).pack()
        self.forecast_map_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.forecast_map_canvas.mpl_connect(
            "motion_notify_event", lambda event: self._forecast_on_pick(event, "map")
        )
        self.forecast_map_canvas.mpl_connect(
            "button_press_event", lambda event: self._forecast_on_pick(event, "map", select=True)
        )

        band_frame = ttk.Frame(inner)
        inner.add(band_frame, text="Bubble Band")
        self.forecast_band_fig = Figure(figsize=(10, 10), dpi=100)
        self.forecast_band_ax = self.forecast_band_fig.add_subplot(111)
        self.forecast_band_canvas = FigureCanvasTkAgg(self.forecast_band_fig, master=band_frame)
        NavigationToolbar2Tk(self.forecast_band_canvas, band_frame).pack()
        self.forecast_band_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.forecast_band_canvas.mpl_connect(
            "motion_notify_event", lambda event: self._forecast_on_pick(event, "band")
        )
        self.forecast_band_canvas.mpl_connect(
            "button_press_event", lambda event: self._forecast_on_pick(event, "band", select=True)
        )

        detail_frame = ttk.Frame(inner)
        inner.add(detail_frame, text="Player Detail")
        self.forecast_detail_fig = Figure(figsize=(9, 5), dpi=100)
        self.forecast_detail_ax = self.forecast_detail_fig.add_subplot(111)
        self.forecast_detail_canvas = FigureCanvasTkAgg(self.forecast_detail_fig, master=detail_frame)
        NavigationToolbar2Tk(self.forecast_detail_canvas, detail_frame).pack()

        projection_frame = ttk.Frame(detail_frame)
        projection_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=5, pady=5)
        columns = (
            "Rank",
            "Player",
            "Reg now/prior",
            "Reg exp (rem)",
            "IC now/prior",
            "IC exp (rem)",
            "Total rem",
            "Basis",
        )
        self.forecast_projection_tree = ttk.Treeview(
            projection_frame, columns=columns, show="headings", height=8
        )
        widths = (45, 180, 95, 95, 85, 85, 75, 250)
        for col, width in zip(columns, widths, strict=True):
            self.forecast_projection_tree.heading(col, text=col)
            self.forecast_projection_tree.column(col, width=width, anchor=tk.W)
        self.forecast_projection_tree.tag_configure("search", background="#FFF2CC")
        projection_scroll = ttk.Scrollbar(
            projection_frame, orient=tk.VERTICAL, command=self.forecast_projection_tree.yview
        )
        self.forecast_projection_tree.configure(yscrollcommand=projection_scroll.set)
        self.forecast_projection_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        projection_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.forecast_projection_tree.bind("<<TreeviewSelect>>", self._forecast_on_projection_select)

        self.forecast_detail_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _forecast_build_config(self) -> ForecastConfig:
        """Parse the forecast controls into a ForecastConfig."""
        as_of_text = self.forecast_as_of_var.get().strip()
        as_of = None
        if as_of_text:
            as_of = datetime.strptime(as_of_text, "%Y-%m-%d").date()
        try:
            ceiling_gain = float(self.forecast_ceiling_gain_var.get().strip() or "1.0")
            simulations = int(self.forecast_sims_var.get().strip() or "500")
        except ValueError as exc:
            raise ValueError("Ceiling tiers/event and Sims must be numbers.") from exc
        if ceiling_gain < 0 or simulations < 50:
            raise ValueError("Ceiling tiers/event must be >= 0 and Sims must be >= 50.")
        return ForecastConfig(
            as_of=as_of,
            include_cup_challenge=self.forecast_include_cup_var.get(),
            scenario=self.forecast_scenario_var.get().strip() or "Baseline",
            ceiling_tiers_per_event=ceiling_gain,
            show_ceiling=self.forecast_show_ceiling_var.get(),
            simulations=simulations,
        )

    def _forecast_run(self) -> None:
        """Start the forecast in a worker so the Tk window stays responsive."""
        if self.forecast_running:
            return
        try:
            config = self._forecast_build_config()
        except ValueError as exc:
            messagebox.showerror("Invalid forecast settings", str(exc))
            return
        season = self.season_var.get().strip() or DEFAULT_SEASON
        region = self.forecast_region_var.get().strip().upper() or "NA"

        while not self.forecast_queue.empty():
            self.forecast_queue.get_nowait()
        self.forecast_running = True
        self.forecast_run_button.configure(text="Running...", state=tk.DISABLED)
        self.forecast_status_var.set(
            f"Computing forecast for {region} ({season}) — the window stays usable..."
        )
        self.update_idletasks()

        def worker() -> None:
            try:
                reset_forecast_cache(season)
                forecast = build_forecast(season, region, config)
                self.forecast_queue.put((forecast, None))
            except Exception as exc:  # noqa: BLE001 - surfaced in the GUI below
                logger.error("Forecast failed: %s", exc)
                self.forecast_queue.put((None, exc))

        Thread(target=worker, name="invite-forecast", daemon=True).start()
        self.after(50, self._forecast_poll_queue)

    def _forecast_poll_queue(self) -> None:
        """Move worker results back onto Tk's main thread."""
        try:
            result, error = self.forecast_queue.get_nowait()
        except Empty:
            if self.forecast_running:
                self.after(50, self._forecast_poll_queue)
            return
        self._forecast_finish(result, error)

    def _forecast_finish(
        self, result: ForecastResult | None, error: Exception | None
    ) -> None:
        """Apply a completed forecast from the main thread only."""
        self.forecast_running = False
        self.forecast_run_button.configure(text="Run forecast", state=tk.NORMAL)
        if error is not None:
            self.forecast_status_var.set(f"Forecast failed: {error}")
            return
        if result is None:
            self.forecast_status_var.set("Forecast returned no result.")
            return

        self.forecast_result = result
        self.forecast_selected_key = result.players[0].key if result.players else None
        try:
            self._forecast_redraw()
        except Exception as exc:  # noqa: BLE001 - never kill the app on a draw error
            logger.error("Forecast redraw failed: %s", exc)
            self.forecast_status_var.set(f"Forecast computed, but display failed: {exc}")
            return

        projected_median = (
            result.players[0].projected_cutoff_p50 if result.players else result.cutoff_cp
        )
        summary = (
            f"{len(result.players)} players | as of {result.as_of:%Y-%m-%d} | "
            f"cutoff now {result.cutoff_cp} -> projected median {projected_median} | "
            "calibrated directional estimates, not exact odds"
        )
        if result.warnings:
            summary += " | " + " ".join(result.warnings)
        self.forecast_status_var.set(summary)

    def _forecast_search_players(self) -> set[tuple[str, str]]:
        """Return keys of players matching the comma-separated search box."""
        result = self.forecast_result
        if result is None:
            return set()
        terms = [
            term.strip().casefold()
            for term in self.forecast_search_var.get().replace(";", ",").split(",")
            if term.strip()
        ]
        if not terms:
            return set()
        return {
            player.key
            for player in result.players
            if any(term in player.name.casefold() for term in terms)
        }

    def _forecast_on_search_changed(self, _event=None) -> None:
        """Debounce search redraws so typing several names stays responsive."""
        if self.forecast_search_after_id is not None:
            self.after_cancel(self.forecast_search_after_id)
        self.forecast_search_after_id = self.after(1000, self._forecast_apply_search)

    def _forecast_apply_search(self, _event=None) -> None:
        """Redraw highlights for the current search text."""
        if self.forecast_search_after_id is not None:
            self.after_cancel(self.forecast_search_after_id)
            self.forecast_search_after_id = None
        self._forecast_redraw()
        result = self.forecast_result
        matches = self._forecast_search_players()
        if result is not None and matches:
            names = [player.name for player in result.players if player.key in matches]
            self.forecast_status_var.set(f"{len(matches)} search matches: " + ", ".join(names))
        elif result is not None and self.forecast_search_var.get().strip():
            self.forecast_status_var.set("No players match the search.")

    def _forecast_clear_search(self) -> None:
        if self.forecast_search_after_id is not None:
            self.after_cancel(self.forecast_search_after_id)
            self.forecast_search_after_id = None
        self.forecast_search_var.set("")
        self._forecast_apply_search()

    def _forecast_redraw(self) -> None:
        result = self.forecast_result
        if result is None:
            return
        search_keys = self._forecast_search_players()
        draw_safety_map(self.forecast_map_ax, result, self.forecast_selected_key, search_keys)
        self.forecast_map_canvas.draw_idle()
        draw_bubble_band(self.forecast_band_ax, result, self.forecast_selected_key, search_keys)
        self.forecast_band_canvas.draw_idle()
        self._forecast_populate_projection_table(result, search_keys)
        selected = result.player_by_key(self.forecast_selected_key) if self.forecast_selected_key else None
        if selected is not None:
            draw_player_detail(self.forecast_detail_ax, result, selected)
            self.forecast_selected_var.set(describe_player(selected))
        else:
            self.forecast_detail_ax.clear()
            self.forecast_detail_ax.set_axis_off()
            self.forecast_selected_var.set("No player selected — click a dot or name")
        self.forecast_detail_canvas.draw_idle()

    def _forecast_populate_projection_table(
        self, result: ForecastResult, search_keys: set[tuple[str, str]]
    ) -> None:
        tree = self.forecast_projection_tree
        if self.forecast_table_result is result and len(tree.get_children()) == len(result.players):
            self.forecast_table_updating = True
            try:
                for player in result.players:
                    item_id = f"{player.key[0]}|{player.key[1]}"
                    tree.item(item_id, tags=("search",) if player.key in search_keys else ())
                # Do not call selection_set here: Tk queues <<TreeviewSelect>>
                # and that would trigger another redraw in an endless loop.
            finally:
                self.forecast_table_updating = False
            return

        self.forecast_table_updating = True
        try:
            for item in tree.get_children():
                tree.delete(item)
            self.forecast_projection_ids.clear()
            for player in result.players:
                item_id = f"{player.key[0]}|{player.key[1]}"
                self.forecast_projection_ids[item_id] = player.key
                tags = ("search",) if player.key in search_keys else ()
                tree.insert(
                    "",
                    tk.END,
                    iid=item_id,
                    tags=tags,
                    values=(
                        player.rank,
                        player.name,
                        f"{player.current_regionals} / {player.prior_regionals}",
                        f"{player.expected_regionals} ({player.remaining_regionals})",
                        f"{player.current_ics} / {player.prior_ics}",
                        f"{player.expected_ics} ({player.remaining_ics})",
                        player.events_remaining,
                        player.attendance_basis,
                    ),
                )
            self.forecast_table_result = result
        finally:
            self.forecast_table_updating = False

    def _forecast_on_projection_select(self, _event=None) -> None:
        """Selecting a projection row updates the player detail across views."""
        if self.forecast_table_updating:
            return
        selected = self.forecast_projection_tree.selection()
        if not selected:
            return
        key = self.forecast_projection_ids.get(selected[0])
        if key is None:
            return
        self.forecast_selected_key = key
        self._forecast_redraw()

    def _forecast_on_pick(self, event, view: str, *, select: bool = False) -> None:
        """Hover updates the status line; click selects a player across all views."""
        result = self.forecast_result
        if result is None or not event.inaxes or event.xdata is None or event.ydata is None:
            return
        ax = self.forecast_map_ax if view == "map" else self.forecast_band_ax
        player = nearest_player(
            ax,
            result,
            event.xdata,
            event.ydata,
            view=view,
            selected_key=self.forecast_selected_key,
            search_keys=self._forecast_search_players(),
        )
        if player is None:
            return
        if select:
            self.forecast_selected_key = player.key
            self._forecast_redraw()
        else:
            self.forecast_status_var.set(describe_player(player))

    # --- More Charts Tab ---
    def _build_more_charts_tab(self, parent: ttk.Frame) -> None:
        """Tab-of-tabs with the CP race, events attended, Moneyball and invite flow."""
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(top, text="Season:").pack(side=tk.LEFT)
        self._season_combobox(top).pack(side=tk.LEFT, padx=5)
        ttk.Label(top, text="Region:").pack(side=tk.LEFT, padx=(15, 0))
        self.more_charts_region_var = tk.StringVar(value="NA")
        region_codes = ["NA", "EU", "LA", "OC", "MEA"]
        mc_region_combo = ttk.Combobox(
            top,
            textvariable=self.more_charts_region_var,
            values=region_codes,
            width=8,
            state="readonly",
        )
        mc_region_combo.pack(side=tk.LEFT, padx=5)
        ttk.Button(top, text="Refresh All", command=self._more_charts_refresh_all).pack(side=tk.LEFT, padx=5)

        self.more_charts_data: dict = {}
        inner = ttk.Notebook(parent)
        inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Sub-tab: Top 135 race (histogram + box)
        race_frame = ttk.Frame(inner)
        inner.add(race_frame, text="Top 135 race")
        self._build_more_charts_race_tab(race_frame)

        # Sub-tab: Events attended
        ev_frame = ttk.Frame(inner)
        inner.add(ev_frame, text="Events attended")
        self._build_more_charts_events_tab(ev_frame)

        # Sub-tab: Moneyball efficiency (smallest fields, best CP haul)
        money_frame = ttk.Frame(inner)
        inner.add(money_frame, text="Moneyball")
        self._build_more_charts_moneyball_tab(money_frame)

        # Sub-tab: Worlds invite-flow Sankey (kept / entered / autobids per date)
        invite_frame = ttk.Frame(inner)
        inner.add(invite_frame, text="Invite flow")
        self._build_more_charts_invite_flow_tab(invite_frame)

    def _more_charts_refresh_all(self) -> None:
        """Load region leaderboard and refresh all More Charts figures."""
        # Invite flows use the tournament snapshots directly, so they render
        # even when the aggregate-based charts have nothing to show.
        self._more_charts_draw_invite_flow()
        season = self.season_var.get().strip() or DEFAULT_SEASON
        region = self.more_charts_region_var.get().strip().upper() or "NA"
        try:
            df, cutoff_rank, cutoff_cp = get_region_leaderboard(
                season, region, exclude_autobid=True, force_aggregate=True
            )
            self.more_charts_data["df"] = df
            self.more_charts_data["cutoff_rank"] = cutoff_rank
            self.more_charts_data["cutoff_cp"] = cutoff_cp
            self.more_charts_data["region"] = region
        except Exception as exc:
            logger.error("More Charts load: %s", exc)
            self.more_charts_data = {}
            messagebox.showerror("Error", str(exc))
            return
        self._more_charts_draw_race()
        self._more_charts_draw_events()
        self._more_charts_draw_moneyball()

    def _build_more_charts_race_tab(self, parent: ttk.Frame) -> None:
        """Histogram and box plot for Top 135 race."""
        sub = ttk.Notebook(parent)
        sub.pack(fill=tk.BOTH, expand=True)
        hist_frame = ttk.Frame(sub)
        sub.add(hist_frame, text="CP histogram")
        hist_opts = ttk.Frame(hist_frame)
        hist_opts.pack(fill=tk.X, padx=5, pady=4)
        ttk.Label(hist_opts, text="Top N players:").pack(side=tk.LEFT, padx=(0, 4))
        self.mc_hist_top_n_var = tk.StringVar(value="1000")
        ttk.Entry(hist_opts, textvariable=self.mc_hist_top_n_var, width=8).pack(side=tk.LEFT, padx=2)
        self.mc_hist_log_y_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            hist_opts,
            text="Logarithmic Y axis",
            variable=self.mc_hist_log_y_var,
            command=self._more_charts_draw_hist_only,
        ).pack(side=tk.LEFT, padx=10)
        ttk.Button(hist_opts, text="Redraw histogram", command=self._more_charts_draw_hist_only).pack(side=tk.LEFT, padx=5)
        self.mc_hist_fig = Figure(figsize=(8, 4), dpi=100)
        self.mc_hist_ax = self.mc_hist_fig.add_subplot(111)
        self.mc_hist_canvas = FigureCanvasTkAgg(self.mc_hist_fig, master=hist_frame)
        self.mc_hist_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        box_frame = ttk.Frame(sub)
        sub.add(box_frame, text="CP by rank bucket (box)")
        self.mc_box_fig = Figure(figsize=(8, 4), dpi=100)
        self.mc_box_ax = self.mc_box_fig.add_subplot(111)
        self.mc_box_canvas = FigureCanvasTkAgg(self.mc_box_fig, master=box_frame)
        self.mc_box_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _more_charts_draw_hist_only(self) -> None:
        """Redraw CP histogram (top N + log Y from UI)."""
        df = self.more_charts_data.get("df")
        cutoff_cp = self.more_charts_data.get("cutoff_cp")
        cutoff_rank = self.more_charts_data.get("cutoff_rank")
        region = self.more_charts_data.get("region", "NA")
        self.mc_hist_ax.clear()
        self.mc_hist_ax.set_yscale("linear")
        top_n = 1000
        try:
            top_n = max(1, int(self.mc_hist_top_n_var.get().strip() or "1000"))
        except ValueError:
            top_n = 1000
        if df is not None and not df.empty:
            centers, counts, _ = histogram_cp_data(df, cutoff_cp, bin_width=50, top_n=top_n)
            if centers and counts:
                self.mc_hist_ax.bar(centers, counts, width=45, color=CHART_COLORS[1], edgecolor="white")
            if cutoff_cp is not None:
                self.mc_hist_ax.axvline(
                    x=cutoff_cp,
                    color=CHART_COLORS[5],
                    linestyle="--",
                    linewidth=2,
                    label=f"Cutoff (rank {cutoff_rank})",
                )
        if self.mc_hist_log_y_var.get():
            # Symlog handles zero counts; pure log cannot show 0-height bars.
            self.mc_hist_ax.set_yscale("symlog", linthresh=1.0)
        self.mc_hist_ax.set_xlabel("Total CP")
        self.mc_hist_ax.set_ylabel("Number of players")
        self.mc_hist_ax.set_title(
            f"Distribution of CP ({region}) — top {top_n} by rank, cutoff rank {cutoff_rank}"
        )
        self.mc_hist_ax.legend()
        self.mc_hist_ax.grid(True, alpha=0.3)
        self.mc_hist_canvas.draw_idle()

    def _more_charts_draw_box_only(self) -> None:
        """Redraw rank-bucket box plot with value labels."""
        df = self.more_charts_data.get("df")
        cutoff_rank = self.more_charts_data.get("cutoff_rank")
        region = self.more_charts_data.get("region", "NA")
        self.mc_box_ax.clear()
        if df is not None and not df.empty:
            labels, data = box_plot_rank_buckets(df, cutoff_rank)
            if labels and data:
                bp = self.mc_box_ax.boxplot(data, tick_labels=labels, patch_artist=True)
                for i, patch in enumerate(bp["boxes"]):
                    patch.set_facecolor(CHART_COLORS[i % len(CHART_COLORS)])
                # Annotate median and whisker ends (matplotlib PathPatch uses set_facecolor).
                for i in range(len(data)):
                    if not data[i]:
                        continue
                    x = i + 1
                    med = float(bp["medians"][i].get_ydata()[0])
                    wlo = bp["whiskers"][2 * i].get_ydata()
                    whi = bp["whiskers"][2 * i + 1].get_ydata()
                    lo_end = float(min(wlo))
                    hi_end = float(max(whi))
                    offset = 0.22
                    self.mc_box_ax.text(
                        x + offset,
                        med,
                        f"med {med:.0f}",
                        fontsize=8,
                        va="center",
                        ha="left",
                    )
                    self.mc_box_ax.text(
                        x + offset,
                        hi_end,
                        f"hi {hi_end:.0f}",
                        fontsize=8,
                        va="bottom",
                        ha="left",
                    )
                    self.mc_box_ax.text(
                        x + offset,
                        lo_end,
                        f"lo {lo_end:.0f}",
                        fontsize=8,
                        va="top",
                        ha="left",
                    )
        self.mc_box_ax.set_xlabel("Rank bucket")
        self.mc_box_ax.set_ylabel("Total CP")
        self.mc_box_ax.set_title(f"CP by rank bucket ({region})")
        self.mc_box_ax.grid(True, alpha=0.3, axis="y")
        self.mc_box_fig.tight_layout()
        self.mc_box_canvas.draw_idle()

    def _more_charts_draw_race(self) -> None:
        self._more_charts_draw_hist_only()
        self._more_charts_draw_box_only()

    def _build_more_charts_events_tab(self, parent: ttk.Frame) -> None:
        """Histogram of events attended (1, 2, ..., 10+)."""
        opts = ttk.Frame(parent)
        opts.pack(fill=tk.X, padx=5, pady=5)
        self.mc_events_log_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts,
            text="Logarithmic Y axis",
            variable=self.mc_events_log_var,
            command=self._more_charts_draw_events,
        ).pack(side=tk.LEFT, padx=5)
        self.mc_events_fig = Figure(figsize=(8, 4), dpi=100)
        self.mc_events_ax = self.mc_events_fig.add_subplot(111)
        self.mc_events_canvas = FigureCanvasTkAgg(self.mc_events_fig, master=parent)
        self.mc_events_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _more_charts_draw_events(self) -> None:
        df = self.more_charts_data.get("df")
        region = self.more_charts_data.get("region", "NA")
        self.mc_events_ax.clear()
        self.mc_events_ax.set_yscale("linear")
        if df is not None and not df.empty:
            counts, labels = events_attended_histogram(df, cap_at=10)
            if counts and labels:
                x = list(range(len(labels)))
                self.mc_events_ax.bar(x, counts, color=CHART_COLORS[2], edgecolor="white")
                self.mc_events_ax.set_xticks(x)
                self.mc_events_ax.set_xticklabels(labels)
                if self.mc_events_log_var.get():
                    self.mc_events_ax.set_yscale("symlog", linthresh=1.0)
        self.mc_events_ax.set_xlabel("Number of events attended")
        self.mc_events_ax.set_ylabel("Number of players")
        self.mc_events_ax.set_title(f"Events attended ({region})" if (df is not None and not df.empty) else f"Events attended ({region}) — click Refresh All")
        self.mc_events_ax.grid(True, alpha=0.3, axis="y")
        self.mc_events_canvas.draw_idle()

    # --- Moneyball Tab ---
    def _build_more_charts_moneyball_tab(self, parent: ttk.Frame) -> None:
        """Efficiency of top-5 CP finishes at the smallest fields."""
        opts = ttk.Frame(parent)
        opts.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(opts, text="Region:").pack(side=tk.LEFT, padx=(0, 4))
        self.mc_money_region_var = tk.StringVar(value="ALL")
        ttk.Combobox(
            opts,
            textvariable=self.mc_money_region_var,
            values=list(REGION_OPTIONS),
            width=7,
            state="readonly",
        ).pack(side=tk.LEFT, padx=2)

        ttk.Label(opts, text="Min finishes:").pack(side=tk.LEFT, padx=(14, 4))
        self.mc_money_min_var = tk.StringVar(value=str(DEFAULT_MIN_COUNTING_FINISHES))
        ttk.Entry(opts, textvariable=self.mc_money_min_var, width=5).pack(side=tk.LEFT, padx=2)

        ttk.Label(opts, text="Top X:").pack(side=tk.LEFT, padx=(14, 4))
        self.mc_money_top_var = tk.StringVar(value=str(DEFAULT_TOP_X))
        ttk.Entry(opts, textvariable=self.mc_money_top_var, width=6).pack(side=tk.LEFT, padx=2)

        self.mc_money_autobid_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opts,
            text="Include autobid winners",
            variable=self.mc_money_autobid_var,
            command=self._more_charts_draw_moneyball,
        ).pack(side=tk.LEFT, padx=(14, 4))

        ttk.Button(
            opts, text="Refresh", command=self._more_charts_draw_moneyball
        ).pack(side=tk.LEFT, padx=(14, 2))

        search_frame = ttk.Frame(parent)
        search_frame.pack(fill=tk.X, padx=5, pady=(0, 4))
        ttk.Label(search_frame, text="Find player:").pack(side=tk.LEFT, padx=(2, 4))
        self.mc_money_search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.mc_money_search_var, width=24)
        search_entry.pack(side=tk.LEFT, padx=2)
        search_entry.bind("<Return>", lambda *_: self._more_charts_draw_moneyball())
        ttk.Button(
            search_frame, text="Find", command=self._more_charts_draw_moneyball
        ).pack(side=tk.LEFT, padx=2)
        ttk.Label(
            search_frame,
            text="(highlights matches in the chart and table)",
            foreground="#6b7280",
        ).pack(side=tk.LEFT, padx=(8, 2))

        ttk.Label(
            parent,
            text=(
                "Efficiency = CP / (event kicker tier + 1), averaged over the top 5 CP-scoring finishes. "
                "Higher means more CP extracted from smaller fields. Autobid winners are included by "
                "default because winning a small regional earns an autobid. Double-click a row to see "
                "that player's events."
            ),
            wraplength=900,
            foreground="#4b5563",
        ).pack(fill=tk.X, padx=8, pady=(0, 4))

        self.mc_money_summary_var = tk.StringVar(value="")
        ttk.Label(
            parent, textvariable=self.mc_money_summary_var, foreground="#1e40af"
        ).pack(fill=tk.X, padx=8, pady=(0, 4))

        self.mc_money_fig = Figure(figsize=(10, 4), dpi=100)
        self.mc_money_ax = self.mc_money_fig.add_subplot(111)
        self.mc_money_canvas = FigureCanvasTkAgg(self.mc_money_fig, master=parent)
        self.mc_money_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        table_frame = ttk.Frame(parent)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        cols = ("Rank", "Name", "Region", "TotalCP", "Score", "AvgTier", "SmallestField", "Finishes")
        self.mc_money_tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=10)
        widths = {
            "Rank": 55, "Name": 190, "Region": 70, "TotalCP": 85,
            "Score": 75, "AvgTier": 80, "SmallestField": 110, "Finishes": 85,
        }
        for c in cols:
            self.mc_money_tree.heading(
                c, text=c, command=lambda col=c: self._sort_moneyball_tree(col)
            )
            self.mc_money_tree.column(c, width=widths[c])
        money_scroll = ttk.Scrollbar(
            table_frame, orient=tk.VERTICAL, command=self.mc_money_tree.yview
        )
        self.mc_money_tree.configure(yscrollcommand=money_scroll.set)
        self.mc_money_tree.bind("<Double-1>", self._on_moneyball_double_click)
        self.mc_money_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        money_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.mc_money_sort_key = "Rank"
        self.mc_money_sort_col = "Rank"
        self.mc_money_sort_reverse = False

    def _more_charts_draw_moneyball(self) -> None:
        """Recompute and redraw the Moneyball chart and table."""
        self.mc_money_ax.clear()
        for item in self.mc_money_tree.get_children():
            self.mc_money_tree.delete(item)
        self.mc_money_summary_var.set("")
        self.more_charts_data["moneyball_df"] = pd.DataFrame()

        season = self.season_var.get().strip() or DEFAULT_SEASON
        region = self.mc_money_region_var.get().strip().upper() or "ALL"
        try:
            min_finishes = max(
                1, int(self.mc_money_min_var.get().strip() or DEFAULT_MIN_COUNTING_FINISHES)
            )
        except ValueError:
            min_finishes = DEFAULT_MIN_COUNTING_FINISHES
        try:
            top_x = max(1, int(self.mc_money_top_var.get().strip() or DEFAULT_TOP_X))
        except ValueError:
            top_x = DEFAULT_TOP_X

        try:
            mb = moneyball_leaderboard(
                season,
                region_group=region,
                min_counting_finishes=min_finishes,
                top_x=top_x,
                include_autobid=self.mc_money_autobid_var.get(),
            )
        except Exception as exc:
            logger.error("Moneyball load: %s", exc)
            self.mc_money_ax.set_title("Moneyball — error loading data")
            self.mc_money_canvas.draw_idle()
            return

        self.more_charts_data["moneyball_df"] = mb
        if mb.empty:
            self.mc_money_ax.set_title(f"Moneyball ({region}) — no qualifying players")
            self.mc_money_canvas.draw_idle()
            return

        top = mb.iloc[0]
        self.mc_money_summary_var.set(
            f"Top moneyball player: {top['Name']} — {int(top['TotalCP']):,} CP from "
            f"{int(top['CountingFinishes'])} counting finishes, avg kicker tier "
            f"{top['AvgEventTier']:g}, smallest field {int(top['SmallestField']):,}."
        )

        matches = self._moneyball_match_names()
        groups = sorted(mb["RegionGroup"].unique())
        color_for = {g: CHART_COLORS[i % len(CHART_COLORS)] for i, g in enumerate(groups)}
        for group in groups:
            sub = mb[mb["RegionGroup"] == group]
            self.mc_money_ax.scatter(
                sub["TotalCP"],
                sub["MoneyballScore"],
                c=color_for[group],
                alpha=0.7,
                s=45,
                label=str(group),
            )
        for _, row in mb.head(10).iterrows():
            self.mc_money_ax.annotate(
                str(row["Name"])[:16],
                (row["TotalCP"], row["MoneyballScore"]),
                fontsize=7,
                xytext=(4, 4),
                textcoords="offset points",
            )
        if matches:
            found = mb[mb["Name"].isin(matches)]
            self.mc_money_ax.scatter(
                found["TotalCP"],
                found["MoneyballScore"],
                s=180,
                facecolors="none",
                edgecolors="#dc2626",
                linewidths=2.5,
                zorder=5,
                label="Search match",
            )
            for _, row in found.iterrows():
                self.mc_money_ax.annotate(
                    str(row["Name"])[:22],
                    (row["TotalCP"], row["MoneyballScore"]),
                    fontsize=9,
                    color="#dc2626",
                    fontweight="bold",
                    xytext=(6, 8),
                    textcoords="offset points",
                    zorder=6,
                )
        self.mc_money_ax.set_xlabel("Total CP (top 5 finishes)")
        self.mc_money_ax.set_ylabel("Moneyball efficiency score")
        self.mc_money_ax.set_title(f"Moneyball — CP per field-size tier ({region}, top {top_x})")
        self.mc_money_ax.grid(True, alpha=0.3)
        self.mc_money_ax.legend(fontsize=8)
        self.mc_money_canvas.draw_idle()

        self.mc_money_sort_key = "Rank"
        self.mc_money_sort_col = "Rank"
        self.mc_money_sort_reverse = False
        self._populate_moneyball_tree(mb)
        self._select_moneyball_matches()

    def _select_moneyball_matches(self) -> None:
        """Keep search matches selected after a redraw or column re-sort."""
        matches = self._moneyball_match_names()
        if not matches:
            return
        lowered = {name.lower() for name in matches}
        for item in self.mc_money_tree.get_children():
            if str(self.mc_money_tree.item(item, "values")[1]).lower() in lowered:
                self.mc_money_tree.selection_add(item)
                self.mc_money_tree.see(item)

    def _moneyball_match_names(self) -> list[str]:
        """Player names in the current view matching the search box (substring, case-insensitive)."""
        query = self.mc_money_search_var.get().strip().lower()
        if not query:
            return []
        mb = self.more_charts_data.get("moneyball_df")
        if mb is None or mb.empty:
            return []
        hit = mb[mb["Name"].str.lower().str.contains(query, regex=False, na=False)]
        return [str(name) for name in hit["Name"].tolist()]

    def _on_moneyball_double_click(self, event) -> None:
        """Show the player's full season event list, like the Leaderboard tab."""
        item_id = self.mc_money_tree.identify_row(event.y)
        if not item_id:
            return
        values = self.mc_money_tree.item(item_id, "values")
        name = str(values[1]) if len(values) > 1 else ""
        region = str(values[2]) if len(values) > 2 else ""
        mb = self.more_charts_data.get("moneyball_df")
        if mb is None or mb.empty:
            return
        row = mb[
            (mb["Name"] == name)
            & ((mb["RegionCode"] == region) | (mb["RegionGroup"] == region))
        ]
        if row.empty:
            row = mb[mb["Name"] == name]
        if row.empty:
            return
        PlayerResultsViewer(self, name, row.iloc[0].get("AllResults") or [])

    @staticmethod
    def _moneyball_tree_values(row) -> tuple:
        return (
            int(row["Rank"]),
            str(row["Name"]),
            str(row["RegionCode"] or row["RegionGroup"]),
            int(row["TotalCP"]),
            float(row["MoneyballScore"]),
            float(row["AvgEventTier"]),
            int(row["SmallestField"]),
            int(row["CountingFinishes"]),
        )

    def _populate_moneyball_tree(self, df: pd.DataFrame) -> None:
        for item in self.mc_money_tree.get_children():
            self.mc_money_tree.delete(item)
        ordered = df
        if self.mc_money_sort_key in df.columns:
            ordered = df.sort_values(
                by=self.mc_money_sort_key, ascending=not self.mc_money_sort_reverse
            )
        for _, row in ordered.iterrows():
            self.mc_money_tree.insert("", tk.END, values=self._moneyball_tree_values(row))

    def _sort_moneyball_tree(self, col: str) -> None:
        df = self.more_charts_data.get("moneyball_df")
        if df is None or df.empty:
            return
        key_map = {
            "Region": "RegionGroup",
            "Score": "MoneyballScore",
            "AvgTier": "AvgEventTier",
            "SmallestField": "SmallestField",
            "Finishes": "CountingFinishes",
        }
        key = key_map.get(col, col)
        for c in self.mc_money_tree["columns"]:
            self.mc_money_tree.heading(c, text=c)
        if self.mc_money_sort_col == col:
            self.mc_money_sort_reverse = not self.mc_money_sort_reverse
        else:
            self.mc_money_sort_col = col
            self.mc_money_sort_reverse = True
        self.mc_money_sort_key = key
        arrow = " ▾" if self.mc_money_sort_reverse else " ▴"
        self.mc_money_tree.heading(col, text=col + arrow)
        self._populate_moneyball_tree(df)
        self._select_moneyball_matches()

    # --- Invite flow (Sankey) ---
    def _build_more_charts_invite_flow_tab(self, parent: ttk.Frame) -> None:
        """Build the invite-flow Sankey sub-tab (uses the shared season/region)."""
        self.mc_invite_flow_fig = Figure(figsize=(10, 4), dpi=100)
        self.mc_invite_flow_ax = self.mc_invite_flow_fig.add_subplot(111)
        self.mc_invite_flow_canvas = FigureCanvasTkAgg(self.mc_invite_flow_fig, master=parent)
        self.mc_invite_flow_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.mc_invite_flow_status_var = tk.StringVar(
            value="Click 'Refresh All' to load invite flows, then hover a date for details."
        )
        ttk.Label(parent, textvariable=self.mc_invite_flow_status_var, wraplength=900).pack(
            fill=tk.X, padx=5, pady=4
        )
        self.mc_invite_flow_canvas.mpl_connect(
            "motion_notify_event", self._more_charts_invite_flow_hover
        )

    def _more_charts_draw_invite_flow(self) -> None:
        """Load and draw invite flows for the selected season and region."""
        season = self.season_var.get().strip() or DEFAULT_SEASON
        region = self.more_charts_region_var.get().strip().upper() or "NA"
        try:
            flow = get_invite_flows(season, region)
        except Exception as exc:
            logger.error("Invite flow load: %s", exc)
            self.mc_invite_flow_status_var.set(f"Error loading invite flows: {exc}")
            self.mc_invite_flow_ax.clear()
            self.mc_invite_flow_ax.set_axis_off()
            self.mc_invite_flow_canvas.draw_idle()
            return
        self.more_charts_data["invite_flow"] = flow
        draw_invite_flow_sankey(self.mc_invite_flow_ax, flow)
        self.mc_invite_flow_canvas.draw_idle()
        if flow.stages:
            self.mc_invite_flow_status_var.set(
                f"Hover a column for details. Latest: {describe_column(flow, len(flow.stages) - 1)}"
            )
        else:
            self.mc_invite_flow_status_var.set("No Regional/IC data for this season and region.")

    def _more_charts_invite_flow_hover(self, event) -> None:
        """Show kept/entered/autobid counts for the date under the cursor."""
        flow = self.more_charts_data.get("invite_flow")
        if flow is None or not event.inaxes or event.xdata is None:
            return
        index = int(round(event.xdata))
        if not 0 <= index < len(flow.stages):
            return
        self.mc_invite_flow_status_var.set(describe_column(flow, index))


