"""Pick the right history backend for the current profile.

Store-nothing stays the default. When the user has opted into history AND an OS-keyring vault can
be opened AND the SQLCipher wheel is installed, history persists encrypted on disk; otherwise it
falls back to the in-memory store so the app still works (history is then per-session). Either way
the 30-day TTL applies. A zero-knowledge (passphrase) vault is not auto-unlockable from the GUI, so
it also falls back to in-memory until unlocked via the CLI.
"""

from __future__ import annotations

from searchmob_desktop.data.history import (
    DEFAULT_HISTORY_TTL_MS,
    HistoryStore,
    InMemoryHistoryStore,
    SqlCipherHistoryStore,
    sqlcipher_available,
)
from searchmob_desktop.data.vault_access import open_os_vault
from searchmob_desktop.prefs import UserPreferences

_HISTORY_DB_FILENAME = "history.db"


def build_history_store(prefs: UserPreferences) -> HistoryStore:
    """Return the best available history store for `prefs`, already set to the enabled state.

    Persistent (encrypted) when history is enabled and the vault + SQLCipher are available; the
    vault is created on first opt-in. Falls back to in-memory otherwise. Never raises.
    """
    if prefs.history_enabled and sqlcipher_available():
        try:
            storage = open_os_vault(create=True)
        except Exception:
            storage = None
        if storage is not None and storage.is_unlocked:
            db_path = storage.metadata_store.path.parent / _HISTORY_DB_FILENAME
            store: HistoryStore = SqlCipherHistoryStore(
                db_path, storage.dek_provider(), ttl_ms=DEFAULT_HISTORY_TTL_MS
            )
            store.set_enabled(True)
            return store

    fallback = InMemoryHistoryStore(ttl_ms=DEFAULT_HISTORY_TTL_MS)
    fallback.set_enabled(prefs.history_enabled)
    return fallback
