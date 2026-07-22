"""Dialog for loading pokedata.ovh HTML files for Total CP Analysis."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from gui.constants import DEFAULT_SEASON
from logger import logger
from storage import load_total_cp_data, save_total_cp_data

if TYPE_CHECKING:
    from gui.app import App
from total_cp_html_parser import parse_pokedata_html
from total_cp_merge import find_similar_names, merge_duplicate_entries
from total_cp_parser import TotalCPEntry, merge_pokedata_entries, parse_pokedata_text


class LoadTotalCPFileDialog(tk.Toplevel):
    """Dialog for loading pokedata.ovh HTML file."""

    def __init__(self, parent: App, file_path: str) -> None:
        super().__init__(parent)
        self.parent = parent
        self.file_path = file_path
        self.title("Load Total CP Data")
        self.geometry("600x400")

        info_frame = ttk.Frame(self)
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(info_frame, text=f"Loading file: {file_path}", wraplength=550).pack(anchor="w")

        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, padx=10, pady=5)
        self.status_label = ttk.Label(status_frame, text="Parsing file...")
        self.status_label.pack()

        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(button_frame, text="Check Duplicates", command=self._check_duplicates).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Load & Save", command=self._load_and_save).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=5)

        self.parsed_entries: list[TotalCPEntry] = []
        self.merge_mappings: dict[str, str] = {}
        self._parse_file()

    def _parse_file(self) -> None:
        try:
            with open(self.file_path, encoding="utf-8") as f:
                html_content = f.read()

            self.parsed_entries = parse_pokedata_html(html_content)

            if not self.parsed_entries:
                self.parsed_entries = parse_pokedata_text(html_content)

            if self.parsed_entries:
                self.status_label.config(text=f"Parsed {len(self.parsed_entries)} entries successfully.")
            else:
                self.status_label.config(text="Warning: No entries parsed. Check file format.")
        except Exception as exc:
            logger.error("Failed to parse file: %s", exc)
            self.status_label.config(text=f"Error parsing file: {exc}")

    def _check_duplicates(self) -> None:
        if not self.parsed_entries:
            messagebox.showwarning("No Data", "No entries were parsed from the file.")
            return

        similar_pairs = find_similar_names(self.parsed_entries, similarity_threshold=0.7)

        if not similar_pairs:
            messagebox.showinfo("No Duplicates", "No potential duplicate entries found.")
            return

        from gui.dialogs.pokedata_merge import PokedataMergeDialog

        PokedataMergeDialog(self, similar_pairs, self.parsed_entries)

    def _load_and_save(self) -> None:
        if not self.parsed_entries:
            messagebox.showwarning("No Data", "No entries were parsed from the file.")
            return

        try:
            if self.merge_mappings:
                self.parsed_entries = merge_duplicate_entries(self.parsed_entries, self.merge_mappings)

            season = self.parent.total_cp_season_var.get().strip() or DEFAULT_SEASON
            existing_data = load_total_cp_data(season)

            existing_entries: list[TotalCPEntry] = []
            for entry_dict in existing_data:
                date_points_raw = entry_dict.get("date_points", [])
                date_points: list[tuple[str, int, int]] = []
                for dp in date_points_raw:
                    if isinstance(dp, (list, tuple)) and len(dp) == 3:
                        date_points.append((str(dp[0]), int(dp[1]), int(dp[2])))

                existing_entries.append(
                    TotalCPEntry(
                        rank=entry_dict.get("rank", 0),
                        raw_name=entry_dict.get("raw_name", ""),
                        country=entry_dict.get("country", ""),
                        current_points=entry_dict.get("current_points", 0),
                        date_points=date_points,
                    )
                )

            merged = merge_pokedata_entries(existing_entries, self.parsed_entries)

            entries_dict = []
            for entry in merged:
                entries_dict.append({
                    "rank": entry.rank,
                    "raw_name": entry.raw_name,
                    "country": entry.country,
                    "current_points": entry.current_points,
                    "date_points": entry.date_points,
                })

            save_total_cp_data(season, entries_dict)
            messagebox.showinfo("Saved", f"Saved {len(self.parsed_entries)} new entries. Total: {len(merged)} entries.")
            self.destroy()
            self.parent._refresh_total_cp_analysis()
        except Exception as exc:
            logger.error("Failed to save total CP data: %s", exc)
            messagebox.showerror("Error", f"Failed to save data: {exc}")
