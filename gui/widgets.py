"""Shared widget components for the GUI."""

import tkinter as tk
from tkinter import ttk


def make_scrollable_treeview(
    parent: tk.Widget,
    columns: tuple[str, ...],
    heading_texts: tuple[str, ...] | None = None,
    column_widths: tuple[int, ...] | None = None,
    selectmode: str = "browse",
    show: str = "headings",
) -> ttk.Treeview:
    """Create a Treeview with vertical and horizontal scrollbars packed in a grid.

    Returns the configured Treeview widget.
    """
    frame = ttk.Frame(parent)
    frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

    tree = ttk.Treeview(frame, columns=columns, show=show, selectmode=selectmode)

    for idx, col in enumerate(columns):
        text = heading_texts[idx] if heading_texts else col
        width = column_widths[idx] if column_widths else 120
        tree.heading(col, text=text)
        tree.column(col, width=width)

    v_scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
    h_scrollbar = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
    tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

    tree.grid(row=0, column=0, sticky="nsew")
    v_scrollbar.grid(row=0, column=1, sticky="ns")
    h_scrollbar.grid(row=1, column=0, sticky="ew")
    frame.grid_rowconfigure(0, weight=1)
    frame.grid_columnconfigure(0, weight=1)

    return tree


class InlineEdit:
    """Helper for inline editing of Treeview cells on double-click."""

    def __init__(self, tree: ttk.Treeview, editable_columns: set[int] | None = None) -> None:
        self.tree = tree
        self.editable_columns = editable_columns

    def bind(self) -> None:
        self.tree.bind("<Double-1>", self._on_double_click)

    def _on_double_click(self, event) -> None:
        item_id = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not item_id:
            return
        col_index = int(column.replace("#", "")) - 1
        if self.editable_columns is not None and col_index not in self.editable_columns:
            return

        x, y, width, height = self.tree.bbox(item_id, column)
        values = self.tree.item(item_id, "values")
        if col_index >= len(values):
            return
        value = values[col_index]

        edit_var = tk.StringVar(value=value)
        entry = ttk.Entry(self.tree, textvariable=edit_var)
        entry.place(x=x, y=y, width=width, height=height)

        def on_focus_out(_event=None) -> None:
            new_values = list(self.tree.item(item_id, "values"))
            if col_index < len(new_values):
                new_values[col_index] = edit_var.get()
                self.tree.item(item_id, values=new_values)
            entry.destroy()

        def on_return(event) -> None:
            on_focus_out()

        entry.bind("<FocusOut>", on_focus_out)
        entry.bind("<Return>", on_return)
        entry.focus_set()
