"""Search-history viewer, mirroring the Android `HistoryScreen`.

Lists saved queries newest-first with their timestamps, lets the user delete one or clear all, and
exports / imports history as JSON for moving to a new device. All operations go through the
injected `HistoryStore`, so the same dialog works over the in-memory or the encrypted backend.

Export/import use the same shape as the Android app: a JSON array of `{"query", "timestampMs"}`
objects, so a file exported on phone or desktop imports on either.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from searchmob_desktop.data.history import HistoryEntry, HistoryStore

_ENTRY_ROLE = Qt.ItemDataRole.UserRole + 1

# Upper bound on an imported history JSON file (history is small; this stops a memory-exhaustion
# import). 16 MiB comfortably holds years of queries.
_MAX_IMPORT_BYTES = 16 * 1024 * 1024


def _format_timestamp(timestamp_ms: int) -> str:
    """Human-readable local time for a stored entry, fail-soft to the raw value."""
    try:
        return datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OverflowError, OSError):
        return str(timestamp_ms)


class HistoryDialog(QDialog):
    """View, delete, clear, and export/import on-device search history."""

    def __init__(self, history_store: HistoryStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._history = history_store
        self.setWindowTitle("Search history")
        self.setModal(True)
        self.resize(560, 560)

        outer = QVBoxLayout(self)

        self._status = QLabel()
        self._status.setProperty("role", "muted")
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        outer.addWidget(self._list, stretch=1)

        # Row actions.
        row = QHBoxLayout()
        self._delete_btn = QPushButton("Delete selected")
        self._delete_btn.clicked.connect(self._on_delete_selected)
        self._clear_btn = QPushButton("Clear all")
        self._clear_btn.clicked.connect(self._on_clear_all)
        row.addWidget(self._delete_btn)
        row.addWidget(self._clear_btn)
        row.addStretch(1)
        outer.addLayout(row)

        # Portability actions.
        io_row = QHBoxLayout()
        export_btn = QPushButton("Export to file...")
        export_btn.clicked.connect(self._on_export)
        import_btn = QPushButton("Import from file...")
        import_btn.clicked.connect(self._on_import)
        io_row.addWidget(export_btn)
        io_row.addWidget(import_btn)
        io_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        io_row.addWidget(close_btn)
        outer.addLayout(io_row)

        self._refresh()

    # --- Data ---------------------------------------------------------------------------------

    def _refresh(self) -> None:
        self._list.clear()
        enabled = self._history.enabled
        entries = self._history.export_entries() if enabled else []
        for entry in entries:
            item = QListWidgetItem(f"{entry.query}    ({_format_timestamp(entry.timestamp_ms)})")
            item.setData(_ENTRY_ROLE, (entry.query, entry.timestamp_ms))
            self._list.addItem(item)

        if not enabled:
            self._status.setText("Search history is off. Turn it on in Settings to record queries.")
        elif not entries:
            self._status.setText("No saved searches yet.")
        else:
            self._status.setText(
                f"{len(entries)} saved {'search' if len(entries) == 1 else 'searches'}."
            )

        has_entries = bool(entries)
        self._delete_btn.setEnabled(has_entries)
        self._clear_btn.setEnabled(has_entries)

    # --- Actions ------------------------------------------------------------------------------

    def _on_delete_selected(self) -> None:
        for item in self._list.selectedItems():
            data = item.data(_ENTRY_ROLE)
            if isinstance(data, tuple) and len(data) == 2:
                query, timestamp_ms = data
                self._history.delete(str(query), int(timestamp_ms))
        self._refresh()

    def _on_clear_all(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Clear all history?",
            "Delete every saved search on this device? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._history.clear()
            self._refresh()

    def _on_export(self) -> None:
        entries = self._history.export_entries()
        if not entries:
            QMessageBox.information(self, "Nothing to export", "There is no history to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export history", "searchmob-history.json", "JSON files (*.json)"
        )
        if not path:
            return
        payload = [{"query": e.query, "timestampMs": e.timestamp_ms} for e in entries]
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "History exported", f"Exported {len(payload)} entries.")

    def _on_import(self) -> None:
        if not self._history.enabled:
            QMessageBox.information(
                self,
                "History is off",
                "Turn on search history in Settings before importing.",
            )
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import history", "", "JSON files (*.json)")
        if not path:
            return
        entries = self._parse_import_file(path)
        if entries is None:
            return
        added = self._history.import_entries(entries)
        self._refresh()
        QMessageBox.information(
            self,
            "History imported",
            f"Imported {added} new {'entry' if added == 1 else 'entries'}.",
        )

    def _parse_import_file(self, path: str) -> list[HistoryEntry] | None:
        """Parse the export JSON into entries. Returns `None` (after warning) on a bad file."""
        import os

        from searchmob_desktop.data.history import HistoryEntry

        try:
            # Cap the file size so a huge/malicious import can't exhaust memory.
            if os.path.getsize(path) > _MAX_IMPORT_BYTES:
                QMessageBox.warning(
                    self,
                    "File too large",
                    "That history file is too large to import (limit 16 MiB).",
                )
                return None
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "Import failed", f"Could not read the file: {exc}")
            return None
        if not isinstance(raw, list):
            QMessageBox.warning(self, "Import failed", "The file is not a history export.")
            return None
        entries: list[HistoryEntry] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            query = item.get("query")
            # Accept both the Android `timestampMs` and a snake_case fallback.
            ts = item.get("timestampMs", item.get("timestamp_ms"))
            if not isinstance(query, str) or not query:
                continue
            if not isinstance(ts, int):
                continue
            entries.append(HistoryEntry(query=query, timestamp_ms=ts))
        return entries
