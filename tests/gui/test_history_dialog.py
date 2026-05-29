"""HistoryDialog: list, delete, clear, export, import over an in-memory store (headless)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from searchmob_desktop.data.history import InMemoryHistoryStore
from searchmob_desktop.gui.history_dialog import HistoryDialog


def _enabled_store() -> InMemoryHistoryStore:
    store = InMemoryHistoryStore()
    store.set_enabled(True)
    store.add("python", timestamp_ms=1000)
    store.add("rust", timestamp_ms=2000)
    store.add("kotlin", timestamp_ms=3000)
    return store


def test_lists_entries_newest_first(qapp: object) -> None:
    dialog = HistoryDialog(_enabled_store())
    rows = [dialog._list.item(i).text() for i in range(dialog._list.count())]
    assert dialog._list.count() == 3
    assert rows[0].startswith("kotlin")  # newest first


def test_disabled_store_shows_hint_and_no_rows(qapp: object) -> None:
    dialog = HistoryDialog(InMemoryHistoryStore())  # disabled
    assert dialog._list.count() == 0
    assert "off" in dialog._status.text().lower()


def test_delete_selected_removes_from_store(qapp: object) -> None:
    store = _enabled_store()
    dialog = HistoryDialog(store)
    dialog._list.item(0).setSelected(True)  # the newest ("kotlin")
    dialog._on_delete_selected()
    assert {e.query for e in store.export_entries()} == {"python", "rust"}
    assert dialog._list.count() == 2


def test_clear_all_empties_store(qapp: object, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    store = _enabled_store()
    dialog = HistoryDialog(store)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog._on_clear_all()
    assert store.export_entries() == []
    assert dialog._list.count() == 0


def test_export_writes_android_compatible_json(
    qapp: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    out = tmp_path / "history.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    HistoryDialog(_enabled_store())._on_export()

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload[0] == {"query": "kotlin", "timestampMs": 3000}
    assert {row["query"] for row in payload} == {"python", "rust", "kotlin"}


def test_import_merges_from_file(
    qapp: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    src = tmp_path / "in.json"
    src.write_text(json.dumps([{"query": "imported", "timestampMs": 5000}]), encoding="utf-8")
    store = _enabled_store()
    dialog = HistoryDialog(store)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(src), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dialog._on_import()
    assert "imported" in {e.query for e in store.export_entries()}
    assert dialog._list.count() == 4
