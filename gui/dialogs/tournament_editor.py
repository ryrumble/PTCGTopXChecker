"""Tournament editor dialog for viewing and editing a tournament's data."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from aggregation import invalidate_season_caches
from gui.constants import DEFAULT_SEASON, SEASONS
from logger import logger

if TYPE_CHECKING:
    from gui.app import App
from parsers import ParsedEntry
from storage import load_json, save_json
from utils import TournamentKey, normalize_player_name


class TournamentEditor(tk.Toplevel):
    """Window for viewing and editing a tournament's data."""

    def __init__(self, parent: App, tournament_path: Path) -> None:
        super().__init__(parent)
        self.parent = parent
        self.tournament_path = tournament_path
        self.data = load_json(tournament_path)
        self.original_entries: list[ParsedEntry] = []

        self.title(f"Edit Tournament: {self.data.get('metadata', {}).get('title', 'Unknown')}")
        self.geometry("900x700")

        self._build_ui()
        self._load_data()

    def _build_ui(self) -> None:
        meta_frame = ttk.LabelFrame(self, text="Tournament Metadata")
        meta_frame.pack(fill=tk.X, padx=10, pady=5)

        meta = self.data.get("metadata", {})

        title_row = ttk.Frame(meta_frame)
        title_row.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(title_row, text="Title:", width=12).pack(side=tk.LEFT)
        self.meta_title_var = tk.StringVar(value=meta.get("title", ""))
        ttk.Entry(title_row, textvariable=self.meta_title_var, width=50).pack(side=tk.LEFT, padx=5)

        type_row = ttk.Frame(meta_frame)
        type_row.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(type_row, text="Type:", width=12).pack(side=tk.LEFT)
        self.meta_type_var = tk.StringVar(value=meta.get("tournament_type", "REGIONAL"))
        ttk.Combobox(
            type_row, textvariable=self.meta_type_var, values=["REGIONAL", "IC"], width=15, state="readonly",
        ).pack(side=tk.LEFT, padx=5)

        season_row = ttk.Frame(meta_frame)
        season_row.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(season_row, text="Season:", width=12).pack(side=tk.LEFT)
        self.meta_season_var = tk.StringVar(value=meta.get("season", "") or DEFAULT_SEASON)
        ttk.Combobox(
            season_row, textvariable=self.meta_season_var, values=SEASONS, width=15, state="readonly",
        ).pack(side=tk.LEFT, padx=5)

        comp_row = ttk.Frame(meta_frame)
        comp_row.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(comp_row, text="Competitors:", width=12).pack(side=tk.LEFT)
        self.meta_competitors_var = tk.StringVar(value=str(meta.get("num_competitors", 0)))
        ttk.Entry(comp_row, textvariable=self.meta_competitors_var, width=15).pack(side=tk.LEFT, padx=5)

        date_row = ttk.Frame(meta_frame)
        date_row.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(date_row, text="Date (YYYY-MM-DD):", width=12).pack(side=tk.LEFT)
        self.meta_date_var = tk.StringVar(value=meta.get("tournament_date", ""))
        ttk.Entry(date_row, textvariable=self.meta_date_var, width=15).pack(side=tk.LEFT, padx=5)

        url_row = ttk.Frame(meta_frame)
        url_row.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(url_row, text="URL:", width=12).pack(side=tk.LEFT)
        self.meta_url_var = tk.StringVar(value=meta.get("url", ""))
        ttk.Entry(url_row, textvariable=self.meta_url_var, width=50).pack(side=tk.LEFT, padx=5)

        table_frame = ttk.Frame(self)
        table_frame.pack(fill=tk.BOTH, padx=10, pady=5, expand=True)

        columns = ("placement", "name", "region")
        self.edit_tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        for col, text in zip(columns, ["Placement", "Name", "Region"]):
            self.edit_tree.heading(col, text=text)
            self.edit_tree.column(col, width=200)

        e_v_scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.edit_tree.yview)
        e_h_scrollbar = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.edit_tree.xview)
        self.edit_tree.configure(yscrollcommand=e_v_scrollbar.set, xscrollcommand=e_h_scrollbar.set)

        self.edit_tree.grid(row=0, column=0, sticky="nsew")
        e_v_scrollbar.grid(row=0, column=1, sticky="ns")
        e_h_scrollbar.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        self.edit_tree.bind("<Double-1>", self._on_edit_tree_double_click)

        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(button_frame, text="Delete Tournament", command=self._delete_tournament).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Save Changes", command=self._save_changes).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=5)

    def _load_data(self) -> None:
        self.edit_tree.delete(*self.edit_tree.get_children())
        self.original_entries = []

        for entry in self.data.get("normalized_entries", []):
            placement = entry.get("placement", 0)
            name = entry.get("normalized_name", "")
            region = entry.get("region_code", "") or ""
            self.edit_tree.insert("", tk.END, values=(placement, name, region))
            self.original_entries.append(
                ParsedEntry(placement=int(placement), raw_name=name, region_code=region or None)
            )

    def _on_edit_tree_double_click(self, event) -> None:
        item_id = self.edit_tree.identify_row(event.y)
        column = self.edit_tree.identify_column(event.x)
        if not item_id or column not in ("#2", "#3"):
            return
        col_index = int(column.replace("#", "")) - 1
        x, y, width, height = self.edit_tree.bbox(item_id, column)
        value = self.edit_tree.item(item_id, "values")[col_index]

        edit_var = tk.StringVar(value=value)
        entry = ttk.Entry(self.edit_tree, textvariable=edit_var)
        entry.place(x=x, y=y, width=width, height=height)

        def on_focus_out(_event=None):
            new_values = list(self.edit_tree.item(item_id, "values"))
            new_values[col_index] = edit_var.get()
            self.edit_tree.item(item_id, values=new_values)
            entry.destroy()

        def on_return(_event):
            on_focus_out()

        entry.bind("<FocusOut>", on_focus_out)
        entry.bind("<Return>", on_return)
        entry.focus_set()

    def _save_changes(self) -> None:
        title = self.meta_title_var.get().strip()
        if not title:
            messagebox.showerror("Invalid Data", "Tournament title cannot be empty.")
            return

        try:
            num_comp = int(self.meta_competitors_var.get() or "0")
        except ValueError:
            messagebox.showerror("Invalid Data", "Number of competitors must be an integer.")
            return

        updated_entries: list[ParsedEntry] = []
        for item_id in self.edit_tree.get_children():
            vals = self.edit_tree.item(item_id, "values")
            try:
                placement = int(vals[0])
                name = vals[1].strip()
                region = vals[2].strip() or None
                updated_entries.append(ParsedEntry(placement=placement, raw_name=name, region_code=region))
            except (ValueError, IndexError) as exc:
                messagebox.showerror("Invalid Data", f"Invalid entry data: {exc}")
                return

        missing_regions = [e for e in updated_entries if not e.region_code]
        if missing_regions:
            if not messagebox.askyesno(
                "Missing Regions", f"{len(missing_regions)} entries are missing region codes. Save anyway?"
            ):
                return

        raw_entries = []
        normalized_entries = []
        for e in updated_entries:
            raw_entries.append({"placement": e.placement, "raw_name": e.raw_name, "region_code": e.region_code})
            normalized_entries.append({
                "placement": e.placement,
                "normalized_name": normalize_player_name(e.raw_name),
                "region_code": e.region_code,
            })

        meta = self.data.get("metadata", {})
        meta["title"] = title
        meta["title_norm"] = title.strip()
        meta["tournament_type"] = self.meta_type_var.get().strip().upper()
        meta["season"] = self.meta_season_var.get().strip()
        meta["num_competitors"] = num_comp
        meta["tournament_date"] = self.meta_date_var.get().strip()
        meta["url"] = self.meta_url_var.get().strip()

        new_key = TournamentKey(title_norm=meta["title_norm"], url=meta["url"] or "", season=meta["season"])
        meta["id"] = new_key.to_id()

        self.data["raw_entries"] = raw_entries
        self.data["normalized_entries"] = normalized_entries
        self.data["metadata"] = meta

        save_json(self.tournament_path, self.data)
        inv_season = (self.data.get("metadata") or {}).get("season", "").strip() or DEFAULT_SEASON
        invalidate_season_caches(inv_season)
        messagebox.showinfo("Saved", "Tournament data saved successfully.")
        self.parent._refresh_tournaments_list()
        self.destroy()

    def _delete_tournament(self) -> None:
        title = self.data.get("metadata", {}).get("title", "this tournament")
        if not messagebox.askyesno(
            "Confirm Delete", f"Are you sure you want to delete '{title}'?\n\nThis action cannot be undone."
        ):
            return

        try:
            del_season = (self.data.get("metadata") or {}).get("season", "").strip() or DEFAULT_SEASON
            self.tournament_path.unlink()
            invalidate_season_caches(del_season)
            messagebox.showinfo("Deleted", f"Tournament '{title}' has been deleted.")
            self.parent._refresh_tournaments_list()
            self.destroy()
        except Exception as exc:
            logger.error("Failed to delete tournament: %s", exc)
            messagebox.showerror("Error", f"Failed to delete tournament: {exc}")
