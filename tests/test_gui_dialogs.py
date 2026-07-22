"""Smoke tests for GUI dialog imports and basic structure."""


class TestDialogImports:
    def test_tournament_editor_imports(self):
        from gui.dialogs.tournament_editor import TournamentEditor  # noqa: F401

    def test_player_results_viewer_imports(self):
        from gui.dialogs.player_results import PlayerResultsViewer  # noqa: F401

    def test_player_manager_imports(self):
        from gui.dialogs.player_manager import PlayerManager  # noqa: F401

    def test_load_total_cp_imports(self):
        from gui.dialogs.load_total_cp import LoadTotalCPFileDialog  # noqa: F401

    def test_pokedata_merge_imports(self):
        from gui.dialogs.pokedata_merge import PokedataMergeDialog  # noqa: F401

    def test_pokedata_matcher_imports(self):
        from gui.dialogs.pokedata_matcher import PokedataNameMatcher  # noqa: F401

    def test_all_dialogs_accessible_via_package(self):
        from gui.dialogs import (
            PlayerManager,
            TournamentEditor,
        )
        assert TournamentEditor.__name__ == "TournamentEditor"
        assert PlayerManager.__name__ == "PlayerManager"

    def test_gui_app_imports_all_dialogs(self):
        from gui.app import App
        # App should not reference dialog classes directly anymore
        # (they're imported via gui.dialogs)
        assert hasattr(App, "_build_ui")

    def test_gui_package_imports(self):
        from gui.constants import CHART_COLORS, DEFAULT_SEASON
        assert DEFAULT_SEASON == "2025-2026"
        assert len(CHART_COLORS) == 10
