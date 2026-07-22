"""Player name merge/split management dialog."""

from __future__ import annotations

import tkinter as tk
from collections import defaultdict
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Any

from aggregation import aggregate_season, invalidate_season_caches
from logger import logger
from storage import (
    list_tournament_files,
    load_json,
    load_player_mappings,
    save_json,
    save_player_mappings,
)

if TYPE_CHECKING:
    from gui.app import App


class PlayerManager(tk.Toplevel):
    """Window for managing player name merges and splits."""

    def __init__(self, parent: App, season: str) -> None:
        super().__init__(parent)
        self.parent = parent
        self.season = season
        self.mappings = load_player_mappings(season)

        self.title(f"Player Manager - {season}")
        self.geometry("1000x700")

        self._build_ui()
        self._load_players()

    def _build_ui(self) -> None:
        info_frame = ttk.Frame(self)
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(
            info_frame,
            text="Select multiple players to merge into one canonical name, or select a player to view/split their appearances.",
            wraplength=800,
        ).pack(anchor="w")

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        merge_frame = ttk.Frame(notebook)
        notebook.add(merge_frame, text="Merge Players")
        self._build_merge_tab(merge_frame)

        split_frame = ttk.Frame(notebook)
        notebook.add(split_frame, text="Split Player")
        self._build_split_tab(split_frame)

        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(button_frame, text="Save Mappings", command=self._save_mappings).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Close", command=self.destroy).pack(side=tk.RIGHT, padx=5)

    def _build_merge_tab(self, parent: ttk.Frame) -> None:
        list_frame = ttk.Frame(parent)
        list_frame.pack(fill=tk.BOTH, padx=10, pady=5, expand=True)

        columns = ("name", "region", "tournaments", "total_cp")
        self.merge_tree = ttk.Treeview(list_frame, columns=columns, show="tree headings", selectmode="extended")
        self.merge_tree.heading("#0", text="")
        self.merge_tree.column("#0", width=30)
        for col, text in zip(columns, ["Name", "Region", "Tournaments", "Total CP"]):
            self.merge_tree.heading(col, text=text)
            self.merge_tree.column(col, width=200)

        m_v_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.merge_tree.yview)
        m_h_scrollbar = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.merge_tree.xview)
        self.merge_tree.configure(yscrollcommand=m_v_scrollbar.set, xscrollcommand=m_h_scrollbar.set)

        self.merge_tree.grid(row=0, column=0, sticky="nsew")
        m_v_scrollbar.grid(row=0, column=1, sticky="ns")
        m_h_scrollbar.grid(row=1, column=0, sticky="ew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        merge_controls = ttk.Frame(parent)
        merge_controls.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(merge_controls, text="Merge selected players into:").pack(side=tk.LEFT, padx=5)
        self.merge_target_var = tk.StringVar()
        ttk.Entry(merge_controls, textvariable=self.merge_target_var, width=30).pack(side=tk.LEFT, padx=5)
        ttk.Button(merge_controls, text="Merge", command=self._merge_players).pack(side=tk.LEFT, padx=5)

    def _build_split_tab(self, parent: ttk.Frame) -> None:
        select_frame = ttk.Frame(parent)
        select_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(select_frame, text="Select player to view/split:").pack(side=tk.LEFT, padx=5)
        self.split_player_var = tk.StringVar()
        self.split_player_combo = ttk.Combobox(select_frame, textvariable=self.split_player_var, width=30)
        self.split_player_combo.pack(side=tk.LEFT, padx=5)
        self.split_player_combo.bind("<<ComboboxSelected>>", self._on_split_player_selected)

        appearances_frame = ttk.LabelFrame(parent, text="Tournament Appearances")
        appearances_frame.pack(fill=tk.BOTH, padx=10, pady=5, expand=True)

        columns = ("tournament", "placement", "name", "region")
        self.split_tree = ttk.Treeview(appearances_frame, columns=columns, show="headings")
        for col, text in zip(columns, ["Tournament", "Placement", "Name", "Region"]):
            self.split_tree.heading(col, text=text)
            self.split_tree.column(col, width=150)

        s_v_scrollbar = ttk.Scrollbar(appearances_frame, orient=tk.VERTICAL, command=self.split_tree.yview)
        s_h_scrollbar = ttk.Scrollbar(appearances_frame, orient=tk.HORIZONTAL, command=self.split_tree.xview)
        self.split_tree.configure(yscrollcommand=s_v_scrollbar.set, xscrollcommand=s_h_scrollbar.set)

        self.split_tree.grid(row=0, column=0, sticky="nsew")
        s_v_scrollbar.grid(row=0, column=1, sticky="ns")
        s_h_scrollbar.grid(row=1, column=0, sticky="ew")
        appearances_frame.grid_rowconfigure(0, weight=1)
        appearances_frame.grid_columnconfigure(0, weight=1)

        split_controls = ttk.Frame(parent)
        split_controls.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(split_controls, text="Rename selected appearance to:").pack(side=tk.LEFT, padx=5)
        self.split_new_name_var = tk.StringVar()
        ttk.Entry(split_controls, textvariable=self.split_new_name_var, width=30).pack(side=tk.LEFT, padx=5)
        ttk.Button(split_controls, text="Split", command=self._split_player).pack(side=tk.LEFT, padx=5)

    def _load_players(self) -> None:
        df = aggregate_season(self.season)
        if df is None or df.empty:
            messagebox.showinfo("No Data", "No players found for this season.")
            return

        files = list_tournament_files(self.season)
        player_tournaments: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for path in files:
            try:
                data = load_json(path)
                meta = data.get("metadata", {})
                title = meta.get("title", "Unknown")
                for entry in data.get("normalized_entries", []):
                    name = entry.get("normalized_name", "")
                    if name:
                        player_tournaments[name].append({
                            "tournament": title,
                            "placement": entry.get("placement", 0),
                            "name": name,
                            "region": entry.get("region_code", ""),
                            "file_path": path,
                            "entry_index": data.get("normalized_entries", []).index(entry),
                        })
            except Exception as exc:
                logger.error("Failed to load tournament %s: %s", path, exc)

        self.merge_tree.delete(*self.merge_tree.get_children())
        self.player_data: dict[str, dict[str, Any]] = {}

        for _, row in df.iterrows():
            name = row["Name"]
            region = row.get("RegionCode", "")
            num_tournaments = row.get("NumTournaments", 0)
            total_cp = row.get("TotalCP", 0)

            canonical_name = self.mappings.get("merges", {}).get(name, name)

            item_id = self.merge_tree.insert(
                "", tk.END, text="☐", values=(canonical_name, region, num_tournaments, total_cp),
            )
            self.player_data[item_id] = {
                "original_name": name,
                "canonical_name": canonical_name,
                "tournaments": player_tournaments.get(name, []),
            }

        player_names = sorted(set(df["Name"].tolist()))
        self.split_player_combo["values"] = player_names

    def _merge_players(self) -> None:
        selected = self.merge_tree.selection()
        if len(selected) < 2:
            messagebox.showwarning("Selection Required", "Please select at least 2 players to merge.")
            return

        target_name = self.merge_target_var.get().strip()
        if not target_name:
            messagebox.showwarning("Target Required", "Please enter a target name for the merge.")
            return

        names_to_merge = []
        for item_id in selected:
            data = self.player_data.get(item_id, {})
            orig_name = data.get("original_name", "")
            if orig_name:
                names_to_merge.append(orig_name)

        if not names_to_merge:
            messagebox.showerror("Error", "Could not determine player names from selection.")
            return

        names_str = ", ".join(names_to_merge)
        if not messagebox.askyesno("Confirm Merge", f"Merge these players into '{target_name}'?\n\n{names_str}"):
            return

        if "merges" not in self.mappings:
            self.mappings["merges"] = {}

        for name in names_to_merge:
            self.mappings["merges"][name] = target_name

        messagebox.showinfo("Merged", "Players merged. Remember to save mappings and refresh leaderboard.")
        self._load_players()
        self.merge_target_var.set("")

    def _on_split_player_selected(self, event=None) -> None:
        player_name = self.split_player_var.get()
        if not player_name:
            return

        self.split_tree.delete(*self.split_tree.get_children())
        self.split_appearances: list[dict[str, Any]] = []

        files = list_tournament_files(self.season)
        for path in files:
            try:
                data = load_json(path)
                meta = data.get("metadata", {})
                title = meta.get("title", "Unknown")
                for idx, entry in enumerate(data.get("normalized_entries", [])):
                    name = entry.get("normalized_name", "")
                    canonical = self.mappings.get("merges", {}).get(name, name)
                    if canonical == player_name or name == player_name:
                        self.split_tree.insert(
                            "",
                            tk.END,
                            values=(title, entry.get("placement", 0), name, entry.get("region_code", "")),
                        )
                        self.split_appearances.append({
                            "file_path": path,
                            "entry_index": idx,
                            "original_name": name,
                        })
            except Exception as exc:
                logger.error("Failed to load tournament %s: %s", path, exc)

    def _split_player(self) -> None:
        selected = self.split_tree.selection()
        if not selected:
            messagebox.showwarning("Selection Required", "Please select an appearance to split.")
            return

        new_name = self.split_new_name_var.get().strip()
        if not new_name:
            messagebox.showwarning("Name Required", "Please enter a new name for this appearance.")
            return

        item_id = selected[0]
        idx = self.split_tree.index(item_id)
        if idx >= len(self.split_appearances):
            messagebox.showerror("Error", "Invalid selection.")
            return

        appearance = self.split_appearances[idx]

        if not messagebox.askyesno(
            "Confirm Split", f"Rename this appearance from '{appearance['original_name']}' to '{new_name}'?"
        ):
            return

        try:
            data = load_json(appearance["file_path"])
            entry = data["normalized_entries"][appearance["entry_index"]]
            entry["normalized_name"] = new_name
            if "raw_entries" in data and appearance["entry_index"] < len(data["raw_entries"]):
                data["raw_entries"][appearance["entry_index"]]["raw_name"] = new_name

            save_json(appearance["file_path"], data)
            invalidate_season_caches(self.season)
            messagebox.showinfo("Split", f"Appearance renamed to '{new_name}'. Refresh leaderboard to see changes.")
            self._on_split_player_selected()
            self.split_new_name_var.set("")
        except Exception as exc:
            logger.error("Failed to split player: %s", exc)
            messagebox.showerror("Error", f"Failed to split player: {exc}")

    def _save_mappings(self) -> None:
        save_player_mappings(self.season, self.mappings)
        invalidate_season_caches(self.season)
        messagebox.showinfo("Saved", "Player mappings saved. Refresh leaderboard to see changes.")
        self.destroy()
