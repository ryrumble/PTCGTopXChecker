"""Tests for season discovery used by the season dropdown."""

import storage


def test_list_seasons_includes_data_dirs_and_newest_known_season(tmp_path, monkeypatch):
    (tmp_path / "2025-2026").mkdir()
    (tmp_path / "2024-2025").mkdir()
    (tmp_path / "not-a-season").mkdir()
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

    assert storage.list_seasons() == ["2026-2027", "2025-2026", "2024-2025"]


def test_list_seasons_when_no_data_dir_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path / "missing")

    assert storage.list_seasons() == ["2026-2027"]
