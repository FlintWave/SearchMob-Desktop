"""Tabbed settings dialog mirroring the Android `SettingsScreen`.

Sections per the original spec: Appearance, Search engines, BYO API keys, Search history,
Suggestions, Updates, Network, Device setup. All toggles persist to `JsonPreferencesStore`
immediately on change so an Apply / OK button is unnecessary. The BYO keys go to the encrypted
vault. The network toggle gate-keeps behind the same warning text the Android dialog uses.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from searchmob_desktop.data import (
    ZERO_KNOWLEDGE_UNRECOVERABLE_WARNING,
    BootstrapMetadataStore,
    EncryptedPreferences,
    InMemoryHistoryStore,
    StorageBootstrap,
    WrapMode,
)
from searchmob_desktop.data.crypto.keyring_kek import KeyringKekStore
from searchmob_desktop.data.crypto.wrap import KeyringDekWrapper
from searchmob_desktop.engines import make_privacy_client
from searchmob_desktop.gui.browser_setup_dialog import BrowserSetupDialog
from searchmob_desktop.gui.engines_catalog import ENGINE_CATALOG, is_engine_enabled
from searchmob_desktop.gui.theme import DARK, LIGHT, SYSTEM
from searchmob_desktop.gui.workers import AsyncWorker
from searchmob_desktop.prefs import JsonPreferencesStore, UserPreferences
from searchmob_desktop.update import RELEASES_PAGE_URL, UpdateInfo, fetch_latest
from searchmob_desktop.version import __version__

if TYPE_CHECKING:
    from searchmob_desktop.gui.server_controller import LocalServerController

NETWORK_WARNING = (
    "Only use this on protected networks shared with people and machines you know and trust, "
    "such as a Tailscale network. Never enable it on open or public Wi-Fi, like hotel or "
    "coffee-shop networks. SearchMob has no password, so anyone who can reach this computer "
    "on the network can run searches through it."
)

# Encrypted prefs keys for the two BYO API keys. Kept short so the on-disk blob stays small.
_BRAVE_KEY = "brave_api_key"
_MOJEEK_KEY = "mojeek_api_key"


def _vault_prefs_path(metadata_store: BootstrapMetadataStore) -> Path:
    """Companion file location for the encrypted prefs blob.

    Lives next to the vault metadata so the whole encrypted set is co-located. Matches the
    Android approach of putting both files under the same data dir.
    """
    return metadata_store.path.parent / "encrypted_prefs.bin"


class SettingsDialog(QDialog):
    """The settings dialog. Owns its own `StorageBootstrap` so the lock state survives a re-open."""

    themeChanged = Signal(str)
    historyCleared = Signal()

    def __init__(
        self,
        prefs_store: JsonPreferencesStore,
        server_controller: LocalServerController | None = None,
        history_store: InMemoryHistoryStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(720, 640)

        self._prefs_store = prefs_store
        self._server_controller = server_controller
        self._history_store = history_store
        self._storage: StorageBootstrap | None = None
        self._pool = QThreadPool.globalInstance()

        self._prefs = prefs_store.load()

        outer = QVBoxLayout(self)
        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_appearance_tab(), "Appearance")
        self._tabs.addTab(self._build_engines_tab(), "Search engines")
        self._tabs.addTab(self._build_keys_tab(), "API keys")
        self._tabs.addTab(self._build_history_tab(), "Search history")
        self._tabs.addTab(self._build_suggestions_tab(), "Suggestions")
        self._tabs.addTab(self._build_updates_tab(), "Updates")
        self._tabs.addTab(self._build_network_tab(), "Network")
        self._tabs.addTab(self._build_device_tab(), "Device setup")
        outer.addWidget(self._tabs)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        outer.addLayout(bottom)

    # --- Persistence helper ------------------------------------------------------------------

    def _save(self, new_prefs: UserPreferences) -> None:
        self._prefs = new_prefs
        try:
            self._prefs_store.save(new_prefs)
        except OSError as exc:
            QMessageBox.warning(self, "Could not save settings", str(exc))

    # --- Appearance --------------------------------------------------------------------------

    def _build_appearance_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Theme"))

        group = QButtonGroup(tab)
        radios = [
            (LIGHT, QRadioButton("Light")),
            (DARK, QRadioButton("Dark")),
            (SYSTEM, QRadioButton("Follow system")),
        ]
        current = self._prefs.theme
        for value, radio in radios:
            radio.setChecked(value == current)
            group.addButton(radio)
            layout.addWidget(radio)

        def _on_changed() -> None:
            for value, radio in radios:
                if radio.isChecked():
                    self._save(replace(self._prefs, theme=value))
                    self.themeChanged.emit(value)
                    return

        for _, radio in radios:
            radio.toggled.connect(_on_changed)
        layout.addStretch(1)
        return tab

    # --- Engines -----------------------------------------------------------------------------

    def _build_engines_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Pick which engines run on every search."))

        existing = dict(self._prefs.engine_enabled) if self._prefs.engine_enabled else {}

        def _make_toggle(engine_id: str, label: str, needs_key: bool) -> QCheckBox:
            cb = QCheckBox(label + (" (needs an API key, below)" if needs_key else ""))
            cb.setChecked(is_engine_enabled(engine_id, existing))

            def _on_toggled(checked: bool) -> None:
                current = dict(self._prefs.engine_enabled) if self._prefs.engine_enabled else {}
                current[engine_id] = checked
                self._save(replace(self._prefs, engine_enabled=current))

            cb.toggled.connect(_on_toggled)
            return cb

        for entry in ENGINE_CATALOG:
            layout.addWidget(_make_toggle(entry.id, entry.display_name, entry.requires_api_key))

        note = QLabel(
            "Engine changes apply to the next search. Restart the local server (if running) "
            "to pick up the new engine list there too."
        )
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        layout.addWidget(note)
        layout.addStretch(1)
        return tab

    # --- API keys ----------------------------------------------------------------------------

    def _build_keys_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(
            QLabel(
                "Bring-your-own API keys. Keys are stored in your encrypted vault and never "
                "appear in plain text on disk."
            )
        )

        self._brave_status = QLabel(self._key_status_text("Brave Search", _BRAVE_KEY))
        self._brave_input = QLineEdit()
        self._brave_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._brave_input.setPlaceholderText("Brave Search API key")
        layout.addWidget(self._brave_status)
        layout.addWidget(self._brave_input)
        brave_row = QHBoxLayout()
        brave_save = QPushButton("Save Brave key")
        brave_clear = QPushButton("Clear Brave key")
        brave_save.clicked.connect(lambda: self._save_api_key(_BRAVE_KEY, self._brave_input))
        brave_clear.clicked.connect(lambda: self._clear_api_key(_BRAVE_KEY, self._brave_input))
        brave_row.addWidget(brave_save)
        brave_row.addWidget(brave_clear)
        brave_row.addStretch(1)
        layout.addLayout(brave_row)

        self._mojeek_status = QLabel(self._key_status_text("Mojeek", _MOJEEK_KEY))
        self._mojeek_input = QLineEdit()
        self._mojeek_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._mojeek_input.setPlaceholderText("Mojeek API key")
        layout.addWidget(self._mojeek_status)
        layout.addWidget(self._mojeek_input)
        mojeek_row = QHBoxLayout()
        mojeek_save = QPushButton("Save Mojeek key")
        mojeek_clear = QPushButton("Clear Mojeek key")
        mojeek_save.clicked.connect(lambda: self._save_api_key(_MOJEEK_KEY, self._mojeek_input))
        mojeek_clear.clicked.connect(lambda: self._clear_api_key(_MOJEEK_KEY, self._mojeek_input))
        mojeek_row.addWidget(mojeek_save)
        mojeek_row.addWidget(mojeek_clear)
        mojeek_row.addStretch(1)
        layout.addLayout(mojeek_row)

        note = QLabel(
            "The CLI also reads SEARCHMOB_BRAVE_API_KEY and SEARCHMOB_MOJEEK_API_KEY from the "
            "environment. Either source is fine."
        )
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        layout.addWidget(note)
        layout.addStretch(1)
        return tab

    def _ensure_storage(self) -> StorageBootstrap | None:
        """Build (and bootstrap on first use) the vault. Returns `None` on failure.

        First-call: if no metadata file exists, do `first_run()` to initialize OS-keyring mode.
        Subsequent calls reuse the same `StorageBootstrap` instance so the unlocked DEK persists.
        """
        if self._storage is not None:
            return self._storage
        try:
            metadata_store = BootstrapMetadataStore()
            fallback_path = metadata_store.path.parent / "keyring-fallback.kek"
            kek_store = KeyringKekStore(fallback_file_path=fallback_path)
            wrapper = KeyringDekWrapper(kek_store)
            storage = StorageBootstrap(
                metadata_store=metadata_store,
                keyring_wrapper=wrapper,
                keyring_clearer=kek_store.clear,
            )
            if storage.mode is None:
                storage.first_run()
            elif storage.mode == WrapMode.OS and not storage.is_unlocked:
                storage.unlock_keyring()
            self._storage = storage
        except Exception as exc:
            QMessageBox.warning(self, "Vault unavailable", str(exc))
            return None
        return self._storage

    def _vault_prefs(self) -> EncryptedPreferences | None:
        storage = self._ensure_storage()
        if storage is None or not storage.is_unlocked:
            if storage is not None and storage.mode == WrapMode.PASSPHRASE:
                QMessageBox.information(
                    self,
                    "Vault locked",
                    "Your vault is in zero-knowledge mode. Unlock it from the CLI "
                    "(searchmob-desktop vault unlock) before saving keys here.",
                )
            return None
        prefs_file = _vault_prefs_path(storage.metadata_store)
        return EncryptedPreferences(prefs_file, dek_provider=storage.dek_provider())

    def _key_status_text(self, label: str, key: str) -> str:
        try:
            metadata_store = BootstrapMetadataStore()
            if not metadata_store.path.exists():
                return f"{label}: not set"
            # We do not pre-unlock here; the status is best-effort while the vault is locked.
            prefs_file = _vault_prefs_path(metadata_store)
            if not prefs_file.exists():
                return f"{label}: not set"
            return f"{label}: set"
        except Exception:
            return f"{label}: status unavailable"

    def _save_api_key(self, key: str, input_widget: QLineEdit) -> None:
        value = input_widget.text().strip()
        if not value:
            return
        ep = self._vault_prefs()
        if ep is None:
            return
        try:
            ep.put(key, value)
        except OSError as exc:
            QMessageBox.warning(self, "Could not save key", str(exc))
            return
        input_widget.clear()
        label = "Brave Search" if key == _BRAVE_KEY else "Mojeek"
        status = self._brave_status if key == _BRAVE_KEY else self._mojeek_status
        status.setText(f"{label}: set")

    def _clear_api_key(self, key: str, input_widget: QLineEdit) -> None:
        ep = self._vault_prefs()
        if ep is None:
            return
        try:
            ep.remove(key)
        except OSError as exc:
            QMessageBox.warning(self, "Could not clear key", str(exc))
            return
        input_widget.clear()
        label = "Brave Search" if key == _BRAVE_KEY else "Mojeek"
        status = self._brave_status if key == _BRAVE_KEY else self._mojeek_status
        status.setText(f"{label}: cleared")

    # --- Search history ----------------------------------------------------------------------

    def _build_history_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        cb = QCheckBox("Store search history")
        cb.setChecked(self._prefs.history_enabled)
        sub = QLabel(
            "Off by default. When on, queries are stored locally and encrypted at rest. "
            "Toggling here takes effect on the next search."
        )
        sub.setWordWrap(True)
        sub.setProperty("role", "muted")

        def _on_toggled(checked: bool) -> None:
            self._save(replace(self._prefs, history_enabled=checked))
            if self._history_store is not None:
                self._history_store.set_enabled(checked)

        cb.toggled.connect(_on_toggled)
        layout.addWidget(cb)
        layout.addWidget(sub)

        clear_btn = QPushButton("Clear history")
        clear_btn.clicked.connect(self._on_clear_history)
        layout.addWidget(clear_btn)

        zk_btn = QPushButton("Set up zero-knowledge passphrase")
        zk_btn.clicked.connect(self._on_setup_zero_knowledge)
        layout.addWidget(zk_btn)

        layout.addStretch(1)
        return tab

    def _on_clear_history(self) -> None:
        if self._history_store is not None:
            try:
                self._history_store.clear()
            except Exception as exc:
                QMessageBox.warning(self, "Could not clear history", str(exc))
                return
            self.historyCleared.emit()
            QMessageBox.information(self, "History cleared", "Your search history was cleared.")

    def _on_setup_zero_knowledge(self) -> None:
        # The warning + the matched-pair passphrase capture happen in one dialog so we cannot
        # half-arm the mode. If the warning is dismissed the function returns before touching
        # the vault.
        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setWindowTitle("Zero-knowledge encryption")
        confirm.setText("Set up zero-knowledge passphrase?")
        confirm.setInformativeText(ZERO_KNOWLEDGE_UNRECOVERABLE_WARNING)
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok
        )
        if confirm.exec() != QMessageBox.StandardButton.Ok:
            return

        new_pass = _PassphraseEntryDialog(self).exec_and_get()
        if new_pass is None:
            return

        storage = self._ensure_storage()
        if storage is None or not storage.is_unlocked:
            QMessageBox.warning(
                self,
                "Vault not ready",
                "The vault is not unlocked. Run searchmob-desktop vault unlock first.",
            )
            return
        try:
            buf = bytearray(new_pass.encode("utf-8"))
            storage.enable_zero_knowledge(buf, warning_confirmed=True)
            # Zero our copy of the buffer so the passphrase does not linger.
            for i in range(len(buf)):
                buf[i] = 0
        except Exception as exc:
            QMessageBox.warning(self, "Could not enable zero-knowledge", str(exc))
            return
        QMessageBox.information(
            self,
            "Zero-knowledge enabled",
            "The vault is now encrypted with your passphrase. Keep it safe; the data is "
            "unrecoverable without it.",
        )

    # --- Suggestions -------------------------------------------------------------------------

    def _build_suggestions_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        cb = QCheckBox("Live suggestions from the web")
        cb.setChecked(self._prefs.upstream_suggestions_enabled)
        sub = QLabel(
            "Off by default. When on, what you type is sent to DuckDuckGo's suggestion service "
            "through the privacy proxy as you type, to offer live autocomplete. Off keeps "
            "suggestions to your local history only."
        )
        sub.setWordWrap(True)
        sub.setProperty("role", "muted")

        def _on_toggled(checked: bool) -> None:
            self._save(replace(self._prefs, upstream_suggestions_enabled=checked))

        cb.toggled.connect(_on_toggled)
        layout.addWidget(cb)
        layout.addWidget(sub)
        layout.addStretch(1)
        return tab

    # --- Updates -----------------------------------------------------------------------------

    def _build_updates_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        cb = QCheckBox("Check for updates on launch")
        cb.setChecked(self._prefs.update_check_enabled)
        sub = QLabel(
            "On by default. Checks GitHub about once a day for a newer release, through the "
            "privacy proxy. This is the only outbound traffic that is not a search. Turn it "
            "off to disable it."
        )
        sub.setWordWrap(True)
        sub.setProperty("role", "muted")

        def _on_toggled(checked: bool) -> None:
            self._save(replace(self._prefs, update_check_enabled=checked))

        cb.toggled.connect(_on_toggled)
        layout.addWidget(cb)
        layout.addWidget(sub)

        check_now = QPushButton("Check now")
        check_now.clicked.connect(self._on_check_now)
        layout.addWidget(check_now)
        layout.addStretch(1)
        return tab

    def _on_check_now(self) -> None:
        from searchmob_desktop.update import VersionTag

        async def _probe() -> UpdateInfo | None:
            async with make_privacy_client(4.0) as client:
                return await fetch_latest(client)

        worker: AsyncWorker[UpdateInfo | None] = AsyncWorker(_probe)

        def _on_finished(info_obj: object) -> None:
            stamped = replace(self._prefs, last_update_check_ms=int(time.time() * 1000))
            self._save(stamped)
            if not isinstance(info_obj, UpdateInfo):
                QMessageBox.warning(
                    self,
                    "Update check failed",
                    f"Could not reach GitHub. Releases page: {RELEASES_PAGE_URL}",
                )
                return
            info: UpdateInfo = info_obj
            parsed = VersionTag.parse(__version__)
            current = parsed.to_version_code() if parsed else 0
            if info.is_newer_than(current):
                v = info.latest_version
                QMessageBox.information(
                    self,
                    "Update available",
                    f"A newer version is available: "
                    f"{v.year:02d}.{v.month:02d}.{v.build:02d}\n{info.release_url}",
                )
            else:
                QMessageBox.information(
                    self,
                    "Up to date",
                    f"You are on the latest version ({__version__}).",
                )

        def _on_failed(message: str) -> None:
            QMessageBox.warning(self, "Update check failed", message)

        worker.signals.finished.connect(_on_finished)
        worker.signals.failed.connect(_on_failed)
        self._pool.start(worker)

    # --- Network -----------------------------------------------------------------------------

    def _build_network_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        cb = QCheckBox("Allow access from your network (advanced)")
        cb.setChecked(self._prefs.network_access_enabled)
        sub = QLabel("Off by default. When on, other devices on your network can reach SearchMob.")
        sub.setWordWrap(True)
        sub.setProperty("role", "muted")

        def _on_toggled(checked: bool) -> None:
            if checked and not self._prefs.network_access_enabled:
                # Show the warning modal. If declined, snap the checkbox back to off.
                confirm = QMessageBox(self)
                confirm.setIcon(QMessageBox.Icon.Warning)
                confirm.setWindowTitle("Allow network access?")
                confirm.setText("Allow network access?")
                confirm.setInformativeText(NETWORK_WARNING)
                confirm.setStandardButtons(
                    QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok
                )
                if confirm.exec() != QMessageBox.StandardButton.Ok:
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
                    return
            self._save(replace(self._prefs, network_access_enabled=checked))
            # If the server is running, tell the controller; takes effect on next restart.
            if self._server_controller is not None:
                from searchmob_desktop.server import LOOPBACK_HOST

                self._server_controller.set_host("0.0.0.0" if checked else LOOPBACK_HOST)

        cb.toggled.connect(_on_toggled)
        layout.addWidget(cb)
        layout.addWidget(sub)

        info = QLabel(
            "When on, restart the local server from the main window so the new bind address "
            "takes effect."
        )
        info.setWordWrap(True)
        info.setProperty("role", "muted")
        layout.addWidget(info)
        layout.addStretch(1)
        return tab

    # --- Device setup ------------------------------------------------------------------------

    def _build_device_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        intro = QLabel(
            "Set SearchMob as your browser's default search engine so address-bar searches go "
            "through your private local server."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        btn = QPushButton("Open browser setup")
        btn.clicked.connect(self._open_browser_setup)
        layout.addWidget(btn)

        about_btn = QPushButton("About and privacy")
        about_btn.clicked.connect(self._open_about)
        layout.addWidget(about_btn)
        layout.addStretch(1)
        return tab

    def _open_browser_setup(self) -> None:
        from searchmob_desktop.server import LOOPBACK_HOST

        host = LOOPBACK_HOST
        port: int | None = None
        if self._server_controller is not None and self._server_controller.is_running:
            host = "127.0.0.1"
            port = 8787  # default; the controller does not expose the live port today
        dialog = BrowserSetupDialog(host=host, port=port, parent=self)
        dialog.exec()

    def _open_about(self) -> None:
        from searchmob_desktop.gui.about_dialog import AboutDialog

        AboutDialog(self).exec()


class _PassphraseEntryDialog(QDialog):
    """Two-field passphrase capture. The OK button stays disabled until both fields match."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set zero-knowledge passphrase")
        self.setModal(True)
        layout = QVBoxLayout(self)

        warning = QLabel(ZERO_KNOWLEDGE_UNRECOVERABLE_WARNING)
        warning.setWordWrap(True)
        warning.setProperty("role", "caveat-text")
        layout.addWidget(warning)

        self._p1 = QLineEdit()
        self._p1.setEchoMode(QLineEdit.EchoMode.Password)
        self._p1.setPlaceholderText("New passphrase")
        self._p2 = QLineEdit()
        self._p2.setEchoMode(QLineEdit.EchoMode.Password)
        self._p2.setPlaceholderText("Confirm passphrase")
        layout.addWidget(self._p1)
        layout.addWidget(self._p2)

        self._status = QLabel("Enter a passphrase and confirm it.")
        self._status.setProperty("role", "muted")
        layout.addWidget(self._status)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self._ok = QPushButton("Enable zero-knowledge")
        self._ok.setEnabled(False)
        self._ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self._ok)
        layout.addLayout(row)

        self._p1.textChanged.connect(self._recheck)
        self._p2.textChanged.connect(self._recheck)

    def _recheck(self) -> None:
        a = self._p1.text()
        b = self._p2.text()
        if not a or not b:
            self._status.setText("Enter a passphrase and confirm it.")
            self._ok.setEnabled(False)
        elif a != b:
            self._status.setText("Passphrases do not match.")
            self._ok.setEnabled(False)
        else:
            self._status.setText("Passphrases match.")
            self._ok.setEnabled(True)

    def exec_and_get(self) -> str | None:
        if self.exec() == QDialog.DialogCode.Accepted:
            return self._p1.text()
        return None


__all__ = ["SettingsDialog"]
