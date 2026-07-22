"""PKMN Top X Checker GUI package."""

from gui.app import App


def run_gui() -> None:
    app = App()
    app.mainloop()
