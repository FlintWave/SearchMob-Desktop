"""MainWindow binds the server per the saved network-mode preference at startup."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from searchmob_desktop.gui.main_window import MainWindow
from searchmob_desktop.prefs import JsonPreferencesStore


def _store(tmp_path: Path, *, network: bool) -> JsonPreferencesStore:
    store = JsonPreferencesStore(path=tmp_path / "prefs.json")
    store.save(dataclasses.replace(store.load(), network_access_enabled=network))
    return store


def test_binds_all_interfaces_when_network_mode_on(qapp: object, tmp_path: Path) -> None:
    window = MainWindow(prefs_store=_store(tmp_path, network=True))
    assert window._server._host == "0.0.0.0"


def test_binds_loopback_when_network_mode_off(qapp: object, tmp_path: Path) -> None:
    window = MainWindow(prefs_store=_store(tmp_path, network=False))
    assert window._server._host == "127.0.0.1"
