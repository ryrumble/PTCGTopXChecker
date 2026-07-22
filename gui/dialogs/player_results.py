"""Player results viewer dialog."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gui.app import App


class PlayerResultsViewer(tk.Toplevel):
    """Window showing a player's tournament results."""

    def __init__(self, parent: App, player_name: str, results: list[dict[str, Any]]) -> None:
        super().__init__(parent)
        self.title(f"Tournament Results: {player_name}")
        self.geometry("700x500")

        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(header, text=f"Tournament Results for {player_name}", font=("", 12, "bold")).pack()

        table_frame = ttk.Frame(self)
        table_frame.pack(fill=tk.BOTH, padx=10, pady=5, expand=True)

        columns = ("tournament", "placement", "type", "cp")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        for col, text in zip(columns, ["Tournament", "Placement", "Type", "CP"]):
            tree.heading(col, text=text)
            tree.column(col, width=80)

        v_scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=tree.yview)
        h_scrollbar = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        if results:
            for result in sorted(results, key=lambda x: x.get("cp", 0), reverse=True):
                tree.insert(
                    "",
                    tk.END,
                    values=(
                        result.get("tournament", "Unknown"),
                        result.get("placement", "N/A"),
                        result.get("type", "N/A"),
                        result.get("cp", 0),
                    ),
                )
        else:
            tree.insert("", tk.END, values=("No tournament results found", "", "", ""))

        try:
            font = tkfont.nametofont("TkDefaultFont")
            for cidx, col in enumerate(columns):
                max_w = 60
                for item in tree.get_children():
                    vals = tree.item(item, "values")
                    if cidx < len(vals):
                        s = str(vals[cidx])
                        w = font.measure(s) + 20
                        max_w = max(max_w, min(w, 600))
                if col == "tournament":
                    max_w = max(max_w, 220)
                tree.column(col, width=max_w)
        except Exception:
            tree.column("tournament", width=280)
            tree.column("placement", width=90)
            tree.column("type", width=100)
            tree.column("cp", width=60)

        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(button_frame, text="Close", command=self.destroy).pack(side=tk.RIGHT)
