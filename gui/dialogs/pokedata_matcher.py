"""Dialog for matching pokedata.ovh names with regional tournament names."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from aggregation import aggregate_season
from storage import load_pokedata_name_mappings, load_total_cp_data, save_pokedata_name_mappings

if TYPE_CHECKING:
    from gui.app import App
from utils import normalize_player_name


class PokedataNameMatcher(tk.Toplevel):
    """Dialog for matching pokedata.ovh names with regional names."""

    def __init__(self, parent: App, season: str) -> None:
        super().__init__(parent)
        self.parent = parent
        self.season = season
        self.title(f"Match Pokedata Names - {season}")
        self.geometry("900x700")

        total_cp_entries = load_total_cp_data(season)
        regional_df = aggregate_season(season)

        if not total_cp_entries or regional_df is None or regional_df.empty:
            messagebox.showinfo("No Data", "No total CP data or regional data found.")
            self.destroy()
            return

        self.total_cp_entries = total_cp_entries
        self.regional_df = regional_df

        regional_list = []
        for _, row in regional_df.iterrows():
            name = row["Name"]
            normalized = normalize_player_name(name)
            cp = row["TotalCP"]
            country = row.get("RegionCode", "")
            regional_list.append((name, normalized, cp, country))

        regional_list.sort(key=lambda x: x[2], reverse=True)

        name_mappings = load_pokedata_name_mappings(season)
        already_matched = set(name_mappings.values())
        already_matched_normalized = {normalize_player_name(n) for n in already_matched}

        self.regional_list = [
            (name, normalized, cp, country)
            for name, normalized, cp, country in regional_list
            if normalized not in already_matched_normalized
        ]

        regional_names_normalized = {normalize_player_name(n): n for n in regional_df["Name"].tolist()}
        unmatched: list[tuple[str, str, int, str]] = []
        for entry_dict in total_cp_entries:
            pokedata_name = entry_dict.get("raw_name", "")
            normalized_pokedata = normalize_player_name(pokedata_name)
            pokedata_cp = entry_dict.get("current_points", 0)
            pokedata_country = entry_dict.get("country", "")

            if normalized_pokedata in name_mappings:
                continue
            if normalized_pokedata in regional_names_normalized:
                continue
            unmatched.append((pokedata_name, normalized_pokedata, pokedata_cp, pokedata_country))

        if not unmatched:
            messagebox.showinfo("All Matched", "All pokedata names are already matched!")
            self.destroy()
            return

        self.unmatched = unmatched
        self.name_mappings = name_mappings.copy()
        self.current_index = 0

        self._build_ui()
        self._show_current_match()

    def _build_ui(self) -> None:
        match_frame = ttk.LabelFrame(self, text="Current Match")
        match_frame.pack(fill=tk.X, padx=10, pady=5)

        self.pokedata_label = ttk.Label(match_frame, text="", font=("", 12, "bold"), wraplength=400)
        self.pokedata_label.pack(pady=10)

        ttk.Label(match_frame, text="Match to regional name:").pack()

        country_frame = ttk.Frame(match_frame)
        country_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(country_frame, text="Country Filter:").pack(side=tk.LEFT)
        self.country_filter_var = tk.StringVar()
        countries = sorted(set(country for _, _, _, country in self.regional_list if country))
        self.country_filter_combo = ttk.Combobox(
            country_frame, textvariable=self.country_filter_var, values=[""] + countries, width=10, state="readonly",
        )
        self.country_filter_combo.pack(side=tk.LEFT, padx=5)
        self.country_filter_combo.bind("<<ComboboxSelected>>", lambda e: self._filter_regional_names())

        search_frame = ttk.Frame(match_frame)
        search_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=30)
        search_entry.pack(side=tk.LEFT, padx=5)
        search_entry.bind("<KeyRelease>", lambda e: self._filter_regional_names())

        list_frame = ttk.Frame(match_frame)
        list_frame.pack(fill=tk.BOTH, padx=10, pady=5, expand=True)

        self.regional_listbox = tk.Listbox(list_frame, height=10)
        self.regional_listbox.pack(fill=tk.BOTH, expand=True)
        self.regional_listbox.bind("<<ListboxSelect>>", self._on_regional_selected)
        self.regional_display_to_name: dict[str, str] = {}

        button_frame = ttk.Frame(match_frame)
        button_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(button_frame, text="Skip", command=self._skip_match).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="No Match", command=self._no_match).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Confirm Match", command=self._confirm_match).pack(side=tk.LEFT, padx=5)

        progress_frame = ttk.Frame(self)
        progress_frame.pack(fill=tk.X, padx=10, pady=5)
        self.progress_label = ttk.Label(progress_frame, text="")
        self.progress_label.pack()

        nav_frame = ttk.Frame(self)
        nav_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(nav_frame, text="Previous", command=self._previous_match).pack(side=tk.LEFT, padx=5)
        ttk.Button(nav_frame, text="Next", command=self._next_match).pack(side=tk.LEFT, padx=5)
        ttk.Button(nav_frame, text="Save & Close", command=self._save_and_close).pack(side=tk.RIGHT, padx=5)

        self.selected_regional_name = None

    def _filter_regional_names(self) -> None:
        search_term = self.search_var.get().lower()
        country_filter = self.country_filter_var.get().strip()

        filtered = []
        for name, normalized, cp, country in self.regional_list:
            if country_filter and country != country_filter:
                continue
            if search_term and search_term not in name.lower():
                continue
            display_text = f"{name} (CP: {cp})"
            if country:
                display_text += f" [{country}]"
            filtered.append((name, normalized, cp, country, display_text))

        filtered.sort(key=lambda x: x[2], reverse=True)

        self.regional_listbox.delete(0, tk.END)
        self.regional_display_to_name.clear()
        for name, _normalized, _cp, _country, display_text in filtered:
            self.regional_listbox.insert(tk.END, display_text)
            self.regional_display_to_name[display_text] = name

    def _on_regional_selected(self, event) -> None:
        selection = self.regional_listbox.curselection()
        if selection:
            index = selection[0]
            display_text = self.regional_listbox.get(index)
            self.selected_regional_name = self.regional_display_to_name.get(display_text)
            if not self.selected_regional_name:
                if " (CP:" in display_text:
                    self.selected_regional_name = display_text.split(" (CP:")[0]
                else:
                    self.selected_regional_name = display_text

    def _show_current_match(self) -> None:
        if self.current_index >= len(self.unmatched):
            messagebox.showinfo("Complete", "All names processed!")
            self._save_and_close()
            return

        pokedata_name, normalized, pokedata_cp, pokedata_country = self.unmatched[self.current_index]
        country_text = f" [{pokedata_country}]" if pokedata_country else ""
        self.pokedata_label.config(text=f"Pokedata Name: {pokedata_name} (CP: {pokedata_cp}){country_text}")

        self.selected_regional_name = None
        self.search_var.set("")
        self.country_filter_var.set("")
        self._filter_regional_names()

        self.progress_label.config(text=f"Match {self.current_index + 1} of {len(self.unmatched)}")

    def _skip_match(self) -> None:
        self._next_match()

    def _no_match(self) -> None:
        self._next_match()

    def _confirm_match(self) -> None:
        if not self.selected_regional_name:
            messagebox.showwarning("No Selection", "Please select a regional name to match.")
            return

        pokedata_name, normalized, pokedata_cp, pokedata_country = self.unmatched[self.current_index]
        self.name_mappings[normalized] = normalize_player_name(self.selected_regional_name)
        self._next_match()

    def _previous_match(self) -> None:
        if self.current_index > 0:
            self.current_index -= 1
            self._show_current_match()

    def _next_match(self) -> None:
        self.current_index += 1
        self._show_current_match()

    def _save_and_close(self) -> None:
        save_pokedata_name_mappings(self.season, self.name_mappings)
        messagebox.showinfo("Saved", "Name mappings saved.")
        self.destroy()
        self.parent._refresh_total_cp_analysis()
