"""Dialog for merging duplicate pokedata entries."""

from __future__ import annotations

import tkinter as tk
from collections import defaultdict
from tkinter import messagebox, ttk

from total_cp_parser import TotalCPEntry


class PokedataMergeDialog(tk.Toplevel):
    """Dialog for merging duplicate pokedata entries."""

    def __init__(self, parent, similar_pairs: list[tuple[str, str, float]], entries: list[TotalCPEntry]) -> None:
        super().__init__(parent)
        self.parent = parent
        self.similar_pairs = similar_pairs
        self.entries = entries
        self.title("Merge Duplicate Entries")
        self.geometry("900x600")

        info_frame = ttk.Frame(self)
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(
            info_frame,
            text=f"Found {len(similar_pairs)} potential duplicate pairs. Select which name to keep for each pair.",
            wraplength=800,
        ).pack(anchor="w")

        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, padx=10, pady=5, expand=True)

        columns = ("name1", "cp1", "name2", "cp2", "similarity", "merge_to")
        self.merge_tree = ttk.Treeview(list_frame, columns=columns, show="headings")
        for col, text in zip(columns, ["Name 1", "CP 1", "Name 2", "CP 2", "Similarity", "Merge To"]):
            self.merge_tree.heading(col, text=text)
            self.merge_tree.column(col, width=120)

        m_v_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.merge_tree.yview)
        m_h_scrollbar = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.merge_tree.xview)
        self.merge_tree.configure(yscrollcommand=m_v_scrollbar.set, xscrollcommand=m_h_scrollbar.set)

        self.merge_tree.grid(row=0, column=0, sticky="nsew")
        m_v_scrollbar.grid(row=0, column=1, sticky="ns")
        m_h_scrollbar.grid(row=1, column=0, sticky="ew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self.merge_data: list[tuple[str, str, str, str]] = []
        name_to_entries: dict[str, list[TotalCPEntry]] = defaultdict(list)
        for entry in entries:
            name_to_entries[entry.normalized_name].append(entry)

        for name1, name2, similarity in similar_pairs:
            entries1 = name_to_entries.get(name1, [])
            entries2 = name_to_entries.get(name2, [])
            cp1 = max(e.current_points for e in entries1) if entries1 else 0
            cp2 = max(e.current_points for e in entries2) if entries2 else 0
            default_target = name1 if cp1 > cp2 or (cp1 == cp2 and len(name1) > len(name2)) else name2

            item_id = self.merge_tree.insert(
                "", tk.END, values=(name1, cp1, name2, cp2, f"{similarity:.1%}", default_target),
            )
            self.merge_data.append((name1, name2, default_target, item_id))

        self.merge_tree.bind("<Double-1>", self._on_double_click)

        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(button_frame, text="Apply Merges", command=self._apply_merges).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=5)

    def _on_double_click(self, event) -> None:
        item_id = self.merge_tree.identify_row(event.y)
        column = self.merge_tree.identify_column(event.x)
        if not item_id or column != "#6":
            return

        values = list(self.merge_tree.item(item_id, "values"))
        current_target = values[5]
        name1 = values[0]
        name2 = values[2]

        target_window = tk.Toplevel(self)
        target_window.title("Select Merge Target")
        target_window.geometry("300x150")

        ttk.Label(target_window, text="Merge to which name?").pack(pady=10)

        target_var = tk.StringVar(value=current_target)
        ttk.Radiobutton(target_window, text=name1, variable=target_var, value=name1).pack()
        ttk.Radiobutton(target_window, text=name2, variable=target_var, value=name2).pack()

        def confirm():
            new_target = target_var.get()
            values[5] = new_target
            self.merge_tree.item(item_id, values=values)
            for i, (n1, n2, _old_target, item) in enumerate(self.merge_data):
                if item == item_id:
                    self.merge_data[i] = (n1, n2, new_target, item)
                    break
            target_window.destroy()

        ttk.Button(target_window, text="OK", command=confirm).pack(pady=10)

    def _apply_merges(self) -> None:
        merge_mappings = {}
        for name1, name2, target, _item_id in self.merge_data:
            if target == name1:
                merge_mappings[name2] = name1
            else:
                merge_mappings[name1] = name2

        self.parent.merge_mappings = merge_mappings
        messagebox.showinfo("Merges Applied", f"Applied {len(merge_mappings)} merge(s). They will be used when you save.")
        self.destroy()
