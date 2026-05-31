"""Tabbed settings dialog mirroring the Android `SettingsScreen`.

Sections per the original spec: Appearance, Search engines, BYO API keys, Search history,
Suggestions, Updates, Network, Device setup. All toggles persist to `JsonPreferencesStore`
immediately on change so an Apply / OK button is unnecessary. The BYO keys go to the encrypted
vault. The network toggle gate-keeps behind the same warning text the Android dialog uses.
"""

from __future__ import annotations

import os
import secrets
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
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
    HistoryStore,
    StorageBootstrap,
    WrapMode,
)
from searchmob_desktop.data.api_keys import BRAVE_KEY, KAGI_KEY, MOJEEK_KEY
from searchmob_desktop.data.crypto.keyring_kek import KeyringKekStore
from searchmob_desktop.data.crypto.wrap import KeyringDekWrapper
from searchmob_desktop.data.ranking_store import load_ranking_rules, save_ranking_rules
from searchmob_desktop.engines import make_privacy_client
from searchmob_desktop.engines.local_llm import LlmBackend, detect_backends
from searchmob_desktop.engines.rank import (
    RankingRules,
    parse_goggles,
)
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

# Encrypted prefs keys for the BYO API keys come from `data.api_keys` so the write side here and
# the read side in the engine builders never drift. Local aliases keep the call sites terse.
_BRAVE_KEY = BRAVE_KEY
_MOJEEK_KEY = MOJEEK_KEY
_KAGI_KEY = KAGI_KEY

# Upper bound on imported goggle / ranking-rules files. These are tiny in practice; the cap stops a
# multi-GB file (malicious "community goggle" or a mistaken pick) from being read fully into memory.
_MAX_IMPORT_BYTES = 4 * 1024 * 1024

# The Local AI model dropdown stores each item's (base_url, model) as a single string keyed by this
# separator. A string is used instead of a tuple because QComboBox.findData matches strings reliably
# but not Python tuples. The separator is a control char that never appears in a URL or model id.
_LLM_KEY_SEP = "\x1f"


def _llm_key(base_url: str, model: str) -> str:
    """Pack a (base_url, model) pair into the dropdown's string item-data key."""
    return f"{base_url}{_LLM_KEY_SEP}{model}"


def _parse_llm_key(data: object) -> tuple[str, str] | None:
    """Unpack a dropdown key back into (base_url, model), or None for the "Off" entry / bad data."""
    if isinstance(data, str) and _LLM_KEY_SEP in data:
        base_url, model = data.split(_LLM_KEY_SEP, 1)
        if base_url and model:
            return base_url, model
    return None


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
    rulesChanged = Signal()

    def __init__(
        self,
        prefs_store: JsonPreferencesStore,
        server_controller: LocalServerController | None = None,
        history_store: HistoryStore | None = None,
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
        # Working copy of the personalization rules; each edit persists to the vault and emits
        # `rulesChanged` so the main window re-ranks the current results live.
        self._ranking = load_ranking_rules()

        outer = QVBoxLayout(self)
        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_appearance_tab(), "Appearance")
        self._tabs.addTab(self._build_engines_tab(), "Search engines")
        self._tabs.addTab(self._build_keys_tab(), "API keys")
        self._tabs.addTab(self._build_ranking_tab(), "Result ranking")
        self._local_ai_tab_index = self._tabs.addTab(self._build_local_ai_tab(), "Local AI")
        self._tabs.addTab(self._build_history_tab(), "Search history")
        self._tabs.addTab(self._build_suggestions_tab(), "Suggestions")
        self._tabs.addTab(self._build_updates_tab(), "Updates")
        self._tabs.addTab(self._build_network_tab(), "Network")
        self._tabs.addTab(self._build_device_tab(), "Device setup")
        # Detect local models the first time the user opens the Local AI tab (not on every dialog
        # construction, which would probe loopback during unrelated settings work and in tests).
        self._tabs.currentChanged.connect(self._on_settings_tab_changed)
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

    # --- Result ranking ----------------------------------------------------------------------

    def _build_ranking_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(
            QLabel(
                "Personalize results locally. Block / lower / raise / pin a domain by "
                "right-clicking a result; pick a scope to focus results on a set of sites; or "
                "import goggles (Brave Goggles format). Rules are stored in your encrypted vault "
                "and applied on this device only."
            )
        )

        slop_row = QHBoxLayout()
        slop_row.addWidget(QLabel("Filter AI-generated / low-quality sites:"))
        self._slop_combo = QComboBox()
        for label, value in (("Downrank", "downrank"), ("Hide", "hide"), ("Off", "off")):
            self._slop_combo.addItem(label, value)
        self._slop_combo.setCurrentIndex(
            max(0, self._slop_combo.findData(self._prefs.ai_slop_mode))
        )
        self._slop_combo.currentIndexChanged.connect(self._on_slop_changed)
        slop_row.addWidget(self._slop_combo, stretch=1)
        layout.addLayout(slop_row)
        slop_help = QLabel(
            "On by default. Downrank pushes known AI content farms and low-quality sites below "
            "other results; Hide removes them. The bundled list is applied on your device - your "
            "query never leaves it for filtering - and your own domain rules above always win."
        )
        slop_help.setWordWrap(True)
        slop_help.setProperty("role", "muted")
        layout.addWidget(slop_help)

        lens_row = QHBoxLayout()
        lens_row.addWidget(QLabel("Active scope:"))
        self._lens_combo = QComboBox()
        self._lens_combo.currentIndexChanged.connect(self._on_lens_selected)
        lens_row.addWidget(self._lens_combo, stretch=1)
        layout.addLayout(lens_row)

        layout.addWidget(QLabel("Domain rules"))
        self._rules_list = QListWidget()
        self._rule_domains: list[str] = []
        layout.addWidget(self._rules_list, stretch=1)
        rules_btns = QHBoxLayout()
        remove_btn = QPushButton("Remove selected")
        remove_btn.clicked.connect(self._on_remove_domain_rule)
        clear_rules_btn = QPushButton("Clear all domain rules")
        clear_rules_btn.clicked.connect(self._on_clear_domain_rules)
        rules_btns.addWidget(remove_btn)
        rules_btns.addWidget(clear_rules_btn)
        rules_btns.addStretch(1)
        layout.addLayout(rules_btns)

        self._goggle_status = QLabel()
        self._goggle_status.setProperty("role", "muted")
        layout.addWidget(self._goggle_status)
        self._goggle_text = QPlainTextEdit()
        self._goggle_text.setPlaceholderText(
            "Paste goggle rules, e.g.  $discard,site=example.com  or  $boost,site=dev.to"
        )
        self._goggle_text.setFixedHeight(72)
        layout.addWidget(self._goggle_text)
        goggle_btns = QHBoxLayout()
        import_paste_btn = QPushButton("Import pasted goggles")
        import_paste_btn.clicked.connect(self._on_import_goggles_pasted)
        import_file_btn = QPushButton("Import goggles file...")
        import_file_btn.clicked.connect(self._on_import_goggles_file)
        clear_goggles_btn = QPushButton("Clear goggles")
        clear_goggles_btn.clicked.connect(self._on_clear_goggles)
        goggle_btns.addWidget(import_paste_btn)
        goggle_btns.addWidget(import_file_btn)
        goggle_btns.addWidget(clear_goggles_btn)
        goggle_btns.addStretch(1)
        layout.addLayout(goggle_btns)

        io_row = QHBoxLayout()
        export_btn = QPushButton("Export rules...")
        export_btn.clicked.connect(self._on_export_rules)
        import_btn = QPushButton("Import rules...")
        import_btn.clicked.connect(self._on_import_rules)
        io_row.addWidget(export_btn)
        io_row.addWidget(import_btn)
        io_row.addStretch(1)
        layout.addLayout(io_row)

        self._refresh_ranking_widgets()
        return tab

    def _save_ranking(self, rules: RankingRules) -> None:
        if not save_ranking_rules(rules):
            QMessageBox.warning(
                self,
                "Could not save ranking rules",
                "The encrypted vault is unavailable, so the rules could not be saved. Enable "
                "search history or save an API key first to initialize the vault.",
            )
            return
        self._ranking = rules
        self.rulesChanged.emit()
        self._refresh_ranking_widgets()

    def _refresh_ranking_widgets(self) -> None:
        self._lens_combo.blockSignals(True)
        self._lens_combo.clear()
        self._lens_combo.addItem("None")
        names = [lens.name for lens in self._ranking.lenses]
        for name in names:
            self._lens_combo.addItem(name)
        active = self._ranking.active_lens
        self._lens_combo.setCurrentIndex(names.index(active) + 1 if active in names else 0)
        self._lens_combo.blockSignals(False)

        self._rules_list.clear()
        self._rule_domains = []
        for domain, rule in sorted(self._ranking.domain_rules.items()):
            self._rules_list.addItem(f"{domain}  -  {rule.value}")
            self._rule_domains.append(domain)

        count = len(self._ranking.goggles)
        self._goggle_status.setText(
            f"{count} goggle rule{'' if count == 1 else 's'} imported."
            if count
            else "No goggles imported."
        )

    def _on_lens_selected(self, index: int) -> None:
        name = None if index <= 0 else self._lens_combo.currentText()
        self._save_ranking(replace(self._ranking, active_lens=name))

    def _on_slop_changed(self) -> None:
        """AI-slop filter mode changed: persist it and re-rank the current results live."""
        self._save(replace(self._prefs, ai_slop_mode=str(self._slop_combo.currentData())))
        self.rulesChanged.emit()

    def _on_remove_domain_rule(self) -> None:
        row = self._rules_list.currentRow()
        if 0 <= row < len(self._rule_domains):
            self._save_ranking(self._ranking.without_domain_rule(self._rule_domains[row]))

    def _on_clear_domain_rules(self) -> None:
        self._save_ranking(replace(self._ranking, domain_rules={}))

    def _on_import_goggles_pasted(self) -> None:
        self._import_goggles(self._goggle_text.toPlainText())
        self._goggle_text.clear()

    def _on_import_goggles_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import goggles", "", "Goggle files (*.goggle *.txt);;All files (*)"
        )
        if not path:
            return
        text = self._read_capped_text(path)
        if text is None:
            return
        self._import_goggles(text)

    def _import_goggles(self, text: str) -> None:
        parsed = parse_goggles(text)
        if not parsed:
            QMessageBox.information(
                self, "No goggle rules", "Nothing recognizable to import from that text."
            )
            return
        self._save_ranking(replace(self._ranking, goggles=self._ranking.goggles + tuple(parsed)))
        QMessageBox.information(self, "Goggles imported", f"Imported {len(parsed)} rule(s).")

    def _on_clear_goggles(self) -> None:
        self._save_ranking(replace(self._ranking, goggles=()))

    def _on_export_rules(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export ranking rules", "searchmob-ranking.json", "JSON files (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._ranking.to_json())
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Rules exported", "Your ranking rules were exported.")

    def _on_import_rules(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import ranking rules", "", "JSON files (*.json);;All files (*)"
        )
        if not path:
            return
        text = self._read_capped_text(path)
        if text is None:
            return
        self._save_ranking(RankingRules.from_json(text))
        QMessageBox.information(self, "Rules imported", "Your ranking rules were imported.")

    def _read_capped_text(self, path: str) -> str | None:
        """Read a small import file, rejecting anything over the size cap. Warns on failure."""
        try:
            if os.path.getsize(path) > _MAX_IMPORT_BYTES:
                QMessageBox.warning(
                    self, "File too large", "That file is too large to import (limit 4 MiB)."
                )
                return None
            with open(path, encoding="utf-8") as fh:
                return fh.read(_MAX_IMPORT_BYTES + 1)
        except OSError as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return None

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
        brave_caveat = QLabel(
            "Note: Brave's Search API terms prohibit storing or caching results. If you enable "
            "search history with a Brave key, Brave results may be saved locally — that is your "
            "responsibility under Brave's terms."
        )
        brave_caveat.setWordWrap(True)
        brave_caveat.setProperty("role", "muted")
        layout.addWidget(brave_caveat)

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

        self._kagi_status = QLabel(self._key_status_text("Kagi", _KAGI_KEY))
        self._kagi_input = QLineEdit()
        self._kagi_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._kagi_input.setPlaceholderText("Kagi API key (from kagi.com/settings/api)")
        layout.addWidget(self._kagi_status)
        layout.addWidget(self._kagi_input)
        kagi_row = QHBoxLayout()
        kagi_save = QPushButton("Save Kagi key")
        kagi_clear = QPushButton("Clear Kagi key")
        kagi_save.clicked.connect(lambda: self._save_api_key(_KAGI_KEY, self._kagi_input))
        kagi_clear.clicked.connect(lambda: self._clear_api_key(_KAGI_KEY, self._kagi_input))
        kagi_row.addWidget(kagi_save)
        kagi_row.addWidget(kagi_clear)
        kagi_row.addStretch(1)
        layout.addLayout(kagi_row)

        note = QLabel(
            "The CLI also reads SEARCHMOB_BRAVE_API_KEY, SEARCHMOB_MOJEEK_API_KEY, and "
            "SEARCHMOB_KAGI_API_KEY from the environment. Either source is fine."
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

    # --- Local AI ----------------------------------------------------------------------------

    def _build_local_ai_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        intro = QLabel(
            "Show a short answer above results, generated by a language model running on this "
            "computer. It uses only your search results and never leaves your device. Pick a model "
            "below to turn it on (you need Ollama on port 11434 or LM Studio on port 1234). A "
            "large model can take a while to answer the first time."
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "muted")
        layout.addWidget(intro)

        # One control does both jobs: the Model dropdown lists "Off" plus every model found on this
        # machine. Pick a model to turn the answer box on; pick "Off" to turn it off. There is no
        # separate enable step, so a chosen model is never silently inert.
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        self._llm_combo = QComboBox()
        self._llm_combo.currentIndexChanged.connect(self._on_llm_selection_changed)
        model_row.addWidget(self._llm_combo, stretch=1)
        self._detect_btn = QPushButton("Rescan")
        self._detect_btn.clicked.connect(self._on_detect_models)
        model_row.addWidget(self._detect_btn)
        layout.addLayout(model_row)

        self._llm_status = QLabel("")
        self._llm_status.setWordWrap(True)
        self._llm_status.setProperty("role", "muted")
        layout.addWidget(self._llm_status)
        layout.addStretch(1)

        # Populate immediately with what we already know (Off + the saved model, if any) so the box
        # is never blank, then detect the live list the first time this tab is shown.
        self._llm_detected_once = False
        self._populate_llm_combo([])
        return tab

    def _populate_llm_combo(self, backends: list[LlmBackend]) -> None:
        """Fill the Model dropdown with "Off" plus every detected model, selecting the saved one.

        The saved model is kept in the list even when no server currently reports it (e.g. the
        server is briefly down), so the user's choice does not vanish. Signals are blocked while
        rebuilding so repopulating never spuriously flips the enabled state.
        """
        # Each model item stores a string key "base_url\x1fmodel" (not a tuple): findData matches
        # strings reliably but not Python tuples, so the string key is what lets the saved model be
        # re-selected. "Off" stores an empty string.
        models: list[tuple[str, str]] = []  # (key, display)
        for backend in backends:
            for model in backend.models:
                models.append((_llm_key(backend.base_url, model), f"{backend.name} — {model}"))
        saved_key = _llm_key(self._prefs.llm_base_url, self._prefs.llm_model)
        if self._prefs.llm_model and not any(key == saved_key for key, _ in models):
            models.insert(0, (saved_key, f"{self._prefs.llm_model} (saved)"))

        self._llm_combo.blockSignals(True)
        self._llm_combo.clear()
        self._llm_combo.addItem("Off (no AI answer)", "")
        for key, display in models:
            self._llm_combo.addItem(display, key)
        # Select the saved model only if the feature is on; otherwise rest on "Off".
        target = self._llm_combo.findData(saved_key) if self._prefs.llm_enabled else -1
        self._llm_combo.setCurrentIndex(target if target >= 0 else 0)
        self._llm_combo.blockSignals(False)

    def _on_settings_tab_changed(self, index: int) -> None:
        if index == self._local_ai_tab_index:
            self.maybe_detect_local_models()

    def maybe_detect_local_models(self) -> None:
        """Detect models the first time the Local AI tab is shown (called from the tab switcher)."""
        if not self._llm_detected_once:
            self._llm_detected_once = True
            self._on_detect_models()

    def _on_detect_models(self) -> None:
        self._detect_btn.setEnabled(False)
        self._llm_status.setText("Looking for local model servers ...")

        async def _probe() -> list[LlmBackend]:
            return await detect_backends()

        worker: AsyncWorker[list[LlmBackend]] = AsyncWorker(_probe)
        worker.signals.finished.connect(self._on_models_detected)
        worker.signals.failed.connect(self._on_detect_failed)
        worker.start(self._pool)

    def _on_detect_failed(self, _message: str) -> None:
        self._detect_btn.setEnabled(True)
        self._llm_status.setText(
            "Could not reach a local model server. Is Ollama or LM Studio running?"
        )

    def _on_models_detected(self, payload: object) -> None:
        self._detect_btn.setEnabled(True)
        backends = (
            [b for b in payload if isinstance(b, LlmBackend)] if isinstance(payload, list) else []
        )
        self._populate_llm_combo(backends)
        count = sum(len(b.models) for b in backends)
        if count:
            self._llm_status.setText(f"Found {count} model(s). Pick one to turn on the answer box.")
        else:
            self._llm_status.setText(
                "No local model server found on 127.0.0.1 (Ollama :11434 or LM Studio :1234)."
            )

    def _on_llm_selection_changed(self) -> None:
        """Model dropdown changed: "Off" disables the box; a model enables it and is saved."""
        parsed = _parse_llm_key(self._llm_combo.currentData())
        if parsed is not None:
            base_url, model = parsed
            self._save(
                replace(
                    self._prefs,
                    llm_base_url=base_url,
                    llm_model=model,
                    llm_enabled=True,
                )
            )
            self._llm_status.setText(f"On. Answers will use {model}.")
        else:
            self._save(replace(self._prefs, llm_enabled=False))
            self._llm_status.setText("Off.")

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

        summary_cb = QCheckBox("Show a Wikipedia summary for some searches")
        summary_cb.setChecked(self._prefs.summary_enabled)
        summary_sub = QLabel(
            "On by default. For entity-like queries, shows a short summary card above results from "
            "the related Wikipedia article. Adds at most one extra request to Wikipedia (already a "
            "search engine here) through the privacy proxy."
        )
        summary_sub.setWordWrap(True)
        summary_sub.setProperty("role", "muted")
        summary_cb.toggled.connect(
            lambda checked: self._save(replace(self._prefs, summary_enabled=checked))
        )
        layout.addWidget(summary_cb)
        layout.addWidget(summary_sub)

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

        self._check_now_btn = QPushButton("Check now")
        self._check_now_btn.clicked.connect(self._on_check_now)
        layout.addWidget(self._check_now_btn)
        layout.addStretch(1)
        return tab

    def _on_check_now(self) -> None:
        from searchmob_desktop.update import VersionTag

        # One check at a time: disabling the button stops rapid clicks from stacking concurrent
        # workers (and duplicate result dialogs). Re-enabled when the check finishes or fails.
        self._check_now_btn.setEnabled(False)

        async def _probe() -> UpdateInfo | None:
            async with make_privacy_client(4.0) as client:
                return await fetch_latest(client)

        worker: AsyncWorker[UpdateInfo | None] = AsyncWorker(_probe)

        def _on_finished(info_obj: object) -> None:
            self._check_now_btn.setEnabled(True)
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
            self._check_now_btn.setEnabled(True)
            QMessageBox.warning(self, "Update check failed", message)

        worker.signals.finished.connect(_on_finished)
        worker.signals.failed.connect(_on_failed)
        worker.start(self._pool)

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
            # Mint a network access token the first time network mode is turned on, then reuse it
            # on later toggles. The token gates the query routes for off-loopback clients and is
            # baked into the descriptor / setup URLs. Keep it on turn-off so re-enabling reuses it.
            token = self._prefs.network_access_token
            if checked and not token:
                token = secrets.token_urlsafe(24)
            self._save(
                replace(
                    self._prefs,
                    network_access_enabled=checked,
                    network_access_token=token,
                )
            )
            # If the server is running, tell the controller; takes effect on next restart.
            if self._server_controller is not None:
                from searchmob_desktop.server import LOOPBACK_HOST

                self._server_controller.set_host("0.0.0.0" if checked else LOOPBACK_HOST)

        cb.toggled.connect(_on_toggled)
        layout.addWidget(cb)
        layout.addWidget(sub)

        # Trusted hostnames: extra names the server accepts in the Host header so a browser on
        # another device can reach SearchMob by name (e.g. a Tailscale MagicDNS name) instead of
        # an IP. The machine's own hostname is always accepted; this covers names it cannot detect.
        hostnames_label = QLabel("Trusted hostnames (network mode)")
        layout.addWidget(hostnames_label)
        self._hostnames_input = QLineEdit()
        self._hostnames_input.setText(", ".join(self._prefs.network_hostnames))
        self._hostnames_input.setPlaceholderText("e.g. my-pc.tailnet.ts.net, my-pc.local")
        self._hostnames_input.editingFinished.connect(self._save_network_hostnames)
        layout.addWidget(self._hostnames_input)
        hostnames_help = QLabel(
            "Comma-separated. Add a name only if it resolves to this machine on the other device "
            "(Tailscale MagicDNS or mDNS). Reaching the server by IP always works without this."
        )
        hostnames_help.setWordWrap(True)
        hostnames_help.setProperty("role", "muted")
        layout.addWidget(hostnames_help)

        info = QLabel(
            "When on, restart the local server from the main window so the new bind address "
            "takes effect."
        )
        info.setWordWrap(True)
        info.setProperty("role", "muted")
        layout.addWidget(info)
        layout.addStretch(1)
        return tab

    def _save_network_hostnames(self) -> None:
        """Parse the comma-separated hostnames field into a normalized tuple and persist it."""
        raw = self._hostnames_input.text()
        parsed = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
        if parsed == self._prefs.network_hostnames:
            return
        self._save(replace(self._prefs, network_hostnames=parsed))

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

        guide_btn = QPushButton("Run the setup guide again")
        guide_btn.clicked.connect(self._open_onboarding)
        layout.addWidget(guide_btn)

        layout.addWidget(self._build_service_section())

        about_btn = QPushButton("About and privacy")
        about_btn.clicked.connect(self._open_about)
        layout.addWidget(about_btn)
        layout.addStretch(1)
        return tab

    def _build_service_section(self) -> QWidget:
        """Controls to run the local server as a background service (Linux systemd user unit)."""
        from searchmob_desktop import service

        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        col = QVBoxLayout(box)

        header = QLabel("Run in the background")
        header_font = header.font()
        header_font.setBold(True)
        header.setFont(header_font)
        col.addWidget(header)

        desc = QLabel(
            "Optionally run the local search server as a background service so your browser can "
            "use SearchMob even when the app window is closed. The app still opens normally."
        )
        desc.setWordWrap(True)
        desc.setProperty("role", "muted")
        col.addWidget(desc)

        self._service_status_label = QLabel()
        self._service_status_label.setWordWrap(True)
        self._service_status_label.setProperty("role", "muted")
        col.addWidget(self._service_status_label)

        row = QHBoxLayout()
        self._service_install_btn = QPushButton("Install and start")
        self._service_install_btn.clicked.connect(self._install_service)
        self._service_remove_btn = QPushButton("Stop and remove")
        self._service_remove_btn.clicked.connect(self._remove_service)
        row.addWidget(self._service_install_btn)
        row.addWidget(self._service_remove_btn)
        row.addStretch(1)
        col.addLayout(row)

        supported = service.is_supported()
        if not supported:
            self._service_install_btn.setEnabled(False)
            self._service_remove_btn.setEnabled(False)
        self._refresh_service_status()
        return box

    def _refresh_service_status(self) -> None:
        from searchmob_desktop import service

        state = service.status()
        self._service_status_label.setText(state.summary())
        if state.supported:
            self._service_install_btn.setText(
                "Reinstall" if state.installed else "Install and start"
            )
            self._service_remove_btn.setEnabled(state.installed)

    def _install_service(self) -> None:
        from searchmob_desktop import service

        # Match the service bind to the current network setting so it acts like the in-app server.
        host = "0.0.0.0" if self._prefs.network_access_enabled else "127.0.0.1"
        ok, message = service.install_and_enable(host=host)
        if not ok:
            QMessageBox.warning(self, "Could not install the service", message)
        self._refresh_service_status()

    def _remove_service(self) -> None:
        from searchmob_desktop import service

        ok, message = service.disable_and_remove()
        if not ok:
            QMessageBox.warning(self, "Could not remove the service", message)
        self._refresh_service_status()

    def _open_onboarding(self) -> None:
        from searchmob_desktop.gui.onboarding_dialog import OnboardingDialog

        OnboardingDialog(
            prefs_store=self._prefs_store,
            server_controller=self._server_controller,
            parent=self,
        ).exec()

    def _open_browser_setup(self) -> None:
        from searchmob_desktop.gui.browser_setup_dialog import choose_setup_host
        from searchmob_desktop.server import local_hostnames

        port: int | None = None
        token: str | None = None
        host = choose_setup_host(
            network_enabled=self._prefs.network_access_enabled,
            configured_hostnames=self._prefs.network_hostnames,
            local_names=sorted(local_hostnames()),
        )
        if self._server_controller is not None and self._server_controller.is_running:
            port = 8787  # default; the controller does not expose the live port today
            # In network mode the query routes are token-gated, so the setup URLs must carry the
            # token or a browser added off-loopback would be rejected. Loopback stays token-free.
            if self._prefs.network_access_enabled and self._prefs.network_access_token:
                token = self._prefs.network_access_token
        dialog = BrowserSetupDialog(host=host, port=port, parent=self, token=token)
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
